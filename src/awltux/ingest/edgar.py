"""EDGAR ingest: CIK resolution, filing sync, and the current-events feed.

Two things this gets right that matter:

* **CIK resolution is a lookup, not a guess.** EDGAR's own ``company_tickers.json``
  is authoritative, and it returns *unpadded* CIKs, so every value is normalised
  on the way in. A wrong CIK silently attaches another company's financials.
* **Only UK-listed names miss out.** EDGAR covers US domestic filers and foreign
  private issuers (20-F/6-K), but a London-only plc is absent entirely. Those
  instruments fall through to Companies House, which is why both sources exist.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import Filing, Instrument, NewsItem, utcnow
from awltux.ingest.symbols import is_uk_listing
from awltux.providers.edgar import EdgarProvider, normalise_cik, parse_atom_entries
from awltux.providers.http import ProviderError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EdgarSyncReport:
    resolved: int = 0
    unresolved: list[str] = field(default_factory=list)
    filings_seen: int = 0
    filings_written: int = 0
    events_written: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "unresolved": self.unresolved[:25],
            "unresolved_count": len(self.unresolved),
            "filings_seen": self.filings_seen,
            "filings_written": self.filings_written,
            "events_written": self.events_written,
            "errors": self.errors[:10],
        }


def resolve_ciks(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: EdgarProvider | None = None,
) -> EdgarSyncReport:
    """Attach SEC CIKs to US-listed instruments from EDGAR's official map."""
    settings = settings or get_settings()
    report = EdgarSyncReport()
    provider = provider or EdgarProvider(settings)

    try:
        ticker_map = provider.get_ticker_map()
    except ProviderError as exc:
        report.errors.append(f"ticker map unavailable: {exc}")
        return report

    instruments = session.execute(
        select(Instrument).where(Instrument.in_universe.is_(True))
    ).scalars().all()

    for instrument in instruments:
        if is_uk_listing(instrument.exchange_name, instrument.yahoo_symbol):
            continue  # London-only listings are not in EDGAR at all
        if instrument.sec_cik:
            report.resolved += 1
            continue

        # EDGAR keys on the bare ticker, and uses "-" where a US listing is a
        # share class (BRK-B vs the provider's BRK.B).
        candidates = []
        if instrument.yahoo_symbol:
            bare = instrument.yahoo_symbol.split(".")[0].upper()
            candidates.extend([bare, bare.replace(".", "-"), bare.replace("-", ".")])
        candidates.append(instrument.t212_ticker.split("_")[0].upper())

        for candidate in candidates:
            entry = ticker_map.get(candidate)
            if entry:
                instrument.sec_cik = normalise_cik(entry["cik"])
                report.resolved += 1
                break
        else:
            report.unresolved.append(instrument.t212_ticker)

    session.flush()
    logger.info(
        "CIK resolution: %d resolved, %d unresolved", report.resolved, len(report.unresolved)
    )
    return report


def _existing_filing_urls(session: Session, ticker: str) -> set[str]:
    return {
        url
        for (url,) in session.execute(
            select(Filing.url).where(Filing.instrument_t212_ticker == ticker)
        ).all()
        if url
    }


def sync_filings(
    session: Session,
    *,
    tickers: list[str] | None = None,
    settings: Settings | None = None,
    provider: EdgarProvider | None = None,
    limit_per_company: int = 15,
) -> EdgarSyncReport:
    """Fetch and store recent filings for every instrument with a CIK."""
    settings = settings or get_settings()
    provider = provider or EdgarProvider(settings)
    report = EdgarSyncReport()

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.sec_cik.is_not(None))
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    instruments = session.execute(statement).scalars().all()
    if not instruments:
        return report

    for instrument in instruments:
        assert instrument.sec_cik is not None
        try:
            filings = provider.get_recent_filings(
                instrument.sec_cik, limit=limit_per_company
            )
        except ProviderError as exc:
            report.errors.append(f"{instrument.t212_ticker}: {exc}")
            continue

        report.filings_seen += len(filings)
        known = _existing_filing_urls(session, instrument.t212_ticker)

        for entry in filings:
            url = entry.get("url")
            if not url or url in known:
                continue

            filed_at = _parse_date(entry.get("filing_date"))
            session.add(
                Filing(
                    instrument_t212_ticker=instrument.t212_ticker,
                    source="edgar",
                    filing_type=entry.get("form"),
                    title=entry.get("description") or entry.get("form"),
                    filed_at=filed_at,
                    url=url,
                    status="pending",
                )
            )
            known.add(url)
            report.filings_written += 1

        # SIC is a free, authoritative sector code for US filers.
        if not instrument.sic_code:
            sic, sic_description = provider.get_sic(instrument.sec_cik)
            if sic:
                instrument.sic_code = sic
                if not instrument.sector:
                    instrument.sector = sic_description or f"SIC {sic}"
                    instrument.sector_source = "edgar_sic"

    session.flush()
    logger.info("filing sync: %s", report.as_dict())
    return report


def ingest_current_events(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: EdgarProvider | None = None,
    form_type: str | None = "8-K",
    count: int = 100,
) -> EdgarSyncReport:
    """Poll EDGAR's current-events Atom feed and record new US filings.

    This is the closest thing to a free real-time corporate-events stream:
    filings appear within roughly a second of dissemination. Entries are matched
    back to instruments by CIK, and anything unmatched is dropped rather than
    guessed at.
    """
    settings = settings or get_settings()
    provider = provider or EdgarProvider(settings)
    report = EdgarSyncReport()

    try:
        entries = provider.get_current_events(form_type=form_type, count=count)
    except ProviderError as exc:
        report.errors.append(str(exc))
        return report

    by_cik: dict[str, Instrument] = {}
    for instrument in session.execute(
        select(Instrument).where(Instrument.sec_cik.is_not(None))
    ).scalars().all():
        if instrument.sec_cik:
            by_cik[instrument.sec_cik] = instrument

    for entry in entries:
        cik = normalise_cik(entry.get("cik"))
        instrument = by_cik.get(cik) if cik else None
        if instrument is None:
            continue

        title = entry.get("title") or f"{form_type or 'filing'} from {instrument.display_name}"
        url = entry.get("link")

        # Dedupe on the canonical URL, falling back to a synthetic key so an
        # entry without a link still cannot be inserted twice.
        from hashlib import sha256

        from awltux.providers.news_rss import canonicalise_url

        basis = canonicalise_url(url) or f"{cik}:{entry.get('updated')}:{title}"
        digest = sha256(basis.encode("utf-8")).hexdigest()

        exists = session.execute(
            select(NewsItem.id).where(NewsItem.url_hash == digest).limit(1)
        ).scalar_one_or_none()
        if exists is not None:
            continue

        session.add(
            NewsItem(
                source="edgar",
                url=url,
                url_hash=digest,
                title=title[:768],
                summary=entry.get("summary"),
                published_at=_parse_iso(entry.get("updated")),
                tickers=[instrument.t212_ticker],
                sectors=[instrument.sector] if instrument.sector else [],
                raw={"form_type": entry.get("form_type"), "cik": cik},
                created_at=utcnow(),
            )
        )
        report.events_written += 1

        # A new filing also belongs in the filings table.
        if not instrument_filing_exists(session, instrument.t212_ticker, url):
            session.add(
                Filing(
                    instrument_t212_ticker=instrument.t212_ticker,
                    source="edgar",
                    filing_type=entry.get("form_type"),
                    title=title[:512],
                    filed_at=_parse_iso(entry.get("updated")),
                    url=url,
                    status="pending",
                )
            )

    session.flush()
    if report.events_written:
        logger.info("edgar events: %d new", report.events_written)
    return report


def instrument_filing_exists(session: Session, ticker: str, url: str | None) -> bool:
    if not url:
        return False
    return (
        session.execute(
            select(Filing.id)
            .where(Filing.instrument_t212_ticker == ticker)
            .where(Filing.url == url)
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _parse_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value).replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def _parse_iso(value: str | None) -> dt.datetime | None:
    return _parse_date(value)


# Re-exported for tests that exercise Atom parsing without a provider.
__all__ = [
    "EdgarSyncReport",
    "ingest_current_events",
    "parse_atom_entries",
    "resolve_ciks",
    "sync_filings",
]

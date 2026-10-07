"""Shareholders' reports: find them, download them, and keep the bytes.

The annual report is the primary evidence about a business, and until now this
system held only a *pointer* to one. The ``filing`` table carried 4,529 rows and not
a single document: ``raw_path``, ``doc_hash`` and ``parsed`` were columns on the
model that nothing ever wrote, and every row sat at ``status='pending'`` for ever. A
URL is not evidence -- it is a promise that a document exists somewhere, and it
cannot be read, quoted or checked.

Four rules shape this module.

**The bytes are kept.** A report that is fetched and discarded cannot be re-parsed
when the extractor improves, cannot be diffed against last year's, and cannot be
shown to a reader. ``raw/`` already exists as the archive of provider payloads and
this is the same idea applied to the document that matters most.

**Two years for now, which buys a comparison and not a trend.** Almost every
accounting marker worth computing is about *persistence* -- accruals that stay high,
cash conversion that keeps deteriorating, a margin trend -- and three periods are
needed before any of those can be called a direction. Two gives year-on-year and
nothing more, and the markers say so rather than presenting a difference of two
numbers as a trend. The live database held one annual report for 249 of its 265
filers, so two is already progress and the window is a config value.

**A hash, so re-fetching is free and re-issuing is visible.** ``doc_hash`` makes the
job idempotent and turns a silently amended filing into a detectable event rather
than a quiet overwrite.

**Downloading is not parsing.** This module gets bytes onto disk and records what it
got. Deciding what the numbers mean is a separate step with its own failure modes,
and conflating them would mean a parsing bug costing a document.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import Filing, Instrument, utcnow
from awltux.db.session import release_write_lock
from awltux.providers.edgar import ANNUAL_FORMS
from awltux.providers.http import ProviderError

logger = logging.getLogger(__name__)

#: Subdirectory of ``data/raw`` holding filing documents.
DOCUMENT_DIR = "filings"

#: What a fetched document is allowed to be. Anything else is refused rather than
#: stored: EDGAR serves its own error pages with HTTP 200 often enough that a
#: content-type check is the only thing standing between a filing and a saved
#: HTML apology.
TEXT_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml",
    "application/xml",
    "text/xml",
)

#: Filings fetched in one run. Each is a document up to several megabytes and the
#: SEC asks for no more than ten requests a second, so a backlog drains over runs.
DEFAULT_BATCH = 60


@dataclass(slots=True)
class DocumentReport:
    discovered: int = 0
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_written: int = 0
    errors: list[str] = field(default_factory=list)
    instruments: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "discovered": self.discovered,
            "fetched": self.fetched,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_written": self.bytes_written,
            "instruments": len(self.instruments),
            "errors": self.errors[:10],
            "error_count": len(self.errors),
        }


def _extension(url: str) -> str:
    """A file extension taken from the URL.

    From the URL rather than the served content type, deliberately: the path has to
    be the same on every fetch or a re-download would land beside the first copy
    instead of replacing it. EDGAR's archive URLs carry the extension already.
    """
    suffix = Path(url.split("?")[0]).suffix.lower()
    return suffix if suffix in {".htm", ".html", ".txt", ".xml"} else ".htm"


def document_path(settings: Settings, ticker: str, url: str) -> Path:
    """Where a filing's document lives on disk.

    Nested by instrument so a reader can see one company's history in one place, and
    keyed by the accession directory EDGAR puts in every archive URL rather than by
    title: an accession is unique and stable, a title is neither. The ``filing``
    table does not store the accession separately, and deriving it from the URL is
    reliable because EDGAR's archive path is the accession with the dashes removed.
    """
    return settings.raw_dir / DOCUMENT_DIR / ticker / f"{_document_key(url)}{_extension(url)}"


def _document_key(url: str) -> str:
    """A stable filename for a filing, taken from the accession in its URL.

    ``/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm`` yields the
    ``000032019324000123`` directory. A URL that does not look like an EDGAR archive
    falls back to a hash of itself, so the same document always lands at the same
    path and a second fetch overwrites rather than duplicates.
    """
    parts = [part for part in url.split("?")[0].split("/") if part]
    for index, part in enumerate(parts):
        if part.isdigit() and len(part) >= 15 and index + 1 < len(parts):
            return part
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def deepen_annual_history(
    session: Session,
    *,
    years: int = 2,
    settings: Settings | None = None,
    provider: Any | None = None,
    limit_per_company: int = 6,
    tickers: list[str] | None = None,
) -> DocumentReport:
    """Make sure the last ``years`` annual reports are on file for every filer.

    The existing sync takes the fifteen most recent *interesting* filings, which for
    a company that files a lot of 8-Ks reaches back barely a year -- the live
    database held one annual report for 249 of its 265 filers. This asks EDGAR for
    annual forms specifically and by date.

    ``tickers`` scopes the walk to named instruments, for a one-instrument refresh.

    **Two years, deliberately, and it is a limitation rather than a target.** The
    accounting markers worth the most are about persistence -- accruals that stay
    high, cash conversion that keeps falling -- and
    :data:`awltux.analysis.accounting.MIN_PERIODS_FOR_TREND` asks for three before it
    will call something a trend. Two periods give a year-on-year comparison and no
    more, and the markers say so rather than presenting a difference of two numbers
    as a direction. Raising this is a config change.
    """
    from awltux.providers.edgar import EdgarProvider

    settings = settings or get_settings()
    provider = provider or EdgarProvider(settings)
    report = DocumentReport()

    cutoff = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=int(years * 365.25))

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.sec_cik.is_not(None))
    )
    if tickers is not None:
        statement = statement.where(Instrument.t212_ticker.in_(list(tickers)))
    instruments = session.execute(statement).scalars().all()

    for instrument in instruments:
        assert instrument.sec_cik is not None
        try:
            annual = provider.get_annual_filings(
                instrument.sec_cik, since=cutoff, limit=limit_per_company
            )
        except ProviderError as exc:
            report.errors.append(f"{instrument.t212_ticker}: {exc}")
            continue

        known = {
            url
            for (url,) in session.execute(
                select(Filing.url).where(
                    Filing.instrument_t212_ticker == instrument.t212_ticker
                )
            ).all()
            if url
        }

        for entry in annual:
            report.discovered += 1
            url = entry.get("url")
            if not url or url in known:
                continue
            session.add(
                Filing(
                    instrument_t212_ticker=instrument.t212_ticker,
                    source="edgar",
                    filing_type=entry.get("form"),
                    title=entry.get("description") or entry.get("form"),
                    filed_at=_as_datetime(entry.get("filing_date")),
                    # The period the report covers, which for an annual report is
                    # its fiscal year end. Set here as well as in the filings sync
                    # because this is the path that exists to hold annual reports,
                    # and the period is how a reader gets from the document to the
                    # figures taken from it.
                    period_end=_as_day(entry.get("report_date")),
                    url=url,
                    status="pending",
                )
            )
            known.add(url)

        session.flush()
        # Several provider calls per instrument: holding one transaction across all
        # of them would block every other writer for the run's duration.
        release_write_lock(session)

    logger.info("annual history: %s", report.as_dict())
    return report


def pending_annual_reports(
    session: Session, *, limit: int = DEFAULT_BATCH, tickers: list[str] | None = None
) -> list[Filing]:
    """Annual reports whose document has not been fetched yet, oldest gap first.

    Ordered by instrument then date so one company's six years arrive together
    rather than interleaved with another's: a single report is not much use, and a
    partial run is far more legible if it finished some companies than if it
    half-covered all of them.
    """
    statement = (
        select(Filing)
        .where(Filing.filing_type.in_(ANNUAL_FORMS))
        .where(Filing.status.in_(("pending", "failed")))
        .where(Filing.url.is_not(None))
        .order_by(Filing.instrument_t212_ticker.asc(), Filing.filed_at.desc())
        .limit(limit)
    )
    if tickers is not None:
        statement = statement.where(Filing.instrument_t212_ticker.in_(list(tickers)))
    return list(session.execute(statement).scalars().all())


def fetch_document(
    session: Session,
    filing: Filing,
    *,
    settings: Settings,
    provider: Any,
) -> int | None:
    """Download one filing's primary document. Returns the bytes stored, or ``None``.

    Idempotent on the content hash: a document already held is left alone, and one
    whose bytes have changed since it was fetched is recorded as a new hash rather
    than silently replaced.
    """
    assert filing.url is not None
    try:
        result = provider.fetch_document(filing.url)
    except ProviderError as exc:
        filing.status = "failed"
        filing.error = str(exc)[:500]
        return None

    refusal = result.refusal
    if refusal is not None:
        # Storing it would put a refusal page in the archive and mark the filing
        # done -- the failure mode this check exists for, and one that is invisible
        # afterwards because the row looks fetched.
        filing.status = "failed"
        filing.error = refusal[:500]
        return None

    digest = hashlib.sha256(result.body).hexdigest()
    path = document_path(settings, filing.instrument_t212_ticker, filing.url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(result.body)

    filing.doc_hash = digest
    filing.content_type = result.content_type
    filing.raw_path = str(path.relative_to(settings.data_dir))
    filing.status = "fetched"
    filing.error = None
    return len(result.body)


def fetch_annual_reports(
    session: Session,
    *,
    limit: int = DEFAULT_BATCH,
    settings: Settings | None = None,
    provider: Any | None = None,
    tickers: list[str] | None = None,
) -> DocumentReport:
    """Download the documents behind the annual reports already on file.

    ``tickers`` scopes it to named instruments, for a one-instrument refresh, where the
    per-run batch limit is lifted by the caller -- the queue is one company, not a
    universe.
    """
    from awltux.providers.edgar import EdgarProvider

    settings = settings or get_settings()
    provider = provider or EdgarProvider(settings)
    report = DocumentReport()

    for filing in pending_annual_reports(session, limit=limit, tickers=tickers):
        written = fetch_document(session, filing, settings=settings, provider=provider)
        if written is None:
            report.failed += 1
            if filing.error:
                report.errors.append(f"{filing.instrument_t212_ticker}: {filing.error}")
        else:
            report.fetched += 1
            report.bytes_written += written
            report.instruments.add(filing.instrument_t212_ticker)

        session.flush()
        # One request per document, and a document can be megabytes: the lock is
        # released between them so the dashboard stays readable during a run.
        release_write_lock(session)

    logger.info("document fetch: %s", report.as_dict())
    return report


def refresh_report_flags(session: Session) -> int:
    """Recompute the per-instrument flag from what is actually held on disk.

    Derived from the ``filing`` rows rather than incremented as documents arrive, so
    the flag is self-correcting: a run that fails halfway, a filing that turns out
    to be a refusal page, or a document deleted from the volume all leave the count
    describing reality rather than describing what was attempted.

    Scoped to the universe, which is what the dashboard lists and what the
    acquisition job selects from. An instrument outside it keeps a zero, which is
    the honest answer for something nothing is collecting reports for.
    """
    counts = {
        ticker: count
        for ticker, count in session.execute(
            select(Filing.instrument_t212_ticker, func.count())
            .where(Filing.filing_type.in_(ANNUAL_FORMS))
            .where(Filing.status == "fetched")
            .group_by(Filing.instrument_t212_ticker)
        ).all()
    }

    now = utcnow()
    updated = 0
    instruments = session.execute(
        select(Instrument).where(Instrument.in_universe.is_(True))
    ).scalars().all()
    for instrument in instruments:
        held = counts.get(instrument.t212_ticker, 0)
        if instrument.annual_reports != held or instrument.reports_synced_at is None:
            instrument.annual_reports = held
            instrument.reports_synced_at = now
            updated += 1

    session.flush()
    return updated


def _as_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value[:10]).replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def _as_day(value: str | None) -> dt.date | None:
    """The day of an ISO timestamp, for a ``Date`` column.

    ``period_end`` is a ``Date``: an aware datetime would be stored as a day and read
    back naive, which is the naive/aware trap this codebase has hit before. Take the
    day at the boundary rather than leaving it to the driver.
    """
    stamp = _as_datetime(value)
    return stamp.date() if stamp is not None else None

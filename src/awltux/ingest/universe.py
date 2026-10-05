"""Sync the Trading 212 instrument universe into the database.

Trading 212 is the only source that knows which instruments a UK account can
actually trade, so it defines the universe. Everything else (prices, filings,
news) is joined onto those instruments afterwards.

The exchange join is not obvious: an instrument carries a ``workingScheduleId``,
and that id belongs to a *schedule* nested inside an exchange, not to the
exchange itself. So the lookup is schedule-id -> exchange, built by walking
``workingSchedules`` on every exchange.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import AppSetting, Exchange, Instrument, InstrumentAlias, utcnow
from awltux.ingest.symbols import derive_yahoo_symbol, is_uk_listing, parse_t212_ticker
from awltux.providers.t212 import T212Provider, classify_exchange_name

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SyncReport:
    exchanges: int = 0
    instruments_seen: int = 0
    instruments_created: int = 0
    instruments_updated: int = 0
    mapped: int = 0
    unmapped: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchanges": self.exchanges,
            "instruments_seen": self.instruments_seen,
            "instruments_created": self.instruments_created,
            "instruments_updated": self.instruments_updated,
            "mapped": self.mapped,
            "unmapped": self.unmapped,
            "warnings": self.warnings[:20],
        }


def _schedule_to_exchange_map(exchanges: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Map every ``workingScheduleId`` to its owning exchange.

    The schedule ids live one level down from the exchange, in their own id space,
    so an instrument's ``workingScheduleId`` cannot be joined to an exchange id
    directly -- it has to be resolved through this map first. Treating the raw
    value as an exchange id produced a foreign-key violation on every instrument.
    """
    mapping: dict[int, dict[str, Any]] = {}
    for exchange in exchanges:
        for schedule in exchange.get("workingSchedules") or []:
            schedule_id = schedule.get("id")
            if schedule_id is not None:
                mapping[int(schedule_id)] = exchange
    return mapping


def synchronize_exchanges(
    session: Session,
    exchanges: list[dict[str, Any]] | None = None,
    provider: T212Provider | None = None,
) -> int:
    """Fetch and upsert exchanges plus their working schedules.

    ``exchanges`` lets a caller that has already fetched the list (the instrument
    sync does, because it needs the schedule map) reuse it -- the endpoint is
    rate-limited to one request per 30 seconds.
    """
    if exchanges is None:
        provider = provider or T212Provider()
        exchanges = provider.get_exchanges()
    now = utcnow()
    count = 0

    for item in exchanges:
        exchange_id = item.get("id")
        if exchange_id is None:
            continue
        row = session.get(Exchange, int(exchange_id))
        name = str(item.get("name") or f"Exchange {exchange_id}")
        if row is None:
            row = Exchange(id=int(exchange_id), name=name)
            session.add(row)
        row.name = name
        row.schedule = {"workingSchedules": item.get("workingSchedules") or []}
        row.updated_at = now
        count += 1

    session.flush()
    logger.info("synced %d exchanges", count)
    return count


def synchronize_instruments(
    session: Session,
    provider: T212Provider | None = None,
    settings: Settings | None = None,
    *,
    exchanges: list[dict[str, Any]] | None = None,
    instruments: list[dict[str, Any]] | None = None,
) -> SyncReport:
    """Upsert every accessible instrument with its resolved provider symbols.

    **Pre-fetched payloads are passed in by the caller.** A scheduler job should
    fetch first and persist second, because Trading 212's limits are strict enough
    that a call can sleep for a minute inside ``BudgetGuard`` -- and holding an
    open transaction across that wait takes SQLite's write lock for the whole
    duration, which locks every other writer (and, with ``BEGIN IMMEDIATE``,
    readers too) out of the database.

    Fetching here is still supported for tests and one-off use, but it is the
    slower path by design.
    """
    settings = settings or get_settings()
    provider = provider or T212Provider(settings)
    report = SyncReport()

    if exchanges is None:
        exchanges = provider.get_exchanges()
    report.exchanges = synchronize_exchanges(session, exchanges=exchanges)
    schedule_map = _schedule_to_exchange_map(exchanges)

    if instruments is None:
        instruments = provider.get_instruments()
    report.instruments_seen = len(instruments)
    existing = {
        row.t212_ticker: row
        for row in session.execute(select(Instrument)).scalars().all()
    }

    for item in instruments:
        ticker = item.get("ticker")
        if not ticker:
            continue

        schedule_id = item.get("workingScheduleId")
        exchange = schedule_map.get(int(schedule_id)) if schedule_id is not None else None
        exchange_name = classify_exchange_name(str(exchange.get("name"))) if exchange else None

        row = existing.get(ticker)
        created = row is None
        if row is None:
            row = Instrument(t212_ticker=ticker, name=str(item.get("name") or ticker))
            session.add(row)
            report.instruments_created += 1
        else:
            report.instruments_updated += 1

        row.name = str(item.get("name") or row.name or ticker)
        row.short_name = item.get("shortName") or row.short_name
        row.isin = item.get("isin") or row.isin
        row.currency_code = item.get("currencyCode") or row.currency_code
        row.instrument_type = item.get("type") or row.instrument_type
        row.extended_hours = bool(item.get("extendedHours") or False)
        row.max_open_quantity = item.get("maxOpenQuantity")
        row.added_on = item.get("addedOn")
        # The raw schedule id is recorded as-is, and the exchange it belongs to is
        # resolved separately. They are different id spaces: schedule ids are
        # nested inside exchanges, so they are not exchange ids.
        row.working_schedule_id = int(schedule_id) if schedule_id is not None else None
        row.exchange_id = int(exchange["id"]) if exchange and exchange.get("id") else None
        if exchange_name:
            row.exchange_name = exchange_name

        _resolve_mapping(session, row, report, created=created)

    session.flush()
    logger.info(
        "synced %d instruments (%d mapped, %d unmapped)",
        report.instruments_seen,
        report.mapped,
        report.unmapped,
    )
    return report


def _resolve_mapping(
    session: Session, row: Instrument, report: SyncReport, *, created: bool
) -> None:
    """Derive and record the Yahoo symbol for an instrument.

    Skips instruments that already carry a *manually confirmed* alias, so a human
    correction is never overwritten by the next scheduled sync.
    """
    manual = session.execute(
        select(InstrumentAlias).where(
            InstrumentAlias.instrument_t212_ticker == row.t212_ticker,
            InstrumentAlias.provider == "yahoo",
            InstrumentAlias.is_manual.is_(True),
        )
    ).scalar_one_or_none()

    if manual is not None:
        row.yahoo_symbol = manual.symbol
        row.mapping_confidence = 1.0
        report.mapped += 1
        return

    mapping = derive_yahoo_symbol(
        row.t212_ticker,
        exchange_name=row.exchange_name,
        currency_code=row.currency_code,
    )

    if not mapping.usable:
        row.yahoo_symbol = None
        row.mapping_confidence = 0.0
        report.unmapped += 1
        if mapping.note and len(report.warnings) < 20:
            report.warnings.append(f"{row.t212_ticker}: {mapping.note}")
        return

    row.yahoo_symbol = mapping.yahoo_symbol
    row.mapping_confidence = mapping.confidence
    report.mapped += 1

    # Record the derivation so a later reviewer can see *why* this symbol was
    # chosen, and can override it.
    alias = session.execute(
        select(InstrumentAlias).where(
            InstrumentAlias.instrument_t212_ticker == row.t212_ticker,
            InstrumentAlias.provider == "yahoo",
        )
    ).scalar_one_or_none()
    if alias is None:
        session.add(
            InstrumentAlias(
                instrument_t212_ticker=row.t212_ticker,
                provider="yahoo",
                symbol=mapping.yahoo_symbol or "",
                confidence=mapping.confidence,
                method=mapping.method,
                is_manual=False,
                note=mapping.note,
            )
        )
    elif not alias.is_manual:
        alias.symbol = mapping.yahoo_symbol or ""
        alias.confidence = mapping.confidence
        alias.method = mapping.method
        alias.note = mapping.note

    if row.isin is None:
        report.warnings.append(f"{row.t212_ticker}: no ISIN returned by Trading 212")


# --------------------------------------------------------------------------- #
# universe construction
# --------------------------------------------------------------------------- #


def refresh_universe(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    """Choose which instruments the app actively analyses.

    Ranking uses market cap when Yahoo has reported one, because that is the only
    free signal of size available. Instruments with no market cap yet are ranked
    below known-large ones but above nothing -- so a fresh database still
    populates rather than selecting an empty universe.

    Held positions, pinned names and any manual inclusion are always in scope,
    and explicit exclusions are always honoured.
    """
    settings = settings or get_settings()
    config = settings.universe

    rows = session.execute(
        select(Instrument).where(Instrument.excluded.is_(False))
    ).scalars().all()

    eligible: list[Instrument] = []
    for row in rows:
        if row.pinned or row.is_held:
            eligible.append(row)
            continue
        if row.instrument_type not in config.instrument_types:
            continue
        if row.yahoo_symbol is None:
            # No price source means no analysis: it cannot be valued or decided.
            continue
        if config.exchanges and row.exchange_name and row.exchange_name not in config.exchanges:
            continue
        eligible.append(row)

    def rank_key(row: Instrument) -> tuple[int, float, float]:
        return (
            0 if (row.pinned or row.is_held) else 1,
            -(row.market_cap or 0.0),
            -(row.median_daily_turnover_gbp or 0.0),
        )

    eligible.sort(key=rank_key)
    selected = eligible[: max(config.size, 1)]
    selected_ids = {row.t212_ticker for row in selected}

    # Falling out of the universe must not delete anything: history, filings and
    # past decisions all reference these rows.
    for row in rows:
        row.in_universe = row.t212_ticker in selected_ids

    session.flush()

    stats = {
        "eligible": len(eligible),
        "selected": len(selected),
        "size_cap": config.size,
        "uk": sum(1 for row in selected if is_uk_listing(row.exchange_name, row.yahoo_symbol)),
        "us": sum(
            1 for row in selected if not is_uk_listing(row.exchange_name, row.yahoo_symbol)
        ),
        "unmapped_eligible": sum(1 for row in rows if row.yahoo_symbol is None),
    }
    logger.info("universe refreshed: %s", stats)
    return stats


def mark_held_instruments(session: Session, provider: T212Provider | None = None) -> int:
    """Flag instruments the account currently holds, from the positions endpoint."""
    provider = provider or T212Provider()
    try:
        positions = provider.get_positions()
    except Exception as exc:
        logger.warning("could not read positions: %s", exc)
        return 0

    held: set[str] = set()
    for position in positions:
        ticker = (position.get("instrument") or {}).get("ticker") or position.get("ticker")
        if ticker:
            held.add(str(ticker))

    count = 0
    for row in session.execute(select(Instrument)).scalars().all():
        was_held = row.is_held
        row.is_held = row.t212_ticker in held
        if row.is_held and not was_held:
            count += 1
    session.flush()
    return len(held)


def ticker_venue_summary(session: Session) -> dict[str, int]:
    """Diagnostic: how many instruments parsed to each venue."""
    summary: dict[str, int] = {}
    for (ticker,) in session.execute(select(Instrument.t212_ticker)).all():
        _, venue = parse_t212_ticker(ticker)
        key = venue or "unqualified"
        summary[key] = summary.get(key, 0) + 1
    return summary


# --------------------------------------------------------------------------- #
# API key capabilities
# --------------------------------------------------------------------------- #

CAPABILITIES_KEY = "t212_capabilities"


def refresh_t212_capabilities(
    session: Session, provider: T212Provider | None = None
) -> dict[str, Any]:
    """Probe which scopes the Trading 212 key actually has, and cache the result.

    Trading 212 issues scoped keys, and a ``metadata``-only key is a perfectly
    reasonable configuration -- it can read the instrument universe but not your
    positions. That has a consequence the rest of the app must not paper over: the
    risk gate cannot enforce its concentration limits without portfolio access.

    The probe is cached rather than run per request, because it makes real calls
    and the answer changes only when the key does.
    """
    provider = provider or T212Provider()
    try:
        capabilities = provider.probe_capabilities()
    except Exception as exc:
        capabilities = {
            "metadata": False,
            "portfolio": False,
            "errors": {"probe": str(exc)[:200]},
        }

    capabilities["checked_at"] = utcnow().isoformat()
    capabilities["environment"] = get_settings().env.t212_env

    row = session.get(AppSetting, CAPABILITIES_KEY)
    if row is None:
        session.add(
            AppSetting(
                key=CAPABILITIES_KEY,
                value=capabilities,
                note="Cached Trading 212 key capabilities",
            )
        )
    else:
        row.value = capabilities
    session.flush()

    if not capabilities.get("portfolio"):
        logger.warning(
            "Trading 212 key cannot read positions (%s). Held-name detection is "
            "disabled and the risk gate will report its concentration limits as "
            "unverified.",
            capabilities.get("errors", {}).get("portfolio", "unknown reason"),
        )
    return capabilities


def cached_t212_capabilities(session: Session) -> dict[str, Any] | None:
    """Read the cached capability probe without making any requests."""
    row = session.get(AppSetting, CAPABILITIES_KEY)
    return row.value if row is not None and isinstance(row.value, dict) else None

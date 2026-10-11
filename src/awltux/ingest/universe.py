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

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import (
    AppSetting,
    DecisionRun,
    Exchange,
    Filing,
    FundamentalPeriod,
    Instrument,
    InstrumentAlias,
    InstrumentBlocker,
    InstrumentLever,
    InstrumentRefresh,
    NewsAnalysis,
    PriceBar,
    Quote,
    ResearchReport,
    SentimentSeries,
    ValuationRun,
    utcnow,
)
from awltux.db.session import release_write_lock
from awltux.ingest import lease
from awltux.ingest.symbols import derive_yahoo_symbol, is_uk_listing, parse_t212_ticker
from awltux.providers.t212 import T212Provider, classify_exchange_name

logger = logging.getLogger(__name__)

#: Instruments upserted before the write lock is released. Small enough that the
#: hold is a fraction of a second, large enough that the flush overhead is noise.
INSTRUMENT_FLUSH_EVERY = 500


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

    for index, item in enumerate(instruments, start=1):
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

        # Flush and release in batches. Everything used to accumulate until one
        # flush at the end, which for the full Trading 212 instrument list is
        # ~18,000 rows and measured 31 seconds holding SQLite's single write lock.
        # That is long enough to break every other writer in the process: a
        # concurrent job's own accounting insert waited out the 15-second
        # busy_timeout and failed with "database is locked", taking the job with
        # it. Batching costs a little throughput and bounds the hold to a fraction
        # of a second.
        if index % INSTRUMENT_FLUSH_EVERY == 0:
            session.flush()
            release_write_lock(session)

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


#: ``app_setting`` key recording that the universe has been populated once. The fact is
#: recorded rather than inferred from "the universe is empty", because a reader who removes
#: every instrument means it: seeding again whenever the count reached zero would quietly undo
#: the removals they asked for. Written in the shape `analysis/metric_fields` uses for its own
#: discovered vocabulary.
UNIVERSE_KEY = "universe"


def initialisation(session: Session) -> dict[str, Any] | None:
    """What the universe was seeded with, or ``None`` if it never has been."""
    row = session.get(AppSetting, UNIVERSE_KEY)
    value = row.value if row is not None else None
    return dict(value) if isinstance(value, dict) else None


def _record_initialisation(session: Session, *, size: int, selected: int) -> None:
    row = session.get(AppSetting, UNIVERSE_KEY)
    if row is None:
        row = AppSetting(key=UNIVERSE_KEY)
        session.add(row)
    row.value = {
        "initialised_at": utcnow().isoformat(),
        "size": size,
        "selected": selected,
    }


def refresh_universe(session: Session, settings: Settings | None = None) -> dict[str, Any]:
    """Seed the universe once, then leave membership to the reader.

    **``universe.size`` is an initialisation value, not a cap.** It used to be applied on
    every run -- the top N by market cap were re-selected and everything below them was set
    back out of the universe, so a name the reader had added by hand displaced the smallest
    name at the bottom, and a name that lost its market cap fell out on its own. That is now
    a one-off: the first run on a database with nothing in the universe selects N instruments,
    records that it did, and every later run only adds **held** positions. Membership after
    that changes by hand -- ``include`` from the search, ``remove`` from the instrument page.

    **Ranking** uses market cap when Yahoo has reported one, because that is the only free
    signal of size available. Instruments with no market cap yet are ranked below known-large
    ones but above nothing -- so a fresh database still populates rather than selecting an
    empty universe. Pinned names and held positions rank first.

    **A held position is always added**, seeding or not: what the account owns is a fact
    rather than a preference, and the whole point of the analysis is to say something about
    it. Nothing here ever sets ``in_universe`` back to ``False`` -- only :func:`remove` does
    that, and only because a person asked.
    """
    settings = settings or get_settings()
    config = settings.universe

    rows = (
        session.execute(select(Instrument).where(Instrument.excluded.is_(False)))
        .scalars()
        .all()
    )
    seeded = initialisation(session)
    members = [row for row in rows if row.in_universe]

    if seeded is None and not members:
        stats = _initialise(session, rows, config)
        logger.info("universe initialised: %s", stats)
        return stats

    # Already populated, or populated before this behaviour existed: `_keep_membership` stamps
    # the flag without re-seeding, so the membership that is there is the membership that stays.
    stats = _keep_membership(session, rows, members, config)
    logger.info("universe membership unchanged: %s", stats)
    return stats


def _initialise(session: Session, rows: list[Instrument], config: Any) -> dict[str, Any]:
    """The first population: the largest eligible instruments, up to the configured size.

    Ranking uses market cap when Yahoo has reported one, because that is the only free signal
    of size available. Instruments with no market cap yet are ranked below known-large ones but
    above nothing -- so a fresh database still populates rather than selecting an empty
    universe. Pinned names and held positions rank first.

    The eligibility counters are built here rather than at the call site: "0 eligible" is the
    same number whether the table is empty, every symbol is unmapped or the exchange filter is
    wrong, and those need different fixes, so the reason has to travel with the count.
    """
    eligible: list[Instrument] = []
    filtered_out_type = 0
    filtered_out_unmapped = 0
    filtered_out_exchange = 0
    for row in rows:
        if row.pinned or row.is_held:
            eligible.append(row)
            continue
        if row.instrument_type not in config.instrument_types:
            filtered_out_type += 1
            continue
        if row.yahoo_symbol is None:
            # No price source means no analysis: it cannot be valued or decided.
            filtered_out_unmapped += 1
            continue
        if config.exchanges and row.exchange_name and row.exchange_name not in config.exchanges:
            filtered_out_exchange += 1
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
    for row in selected:
        row.in_universe = True
    _record_initialisation(session, size=config.size, selected=len(selected))
    session.flush()

    return {
        "mode": "initialised",
        "size_cap": config.size,
        "selected": len(selected),
        "members": len(selected),
        "eligible": len(eligible),
        "instruments_stored": len(rows),
        "uk": sum(1 for row in selected if is_uk_listing(row.exchange_name, row.yahoo_symbol)),
        "us": sum(
            1 for row in selected if not is_uk_listing(row.exchange_name, row.yahoo_symbol)
        ),
        "unmapped_eligible": sum(1 for row in rows if row.yahoo_symbol is None),
        "filtered_out": {
            "instrument_type": filtered_out_type,
            "no_symbol_mapping": filtered_out_unmapped,
            "exchange_not_configured": filtered_out_exchange,
        },
        "added_held": [],
    }


def _keep_membership(
    session: Session, rows: list[Instrument], members: list[Instrument], config: Any
) -> dict[str, Any]:
    """Every run after the first: add the positions the account has taken, remove nothing.

    **A held position is always added**, seeding or not: what the account owns is a fact rather
    than a preference, and the whole point of the analysis is to say something about it.
    Nothing here ever sets ``in_universe`` back to ``False`` -- only :func:`remove` does that,
    and only because a person asked.
    """
    added = [row for row in rows if row.is_held and not row.in_universe]
    for row in added:
        row.in_universe = True
    if initialisation(session) is None:
        # Populated before the flag existed: record the size it was standing at, so a later
        # empty universe is not mistaken for one that was never populated.
        _record_initialisation(session, size=config.size, selected=len(members))
    session.flush()

    total = len(members) + len(added)
    return {
        "mode": "manual",
        "size_cap": config.size,
        "selected": total,
        "members": total,
        "eligible": len(rows),
        "instruments_stored": len(rows),
        "added_held": [row.t212_ticker for row in added],
        "filtered_out": {},
    }


def include(session: Session, ticker: str) -> bool:
    """Put one instrument into the analysed universe, and keep it there.

    **``pinned`` is the mechanism, and it already existed.** ``refresh_universe`` ranks a
    pinned name first and the quotes job polls pinned names intraday, so the flag says
    "somebody asked for this one" in the two places that care. Nothing set it until the search
    block did; every row in the live database is still ``pinned = 0``. It is written here
    rather than in the route so the definition of "in the universe" stays in one module.

    **Nothing displaces it.** The configured size seeds the universe once
    (:func:`refresh_universe`); after that a manual addition is a member alongside everything
    else, and only :func:`remove` takes one out.

    Returns ``False`` for a ticker this database does not hold. That is not "no such
    instrument": Trading 212's list is synced into ``instrument`` by ``t212_instruments``, so
    an unknown ticker means the sync has not run since it was listed.
    """
    row = session.get(Instrument, ticker)
    if row is None:
        return False
    row.pinned = True
    row.in_universe = True
    # An explicit exclusion is a decision not to analyse something, and adding it is a
    # decision to the contrary. Honouring the older one would make the button do nothing.
    row.excluded = False
    session.flush()
    return True


#: Fields on the instrument row that were *derived from the data being deleted*, and so are
#: cleared with it. The listing's own identity (name, ISIN, exchange, provider symbols) and
#: its classification (sector, industry, SIC) are kept: those describe the company, they came
#: from Trading 212 and the registers rather than from anything collected here, and throwing
#: them away would make re-adding an instrument start from nothing for no benefit.
_CLEARED_ON_REMOVAL: tuple[str, ...] = (
    "market_cap",
    "median_daily_turnover_gbp",
    "annual_reports",
    "reports_synced_at",
    "news_polled_at",
    "marketaux_polled_at",
)


def _held_about(ticker: str) -> list[tuple[str, Any, Any]]:
    """Everything this project collected about one instrument: label, table, predicate.

    **One list, used twice.** :func:`footprint` counts it for the confirmation page and
    :func:`remove` deletes it. Two lists -- one to count and one to delete -- would be a
    second source of truth for what removal means, and the failure mode is the quiet one: a
    table shown to the reader as "will be deleted" that is in fact left behind, or the
    reverse, is not visible afterwards in either direction.

    The tables absent from this list are absent deliberately, and the confirmation page names
    them: ``news_item`` (an observation about the world that may name several instruments --
    only the per-subject appraisal goes), ``t212_order`` (the account's own trade history,
    re-synced from the broker) and the correction/adopted rules in ``app_setting`` (keyed by
    the filer, shared by that filer's other listings, and wanted again if this one is
    re-added).
    """
    news_subject = (NewsAnalysis.subject_type == "instrument") & (
        NewsAnalysis.subject_id == ticker
    )
    sentiment_subject = (SentimentSeries.scope_type == "instrument") & (
        SentimentSeries.scope_id == ticker
    )
    research_subject = (ResearchReport.subject_type == "instrument") & (
        ResearchReport.subject_id == ticker
    )
    return [
        ("price bars", PriceBar, PriceBar.instrument_t212_ticker == ticker),
        ("quotes", Quote, Quote.instrument_t212_ticker == ticker),
        ("filed documents", Filing, Filing.instrument_t212_ticker == ticker),
        (
            "accounting periods",
            FundamentalPeriod,
            FundamentalPeriod.instrument_t212_ticker == ticker,
        ),
        ("refreshes", InstrumentRefresh, InstrumentRefresh.instrument_t212_ticker == ticker),
        ("blockers", InstrumentBlocker, InstrumentBlocker.instrument_t212_ticker == ticker),
        ("levers", InstrumentLever, InstrumentLever.instrument_t212_ticker == ticker),
        ("valuations", ValuationRun, ValuationRun.instrument_t212_ticker == ticker),
        # The outcomes cascade from these, which is why they are not listed separately.
        ("decisions", DecisionRun, DecisionRun.instrument_t212_ticker == ticker),
        ("news appraisals", NewsAnalysis, news_subject),
        ("sentiment series", SentimentSeries, sentiment_subject),
        ("research reports", ResearchReport, research_subject),
    ]


def footprint(session: Session, ticker: str) -> dict[str, int]:
    """How much of each thing a removal would delete, for the confirmation page."""
    counts: dict[str, int] = {}
    for label, model, predicate in _held_about(ticker):
        counts[label] = int(
            session.execute(
                select(func.count()).select_from(model).where(predicate)
            ).scalar_one()
            or 0
        )
    return counts


def removable(session: Session, ticker: str) -> str | None:
    """Why this instrument cannot be removed, or ``None`` if it can.

    One function rather than a rule repeated on the page and in the route, because the two
    disagreeing is how a button appears that the server then refuses. The reasons are codes,
    not sentences: the page turns them into prose the way every other outcome in this
    codebase is turned into prose.
    """
    row = session.get(Instrument, ticker)
    if row is None:
        return "unknown"
    if row.is_held:
        # `refresh_universe` adds held instruments back, so allowing this would produce a
        # button that appears to work and is quietly undone by the next run.
        return "held"
    if not row.in_universe:
        return "not-in-universe"
    if ticker in lease.locked_tickers(session):
        # A scoped refresh is mid-write for this instrument. Deleting rows under it would
        # leave the run's own accounting removed and the instrument half-populated.
        #
        # `lease.current` is the wrong question here and looks like the right one: it returns
        # the instrument's lease row *held or not*, and every instrument that has ever been
        # refreshed has one, so testing it made every refreshed instrument look busy.
        return "busy"
    return None


def remove(
    session: Session, ticker: str, settings: Settings | None = None
) -> dict[str, Any]:
    """Take one instrument out of the universe and delete everything collected about it.

    The listing itself stays -- see ``_CLEARED_ON_REMOVAL`` for what is reset and
    :func:`include` for why the row is kept -- so the search block offers it again straight
    away and re-adding it does not wait for the next ``t212_instruments`` sync.

    Returns ``{"refused": reason}`` rather than deleting anything when :func:`removable`
    says no, so a hand-made POST cannot do what the page would not offer.

    **The rows go in one transaction, the files after it commits.** A crash in between leaves
    the rows gone and two orphaned directories, which the next removal of the same ticker
    clears; the alternative order would leave rows pointing at documents that are no longer
    there, which every reader of a filing would have to cope with.
    """
    settings = settings or get_settings()
    reason = removable(session, ticker)
    if reason is not None:
        return {"refused": reason}

    removed: dict[str, int] = {}
    for label, model, predicate in _held_about(ticker):
        result = session.execute(delete(model).where(predicate))
        removed[label] = int(result.rowcount or 0)

    row = session.get(Instrument, ticker)
    if row is not None:
        row.in_universe = False
        row.pinned = False
        # Deliberately *not* `excluded`: that flag is honoured at read time as "never analyse
        # this", and it would also hide the instrument from the search block, leaving no way
        # back. Removing is a membership change, not a blocklist.
        for name in _CLEARED_ON_REMOVAL:
            setattr(row, name, None if name != "annual_reports" else 0)
    session.flush()
    session.commit()

    files = _remove_files(settings, ticker)
    logger.info("removed %s from the universe: %s", ticker, removed)
    return {"ticker": ticker, "removed": removed, "files": files["files"], "bytes": files["bytes"]}


def _remove_files(settings: Settings, ticker: str) -> dict[str, int]:
    """Delete the two directory trees this project writes for one instrument.

    Both are nested by instrument, which is what makes this a directory rather than a list of
    paths: `ingest.documents` owns where a filing is kept and `research.report` owns where a
    report is, so both are asked rather than having their layout restated here.
    """
    import shutil

    from awltux.ingest.documents import instrument_dir
    from awltux.research.report import subject_dir

    count = 0
    size = 0
    for directory in (
        instrument_dir(settings, ticker),
        subject_dir(settings, "instrument", ticker),
    ):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                count += 1
                size += path.stat().st_size
        shutil.rmtree(directory, ignore_errors=True)
    return {"files": count, "bytes": size}


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

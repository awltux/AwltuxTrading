"""Scheduled job entry points.

Each function opens its own session and returns a
:class:`~awltux.scheduler.jobs.JobResult`. They are intentionally thin: all the
work lives in the ingest modules, which are directly testable without the
scheduler.

A job is allowed to fail. The scheduler records the failure and moves on, because
one unreachable free-tier provider must not stop the prices, the filings and the
decisions from being refreshed.
"""

from __future__ import annotations

import logging
from typing import Any

from awltux.config import get_settings
from awltux.db import session_scope
from awltux.scheduler.jobs import JobResult

logger = logging.getLogger(__name__)

#: Rows the relevance backfill will load in one run. Only bounds memory: the work
#: that costs money is capped separately, by ``news.relevance_backfill_per_run``.
RELEVANCE_BACKFILL_ROWS = 5_000


def universe_is_empty(session) -> bool:
    """Whether anything is actually in scope for the universe-driven jobs.

    Several jobs read ``in_universe`` instruments and legitimately do nothing when
    there are none -- but they reported that as a bare ``0``, which looks
    identical to a job that ran and found no news. Naming the cause is the
    difference between "nothing happened" and "nothing could happen".
    """
    from sqlalchemy import func, select

    from awltux.db import Instrument

    count = session.execute(
        select(func.count())
        .select_from(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    ).scalar_one()
    return int(count or 0) == 0


def empty_universe_note(session) -> str | None:
    """Explain a zero-result run, or return ``None`` if the universe is populated."""
    if not universe_is_empty(session):
        return None

    from sqlalchemy import func, select

    from awltux.db import Instrument

    total = session.execute(select(func.count()).select_from(Instrument)).scalar_one()
    if int(total or 0) == 0:
        return (
            "nothing to do: no instruments are stored yet. Run the "
            "'t212_instruments' job first (it needs a working Trading 212 API key)."
        )
    return (
        f"nothing to do: {total} instruments are stored but none are in the "
        "analysed universe. Run the 'universe_refresh' job, or check that the "
        "instrument window includes the exchanges you want."
    )


def sync_instruments() -> JobResult:
    """Pull the Trading 212 instrument universe and resolve provider symbols.

    **Fetch first, then persist.** Trading 212's limits are strict enough that a
    call can sleep for a minute inside the rate-limit guard, and holding a
    transaction across that wait takes SQLite's write lock for the whole time --
    which is what produced "database is locked" for every other writer, and for
    readers once ``BEGIN IMMEDIATE`` was in play.
    """
    from awltux.ingest.universe import (
        synchronize_instruments,
    )
    from awltux.providers.t212 import T212Provider

    provider = T212Provider()

    # --- network phase: no transaction open ---------------------------------
    exchanges = provider.get_exchanges()
    instruments = provider.get_instruments()

    try:
        positions = provider.get_positions()
        holds_readable = True
    except Exception as exc:
        # A metadata-only key cannot read positions. That is a supported
        # configuration, so it is recorded rather than treated as a failure.
        logger.info("positions are not readable with this key: %s", exc)
        positions = []
        holds_readable = False

    # --- database phase: short, and with nothing left to wait for -----------
    with session_scope() as session:
        report = synchronize_instruments(
            session, provider=provider, exchanges=exchanges, instruments=instruments
        )
        held = _apply_positions(session, positions) if holds_readable else 0
        capabilities = _record_capabilities(session, holds_readable, bool(exchanges))

    return JobResult(
        items_seen=report.instruments_seen,
        items_written=report.instruments_created + report.instruments_updated,
        detail={**report.as_dict(), "held": held, "capabilities": capabilities},
    )


def _apply_positions(session, positions: list[dict[str, Any]]) -> int:
    """Flag held instruments from an already-fetched positions payload."""
    from sqlalchemy import select

    from awltux.db import Instrument

    held = {
        str((position.get("instrument") or {}).get("ticker") or position.get("ticker"))
        for position in positions
    }
    held.discard("None")
    count = 0
    for row in session.execute(select(Instrument)).scalars().all():
        was_held = row.is_held
        row.is_held = row.t212_ticker in held
        if row.is_held and not was_held:
            count += 1
    session.flush()
    return len(held)


def _record_capabilities(session, holds_readable: bool, metadata_ok: bool) -> dict[str, Any]:
    """Cache what this key can do, so the UI can explain a reduced feature set."""
    from awltux.db import AppSetting, utcnow
    from awltux.ingest.universe import CAPABILITIES_KEY

    capabilities: dict[str, Any] = {
        "metadata": metadata_ok,
        "portfolio": holds_readable,
        "checked_at": utcnow().isoformat(),
        "errors": {}
        if holds_readable
        else {"portfolio": "the key lacks the 'portfolio' scope, or the read failed"},
    }
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
    return capabilities


def refresh_universe() -> JobResult:
    """Re-select which instruments are actively analysed.

    The ``note`` matters more here than in most jobs. This runs on startup
    alongside ``t212_instruments``, and on a fresh database it can read the
    instrument table before that job has committed -- producing a run that selected
    nothing and looks identical to a legitimate "no instrument qualified". That
    happened: the container's own run history shows the two jobs starting 2ms
    apart, the refresh seeing 0 instruments, and the next run selecting 500.
    """
    from awltux.ingest.universe import refresh_universe as _refresh

    with session_scope() as session:
        stats = _refresh(session)

    stored = stats.get("instruments_stored", 0)
    eligible = stats.get("eligible", 0)
    selected = stats.get("selected", 0)

    note: str | None = None
    if selected == 0:
        if stored == 0:
            note = (
                "no instruments are stored yet, so there was nothing to select from. "
                "This is expected on a fresh database while t212_instruments is still "
                "running; re-run once it has finished."
            )
        elif eligible == 0:
            filters = stats.get("filtered_out") or {}
            reasons = ", ".join(f"{count} by {name}" for name, count in filters.items() if count)
            note = (
                f"{stored} instruments stored but none eligible"
                + (f" ({reasons})" if reasons else "")
                + ". Check universe.instrument_types and universe.exchanges."
            )

    return JobResult(
        items_seen=eligible,
        items_written=selected,
        note=note,
        detail=stats,
    )


def refresh_prices_eod() -> JobResult:
    """End-of-day OHLCV for the whole universe, plus FX for the majors.

    Alternates network and database phases per batch rather than wrapping the
    whole run in one transaction. A single transaction spanning every batch would
    hold SQLite's write lock across hundreds of provider calls, locking out the
    dashboard for the duration.
    """
    from awltux.analysis import fx
    from awltux.ingest.prices import (
        PriceIngestReport,
        chunks,
        load_price_targets,
        persist_batch,
        update_turnover_estimates,
    )
    from awltux.providers.yahoo import YahooProvider

    settings = get_settings()
    provider = YahooProvider(settings)
    report = PriceIngestReport()

    # --- database phase: which instruments, and their symbols ----------------
    with session_scope() as session:
        targets = load_price_targets(session)
    report.tickers_requested = len(targets)
    if not targets:
        return JobResult(detail={**report.as_dict(), "skipped": "empty universe"})

    symbols = list(targets)
    for batch in chunks(symbols, 40):
        # --- network phase: no transaction open -----------------------------
        try:
            series_map = provider.get_history_batch(batch, period="2y")
        except Exception as exc:
            logger.warning("price batch failed (%d symbols): %s", len(batch), exc)
            report.tickers_failed.extend(batch)
            continue

        # --- database phase: short ------------------------------------------
        with session_scope() as session:
            persist_batch(session, batch, series_map, report=report)

    # --- turnover and FX, each in their own short phase ---------------------
    with session_scope() as session:
        report.turnover_updated = update_turnover_estimates(session)

    rates = fx.refresh_common_rates()

    return JobResult(
        items_seen=report.tickers_requested,
        items_written=report.bars_written,
        detail={**report.as_dict(), "fx": rates},
    )


def refresh_prices_intraday() -> JobResult:
    """Quotes for held and pinned names while their markets are open."""
    from sqlalchemy import select

    from awltux.db import Instrument
    from awltux.ingest.prices import QuoteIngestReport, persist_quotes
    from awltux.providers.yahoo import YahooProvider

    settings = get_settings()
    provider = YahooProvider(settings)

    with session_scope() as session:
        # Intraday polling is rationed: held and pinned names only. Refreshing
        # quotes for 500 names every 15 minutes would exhaust the free tier.
        rows = session.execute(
            select(Instrument).where(
                Instrument.is_held.is_(True) | Instrument.pinned.is_(True)
            )
        ).scalars().all()
        targets = [
            (row.t212_ticker, row.yahoo_symbol)
            for row in rows
            if row.yahoo_symbol
        ]

    if not targets:
        return JobResult(detail={"skipped": "no held or pinned instruments"})

    report = QuoteIngestReport(tickers_requested=len(targets))
    # --- network phase ------------------------------------------------------
    snapshots: list[tuple[str, object]] = []
    for ticker, symbol in targets:
        try:
            snapshots.append((ticker, provider.get_quote(symbol)))
        except Exception as exc:
            logger.debug("quote failed for %s: %s", symbol, exc)
            report.tickers_failed.append(symbol)

    # --- database phase -----------------------------------------------------
    with session_scope() as session:
        persist_quotes(session, snapshots, report=report)

    return JobResult(
        items_seen=report.tickers_requested,
        items_written=report.tickers_returned,
        detail=report.as_dict(),
    )


def ingest_news_rss() -> JobResult:
    """Poll RSS and optional providers, then classify anything new."""
    from awltux.ingest.news import ingest_rss_news
    from awltux.llm.classify import build_classifier

    classifier = build_classifier()
    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            # A bare zero here was misleading: it looked like "no news was
            # published" rather than "there was nothing to look for".
            logger.info("news ingest skipped: %s", note)
            return JobResult(note=note)
        report = ingest_rss_news(session, classifier=classifier)

    return JobResult(
        items_seen=report.fetched,
        items_written=report.written,
        note=(
            "polled the whole universe but every feed returned nothing"
            if report.fetched == 0
            else None
        ),
        detail=report.as_dict(),
    )


def analyse_news() -> JobResult:
    """Sceptically appraise recent news: sources, framing, corroboration, claims.

    Deliberately a separate job from the poll. The poll is volume work on hundreds
    of loose headlines and has to stay cheap; this is per-story work that costs a
    model call for the stories that warrant one, and mixing the two would put the
    paid work on the critical path of every five-minute poll.
    """
    from awltux.analysis.news_analysis import analyse_universe
    from awltux.config import get_settings
    from awltux.llm.news_sceptic import build_analyser

    settings = get_settings()
    config = settings.news.scepticism
    if not config.enabled:
        return JobResult(note="news scepticism is disabled in configuration")

    analyser = build_analyser(settings)
    with session_scope() as session:
        report = analyse_universe(
            session,
            settings=settings,
            analyser=analyser,
            days=config.lookback_days,
            limit=config.max_deep_per_run,
            refresh_after_days=config.refresh_after_days,
        )

    if report["examined"] == 0:
        note = "no news in the lookback window to appraise"
    elif report["selected"] == 0:
        note = (
            f"appraised nothing: none of the {report['examined']} recent items cleared "
            "the interest threshold (materiality, framing, held position or thin coverage)"
        )
    elif analyser is None:
        note = (
            "deterministic appraisal only: DeepSeek is not configured, so claims, "
            "omissions and primary-source tracing were not produced"
        )
    else:
        note = None

    return JobResult(
        items_seen=report["selected"],
        items_written=report["appraised"],
        note=note,
        detail=report,
    )


def assess_news_relevance() -> JobResult:
    """Decide whether stored stories are claims about a share price.

    Relevance is normally settled at ingest, by the same classifier call that
    produces the direction. This job exists for the rows that call never reached:

    * items stored before the classifier was configured (the deployment has 261 of
      them, all with ``direction`` and ``materiality`` NULL);
    * items whose classification failed on a transient error;
    * everything written before this rule existed, which the migration deliberately
      left NULL rather than deciding in an unattended schema change.

    It is a separate job from ``news_analysis`` because the two cost very different
    things and answer different questions. Relevance is one cheap classification
    per story -- about a five-hundred-token prompt -- while the scepticism
    appraisal is a deep read rationed to sixty calls a run. Putting them in one job
    would make the cheap backfill wait behind the expensive one.

    Rationed for the same reason every other paid job is: a bounded number of model
    calls per run, oldest first, so a backlog drains over several runs instead of
    spending the month's budget in one. The bound is on calls rather than on rows,
    because the rows decided from what is already stored cost nothing.
    """
    from sqlalchemy import select

    from awltux.analysis.relevance import assess
    from awltux.config import get_settings
    from awltux.db import Instrument, NewsItem
    from awltux.db.session import release_write_lock
    from awltux.llm.classify import build_classifier
    from awltux.providers.news_rss import RawNewsItem

    settings = get_settings()
    # The cap is on *model calls*, not rows. Relevance is decided structurally
    # wherever a direction is already stored -- which is 5,500 of the 5,800 rows in
    # this deployment -- so bounding the row window would make a free, instant
    # backfill take thirty runs to drain while protecting nothing. The paid work is
    # what needs rationing, and the row window is only there to bound memory.
    call_limit = settings.news.relevance_backfill_per_run
    row_limit = RELEVANCE_BACKFILL_ROWS
    classifier = build_classifier(settings)

    with session_scope() as session:
        pending = list(
            session.execute(
                select(NewsItem)
                .where(NewsItem.relevant.is_(None))
                .order_by(NewsItem.id)
                .limit(row_limit)
            ).scalars().all()
        )
        if not pending:
            return JobResult(note="every stored story already has a relevance verdict")

        # Resolve the instrument a story was fetched for, so the classifier is
        # asked about the right company rather than about the ticker string.
        wanted = {ticker for item in pending for ticker in (item.tickers or [])}
        instruments = (
            {
                row.t212_ticker: row
                for row in session.execute(
                    select(Instrument).where(Instrument.t212_ticker.in_(wanted))
                ).scalars().all()
            }
            if wanted
            else {}
        )

        assessed = 0
        classified = 0
        structural = 0
        errors: list[str] = []

        for item in pending:
            instrument = next(
                (instruments.get(ticker) for ticker in (item.tickers or []) if instruments.get(ticker)),
                None,
            )
            about: bool | None = None

            # Only ask the model where there is something to ask. A row that already
            # carries a direction is decided entirely by the structural half of the
            # rule, and re-classifying it would pay again for an answer that is
            # already stored -- 5,500 of the 5,800 rows in this deployment are in
            # that position. The model is needed only for rows whose classification
            # never ran or failed, which is the backlog this job exists for.
            # The row window bounds memory; the call limit bounds spend.
            needs_model = (
                item.direction is None
                and classifier is not None
                and instrument is not None
                and classified < call_limit
            )
            if needs_model:
                # The same rule the ingest path follows: no provider call inside an
                # open transaction.
                release_write_lock(session)
                raw = RawNewsItem(
                    title=item.title,
                    url=item.url or "",
                    source=item.source,
                    summary=item.summary,
                    published_at=item.published_at,
                    tickers=list(item.tickers or []),
                )
                try:
                    updates = classifier(raw, instrument)
                except Exception as exc:  # noqa: BLE001 - one story must not stop the run
                    errors.append(f"{item.id}: {exc}")
                    updates = None
                if updates:
                    item.materiality = updates.get("materiality")
                    item.direction = updates.get("direction")
                    item.horizon = updates.get("horizon")
                    item.sentiment_score = updates.get("sentiment_score")
                    item.relevance = updates.get("relevance")
                    item.engine = updates.get("engine")
                    item.event_type = updates.get("event_type")
                    reasoning = updates.get("reasoning")
                    if reasoning:
                        item.relevance_reason = str(reasoning)[:1000]
                    about = updates.get("is_about_this_company")
                    classified += 1
            else:
                structural += 1

            verdict = assess(
                tickers=item.tickers,
                sectors=item.sectors,
                direction=item.direction,
                materiality=item.materiality,
                about=about,
            )
            item.relevant = verdict.relevant
            if not item.relevance_reason:
                item.relevance_reason = verdict.reason
            assessed += 1

        session.flush()

    if classifier is None:
        note = (
            "relevance recorded structurally only: DeepSeek is not configured, so "
            "stories with no stored direction are not relevant"
        )
    elif classified == 0:
        note = (
            f"no model calls needed: all {assessed} stories already carried a stored "
            "direction, so the rule decided them"
        )
    elif classified >= call_limit:
        remaining = len(pending) - assessed
        note = (
            f"hit the {call_limit}-call ceiling for one run; "
            f"{remaining} stories were not examined and will be picked up next run"
        )
    else:
        note = (
            f"{classified} stories had no direction and were classified; {structural} "
            "were decided from what was already stored"
        )

    return JobResult(
        items_seen=len(pending),
        items_written=assessed,
        note=note,
        detail={
            "assessed": assessed,
            "classified": classified,
            "decided_structurally": structural,
            "errors": errors[:10],
        },
    )


def ingest_edgar_events() -> JobResult:
    """Poll EDGAR's current-events feed for new US filings."""
    from awltux.ingest.edgar import ingest_current_events

    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("edgar event ingest skipped: %s", note)
            return JobResult(note=note)
        report = ingest_current_events(session)

    return JobResult(
        items_seen=len(report.errors),
        items_written=report.events_written,
        detail=report.as_dict(),
    )


def sync_filings() -> JobResult:
    """Refresh filing history for instruments with a resolved CIK."""
    from sqlalchemy import func, select

    from awltux.db import Instrument
    from awltux.ingest.edgar import resolve_ciks
    from awltux.ingest.edgar import sync_filings as _sync

    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("filing sync skipped: %s", note)
            return JobResult(note=note)

        with_cik = session.execute(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.sec_cik.is_not(None))
        ).scalar_one()

        resolution = resolve_ciks(session)
        if int(with_cik or 0) == 0 and not resolution.resolved:
            # Worth naming explicitly: EDGAR covers US filers only, so a
            # London-only book legitimately has nothing here.
            return JobResult(
                note=(
                    "no instruments have a resolved SEC CIK. EDGAR covers US "
                    "filers only; a London-only listing is absent by design and is "
                    "served by Companies House instead."
                ),
                detail={"cik_resolution": resolution.as_dict()},
            )

        report = _sync(session)

    return JobResult(
        items_seen=report.filings_seen,
        items_written=report.filings_written,
        detail={**report.as_dict(), "cik_resolution": resolution.as_dict()},
    )


def sync_fundamentals_job() -> JobResult:
    """Rotating fundamentals refresh, rationed to keep within free-tier limits.

    The configured per-day rotation is divided across the 24 hourly runs so the
    load is spread rather than concentrated in one burst.
    """
    settings = get_settings()
    from awltux.ingest.fundamentals import sync_fundamentals

    per_run = max(1, settings.schedule.fundamentals_rotation_per_day // 24)
    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("fundamentals sync skipped: %s", note)
            return JobResult(note=note)
        report = sync_fundamentals(session, limit=per_run)

    return JobResult(
        items_seen=report.tickers_attempted,
        items_written=report.periods_written,
        detail={**report.as_dict(), "per_run_limit": per_run},
    )


def resolve_uk_companies_job() -> JobResult:
    """Attach Companies House numbers to UK-listed instruments."""
    from awltux.ingest.fundamentals import resolve_uk_companies

    with session_scope() as session:
        summary = resolve_uk_companies(session, limit=50)

    return JobResult(
        items_seen=summary.get("attempted", 0),
        items_written=summary.get("matched", 0),
        detail=summary,
    )


def run_valuations() -> JobResult:
    """Recompute the deterministic valuation for the universe."""
    from awltux.analysis.valuation import run_valuations as _run

    with session_scope() as session:
        stats = _run(session)

    return JobResult(
        items_seen=stats.get("attempted", 0),
        items_written=stats.get("valued", 0),
        detail=stats,
    )


def run_decisions() -> JobResult:
    """Produce a fresh decision for every instrument whose inputs changed."""
    from awltux.decision.service import decide_universe

    with session_scope() as session:
        stats = decide_universe(session)

    return JobResult(
        items_seen=stats.get("attempted", 0),
        items_written=stats.get("decided", 0),
        detail=stats,
    )


def update_calibration() -> JobResult:
    """Score elapsed decisions against subsequent prices."""
    from awltux.audit.calibration import score_pending_decisions

    with session_scope() as session:
        stats = score_pending_decisions(session)

    return JobResult(
        items_seen=stats.get("scored", 0) + stats.get("skipped_no_price", 0),
        items_written=stats.get("scored", 0),
        detail=stats,
    )


def aggregate_sentiment() -> JobResult:
    """Roll news items up into per-stock and per-sector sentiment series."""
    from awltux.analysis.sentiment import aggregate_all

    with session_scope() as session:
        stats = aggregate_all(session)

    return JobResult(
        items_seen=stats.get("instruments_seen", 0),
        items_written=stats.get("rows_written", 0),
        detail=stats,
    )


def apply_retention() -> JobResult:
    """Prune high-volume tables according to the retention policy."""
    import datetime as dt

    from sqlalchemy import delete

    from awltux.db import LLMCall, Quote

    settings = get_settings()
    retention = settings.retention
    now = dt.datetime.now(dt.UTC)
    removed: dict[str, int] = {}

    with session_scope() as session:
        quote_cutoff = now - dt.timedelta(days=retention.quote_days)
        result = session.execute(delete(Quote).where(Quote.ts < quote_cutoff))
        removed["quotes"] = result.rowcount or 0

        llm_cutoff = now - dt.timedelta(days=retention.llm_call_days)
        result = session.execute(delete(LLMCall).where(LLMCall.created_at < llm_cutoff))
        removed["llm_calls"] = result.rowcount or 0

    return JobResult(items_written=sum(removed.values()), detail={"removed": removed})

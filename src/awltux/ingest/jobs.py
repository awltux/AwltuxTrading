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

from awltux.config import get_settings
from awltux.db import session_scope
from awltux.scheduler.jobs import JobResult

logger = logging.getLogger(__name__)


def sync_instruments() -> JobResult:
    """Pull the Trading 212 instrument universe and resolve provider symbols."""
    from awltux.ingest.universe import (
        mark_held_instruments,
        refresh_t212_capabilities,
        synchronize_instruments,
    )

    with session_scope() as session:
        report = synchronize_instruments(session)
        held = mark_held_instruments(session)
        # Probe the key's scopes here rather than per request: the answer changes
        # only when the key does, and the dashboard needs it to explain why
        # holdings may be empty.
        capabilities = refresh_t212_capabilities(session)

    return JobResult(
        items_seen=report.instruments_seen,
        items_written=report.instruments_created + report.instruments_updated,
        detail={**report.as_dict(), "held": held, "capabilities": capabilities},
    )


def refresh_universe() -> JobResult:
    """Re-select which instruments are actively analysed."""
    from awltux.ingest.universe import refresh_universe as _refresh

    with session_scope() as session:
        stats = _refresh(session)

    return JobResult(
        items_seen=stats.get("eligible", 0),
        items_written=stats.get("selected", 0),
        detail=stats,
    )


def refresh_prices_eod() -> JobResult:
    """End-of-day OHLCV for the whole universe, plus FX for the majors."""
    from awltux.analysis import fx
    from awltux.ingest.prices import refresh_prices

    with session_scope() as session:
        report = refresh_prices(session)
        rates = fx.refresh_common_rates()

    return JobResult(
        items_seen=report.tickers_requested,
        items_written=report.bars_written,
        detail={**report.as_dict(), "fx": rates},
    )


def refresh_prices_intraday() -> JobResult:
    """Quotes for held and pinned names while their markets are open."""
    from awltux.ingest.prices import refresh_quotes

    with session_scope() as session:
        from sqlalchemy import select

        from awltux.db import Instrument

        # Intraday polling is rationed: held and pinned names only. Refreshing
        # quotes for 500 names every 15 minutes would exhaust the free tier.
        tickers = [
            row.t212_ticker
            for row in session.execute(
                select(Instrument).where(Instrument.is_held.is_(True) | Instrument.pinned.is_(True))
            ).scalars().all()
        ]
        if not tickers:
            return JobResult(detail={"skipped": "no held or pinned instruments"})
        report = refresh_quotes(session, tickers=tickers)

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
        report = ingest_rss_news(session, classifier=classifier)

    return JobResult(
        items_seen=report.fetched,
        items_written=report.written,
        detail=report.as_dict(),
    )


def ingest_edgar_events() -> JobResult:
    """Poll EDGAR's current-events feed for new US filings."""
    from awltux.ingest.edgar import ingest_current_events

    with session_scope() as session:
        report = ingest_current_events(session)

    return JobResult(
        items_seen=len(report.errors),
        items_written=report.events_written,
        detail=report.as_dict(),
    )


def sync_filings() -> JobResult:
    """Refresh filing history for instruments with a resolved CIK."""
    from awltux.ingest.edgar import resolve_ciks
    from awltux.ingest.edgar import sync_filings as _sync

    with session_scope() as session:
        resolution = resolve_ciks(session)
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

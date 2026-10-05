"""Builds the concrete job list from settings.

Kept separate from :mod:`awltux.scheduler.service` so the service stays generic
and testable with fake jobs.

Each job is gated on the credentials it actually needs, so a missing API key
disables that job *visibly* (it still appears in the health panel, marked
disabled) rather than failing on every tick and burying the real error.
"""

from __future__ import annotations

import logging

from awltux.config import Settings, get_settings
from awltux.scheduler.jobs import JobSpec

logger = logging.getLogger(__name__)


def build_job_specs(settings: Settings | None = None) -> list[JobSpec]:
    """Assemble the scheduled jobs for this deployment."""
    settings = settings or get_settings()
    env = settings.env
    schedule = settings.schedule

    from awltux.ingest import jobs as ingest_jobs

    t212_ready = env.t212_configured
    specs: list[JobSpec] = [
        # --- reference data --------------------------------------------------
        JobSpec(
            id="t212_instruments",
            func=ingest_jobs.sync_instruments,
            interval_seconds=schedule.t212_instruments,
            description="Sync Trading 212 instruments, exchanges and symbol mappings",
            run_on_start=True,
            jitter_seconds=30,
            enabled=t212_ready,
            requires=("T212_API_KEY", "T212_API_SECRET"),
        ),
        JobSpec(
            id="universe_refresh",
            func=ingest_jobs.refresh_universe,
            interval_seconds=schedule.t212_instruments,
            description="Re-select the analysed universe by size and liquidity",
            run_on_start=True,
            jitter_seconds=180,
            enabled=t212_ready,
            requires=("T212_API_KEY", "T212_API_SECRET"),
        ),
        # --- prices ----------------------------------------------------------
        JobSpec(
            id="price_eod",
            func=ingest_jobs.refresh_prices_eod,
            interval_seconds=schedule.prices_eod,
            description="End-of-day OHLCV for the universe, plus FX rates",
            jitter_seconds=1200,
            enabled=True,
        ),
        JobSpec(
            id="price_intraday",
            func=ingest_jobs.refresh_prices_intraday,
            interval_seconds=schedule.prices_intraday,
            description="Quotes for held and pinned names during market hours",
            jitter_seconds=60,
            enabled=True,
        ),
        # --- fundamentals & filings -----------------------------------------
        JobSpec(
            id="fundamentals",
            # Runs hourly and refreshes a slice of the universe each time, so the
            # per-day rotation is spread evenly instead of firing once and
            # hammering the provider for 500 symbols in a single pass.
            func=ingest_jobs.sync_fundamentals_job,
            interval_seconds=3600,
            description="Rotating fundamentals refresh, rationed to the free tier",
            jitter_seconds=300,
            enabled=True,
        ),
        JobSpec(
            id="filings_edgar",
            func=ingest_jobs.sync_filings,
            interval_seconds=schedule.edgar_submissions,
            description="Refresh SEC EDGAR filing history for US filers",
            jitter_seconds=120,
            enabled=True,
        ),
        JobSpec(
            id="edgar_events",
            func=ingest_jobs.ingest_edgar_events,
            interval_seconds=schedule.edgar_atom_events,
            description="Poll the SEC EDGAR current-events feed for new US filings",
            jitter_seconds=5,
            enabled=True,
        ),
        JobSpec(
            id="uk_companies",
            func=ingest_jobs.resolve_uk_companies_job,
            interval_seconds=schedule.companies_house,
            description="Resolve UK listings to Companies House company numbers",
            jitter_seconds=60,
            enabled=bool(env.companies_house_api_key),
            requires=("COMPANIES_HOUSE_API_KEY",),
        ),
        # --- news & sentiment ------------------------------------------------
        JobSpec(
            id="news_rss",
            func=ingest_jobs.ingest_news_rss,
            interval_seconds=schedule.news_rss,
            description="Poll news feeds and classify new headlines",
            jitter_seconds=45,
            enabled=True,
        ),
        JobSpec(
            id="news_analysis",
            func=ingest_jobs.analyse_news,
            interval_seconds=schedule.news_analysis,
            description=(
                "Appraise news sceptically: publisher, framing, independent "
                "sources, claims and omissions"
            ),
            jitter_seconds=120,
            enabled=True,
        ),
        JobSpec(
            id="sentiment",
            func=ingest_jobs.aggregate_sentiment,
            interval_seconds=schedule.sentiment_aggregate,
            description="Aggregate news into per-stock and per-sector sentiment",
            jitter_seconds=120,
            enabled=True,
        ),
        # --- analysis & decisions --------------------------------------------
        JobSpec(
            id="valuation",
            func=ingest_jobs.run_valuations,
            interval_seconds=schedule.valuation,
            description="Recompute deterministic fair-value ranges",
            jitter_seconds=600,
            enabled=True,
        ),
        JobSpec(
            id="decision",
            func=ingest_jobs.run_decisions,
            interval_seconds=schedule.decision,
            description="Produce typed decisions via JEV (or the fallback engines)",
            jitter_seconds=600,
            enabled=True,
        ),
        JobSpec(
            id="calibration",
            func=ingest_jobs.update_calibration,
            interval_seconds=schedule.calibration,
            description="Score elapsed decisions against subsequent prices",
            jitter_seconds=900,
            enabled=True,
        ),
        # --- housekeeping -----------------------------------------------------
        JobSpec(
            id="retention",
            func=ingest_jobs.apply_retention,
            interval_seconds=schedule.retention,
            description="Prune quotes and LLM call logs per the retention policy",
            jitter_seconds=1800,
            enabled=True,
        ),
    ]

    disabled = [spec.id for spec in specs if not spec.enabled]
    if disabled:
        logger.info("jobs disabled for missing credentials: %s", ", ".join(disabled))
    return specs

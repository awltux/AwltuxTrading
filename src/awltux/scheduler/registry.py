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
            id="macro_rates",
            func=ingest_jobs.refresh_macro_rates,
            interval_seconds=schedule.macro_rates,
            description=(
                "Observe the risk-free rate from the US Treasury par yield curve, "
                "which anchors every discount rate"
            ),
            # Needs nothing else, and everything downstream of the valuation model
            # is wrong without it: run it before the first sweep rather than a day
            # after it.
            run_on_start=True,
            enabled=True,
        ),
        JobSpec(
            id="provider_balance",
            func=ingest_jobs.refresh_provider_balances,
            interval_seconds=schedule.provider_balance,
            description=(
                "Ask each model provider what is left on the account, so an empty one "
                "is announced rather than discovered"
            ),
            # Nothing it reads is produced by another job, and it gates nothing: it is
            # the only job whose output is a *warning* rather than a dependency.
            run_on_start=True,
            enabled=True,
        ),
        JobSpec(
            id="t212_instruments",
            func=ingest_jobs.sync_instruments,
            interval_seconds=schedule.t212_instruments,
            description="Sync Trading 212 instruments, exchanges and symbol mappings",
            run_on_start=True,
            enabled=t212_ready,
            requires=("T212_API_KEY", "T212_API_SECRET"),
        ),
        JobSpec(
            id="t212_orders",
            func=ingest_jobs.sync_orders,
            interval_seconds=schedule.t212_orders,
            description=(
                "Store the account's order history, so an instrument page can show its "
                "buy and sell dates"
            ),
            # Deliberately not `run_on_start`: nothing depends on the trade history, so it
            # has no business delaying boot. The first run backfills and later runs are
            # incremental.
            enabled=t212_ready,
            requires=("T212_API_KEY", "T212_API_SECRET"),
        ),
        JobSpec(
            id="held_refresh",
            func=ingest_jobs.refresh_held,
            interval_seconds=schedule.held_refresh,
            description=(
                "Run the full refresh for every instrument the account holds, so a "
                "position's filings, news, valuation and decision stay current"
            ),
            # Held instruments are marked by the positions read inside `t212_instruments`,
            # so that is what this reads. Not `price_eod` or the rest: the refresh runs those
            # itself, for one company at a time.
            depends_on=("t212_instruments",),
            # A key that cannot read positions marks nothing as held, so the job would run
            # hourly and do nothing. Gated visibly instead.
            enabled=t212_ready,
            requires=("T212_API_KEY", "T212_API_SECRET"),
        ),
        JobSpec(
            id="symbol_resolution",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.resolve_symbols,
            interval_seconds=schedule.symbol_resolution,
            description=(
                "Look up the provider symbol by ISIN for instruments a derived one "
                "cannot reach"
            ),
            # After the universe exists, and after a price run has had a chance to
            # fail: the job's whole input is "instruments with no bars".
            depends_on=("t212_instruments", "price_eod"),
            enabled=True,
        ),
        JobSpec(
            id="universe_refresh",
            func=ingest_jobs.refresh_universe,
            interval_seconds=schedule.t212_instruments,
            description="Re-select the analysed universe by size and liquidity",
            run_on_start=True,
            depends_on=("t212_instruments",),
            # Deliberately after t212_instruments, which fetches from the network and
            # commits at the end. Both used to be scheduled for "now", so on a fresh
            # database the refresh read the instrument table before that commit and
            # selected nothing — the container's run history shows them starting 2ms
            # apart with the refresh seeing 0 instruments. Ordering by delay is a
            # heuristic rather than a guarantee, which is why the job also explains a
            # zero result instead of reporting a silent no-op.
            start_delay_seconds=900,
            enabled=t212_ready,
            requires=("T212_API_KEY", "T212_API_SECRET"),
        ),
        # --- prices ----------------------------------------------------------
        JobSpec(
            id="price_eod",
            func=ingest_jobs.refresh_prices_eod,
            interval_seconds=schedule.prices_eod,
            description="End-of-day OHLCV for the universe, plus FX rates",
            depends_on=("universe_refresh",),
            enabled=True,
        ),
        JobSpec(
            id="price_intraday",
            func=ingest_jobs.refresh_prices_intraday,
            interval_seconds=schedule.prices_intraday,
            description="Quotes for held and pinned names during market hours",
            # Needs instruments to know what is held, but nothing about the
            # analysis pipeline: it is a display feed, not an input to a decision.
            depends_on=("t212_instruments",),
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
            depends_on=("universe_refresh",),
            enabled=True,
        ),
        JobSpec(
            id="filings_edgar",
            func=ingest_jobs.sync_filings,
            interval_seconds=schedule.edgar_submissions,
            description="Refresh SEC EDGAR filing history for US filers",
            depends_on=("universe_refresh",),
            enabled=True,
        ),
        JobSpec(
            id="xbrl_statements",
            func=ingest_jobs.sync_xbrl_statements_job,
            # The same cadence as the filing history it depends on: EDGAR
            # publishes a company's facts once per annual report, so asking more
            # often than the filings change buys nothing.
            interval_seconds=schedule.edgar_submissions,
            description="Extract annual statements from XBRL company facts",
            depends_on=("universe_refresh", "filings_edgar"),
            # Only has work while its coverage probe reports a gap. For a filer
            # already stored, a companyfacts request is megabytes to rewrite
            # figures that have not changed.
            backfill=True,
            enabled=True,
        ),
        JobSpec(
            id="shareholder_reports",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.sync_shareholder_reports,
            interval_seconds=schedule.edgar_submissions,
            description=(
                "Download the annual reports: this year and the previous one, with "
                "the bytes kept"
            ),
            # After the filing history exists: this job's input is the annual-form
            # rows that job writes.
            depends_on=("filings_edgar",),
            enabled=True,
        ),
        JobSpec(
            id="edgar_events",
            func=ingest_jobs.ingest_edgar_events,
            interval_seconds=schedule.edgar_atom_events,
            description="Poll the SEC EDGAR current-events feed for new US filings",
            depends_on=("universe_refresh",),
            enabled=True,
        ),
        JobSpec(
            id="uk_companies",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.resolve_uk_companies_job,
            interval_seconds=schedule.companies_house,
            description="Resolve UK listings to Companies House company numbers",
            depends_on=("universe_refresh",),
            enabled=bool(env.companies_house_api_key),
            requires=("COMPANIES_HOUSE_API_KEY",),
        ),
        # --- news & sentiment ------------------------------------------------
        JobSpec(
            id="news_rss",
            func=ingest_jobs.ingest_news_rss,
            interval_seconds=schedule.news_rss,
            description="Poll news feeds and classify new headlines",
            depends_on=("universe_refresh",),
            enabled=True,
        ),
        JobSpec(
            id="news_sectors",
            func=ingest_jobs.ingest_sector_news_job,
            interval_seconds=schedule.news_sectors,
            description=(
                "Poll news for each industry sector, so a sector has stories of its own"
            ),
            # No dependency, and that is the point: this polls eleven sector feeds and
            # does not read the universe at all. Depending on `universe_refresh` would
            # be a claim about a relationship that does not exist, and would make the
            # poll wait behind a job that has nothing to do with it.
            enabled=True,
        ),
        JobSpec(
            id="news_analysis",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.analyse_news,
            interval_seconds=schedule.news_analysis,
            description=(
                "Appraise news sceptically: publisher, framing, independent "
                "sources, claims and omissions"
            ),
            # It appraises stored stories, so there must be stories to appraise.
            depends_on=("news_rss",),
            enabled=True,
        ),
        JobSpec(
            id="news_relevance",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.assess_news_relevance,
            interval_seconds=schedule.news_relevance,
            description=(
                "Decide whether stored stories are claims about a share price, "
                "and backfill the ones nothing has judged"
            ),
            # Deliberately *not* declared on news_analysis. Relevance is the cheap
            # classification that decides what belongs in the flash banner; the
            # appraisal is the expensive deep read that weights it. A story can be
            # relevant and unappraised, and blocking the banner's ordering behind a
            # job rationed to forty calls a run would leave it unsorted for days.
            depends_on=("news_rss",),
            enabled=True,
        ),
        JobSpec(
            id="news_embeddings",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.embed_news,
            interval_seconds=schedule.news_embeddings,
            description=(
                "Vectorise relevant stories so several outlets covering one event "
                "show as a single entry"
            ),
            # On news_rss, not on news_relevance: a story needs a vector to be
            # grouped, and it needs a relevance verdict to be worth the vector, so
            # the ordering is rss -> relevance -> embeddings. Declaring it on
            # relevance alone would leave it wedged whenever relevance had nothing
            # to do.
            depends_on=("news_relevance",),
            enabled=True,
        ),
        JobSpec(
            id="sentiment",
            func=ingest_jobs.aggregate_sentiment,
            interval_seconds=schedule.sentiment_aggregate,
            description="Aggregate news into per-stock and per-sector sentiment",
            # Declared on news_rss rather than news_analysis: the scepticism
            # appraisal improves the credibility weighting but is not required for
            # the aggregate to exist, so treating it as a hard dependency would
            # misreport a working pipeline as blocked.
            depends_on=("news_rss",),
            enabled=True,
        ),
        # --- analysis & decisions --------------------------------------------
        JobSpec(
            id="valuation",
            func=ingest_jobs.run_valuations,
            interval_seconds=schedule.valuation,
            description="Recompute deterministic fair-value ranges",
            depends_on=("price_eod", "fundamentals"),
            enabled=True,
        ),
        JobSpec(
            id="decision",
            func=ingest_jobs.run_decisions,
            interval_seconds=schedule.decision,
            description="Produce typed decisions via JEV (or the fallback engines)",
            # Price, accounts, sentiment and a valuation all reach the decision
            # state. Sentiment is listed last because it is the one the engines
            # tolerate missing; the others change the arithmetic.
            depends_on=("valuation", "sentiment"),
            enabled=True,
        ),
        JobSpec(
            id="calibration",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.update_calibration,
            interval_seconds=schedule.calibration,
            description="Score elapsed decisions against subsequent prices",
            # Prices again, because scoring needs the price at the horizon rather
            # than only at the decision.
            depends_on=("decision", "price_eod"),
            enabled=True,
        ),
        # --- housekeeping -----------------------------------------------------
        JobSpec(
            id="retention",
            # Only has work while its coverage probe reports a gap.
            backfill=True,
            func=ingest_jobs.apply_retention,
            interval_seconds=schedule.retention,
            description="Prune quotes and LLM call logs per the retention policy",
            enabled=True,
        ),
    ]

    disabled = [spec.id for spec in specs if not spec.enabled]
    if disabled:
        logger.info("jobs disabled for missing credentials: %s", ", ".join(disabled))
    return specs

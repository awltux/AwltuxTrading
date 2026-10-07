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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from awltux.db import Instrument

from awltux.config import get_settings
from awltux.db import session_scope
from awltux.scheduler import progress
from awltux.scheduler.jobs import JobResult

logger = logging.getLogger(__name__)

#: Rows the relevance backfill will load in one run. Only bounds memory: the work
#: that costs money is capped separately, by ``news.relevance_backfill_per_run``.
RELEVANCE_BACKFILL_ROWS = 5_000

#: Rows written before the backfill releases SQLite's write lock. See
#: ``INSTRUMENT_FLUSH_EVERY`` in ``ingest/universe.py`` for why an unbounded bulk
#: write is not acceptable here.
RELEVANCE_FLUSH_EVERY = 250


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


def refresh_prices_eod(tickers: list[str] | None = None) -> JobResult:
    """End-of-day OHLCV for the universe, plus FX for the majors.

    Alternates network and database phases per batch rather than wrapping the
    whole run in one transaction. A single transaction spanning every batch would
    hold SQLite's write lock across hundreds of provider calls, locking out the
    dashboard for the duration.

    Instruments are asked for **most in need first** -- never priced, then least
    recently covered -- so a run that cannot reach everything still makes progress
    on the gaps rather than refreshing whichever names happened to sort first.
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

    # --- database phase: which instruments, in what order --------------------
    with session_scope() as session:
        if tickers:
            # Scoped: the named instruments and nothing else, whatever the ration and
            # whatever their coverage. The targeted ordering below exists to spread a
            # universe sweep across runs, and a single named instrument has no queue to
            # be fair to.
            targets = load_price_targets(session, only=tickers)
        else:
            targets = load_price_targets(
                session, limit=settings.schedule.price_eod_max_per_run or None
            )
    report.tickers_requested = len(targets)
    if not targets.symbols:
        return JobResult(detail={**report.as_dict(), "skipped": "empty universe"})

    symbols = targets.symbols
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
        detail={
            **report.as_dict(),
            "fx": rates,
            # What the run was aiming at, so the page can say whether it is
            # closing the gaps or just keeping the covered names fresh.
            "never_priced_targeted": targets.never_priced,
            "stale_targeted": targets.stale,
            "oldest_coverage": targets.oldest_bar,
            "newest_coverage": targets.newest_bar,
        },
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


def ingest_news_rss(tickers: list[str] | None = None) -> JobResult:
    """Poll RSS and optional providers, then classify anything new.

    ``tickers`` scopes the poll to named instruments, for a manual one-instrument
    refresh. The universe walk is ordered by its own cursor, so a scoped run neither
    reads nor advances it.
    """
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
        report = ingest_rss_news(session, tickers=tickers, classifier=classifier)

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


def analyse_news(tickers: list[str] | None = None) -> JobResult:
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
            tickers=tickers,
            settings=settings,
            analyser=analyser,
            days=config.lookback_days,
            # A scoped refresh is asking about one company, so the ration that spreads
            # forty deep reads across the universe has nothing to spread here.
            limit=None if tickers else config.max_deep_per_run,
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


def embed_news() -> JobResult:
    """Give stored stories a vector, so one event can be recognised as one event.

    Only relevant stories are embedded. A story with no instrument and no direction
    never reaches the banner, so a vector for it would be paid for and never
    compared against anything.

    Newest first, because clustering is what the banner uses and the banner looks at
    recent stories. An old backlog is worth less than today's coverage.

    Rationed like every other paid job, and it records *why* it did nothing: "one
    entry per event" and "one entry per story" look identical in the UI, and only
    one of them means the feature works.
    """
    from sqlalchemy import select

    from awltux.analysis.embeddings import EmbeddingClient, embed_text, store_vectors
    from awltux.config import get_settings
    from awltux.db import NewsEmbedding, NewsItem
    from awltux.db.session import release_write_lock

    settings = get_settings()
    config = settings.news.embeddings
    client = EmbeddingClient(settings)
    if not client.configured:
        return JobResult(
            note=(
                "embeddings are not configured, so stories cannot be grouped by "
                "event: set news.embeddings.base_url to an OpenAI-compatible endpoint"
            )
        )

    embedded = 0
    errors: list[str] = []
    fatal = False
    with session_scope() as session:
        already = select(NewsEmbedding.news_item_id).where(
            NewsEmbedding.model == config.model
        )
        pending = list(
            session.execute(
                select(NewsItem)
                .where(NewsItem.relevant.is_(True))
                .where(NewsItem.id.not_in(already))
                .order_by(NewsItem.id.desc())
                .limit(config.max_per_run)
            ).scalars().all()
        )
        if not pending:
            return JobResult(note="every relevant story already has a vector")

        batch_size = max(1, config.batch_size)
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            texts = [embed_text(item) for item in batch]
            # Vector maths is ours; the provider only turns text into numbers.
            release_write_lock(session)
            result = client.embed(texts)
            errors.extend(result.errors)
            if result.vectors:
                kept = len(result.vectors)
                embedded += store_vectors(
                    [item.id for item in batch][:kept],
                    texts[:kept],
                    result.vectors,
                    model=config.model,
                )
            if result.fatal:
                # A rejected credential or a model the account cannot use. The
                # remaining batches cannot succeed either, so asking is sixteen more
                # requests against a rate-limited endpoint to learn nothing.
                fatal = True
                break
            release_write_lock(session)

    client.close()

    # Deduplicate: a rejection repeats identically for every batch, and sixteen
    # copies of one sentence is not more information than one.
    unique: list[str] = []
    for message in errors:
        if message not in unique:
            unique.append(message)

    if fatal:
        note = (
            "stopped after the first batch: "
            f"{unique[0] if unique else 'the endpoint refused the request'}"
        )
    elif embedded == 0:
        note = "no vectors were produced: " + (
            "; ".join(unique[:2]) or "the provider returned nothing"
        )
    elif unique:
        note = f"{embedded} stories embedded; {len(unique)} batch(es) failed and will retry"
    else:
        note = None

    return JobResult(
        items_seen=len(pending),
        items_written=embedded,
        note=note,
        detail={
            "embedded": embedded,
            "model": config.model,
            "stopped_early": fatal,
            "errors": unique[:5],
        },
    )


def assess_news_relevance(tickers: list[str] | None = None) -> JobResult:
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
    from awltux.llm.classify import apply_classification, build_classifier
    from awltux.providers.news_rss import RawNewsItem

    settings = get_settings()
    # The cap is on *model calls*, not rows. Relevance is decided structurally
    # wherever a direction is already stored -- which is 5,500 of the 5,800 rows in
    # this deployment -- so bounding the row window would make a free, instant
    # backfill take thirty runs to drain while protecting nothing. The paid work is
    # what needs rationing, and the row window is only there to bound memory.
    call_limit = settings.news.relevance_backfill_per_run
    classifier = build_classifier(settings)

    with session_scope() as session:
        pending = list(
            session.execute(
                select(NewsItem)
                .where(NewsItem.relevant.is_(None))
                .order_by(NewsItem.id)
                .limit(RELEVANCE_BACKFILL_ROWS if not tickers else None)
            ).scalars().all()
        )
        if tickers:
            # Scoped to a manual refresh, so the window is the instrument rather than a
            # rationed slice of the backlog. Matched in Python because `tickers` is a
            # JSON column and `json_each` cannot use an index -- for one instrument over
            # a deliberate button press that is the right trade, and for the scheduled
            # sweep the rationed window above is what keeps it bounded.
            wanted = set(tickers)
            pending = [
                item for item in pending if wanted & set(item.tickers or [])
            ]
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
                    apply_classification(item, updates)
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

            # Bound the transaction, not just the calls. Only a couple of hundred of
            # the five thousand rows need a model call, so releasing the lock only
            # around those leaves long stretches where thousands of pending updates
            # accumulate and land in one flush -- the same shape as the 31-second
            # instrument sync that broke every concurrent writer.
            if assessed % RELEVANCE_FLUSH_EVERY == 0:
                session.flush()
                release_write_lock(session)

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


def _lookup_symbol(provider, query: str, instrument: Any, *, by_isin: bool):
    """Score the candidates one provider search returns.

    Split out because the job now makes this call twice per stuck instrument, and
    the two calls have to be scored identically apart from where they were found.
    """
    from awltux.ingest.identity import choose_symbol

    if not query:
        return None
    return choose_symbol(
        provider.search_symbols(query),
        instrument_name=instrument.name,
        instrument_exchange=instrument.exchange_name,
        instrument_type=instrument.instrument_type,
        queried_by_isin=by_isin,
    )


def refresh_provider_balances() -> JobResult:
    """Ask each model provider what is left on the account.

    Running out of credit is the one provider failure that is neither transient nor a bug,
    and it presents like both: the decision engine falls back to the deterministic rules,
    the embeddings job records a fatal error, and nothing says *the account is empty*.
    This is the only job here that costs nothing to run and prevents the most.

    A provider that cannot be asked is recorded as unreadable rather than skipped, so the
    banner can say which provider it cannot see and why. Nothing about this job fails the
    run: an unreadable balance is a state, not an error.
    """
    from awltux.providers import balances as balance_probes

    readings = balance_probes.read_all()
    with session_scope() as session:
        balance_probes.store(session, readings)

    readable = [row for row in readings if row.amount is not None]
    unreadable = [row for row in readings if row.amount is None]
    return JobResult(
        items_seen=len(readings),
        items_written=len(readable),
        note=(
            None
            if readable
            else "no provider reported a balance; see the notes for why"
        ),
        detail={
            "balances": {
                row.provider: {
                    "available": row.available,
                    "amount": row.amount,
                    "currency": row.currency,
                    "note": row.note,
                }
                for row in readings
            },
            "unreadable": [row.provider for row in unreadable],
        },
    )


def refresh_macro_rates() -> JobResult:
    """Observe the risk-free rate for every currency the model discounts in.

    One number per currency, and it decides every discounted fair value in the
    database: the rate anchors the CAPM cost of equity, which anchors the discount
    rate. It used to be a constant in ``config.yaml``, which is correct on the day it
    is typed and silently wrong afterwards -- on 2026-10-05 the ten-year Treasury
    yielded 5.31% against a configured 4.2%.

    **Per currency, because a discount rate must match the cash flows.** Roughly a
    quarter of this universe is sterling, and discounting sterling cash flows at a
    dollar rate embeds a cross-currency view the model does not hold. Each currency
    reads its own sovereign's curve; a currency with none wired up is left to the
    configured constant rather than quietly given someone else's rate.

    The observation is *stored* rather than read at import so that a valuation can
    be reproduced against the rate actually in force when it was computed, and so a
    failed fetch degrades to the configured constant instead of failing the sweep.
    One currency failing does not stop the others being recorded.
    """
    from awltux.analysis import macro
    from awltux.providers.gilt import GiltProvider
    from awltux.providers.http import ProviderError
    from awltux.providers.treasury import TreasuryProvider

    settings = get_settings()
    tenor = settings.valuation.risk_free_rate_tenor
    builders = {"treasury": TreasuryProvider, "gilt": GiltProvider}

    written = 0
    seen = 0
    errors: list[str] = []
    detail: dict[str, Any] = {"tenor": tenor, "currencies": {}}

    # One fetch per *source*, not per currency: both currencies a source serves come
    # from the same published curve, and the Treasury's is the whole curve at once.
    for source in sorted(set(macro.CURRENCY_CURVES.values())):
        provider = builders[source](settings)
        try:
            # No session is open across this call, so nothing holds the write lock.
            curve = provider.yield_curve()
        except ProviderError as exc:
            errors.append(f"{source}: {exc}")
            continue
        finally:
            provider.close()

        currencies = [
            code for code, name in macro.CURRENCY_CURVES.items() if name == source
        ]
        for currency in currencies:
            seen += len(curve.rates)
            with session_scope() as session:
                observation = macro.store_observation(
                    session, curve, currency=currency, tenor=tenor
                )
            if observation is None:
                errors.append(
                    f"{currency}: the {tenor} point was missing or implausible in the "
                    f"curve published {curve.as_of.isoformat()}"
                )
                continue
            written += 1
            detail["currencies"][currency] = {
                "as_of": curve.as_of.isoformat(),
                "risk_free_rate": observation.value,
                "source": source,
                "yield_curve": curve.as_dict(),
            }

    if not written:
        note = (
            "; ".join(errors)
            if errors
            else "no currency has a sovereign curve wired up, so nothing was observed"
        )
        return JobResult(note=f"no risk-free rate was stored: {note}", detail=detail)

    if errors:
        # Reported, not swallowed: one currency falling back to the configured
        # constant while another is priced off the market is a state a reader needs
        # to be able to see.
        detail["errors"] = errors

    return JobResult(items_seen=seen, items_written=written, detail=detail)


def sync_shareholder_reports(tickers: list[str] | None = None) -> JobResult:
    """Find and download the annual reports: this year and the previous one.

    The annual report is the primary evidence about a business, and until now this
    system held only a pointer to one. The ``filing`` table carried 4,529 rows and
    not a single document -- ``raw_path``, ``doc_hash`` and ``parsed`` were columns
    on the model that nothing ever wrote -- so every filing sat at ``pending`` for
    ever and the reports could not be read, quoted or checked.

    Two phases, and they are reported separately because they fail differently. The
    first asks EDGAR for the annual forms by date, which is what a multi-year window
    needs and what the general filing sync cannot give: that takes the fifteen most
    recent *interesting* filings, so a company that files a lot of 8-Ks had its
    older 10-Ks cut off by a limit rather than by a date. The second downloads the
    documents behind those rows.

    ``tickers`` scopes both phases to one company and lifts the per-run download
    ration, which exists to spread a universe-wide sweep over several runs.
    """
    from awltux.ingest.documents import (
        deepen_annual_history,
        fetch_annual_reports,
        refresh_report_flags,
    )

    settings = get_settings()
    years = settings.reports.years
    per_run = settings.reports.per_run

    with session_scope() as session:
        discovery = deepen_annual_history(
            session, years=years, settings=settings, tickers=tickers
        )

    with session_scope() as session:
        download = fetch_annual_reports(
            session,
            limit=None if tickers else per_run,
            settings=settings,
            tickers=tickers,
        )
        # The flag is recomputed from the rows rather than incremented as documents
        # arrive, so a run that dies halfway leaves it describing what is held
        # rather than what was attempted.
        flagged = refresh_report_flags(session)

    detail = _document_detail(discovery, download, years=years, flagged=flagged)

    if not discovery.discovered and not download.fetched:
        return JobResult(
            note=(
                "no annual report needed fetching: either every filer already has "
                "its reports stored or none has a resolved CIK"
            ),
            detail=detail,
        )
    return JobResult(
        items_seen=discovery.discovered,
        items_written=download.fetched,
        detail=detail,
    )


def _document_detail(
    discovery: Any, download: Any, *, years: int, flagged: int
) -> dict[str, Any]:
    """What the two phases did, as one run's detail.

    A named step because the two phases fail differently and the reader needs both halves:
    a run that discovered six reports and downloaded none is a download problem, and one
    that discovered none is a discovery problem -- and the counts for each come from a
    different report.
    """
    return {
        "years": years,
        "discovered": discovery.discovered,
        "downloaded": download.fetched,
        "failed": download.failed,
        "bytes_written": download.bytes_written,
        "instruments_covered": len(download.instruments),
        "instruments_flagged": flagged,
        "discovery_errors": discovery.errors[:5],
        "download_errors": download.errors[:5],
    }


def _stuck_instruments(
    session, *, tickers: list[str] | None, limit: int
) -> list[Instrument]:
    """Instruments with an ISIN and no price history: the ones a lookup can help.

    A named step rather than a block inside the job for the reason the job's own docstring
    gives: this is the *input* to the whole thing, and the scoped and sweeping cases
    differ only here. The limit rations a daily sweep across runs; a one-instrument
    refresh must not be rationed out of the run it was asked for, and the "no price
    history" filter is why the refresh runs this *before* prices -- a derived symbol that
    is wrong shows up as an instrument with no bars.
    """
    from sqlalchemy import select

    from awltux.db import Instrument, PriceBar

    priced = select(PriceBar.instrument_t212_ticker).distinct()
    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .where(Instrument.isin.is_not(None))
        .where(Instrument.t212_ticker.not_in(priced))
        .order_by(Instrument.t212_ticker)
    )
    if tickers is not None:
        statement = statement.where(Instrument.t212_ticker.in_(list(tickers)))
    else:
        statement = statement.limit(limit)
    return list(session.execute(statement).scalars().all())


def resolve_symbols(tickers: list[str] | None = None) -> JobResult:
    """Look up the provider symbol for instruments a derived one cannot reach.

    Every price, account and news item joins on a provider symbol, and until now
    that symbol was *derived* from the Trading 212 ticker. That works until the
    ticker is stale, and T212's are frequently former ones -- Humacyte is
    ``AHAC_US_EQ`` there and ``HUMA`` on Yahoo. Deriving cannot recover from that,
    and 92 of 500 instruments were failing every price run forever, invisibly.

    An ISIN does not go stale. It is Trading 212's own identifier, it survives
    renames and restructurings, and searching by it returned the right company for
    seven of the first eight instruments that no derived symbol could reach.

    Only instruments that are actually *stuck* are looked up: those with no stored
    bar. Re-resolving the whole universe would spend hundreds of searches a day to
    confirm what is already working.

    Every outcome is recorded on the alias, including the failures. An alias saying
    "below the 0.70 floor, names share 40% of their words" is a request for a human;
    an instrument with no alias at all is one nobody will ever look at.
    """
    from sqlalchemy import select

    from awltux.config import get_settings
    from awltux.db import Instrument, InstrumentAlias, utcnow
    from awltux.db.session import release_write_lock
    from awltux.ingest.identity import APPLY_FLOOR, describe
    from awltux.providers.http import ProviderError
    from awltux.providers.yahoo import YahooProvider

    settings = get_settings()
    limit = settings.schedule.symbol_resolution_per_run
    provider = YahooProvider(settings)

    with session_scope() as session:
        stuck = _stuck_instruments(session, tickers=tickers, limit=limit)
        if not stuck:
            return JobResult(
                note=(
                    "every universe instrument with an ISIN has price history, so "
                    "there is no symbol left to resolve"
                )
            )

    resolved: list[str] = []
    rejected: list[str] = []
    unresolved: list[str] = []
    errors: list[str] = []

    for position, instrument in enumerate(stuck, start=1):
        # Two provider searches per instrument, each rate-limited, so this run is
        # minutes long and silent without a counted line.
        progress.note(f"{position} of {len(stuck)}: {instrument.t212_ticker}")
        # Release before the search, like every other network call in this codebase.
        with session_scope() as session:
            release_write_lock(session)

        by_isin = True
        try:
            # The ISIN goes first: it survives a rename, which is the whole reason
            # this job exists.
            resolution = _lookup_symbol(provider, instrument.isin or "", instrument, by_isin=True)
            if resolution is None or not resolution.usable:
                # Then the name, whenever the ISIN lookup did not produce something
                # worth applying.
                #
                # This used to run only when the ISIN search returned *no*
                # candidates, which is the rarer case. An ISIN identifies the
                # *company*, and a company can be listed in several places, so
                # Yahoo's ISIN search frequently returns only the foreign listings:
                # BRP's ``CA05577W2004`` comes back as ``DOO.TO`` and
                # ``CA05577W2004.SG``, never as the Nasdaq ``DOO``. The venue check
                # then refuses them -- correctly, because a Toronto price is not the
                # one we want -- and the instrument stayed stuck with its own
                # venue's listing sitting one name search away, never asked for.
                by_isin = False
                by_name = _lookup_symbol(provider, instrument.name, instrument, by_isin=False)
                if by_name is not None and (
                    by_name.usable
                    or resolution is None
                    or by_name.confidence > resolution.confidence
                ):
                    # A usable name match wins outright; otherwise keep whichever of
                    # the two carries more evidence, so the alias records the best
                    # candidate found rather than merely the first.
                    resolution = by_name
        except ProviderError as exc:
            errors.append(f"{instrument.t212_ticker}: {exc}")
            continue

        with session_scope() as session:
            row = session.get(Instrument, instrument.t212_ticker)
            if row is None:
                continue
            alias = session.execute(
                select(InstrumentAlias).where(
                    InstrumentAlias.instrument_t212_ticker == row.t212_ticker,
                    InstrumentAlias.provider == "yahoo",
                )
            ).scalar_one_or_none()
            if alias is None:
                alias = InstrumentAlias(
                    instrument_t212_ticker=row.t212_ticker, provider="yahoo", symbol=""
                )
                session.add(alias)

            # A human's correction is never overwritten -- the same rule the
            # universe sync follows, for the same reason.
            if alias.is_manual:
                continue

            applied = resolution is not None and resolution.usable
            if resolution is not None:
                alias.symbol = resolution.symbol
                alias.confidence = resolution.confidence
                alias.method = resolution.method
                alias.note = describe(resolution, instrument_name=instrument.name)
            else:
                alias.confidence = 0.0
                alias.method = "isin" if by_isin else "name"
                alias.note = describe(None)
            alias.verified_at = utcnow()

            if applied and resolution is not None:
                row.yahoo_symbol = resolution.symbol
                row.mapping_confidence = resolution.confidence
                resolved.append(f"{row.t212_ticker}->{resolution.symbol}")
            elif resolution is not None:
                # Recorded but not trusted. Left unresolved on purpose: attaching
                # another company's prices would be worse than a visible gap.
                rejected.append(f"{row.t212_ticker}->{resolution.symbol}")
            else:
                unresolved.append(row.t212_ticker)
            session.flush()

    if errors:
        note = f"{len(errors)} lookups failed and will retry: {errors[0]}"
    elif not resolved and not rejected:
        note = (
            f"{len(unresolved)} instruments were searched and none has a listing "
            "that matches, so they need a human"
        )
    else:
        note = None

    return JobResult(
        items_seen=len(stuck),
        items_written=len(resolved),
        note=note,
        detail={
            "looked_up": len(stuck),
            "resolved": len(resolved),
            "resolved_symbols": resolved[:25],
            "rejected_below_floor": len(rejected),
            "rejected_symbols": rejected[:25],
            "no_match": len(unresolved),
            "no_match_tickers": unresolved[:25],
            "floor": APPLY_FLOOR,
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


def sync_filings(tickers: list[str] | None = None) -> JobResult:
    """Refresh filing history for instruments with a resolved CIK.

    ``tickers`` scopes the CIK resolution *and* the fetch to named instruments. The
    resolution half matters for a single US listing and is otherwise a no-op, because
    an instrument with a CIK already resolves to itself.
    """
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

        resolution = resolve_ciks(session, tickers=tickers)
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

        report = _sync(session, tickers=tickers)

    return JobResult(
        items_seen=report.filings_seen,
        # A backfilled period is a write: most of the stored filings gained the
        # period they report on in one pass, and reporting written=0 while 4,958
        # rows changed is the kind of number that stops being believed.
        items_written=report.filings_written + report.periods_backfilled,
        detail={**report.as_dict(), "cik_resolution": resolution.as_dict()},
    )


def sync_fundamentals_job(tickers: list[str] | None = None) -> JobResult:
    """Rotating fundamentals refresh, rationed to keep within free-tier limits.

    The configured per-day rotation is divided across the 24 hourly runs so the
    load is spread rather than concentrated in one burst.

    ``tickers`` is the one-instrument scope a manual refresh uses. It is a keyword with a
    default rather than a second function so the scheduled and the scoped run take
    exactly the same path -- same blockers, same progress lines, same report -- and the
    rotation limit is lifted, because a rationed batch of two is not "refresh this one".
    """
    settings = get_settings()
    from awltux.ingest.fundamentals import sync_fundamentals

    per_run = 1 if tickers else max(1, settings.schedule.fundamentals_rotation_per_day // 24)
    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("fundamentals sync skipped: %s", note)
            return JobResult(note=note)
        report = sync_fundamentals(
            session, tickers=tickers, limit=None if tickers else per_run
        )

    return JobResult(
        items_seen=report.tickers_attempted,
        items_written=report.periods_written,
        detail={**report.as_dict(), "per_run_limit": per_run if not tickers else "scoped"},
    )


def sync_xbrl_statements_job(tickers: list[str] | None = None) -> JobResult:
    """Annual statements from XBRL company facts, for US filers.

    Separate from ``fundamentals`` because the two answer different questions and
    fail in different ways. ``fundamentals`` asks a market-data provider for a
    normalised snapshot; this reads the issuer's own tagging of its own statements
    out of EDGAR, which is slower per name and far better per figure. Keeping them
    apart means a rate-limited Yahoo run does not also stop the filings being read.
    """
    settings = get_settings()
    from awltux.ingest.xbrl import sync_xbrl_fundamentals

    per_run = 1 if tickers else max(1, settings.schedule.fundamentals_rotation_per_day // 24)
    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("xbrl statements skipped: %s", note)
            return JobResult(note=note)
        report = sync_xbrl_fundamentals(
            session, settings=settings, tickers=tickers, limit=None if tickers else per_run
        )

    return JobResult(
        items_seen=report.tickers_attempted,
        items_written=report.periods_written,
        detail={**report.as_dict(), "per_run_limit": per_run if not tickers else "scoped"},
    )


def resolve_uk_companies_job(tickers: list[str] | None = None) -> JobResult:
    """Attach Companies House numbers to UK-listed instruments."""
    from awltux.ingest.fundamentals import resolve_uk_companies

    with session_scope() as session:
        summary = resolve_uk_companies(
            session, tickers=tickers, limit=None if tickers else 50
        )

    return JobResult(
        items_seen=summary.get("attempted", 0),
        items_written=summary.get("matched", 0),
        detail=summary,
    )


def run_valuations(tickers: list[str] | None = None) -> JobResult:
    """Recompute the deterministic valuation for the universe."""
    from awltux.analysis.valuation import run_valuations as _run

    with session_scope() as session:
        stats = _run(session, tickers=tickers)

    return JobResult(
        items_seen=stats.get("attempted", 0),
        items_written=stats.get("valued", 0),
        detail=stats,
    )


def run_decisions(tickers: list[str] | None = None) -> JobResult:
    """Produce a fresh decision for every instrument whose inputs changed."""
    from awltux.decision.service import decide_universe

    with session_scope() as session:
        stats = decide_universe(session, tickers=tickers)

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


def aggregate_sentiment(tickers: list[str] | None = None) -> JobResult:
    """Roll news items up into per-stock and per-sector sentiment series."""
    from awltux.analysis.sentiment import aggregate_all

    with session_scope() as session:
        stats = aggregate_all(session, tickers=tickers)

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

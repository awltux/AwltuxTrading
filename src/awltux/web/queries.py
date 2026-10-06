"""Read-only query helpers for the dashboard and JSON API.

Kept in one module so the SQL lives in a single reviewable place, and so the
templates never build their own queries. Every read model here is careful to
return *provenance* alongside values -- source, as-of, engine, confidence --
because a number without its origin is not usable for a decision.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from awltux.analysis import macro
from awltux.db import (
    DecisionOutcome,
    DecisionRun,
    Filing,
    FundamentalPeriod,
    IngestRun,
    Instrument,
    InstrumentAlias,
    NewsAnalysis,
    NewsItem,
    PriceBar,
    Quote,
    SentimentSeries,
    ValuationRun,
)
from awltux.timezones import format_moment, utc_today

SortKey = Literal[
    "composite_score", "short_term_score", "margin_of_safety", "confidence",
    "short_term_confidence", "action", "short_term_action", "name",
    "change_pct", "sentiment", "freshness", "horizon_fit",
]

ACTION_ORDER = {
    "strong_buy": 0,
    "buy": 1,
    "hold": 2,
    "reduce": 3,
    "sell": 4,
    "avoid": 5,
}


@dataclass(slots=True)
class RecommendationRow:
    """One row of the sortable recommendations table.

    Carries **both** horizons rather than one blended call, because they answer
    different questions and are allowed to disagree. Collapsing them would hide
    exactly the case a reader most wants to see: cheap for years but tactically
    broken, or well set up this month and expensive on any longer view.
    """

    ticker: str
    name: str
    sector: str | None
    currency: str | None
    price: float | None
    change_pct: float | None
    fair_value: float | None
    fair_value_low: float | None
    fair_value_high: float | None
    margin_of_safety: float | None

    # Long term.
    action: str | None
    composite_score: float | None
    confidence: float | None
    gate_allowed: bool
    gate_reason: str | None

    # Short term.
    short_term_action: str | None
    short_term_score: float | None
    short_term_confidence: float | None
    short_term_gate_allowed: bool
    short_term_gate_reason: str | None
    setup_score: float | None
    drawdown_risk: float | None

    # Shared.
    horizon_fit: str | None
    engine: str | None
    uncalibrated: bool
    conflict: bool
    sentiment: float | None
    decision_at: dt.datetime | None
    valuation_at: dt.datetime | None
    price_at: dt.datetime | None
    is_held: bool

    def action_for(self, horizon: str) -> str | None:
        return self.short_term_action if horizon == "short_term" else self.action

    def gate_allowed_for(self, horizon: str) -> bool:
        return (
            self.short_term_gate_allowed
            if horizon == "short_term"
            else self.gate_allowed
        )

    def score_for(self, horizon: str) -> float | None:
        return self.short_term_score if horizon == "short_term" else self.composite_score

    @property
    def action_rank(self) -> int:
        return ACTION_ORDER.get(self.action or "", 9)

    @property
    def short_term_action_rank(self) -> int:
        return ACTION_ORDER.get(self.short_term_action or "", 9)

    @property
    def staleness_seconds(self) -> float | None:
        if self.price_at is None:
            return None
        when = self.price_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.UTC)
        return (dt.datetime.now(dt.UTC) - when).total_seconds()


def _latest_decision_ids() -> Select:
    """Ids of the most recent decision per instrument.

    Expressed as ``id IN (SELECT max(id) ... GROUP BY ticker)`` rather than a
    window function joined back onto ``instrument``. ``id`` is monotonically
    assigned, so the maximum id per ticker is its latest decision, and an ``IN``
    subquery avoids the multi-FROM ambiguity that a join across several
    correlated subqueries produces.
    """
    return select(func.max(DecisionRun.id)).group_by(DecisionRun.instrument_t212_ticker)


def _latest_valuation_ids() -> Select:
    return select(func.max(ValuationRun.id)).group_by(ValuationRun.instrument_t212_ticker)


def _recent_bars() -> Select:
    """The last two bars per instrument, from a single table.

    Single-table window query, so there is nothing to join ambiguously; the
    previous close is what makes a one-day change calculable.
    """
    ranked = (
        select(
            PriceBar.instrument_t212_ticker.label("ticker"),
            PriceBar.close.label("close"),
            PriceBar.date.label("bar_date"),
            func.row_number()
            .over(
                partition_by=PriceBar.instrument_t212_ticker,
                order_by=desc(PriceBar.date),
            )
            .label("rn"),
        )
        .subquery()
    )
    return select(ranked.c.ticker, ranked.c.close, ranked.c.bar_date, ranked.c.rn).where(
        ranked.c.rn <= 2
    )


def _latest_sentiment() -> Select:
    ranked = (
        select(
            SentimentSeries.scope_id.label("scope_id"),
            SentimentSeries.score.label("score"),
            func.row_number()
            .over(
                partition_by=SentimentSeries.scope_id,
                order_by=desc(SentimentSeries.date),
            )
            .label("rn"),
        )
        .where(SentimentSeries.scope_type == "instrument")
        .subquery()
    )
    return select(ranked.c.scope_id, ranked.c.score).where(ranked.c.rn == 1)


def _answer_value(answers: dict[str, Any], question: str, field: str) -> float | None:
    """Pull a numeric field out of a stored answer, tolerating its absence."""
    entry = answers.get(question)
    if not isinstance(entry, dict):
        return None
    value = entry.get(field, entry.get("value"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def recommendations(
    session: Session,
    *,
    sort: SortKey = "composite_score",
    direction: Literal["asc", "desc"] = "desc",
    action: str | None = None,
    engine: str | None = None,
    horizon: str = "long_term",
    horizon_fit: str | None = None,
    only_suggestions: bool = False,
    only_held: bool = False,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[RecommendationRow], int]:
    """Return the recommendations table plus the total row count for paging.

    Assembled from a handful of narrow queries rather than one wide join. At a
    few hundred instruments the extra queries are negligible, and the result is
    far easier to reason about than a five-way outer join over correlated
    subqueries.
    """
    # --- 1. which instruments are in scope ---------------------------------
    instrument_query = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    )
    if only_held:
        instrument_query = instrument_query.where(Instrument.is_held.is_(True))
    if search:
        pattern = f"%{search.lower()}%"
        instrument_query = instrument_query.where(
            func.lower(Instrument.t212_ticker).like(pattern)
            | func.lower(Instrument.name).like(pattern)
        )

    instruments = list(session.execute(instrument_query).scalars().all())
    if not instruments:
        return [], 0
    tickers = [row.t212_ticker for row in instruments]

    # --- 2. latest decision and valuation per ticker -----------------------
    decisions: dict[str, DecisionRun] = {
        row.instrument_t212_ticker: row
        for row in session.execute(
            select(DecisionRun).where(DecisionRun.id.in_(_latest_decision_ids()))
        ).scalars().all()
    }
    valuations: dict[str, ValuationRun] = {
        row.instrument_t212_ticker: row
        for row in session.execute(
            select(ValuationRun).where(ValuationRun.id.in_(_latest_valuation_ids()))
        ).scalars().all()
    }

    # --- 3. last two bars and latest sentiment, for the tickers in scope ----
    prices: dict[str, tuple[float | None, dt.date | None]] = {}
    previous: dict[str, float | None] = {}
    for ticker, close, bar_date, rank in session.execute(_recent_bars()).all():
        if ticker not in tickers:
            continue
        if rank == 1:
            prices[ticker] = (close, bar_date)
        elif rank == 2:
            previous[ticker] = close

    sentiments: dict[str, float] = {
        scope_id: score for scope_id, score in session.execute(_latest_sentiment()).all()
    }

    # --- 4. assemble -------------------------------------------------------
    result: list[RecommendationRow] = []
    for instrument in instruments:
        decision = decisions.get(instrument.t212_ticker)
        valuation = valuations.get(instrument.t212_ticker)

        if action and (decision is None or decision.action_for(horizon) != action):
            continue
        if engine and (decision is None or decision.engine != engine):
            continue
        if horizon_fit and (decision is None or decision.horizon_fit != horizon_fit):
            continue
        if only_suggestions and not (
            decision is not None
            and decision.allowed_for(horizon)
            and decision.action_for(horizon) in ("strong_buy", "buy", "reduce", "sell")
        ):
            continue

        price, bar_date = prices.get(instrument.t212_ticker, (None, None))
        previous_close = previous.get(instrument.t212_ticker)

        change_pct: float | None = None
        if price is not None and previous_close:
            change_pct = (price - previous_close) / previous_close * 100.0

        short_gate_reason = None
        if decision is not None and isinstance(decision.short_term_gate, dict):
            short_gate_reason = decision.short_term_gate.get("binding_rule")

        gate_reason = None
        if decision is not None and isinstance(decision.gate, dict):
            gate_reason = decision.gate.get("binding_rule")

        answers = (decision.answers or {}) if decision else {}

        result.append(
            RecommendationRow(
                ticker=instrument.t212_ticker,
                name=instrument.display_name,
                sector=instrument.sector,
                currency=instrument.currency_code,
                price=price,
                change_pct=change_pct,
                fair_value=valuation.fair_value_base if valuation else None,
                fair_value_low=valuation.fair_value_low if valuation else None,
                fair_value_high=valuation.fair_value_high if valuation else None,
                margin_of_safety=valuation.margin_of_safety if valuation else None,
                # Long term.
                action=decision.long_term_action if decision else None,
                composite_score=decision.composite_score if decision else None,
                confidence=decision.confidence if decision else None,
                gate_allowed=bool(decision.gate_allowed) if decision else False,
                gate_reason=gate_reason,
                # Short term.
                short_term_action=decision.short_term_action if decision else None,
                short_term_score=decision.short_term_composite_score if decision else None,
                short_term_confidence=decision.short_term_confidence if decision else None,
                short_term_gate_allowed=(
                    bool(decision.short_term_gate_allowed) if decision else False
                ),
                short_term_gate_reason=short_gate_reason,
                setup_score=_answer_value(answers, "short_term_setup", "score"),
                drawdown_risk=_answer_value(answers, "short_term_drawdown_risk", "score"),
                # Shared.
                horizon_fit=decision.horizon_fit if decision else None,
                engine=decision.engine if decision else None,
                uncalibrated=bool(decision.uncalibrated) if decision else False,
                conflict=bool(decision.conflict_flag) if decision else False,
                sentiment=sentiments.get(instrument.t212_ticker),
                decision_at=decision.created_at if decision else None,
                valuation_at=valuation.as_of if valuation else None,
                price_at=(
                    dt.datetime.combine(bar_date, dt.time(0, 0), tzinfo=dt.UTC)
                    if bar_date
                    else None
                ),
                is_held=instrument.is_held,
            )
        )

    # Sorting happens in Python: the sort keys mix derived values (margin of
    # safety, freshness, action rank) that do not exist as columns, and the
    # universe is a few hundred rows, so an in-memory sort is clearer and fast
    # enough. If the universe grows past a few thousand, move this into SQL.
    result.sort(key=lambda row: _sort_value(row, sort), reverse=(direction == "desc"))
    total = len(result)
    return result[offset : offset + limit], total


def _sort_value(row: RecommendationRow, key: SortKey) -> Any:
    if key == "composite_score":
        return row.composite_score if row.composite_score is not None else -999
    if key == "short_term_score":
        return row.short_term_score if row.short_term_score is not None else -999
    if key == "margin_of_safety":
        return row.margin_of_safety if row.margin_of_safety is not None else -999
    if key == "confidence":
        return row.confidence if row.confidence is not None else -1
    if key == "short_term_confidence":
        return row.short_term_confidence if row.short_term_confidence is not None else -1
    if key == "action":
        return row.action_rank
    if key == "short_term_action":
        return row.short_term_action_rank
    if key == "name":
        return row.name.lower()
    if key == "change_pct":
        return row.change_pct if row.change_pct is not None else -999
    if key == "sentiment":
        return row.sentiment if row.sentiment is not None else -999
    if key == "horizon_fit":
        # "both" sorts highest: it is the one answer that says act on either view.
        return {"both": 0, "long_term": 1, "short_term": 2, "neither": 3, None: 4}.get(
            row.horizon_fit, 4
        )
    if key == "freshness":
        # Newest first when descending: invert so a smaller age sorts higher.
        age = row.staleness_seconds
        return -age if age is not None else -1e18
    return 0


@dataclass(slots=True)
class PredictionRow:
    """One past judgement, with whatever is known about how it turned out."""

    decision: Any
    ticker: str
    name: str | None = None
    #: Outcomes keyed by ``(horizon, horizon_days)``. Empty until the window has
    #: elapsed -- and "not yet knowable" is a different state from "scored flat".
    outcomes: dict[tuple[str, int], Any] = field(default_factory=dict)

    @property
    def scored(self) -> bool:
        return bool(self.outcomes)

    def outcome(self, horizon: str, days: int):
        return self.outcomes.get((horizon, days))

    @property
    def actionable(self) -> bool:
        """Whether this call asserted a direction at all.

        HOLD asserts nothing, so it is excluded from hit rates -- counting it either
        way would flatter or penalise the model for a claim it did not make.
        """
        from awltux.audit.calibration import ACTIONABLE

        return (self.decision.long_term_action or "") in ACTIONABLE or (
            self.decision.short_term_action or ""
        ) in ACTIONABLE


def decision_history(
    session: Session,
    *,
    ticker: str | None = None,
    engine: str | None = None,
    only: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PredictionRow], int]:
    """Past predictions, newest first, with their forward returns where known.

    The ledger the dashboard never had. Every decision is already stored
    immutably -- state, state hash, engine, prompt hashes, both horizons' calls --
    but the only way to read one back was to know its id and ask for the receipt.
    A prediction you cannot find again is not really a record.
    """
    from awltux.audit.calibration import ACTIONABLE

    conditions = []
    if ticker:
        conditions.append(DecisionRun.instrument_t212_ticker == ticker)
    if engine:
        conditions.append(DecisionRun.engine == engine)
    if only == "actionable":
        conditions.append(
            DecisionRun.long_term_action.in_(ACTIONABLE)
            | DecisionRun.short_term_action.in_(ACTIONABLE)
        )
    elif only == "hold":
        conditions.append(
            DecisionRun.long_term_action.not_in(ACTIONABLE)
            & DecisionRun.short_term_action.not_in(ACTIONABLE)
        )

    total = session.execute(
        select(func.count()).select_from(DecisionRun).where(*conditions)
    ).scalar_one()

    decisions = list(
        session.execute(
            select(DecisionRun)
            .where(*conditions)
            .order_by(desc(DecisionRun.created_at), desc(DecisionRun.id))
            .offset(max(offset, 0))
            .limit(limit)
        ).scalars().all()
    )
    if not decisions:
        return [], total

    ids = [row.id for row in decisions]
    outcomes: dict[int, dict[tuple[str, int], Any]] = {}
    for outcome in session.execute(
        select(DecisionOutcome).where(DecisionOutcome.decision_run_id.in_(ids))
    ).scalars().all():
        outcomes.setdefault(outcome.decision_run_id, {})[
            (outcome.horizon, outcome.horizon_days)
        ] = outcome

    names = {
        row.t212_ticker: row.name
        for row in session.execute(
            select(Instrument).where(
                Instrument.t212_ticker.in_([row.instrument_t212_ticker for row in decisions])
            )
        ).scalars().all()
    }

    rows = [
        PredictionRow(
            decision=decision,
            ticker=decision.instrument_t212_ticker,
            name=names.get(decision.instrument_t212_ticker),
            outcomes=outcomes.get(decision.id, {}),
        )
        for decision in decisions
    ]

    if only == "scored":
        # Filtering after the outcome fetch: whether a decision has been scored is
        # a property of a table this query would otherwise have to join, and the
        # page size is small enough that a post-filter costs nothing and keeps the
        # count honest for the other filters.
        rows = [row for row in rows if row.scored]
    return rows, total


def instrument_detail(session: Session, ticker: str) -> dict[str, Any] | None:
    instrument = session.get(Instrument, ticker)
    if instrument is None:
        return None

    decision = session.execute(
        select(DecisionRun)
        .where(DecisionRun.instrument_t212_ticker == ticker)
        .order_by(desc(DecisionRun.created_at))
        .limit(1)
    ).scalar_one_or_none()

    valuation = session.execute(
        select(ValuationRun)
        .where(ValuationRun.instrument_t212_ticker == ticker)
        .order_by(desc(ValuationRun.as_of))
        .limit(1)
    ).scalar_one_or_none()

    bars = session.execute(
        select(PriceBar)
        .where(PriceBar.instrument_t212_ticker == ticker)
        .order_by(desc(PriceBar.date))
        .limit(750)
    ).scalars().all()

    filings = session.execute(
        select(Filing)
        .where(Filing.instrument_t212_ticker == ticker)
        .order_by(desc(Filing.filed_at))
        .limit(50)
    ).scalars().all()

    fundamentals = session.execute(
        select(FundamentalPeriod)
        .where(FundamentalPeriod.instrument_t212_ticker == ticker)
        .order_by(desc(FundamentalPeriod.period_end))
        .limit(40)
    ).scalars().all()

    news = session.execute(
        select(NewsItem)
        .order_by(desc(NewsItem.published_at))
        .limit(40)
    ).scalars().all()
    # Filter in Python: the tickers column is JSON, and the portable SQL for
    # membership differs between SQLite and Postgres.
    related_news = [n for n in news if ticker in (n.tickers or [])][:25]

    # The sceptical appraisals for exactly those stories, keyed by item id so the
    # template can pair them without a second lookup.
    appraisals: dict[int, NewsAnalysis] = {}
    if related_news:
        rows = session.execute(
            select(NewsAnalysis).where(
                NewsAnalysis.news_item_id.in_([n.id for n in related_news])
            )
        ).scalars().all()
        appraisals = {row.news_item_id: row for row in rows}

    outcomes = []
    if decision is not None:
        outcomes = [
            {
                "horizon_days": o.horizon_days,
                "return_pct": o.return_pct,
                "benchmark_return_pct": o.benchmark_return_pct,
                "verdict": o.verdict,
            }
            for o in decision.outcomes
        ]

    return {
        "instrument": instrument,
        "decision": decision,
        "valuation": valuation,
        "bars": list(reversed(bars)),
        "filings": filings,
        "fundamentals": fundamentals,
        "news": related_news,
        "news_analysis": appraisals,
        "outcomes": outcomes,
    }


def recent_news(
    session: Session,
    *,
    limit: int = 50,
    min_materiality: str | None = None,
    ticker: str | None = None,
) -> list[NewsItem]:
    statement = select(NewsItem).order_by(desc(NewsItem.published_at), desc(NewsItem.id))
    if min_materiality:
        statement = statement.where(NewsItem.materiality == min_materiality)
    items = session.execute(statement.limit(limit * 4 if ticker else limit)).scalars().all()
    if ticker:
        items = [item for item in items if ticker in (item.tickers or [])][:limit]
    return list(items)


def sector_sentiment(session: Session, *, days: int = 30) -> dict[str, list[dict[str, Any]]]:
    """Sector sentiment time series, keyed by sector, newest last."""
    cutoff = utc_today() - dt.timedelta(days=days)
    rows = session.execute(
        select(SentimentSeries)
        .where(SentimentSeries.scope_type == "sector")
        .where(SentimentSeries.date >= cutoff)
        .order_by(SentimentSeries.date)
    ).scalars().all()

    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row.scope_id, []).append(
            {
                "date": row.date.isoformat(),
                "score": row.score,
                "articles": row.article_count,
            }
        )
    return out


def universe_stats(session: Session) -> dict[str, Any]:
    """Headline counters for the dashboard header."""
    total = session.execute(
        select(func.count()).select_from(Instrument).where(Instrument.in_universe.is_(True))
    ).scalar_one()
    resolved = session.execute(
        select(func.count())
        .select_from(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.yahoo_symbol.is_not(None))
    ).scalar_one()

    latest_decisions = (
        select(func.count(func.distinct(DecisionRun.instrument_t212_ticker)))
        .select_from(DecisionRun)
        .scalar_subquery()
    )
    counts: dict[str, int] = {}
    action_rows = session.execute(
        select(DecisionRun.long_term_action, func.count())
        .where(DecisionRun.id.in_(_latest_decision_ids()))
        .group_by(DecisionRun.long_term_action)
    ).all()
    for action, count in action_rows:
        counts[action or "unknown"] = count

    short_counts: dict[str, int] = {}
    short_rows = session.execute(
        select(DecisionRun.short_term_action, func.count())
        .where(DecisionRun.id.in_(_latest_decision_ids()))
        .group_by(DecisionRun.short_term_action)
    ).all()
    for action, count in short_rows:
        short_counts[action or "unknown"] = count

    fit_rows = session.execute(
        select(DecisionRun.horizon_fit, func.count())
        .where(DecisionRun.id.in_(_latest_decision_ids()))
        .group_by(DecisionRun.horizon_fit)
    ).all()

    engine_rows = session.execute(
        select(DecisionRun.engine, func.count())
        .where(DecisionRun.id.in_(_latest_decision_ids()))
        .group_by(DecisionRun.engine)
    ).all()

    last_job = session.execute(
        select(IngestRun).order_by(desc(IngestRun.started_at)).limit(1)
    ).scalar_one_or_none()

    return {
        "universe_size": total,
        "mapped": resolved,
        "decided": session.execute(select(latest_decisions)).scalar_one(),
        "action_counts": counts,
        "short_term_action_counts": short_counts,
        "horizon_fit_counts": {fit or "unknown": count for fit, count in fit_rows},
        "engine_counts": {engine or "unknown": count for engine, count in engine_rows},
        "last_job": (
            {
                "job": last_job.job,
                "started_at": last_job.started_at,
                "ok": last_job.ok,
                "error": last_job.error,
            }
            if last_job
            else None
        ),
    }


def price_history(session: Session, ticker: str, *, limit: int = 400) -> list[dict[str, Any]]:
    rows = session.execute(
        select(PriceBar)
        .where(PriceBar.instrument_t212_ticker == ticker)
        .order_by(desc(PriceBar.date))
        .limit(limit)
    ).scalars().all()
    return [
        {"date": bar.date.isoformat(), "close": bar.close, "volume": bar.volume}
        for bar in reversed(rows)
    ]


#: Bars a line needs. One point is a dot, and a dot is not a trend.
MIN_BARS_FOR_CHART = 2


def price_history_waiting_note(session: Session, ticker: str, *, bars: int) -> str | None:
    """What the price panel is waiting for, or ``None`` once it can draw.

    The panel used to render "No price history stored." for every empty case.
    That sentence is true of four situations that need four different responses,
    and reading the same words for all of them is why an empty panel reads as a
    broken one:

    * the instrument is not in the analysed universe, so the end-of-day job
      never asks for it -- ``load_price_targets`` filters on ``in_universe`` --
      and this gap will **not** close on its own;
    * it is in the universe but no provider symbol has been resolved, so there
      is nothing to ask for either;
    * the symbol resolves and the job has simply not run yet, which does close
      on its own;
    * the job ran and the provider returned nothing under that symbol, which
      does not.

    Naming which one it is costs a few reads and saves the reader waiting on a
    gap that will never fill.
    """
    if bars >= MIN_BARS_FOR_CHART:
        return None

    if bars == 1:
        return (
            "Waiting for data — one daily bar is stored and a line needs two. "
            "The next end-of-day price run will add to it."
        )

    instrument = session.get(Instrument, ticker)
    if instrument is None:
        return "Waiting for data — this instrument is not in the database."

    # The provider identity goes into the answer whichever way the rest falls:
    # it is either the symbol the prices will arrive under, or the record of why
    # no symbol was chosen.
    alias = session.execute(
        select(InstrumentAlias)
        .where(InstrumentAlias.instrument_t212_ticker == ticker)
        .where(InstrumentAlias.provider == "yahoo")
        .limit(1)
    ).scalar_one_or_none()
    symbol = instrument.yahoo_symbol or (alias.symbol if alias else None)
    recorded = f" The symbol lookup recorded: {alias.note}" if alias and alias.note else ""

    if instrument.excluded:
        return (
            "Waiting for data — this instrument is excluded from analysis, so the "
            f"end-of-day price job does not request it.{recorded}"
        )
    if not instrument.in_universe:
        # Whether the universe is empty or this name is simply outside it matters:
        # the first is a pipeline that has not run, the second is a decision about
        # this instrument, and only one of them is worth waiting on.
        in_universe = session.execute(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.in_universe.is_(True))
        ).scalar_one()
        if in_universe == 0:
            return (
                "Waiting for data — no instrument is in the analysed universe yet, so "
                "the end-of-day price job has nothing to request. It fills once the "
                f"universe refresh has run.{recorded}"
            )
        return (
            "Waiting for data — this instrument is not in the analysed universe, so the "
            "end-of-day price job does not request it. This panel stays empty until a "
            f"universe refresh selects it.{recorded}"
        )
    if not symbol:
        return (
            "Waiting for data — no Yahoo symbol has been resolved for this instrument, so "
            f"there is nothing to request prices for. Re-run the symbol resolution job.{recorded}"
        )

    last_run = session.execute(
        select(IngestRun)
        .where(IngestRun.job == "price_eod")
        .order_by(desc(IngestRun.started_at))
        .limit(1)
    ).scalar_one_or_none()
    if last_run is None:
        return (
            f"Waiting for data — {symbol} resolves, and the end-of-day price job has not "
            f"recorded a run yet. The first run will fetch the history.{recorded}"
        )

    when = format_moment(last_run.started_at)
    if last_run.error:
        return (
            f"Waiting for data — {symbol} resolves, but the end-of-day price run on {when} "
            f"failed: {last_run.error}.{recorded}"
        )
    # The stored failure list is a sample (capped, see PriceIngestReport.as_dict),
    # so membership here proves the provider was asked, and absence proves nothing.
    if symbol in ((last_run.detail or {}).get("failed") or []):
        return (
            f"Waiting for data — {symbol} resolves, and the end-of-day price run on {when} "
            "asked for it, but the provider returned no history. That usually means the "
            f"symbol is not the one the provider uses, or the listing is suspended.{recorded}"
        )
    return (
        f"Waiting for data — {symbol} resolves, but the end-of-day price run on {when} "
        "stored no bars for it. Instruments that have never been priced are asked for "
        f"first, so the next run should fill it.{recorded}"
    )



#: Which tenors to show, in the order a curve is read. A subset rather than
#: everything: the Treasury publishes fourteen pillars and a table cell with
#: fourteen numbers in it is a data dump, not a shape. Whichever of these a given
#: curve actually has is shown, so the US curve shows six points and the gilt curve
#: three without either being special-cased.
CURVE_TENORS = ("3 Mo", "2 Yr", "5 Yr", "10 Yr", "20 Yr", "30 Yr")

#: The condition under which the "long end is under pressure" reading is wrong.
#:
#: Stated as a number, and stated at all, because a claim with no falsifier is not a
#: reading -- it is a mood, and it cannot be shown to be wrong. From the source
#: material this comes from: if the **US** 30-year settles below this and stays there
#: for a full quarter, buyers came back on their own and most of the reading does not
#: happen.
#:
#: It is deliberately tied to the US curve and not generalised. The claim is about
#: the US 30-year, and the Bank of England's published curve has no 30-year pillar at
#: all -- so applying the same threshold to the gilt curve would be inventing a
#: condition nobody stated. Where there is no such pillar, the page says so.
#:
#: **The duration is not tracked either.** One observation is stored, not a quarter
#: of them, so this reports today's level against the threshold and says plainly that
#: the "for a quarter" half is not being measured. Claiming the falsifier had been
#: evaluated would be the same class of error as the coverage column that reported
#: missing work as done.
FALSIFIER_TENOR = "30 Yr"
FALSIFIER_CURRENCY = "USD"
FALSIFIER_LEVEL = 0.045


def _curve_summary(session: Session, currency: str) -> dict[str, Any] | None:
    """One currency's observed curve, as a shape rather than a single number."""
    observation = macro.read_observation(session, currency)
    if observation is None:
        return None

    curve = macro.stored_curve(session, currency)
    shown = {tenor: curve[tenor] for tenor in CURVE_TENORS if tenor in curve}

    # The longest tenor this curve publishes, which is what a term-premium reading
    # is about. The US curve's longest is 30 years and the gilt curve's is 20, so
    # the label travels with the number instead of being hardcoded to "10s30s".
    long_tenor = max(shown, key=list(CURVE_TENORS).index) if shown else None
    long_end = curve.get(long_tenor) if long_tenor else None
    ten_year = curve.get("10 Yr")
    spread = None if long_end is None or ten_year is None else long_end - ten_year

    return {
        "currency": currency,
        "as_of": observation.as_of,
        "tenor": observation.tenor,
        "value": observation.value,
        "source": observation.source,
        "note": observation.note,
        "curve": shown,
        "long_tenor": long_tenor,
        "spread": spread,
    }


def rate_environment(session: Session) -> dict[str, Any] | None:
    """Every observed yield curve, and the condition that would falsify the reading.

    Reports, never predicts. It says what each country published, what the long end
    is doing relative to the ten-year, and what number would show the reading to be
    wrong -- which is the only part of a macro view that can be checked.

    Per currency, because the model discounts in the currency of the cash flows: a
    page showing one curve would be showing one of the two the sweep actually used.
    """
    currencies = [
        summary
        for code in sorted(macro.CURRENCY_CURVES)
        if (summary := _curve_summary(session, code)) is not None
    ]
    if not currencies:
        return None

    usd = next((summary for summary in currencies if summary["currency"] == FALSIFIER_CURRENCY), None)
    if usd is None:
        falsified = None
        falsifier_note = (
            f"no {FALSIFIER_CURRENCY} curve has been observed, so the condition on its "
            f"{FALSIFIER_TENOR} cannot be checked"
        )
    else:
        level = usd["curve"].get(FALSIFIER_TENOR)
        falsified = None if level is None else (level / 100.0) < FALSIFIER_LEVEL
        falsifier_note = (
            f"the reading is falsified if the {FALSIFIER_CURRENCY} {FALSIFIER_TENOR} "
            f"settles below {FALSIFIER_LEVEL:.2%} for a full quarter; the level is "
            "checked here, the duration is not"
        )

    return {
        "currencies": currencies,
        "falsifier_currency": FALSIFIER_CURRENCY,
        "falsifier_tenor": FALSIFIER_TENOR,
        "falsifier_level": FALSIFIER_LEVEL,
        "falsifier_met": falsified,
        "falsifier_note": falsifier_note,
    }


def latest_quotes(session: Session, tickers: list[str]) -> dict[str, Quote]:
    if not tickers:
        return {}
    rows = session.execute(
        select(Quote).where(Quote.instrument_t212_ticker.in_(tickers)).order_by(desc(Quote.ts))
    ).scalars().all()
    out: dict[str, Quote] = {}
    for quote in rows:
        out.setdefault(quote.instrument_t212_ticker, quote)
    return out

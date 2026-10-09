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

from sqlalchemy import Select, case, desc, func, or_, select
from sqlalchemy.orm import Session

from awltux.analysis import attention as attention_rules
from awltux.analysis import macro, sectors
from awltux.analysis.attention import Reason
from awltux.analysis.embeddings import group_events
from awltux.analysis.relevance import MATERIALITY_ORDER
from awltux.config import get_settings
from awltux.db import (
    DecisionOutcome,
    DecisionRun,
    Filing,
    FundamentalPeriod,
    IngestRun,
    Instrument,
    InstrumentAlias,
    LLMCall,
    NewsItem,
    PriceBar,
    Quote,
    SectorPriceIndex,
    SentimentSeries,
    T212Order,
    ValuationRun,
    utcnow,
)
from awltux.db.news import appraisals_for, mentions_ticker, news_for_ticker
from awltux.timezones import as_utc, format_moment, utc_today

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
    #: The coarse eleven -- what the sector page is keyed on. Beside ``sector`` rather
    #: than replacing it: the row shows the industry string and links to the group.
    sector_group: str | None
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
    #: Why this instrument should not be trusted yet, at the configured attention
    #: level. Empty means assessed and clean, not "not assessed" -- see
    #: :func:`awltux.analysis.attention.assess`.
    attention: tuple[Reason, ...] = ()

    @property
    def attention_summary(self) -> str:
        """Every reason on one line, for a tooltip."""
        return "; ".join(
            f"{reason.label} — {reason.detail}" if reason.detail else reason.label
            for reason in self.attention
        )

    @property
    def attention_count(self) -> int:
        return len(self.attention)

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


def _instruments_in_scope(
    session: Session,
    *,
    only_held: bool = False,
    sector: str | None = None,
    sector_unknown: bool = False,
    sector_group: str | None = None,
    search: str | None = None,
) -> list[Instrument]:
    """The instruments the table may show, narrowed by the column filters.

    Extracted from :func:`recommendations`, which had grown one branch per filter the
    page offers on top of the four phases that assemble a row -- and the page has since
    gained a fifth. The filter set *is* the specification of this table, so the branches
    are not incidental; the point of moving them is that they are all the same kind of
    thing and the assembly below is not.

    ``sector_group`` is the coarse eleven and is a *different question* from ``sector``,
    which is the SEC industry string. Both are kept because both are asked: the
    dashboard's dropdown lists the 148 industry strings a reader can search by name,
    and the sector page is keyed on the eleven that have pages. ``sector_group=UNCLASSIFIED``
    selects the instruments with no group, which is a real population of 185.
    """
    query = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    )
    if only_held:
        query = query.where(Instrument.is_held.is_(True))
    if sector_unknown:
        query = query.where(Instrument.sector.is_(None))
    elif sector:
        query = query.where(Instrument.sector == sector)
    if sector_group == sectors.UNCLASSIFIED:
        query = query.where(Instrument.sector_group.is_(None))
    elif sector_group:
        query = query.where(Instrument.sector_group == sector_group)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.where(
            func.lower(Instrument.t212_ticker).like(pattern)
            | func.lower(Instrument.name).like(pattern)
        )
    return list(session.execute(query).scalars().all())


# A paged query assembled as labelled phases. Both halves of this are deliberate: the
# phases are narrow queries rather than one wide join, and the branches are the filter
# set, which *is* the specification of this table -- one `if` per option the page offers,
# so the readable list of what can be filtered is the query that filters rather than a
# helper a reader has to go and find. What could be cut was cut: the scope phase moved to
# `_instruments_in_scope`, and the assembly loop is flat over instruments already
# narrowed. If this grows a sixth filter, split the assembly out rather than adding a
# reason here.
def recommendations(
    session: Session,
    *,
    sort: SortKey = "composite_score",
    direction: Literal["asc", "desc"] = "desc",
    action: str | None = None,
    engine: str | None = None,
    horizon: str = "long_term",
    horizon_fit: str | None = None,
    sector: str | None = None,
    sector_unknown: bool = False,
    sector_group: str | None = None,
    only_suggestions: bool = False,
    only_held: bool = False,
    needs_attention: bool = False,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[RecommendationRow], int]:
    """Return the recommendations table plus the total row count for paging.

    Assembled from a handful of narrow queries rather than one wide join. At a
    few hundred instruments the extra queries are negligible, and the result is
    far easier to reason about than a five-way outer join over correlated
    subqueries.

    ``sector`` and ``sector_unknown`` are separate arguments because they are
    separate questions. "In Pharmaceuticals" and "has no sector recorded" both
    narrow the table, but the second is asked of a column that is *empty*, and on
    the live database that is 194 of 500 instruments -- a filter that could only
    name a sector would leave a third of the universe unreachable.
    """
    # --- 1. which instruments are in scope ---------------------------------
    instruments = _instruments_in_scope(
        session,
        only_held=only_held,
        sector=sector,
        sector_unknown=sector_unknown,
        sector_group=sector_group,
        search=search,
    )
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

    # --- 4. why each instrument should not be trusted yet -------------------
    #
    # Always assessed, not only when the filter is on: the row carries its reasons either
    # way, so a reader can see *why* a row is suspect without switching the filter on to
    # find out. Bounded by the instruments already in scope, and four queries behind it.
    assessed = attention_rules.assess(session, tickers=tickers)

    # --- 5. assemble -------------------------------------------------------
    result: list[RecommendationRow] = []
    for instrument in instruments:
        decision = decisions.get(instrument.t212_ticker)
        valuation = valuations.get(instrument.t212_ticker)
        attention = assessed.get(instrument.t212_ticker)
        reasons = attention.reasons if attention is not None else ()

        if needs_attention and not reasons:
            continue
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
                sector_group=instrument.sector_group,
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
                attention=tuple(reasons),
            )
        )

    # Sorting happens in Python: the sort keys mix derived values (margin of
    # safety, freshness, action rank) that do not exist as columns, and the
    # universe is a few hundred rows, so an in-memory sort is clearer and fast
    # enough. If the universe grows past a few thousand, move this into SQL.
    result.sort(key=lambda row: _sort_value(row, sort), reverse=(direction == "desc"))
    total = len(result)
    return result[offset : offset + limit], total


def refresh_state(row: Any) -> dict[str, Any] | None:
    """The instrument's last scoped refresh, as the page reads it.

    ``None`` when the instrument has never been refreshed, which the template renders as
    an invitation rather than as an empty table. The step that is *in progress* is
    derived rather than stored: the run appends to ``steps`` as each one finishes, so the
    next step is the one after the last recorded entry, and a completed refresh has no
    step in progress at all.
    """
    if row is None:
        return None

    from awltux.ingest import refresh

    done = [entry for entry in (row.steps or []) if isinstance(entry, dict)]
    sequence = refresh.step_ids()
    # `as_utc`: SQLite returns this naive however the column is declared, and comparing
    # it to an aware clock raises rather than answering.
    running = row.state == "running" and as_utc(row.expires_at) > utcnow()
    # Index by position so a step that is no longer in the sequence -- the registry
    # changed between runs -- cannot make the count wrong.
    finished = len([entry for entry in done if entry.get("step") in sequence])
    return {
        "state": row.state,
        "running": running,
        "note": row.note,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "total_steps": len(sequence),
        "steps_done": finished,
        "current": sequence[finished] if running and finished < len(sequence) else None,
        "steps": done,
        "failed": [entry for entry in done if entry.get("ok") is False],
    }


def _credit_spend(session: Session, *, days: int = 30) -> tuple[dict[str, float], dict[str, int]]:
    """Model spend and call counts per provider, from our own call log.

    Our log rather than the provider's, because it is the only spend figure that exists
    for a provider whose billing endpoint we cannot read -- and because it is measured the
    same way regardless of who is asking.
    """
    spend: dict[str, float] = {}
    calls: dict[str, int] = {}
    for provider, total, count in session.execute(
        select(
            LLMCall.provider,
            func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
            func.count(LLMCall.id),
        )
        .where(LLMCall.created_at >= utcnow() - dt.timedelta(days=days))
        .group_by(LLMCall.provider)
    ).all():
        spend[provider] = float(total or 0.0)
        calls[provider] = int(count or 0)
    return spend, calls


def _payment_failures(session: Session, *, days: int = 7) -> dict[str, str]:
    """The most recent message per provider that reads as a payment refusal.

    Classified in Python rather than with a `LIKE` chain: the marker list is a rule with a
    reason and belongs where it can be read and tested. One per provider, because a
    hundred identical 402s are one problem.
    """
    from awltux.providers.balances import looks_like_payment_failure

    found: dict[str, str] = {}
    for provider, error in session.execute(
        select(LLMCall.provider, LLMCall.error)
        .where(LLMCall.ok.is_(False))
        .where(LLMCall.created_at >= utcnow() - dt.timedelta(days=days))
        .order_by(LLMCall.created_at.desc())
        .limit(200)
    ).all():
        if provider not in found and looks_like_payment_failure(error):
            found[provider] = (error or "")[:240]
    return found


def _credit_warnings(balance: Any, *, failure: str | None, floor: float) -> list[str]:
    """Every reason this provider deserves a line in the banner, worded for a reader.

    Unreadable is deliberately not one of them: several providers cannot be asked at all
    with the credential this project holds, and a bar that is always up is a bar nobody
    reads.
    """
    out: list[str] = []
    if balance.available is False:
        out.append(f"{balance.provider} reports it cannot pay; model calls will fail")
    elif balance.amount is not None and balance.amount < floor:
        shown = f"{balance.amount:,.2f} {balance.currency or ''}".strip()
        out.append(f"{balance.provider} is down to {shown}, below the {floor:,.2f} floor")
    if failure:
        out.append(f"{balance.provider} refused a call for payment: {failure}")
    return out


def provider_status(session: Session, *, settings: Any = None) -> dict[str, Any]:
    """Whether any model provider is out of money, and what each one has left.

    Two independent signals, because one of them needs the provider's co-operation and the
    other does not:

    * **What the provider says.** ``providers/balances.py`` reads DeepSeek's balance
      endpoint. fal's exists and refuses this project's model key (403), so its reading is
      *unreadable* -- which is reported as unreadable and never as zero. An operator who
      adds ``FAL_ADMIN_KEY`` gets a number instead.
    * **What our own calls show.** Every model call is logged with its cost and its error
      in ``llm_call``, so spend and *payment failures* are visible regardless of what any
      provider is willing to expose. A call that failed because the account could not pay
      is direct evidence, and it arrives the moment it happens rather than at the next
      hourly probe.

    Returns ``warnings`` already worded, because the template must not decide what counts
    as a problem -- the same reason the attention reasons are built in analysis rather than
    in Jinja.
    """
    from awltux.providers.balances import Balance, read_stored

    settings = settings or get_settings()
    floor = settings.app.balance_warn_below_usd

    balances = read_stored(session)
    if not balances:
        # Never probed. The job runs on start, so this is the first few seconds after a
        # fresh container rather than a normal state -- and saying so beats a blank bar.
        balances = [
            Balance(name, note="no reading yet; the provider_balance job has not run")
            for name in ("deepseek", "fal")
        ]

    spend, calls = _credit_spend(session)
    failures = _payment_failures(session)

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for balance in balances:
        read_at = as_utc(balance.read_at) if balance.read_at else None
        failure = failures.get(balance.provider)
        rows.append(
            {
                "provider": balance.provider,
                "amount": balance.amount,
                "currency": balance.currency,
                "available": balance.available,
                "note": balance.note,
                "read_at": read_at,
                "stale": read_at is None or (utcnow() - read_at) > dt.timedelta(hours=3),
                "spent": spend.get(balance.provider),
                "calls": calls.get(balance.provider, 0),
                "payment_failure": failure,
            }
        )
        warnings.extend(_credit_warnings(balance, failure=failure, floor=floor))

    return {
        "balances": rows,
        "warnings": warnings,
        # Whether *any* provider reported a number. The strip says so when none did, which
        # is how a reader tells "everything is fine" from "we cannot see anything".
        "readable": any(row["amount"] is not None for row in rows),
        "floor": floor,
    }


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


#: How many of the reader's own trades the instrument page lists. Bounded because a
#: long-held position has hundreds and the page is not a statement.
TRADES_ON_THE_PAGE = 25


@dataclass(frozen=True)
class TradeRow:
    """One execution from the broker, with what those shares would fetch at the latest close.

    **`current_value` moves the cash the trade actually moved, not a fresh conversion.**
    `value` is the broker's own figure in the account's currency -- its FX leg and its fee
    are already in it -- and scaling it by ``close / fill_price`` keeps the two money columns
    comparable, so the percentage beside them is *exactly* their ratio. Inventing a GBP rate
    of our own to re-price the shares would put a number beside a number it does not agree
    with. The trade-off is that FX movement since the fill is not in it: this is the price
    change, deliberately.

    It is also not a live quote: `close` is the newest stored daily bar, the same one the
    price chart ends on, so the table and the chart cannot disagree about "now".
    """

    executed_at: dt.datetime | None
    side: str | None
    quantity: float | None
    fill_price: float | None
    value: float | None
    currency: str | None
    kind: str
    current_value: float | None
    change: float | None


def trade_row(order: T212Order, close: float | None) -> TradeRow:
    """One stored order as the page shows it. Pure, so the arithmetic is testable alone."""
    price = order.fill_price
    change = None
    if close is not None and price:
        change = close / price - 1.0
    current_value = None
    if order.net_value is not None and change is not None:
        current_value = order.net_value * (1.0 + change)
    return TradeRow(
        executed_at=order.filled_at or order.created_at,
        side=order.side,
        quantity=order.filled_quantity,
        fill_price=price,
        value=order.net_value,
        currency=order.currency,
        kind=_trade_kind(order),
        current_value=current_value,
        change=change,
    )


def _trade_kind(order: T212Order) -> str:
    """What the row actually is, in the broker's own vocabulary.

    A stock split or an equity-rights issue arrives in this feed wearing an order's clothes,
    so calling every row a trade would be wrong. The order of the checks is the order the
    distinctions matter in: what kind of fill it was, then whether it completed at all.
    """
    if order.fill_type and order.fill_type != "TRADE":
        return str(order.fill_type).lower().replace("_", " ")
    if order.status and order.status != "FILLED":
        return str(order.status).lower()
    return "trade"


def instrument_detail(
    session: Session,
    ticker: str,
    *,
    news_page: int = 1,
    news_per_page: int = 25,
) -> dict[str, Any] | None:
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

    # Paged, and filtered in SQL. The first version took the newest 40 items across
    # the whole universe and filtered them by ticker afterwards, so the window was
    # global: measured on 6,555 stored items, 131 of the 153 instruments that had
    # news showed none. See `awltux/db/news.py`.
    related_news, news_total = news_for_ticker(
        session, ticker, limit=news_per_page, offset=(news_page - 1) * news_per_page
    )
    # Scoped to *this* instrument: `related_news` can name several companies, and the
    # appraisal the page must show is the one built for the page it is on.
    appraisals = appraisals_for(session, related_news, subject=("instrument", ticker))

    # One entry per *event*, the same grouping the flash banner uses. A profit warning
    # reaches this system five or six times, and this list used to show all of them --
    # so the reader's own company page was the one place the duplicates were certain to
    # appear. Grouping happens inside the page rather than in SQL because the page is
    # already the unit: `news_total` still counts stories, so paging is unchanged and a
    # page of twenty shows however many events those twenty describe.
    news_events, news_clustering = group_events(list(related_news))

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

    trades, trades_truncated = _trades_for(session, ticker)

    return {
        "instrument": instrument,
        "decision": decision,
        "valuation": valuation,
        "bars": list(reversed(bars)),
        "filings": filings,
        "fundamentals": fundamentals,
        "news": related_news,
        "news_events": news_events,
        "news_clustering": news_clustering,
        "news_analysis": appraisals,
        "news_total": news_total,
        "news_page": news_page,
        "news_per_page": news_per_page,
        "news_pages": max(1, -(-news_total // news_per_page)),
        "outcomes": outcomes,
        "trades": trades,
        "trades_truncated": trades_truncated,
    }


def _trades_for(session: Session, ticker: str) -> tuple[list[TradeRow], bool]:
    """The reader's own trades in one instrument, newest execution first.

    One extra row is fetched and then discarded, which is how "there are more than this"
    is known without a second ``COUNT`` over the same predicate. Nulls sort last under a
    descending order in SQLite, so a row with no execution date falls to the bottom rather
    than the top -- it has not happened yet as far as the reader is concerned.

    The latest close is read here rather than passed in, and is the newest stored bar the
    chart also ends on, so the two halves of the page cannot measure "now" differently.
    """
    rows = session.execute(
        select(T212Order)
        .where(T212Order.instrument_t212_ticker == ticker)
        .order_by(desc(T212Order.filled_at), desc(T212Order.order_id))
        .limit(TRADES_ON_THE_PAGE + 1)
    ).scalars().all()
    close = session.execute(
        select(PriceBar.close)
        .where(PriceBar.instrument_t212_ticker == ticker)
        .order_by(desc(PriceBar.date))
        .limit(1)
    ).scalar()
    trades = [trade_row(row, close) for row in rows[:TRADES_ON_THE_PAGE]]
    return trades, len(rows) > TRADES_ON_THE_PAGE


def accounts_detail(session: Session, period_id: int) -> dict[str, Any] | None:
    """One stored period, the comparable one before it, and its instrument.

    **The predecessor is matched on period type and source, not on date alone.** The
    articulation checks compare closing figures against opening ones, and comparing an
    annual XBRL period with the interim snapshot an extractor produced three months
    later would produce a retained-earnings roll-forward that measures the gap between
    two taxonomies rather than the movement in the business. Same type, same source, so
    the two periods are the same kind of statement.

    ``None`` for a period that does not exist, which the route turns into a 404 rather
    than an empty page: an accounts page with no accounts is not a useful answer.
    """
    period = session.get(FundamentalPeriod, period_id)
    if period is None:
        return None

    previous = session.execute(
        select(FundamentalPeriod)
        .where(FundamentalPeriod.instrument_t212_ticker == period.instrument_t212_ticker)
        .where(FundamentalPeriod.period_type == period.period_type)
        .where(FundamentalPeriod.source == period.source)
        .where(FundamentalPeriod.period_end < period.period_end)
        .order_by(desc(FundamentalPeriod.period_end))
        .limit(1)
    ).scalar_one_or_none()

    # Everything up to and including the period on screen, oldest first. The health
    # tab runs the same analysis the instrument page does, and truncating the series
    # is what stops it reporting on a later year than the accounts being read -- a
    # page showing 2022 figures next to 2024 verdicts is worse than no verdicts.
    series = list(
        session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == period.instrument_t212_ticker)
            .where(FundamentalPeriod.period_end <= period.period_end)
            .order_by(FundamentalPeriod.period_end)
        ).scalars().all()
    )

    return {
        "period": period,
        "previous": previous,
        "instrument": session.get(Instrument, period.instrument_t212_ticker),
        "series": series,
    }


def recent_news(
    session: Session,
    *,
    limit: int = 50,
    min_materiality: str | None = None,
    ticker: str | None = None,
) -> list[NewsItem]:
    """The latest news, optionally for one instrument.

    When a ticker is given the filter happens in SQL. It used to fetch ``limit * 4``
    rows globally and filter them in Python, which is the same defect the instrument
    page had: the multiplier was a guess at how far down the global ordering you
    would have to look, and it is wrong in the direction that empties as news grows.
    """
    if ticker:
        items, _ = news_for_ticker(session, ticker, limit=limit)
        if min_materiality:
            items = [item for item in items if item.materiality == min_materiality]
        return items

    statement = select(NewsItem).order_by(desc(NewsItem.published_at), desc(NewsItem.id))
    if min_materiality:
        statement = statement.where(NewsItem.materiality == min_materiality)
    return list(session.execute(statement.limit(limit)).scalars().all())


#: The columns the news listing can be ordered by.
#:
#: **Columns, not the ticker's priority score.** Priority is
#: ``materiality x credibility x recency`` and is computed in Python over a bounded
#: recent window (see ``routes/news.py::_ranked``), so ordering the whole corpus by it
#: would mean loading every row to sort it in memory -- and the recency term needs a
#: fractional power SQLite does not provide without the optional math extension
#: (measured: ``select exp(1)`` on this database raises "no such function"). The stored
#: inputs are what a table can sort, and ``materiality`` is the one that dominates the
#: score. The score itself is on each story's own page, and "best first" is the ticker's
#: job.
NewsSortKey = Literal["published_at", "materiality", "source", "title", "relevance"]

SortDirection = Literal["asc", "desc"]

#: Materiality as the sortable integer its severity order implies.
#:
#: Derived from the analysis layer's own ``MATERIALITY_ORDER`` rather than restated, so a
#: level added there cannot silently sort as the lowest one. ``-1`` is "not assessed",
#: which the ordering places below ``none``: a story nobody has judged is less usable
#: than one judged unimportant, and both are below "mild".
_MATERIALITY_RANK = case(
    {level: rank for rank, level in enumerate(MATERIALITY_ORDER)},
    value=NewsItem.materiality,
    else_=-1,
)


def _news_order(sort: NewsSortKey, direction: SortDirection) -> tuple[Any, ...]:
    """The ORDER BY for the news listing, always ending in a deterministic tie-break.

    **The tie-break is what makes offset paging correct.** ``published_at`` is not
    unique -- a feed's batch shares a timestamp to the second, and Google News alone
    contributes 26,580 of the 27,884 stored stories -- so ordering by it alone leaves the
    rows inside a tie in whatever order SQLite happens to return them. That order is free
    to differ between the count and the page, and between page one and page two, and the
    failure is silent: one story appears twice while another never appears at all.
    ``id`` is unique and monotonic with arrival, so it settles it in the same direction
    the reader asked for.
    """
    key = {
        "published_at": NewsItem.published_at,
        "materiality": _MATERIALITY_RANK,
        "source": NewsItem.source,
        "title": NewsItem.title,
        "relevance": NewsItem.relevant,
    }[sort]
    ordered = key.asc() if direction == "asc" else key.desc()
    tie_break = NewsItem.id.asc() if direction == "asc" else NewsItem.id.desc()
    return (ordered, tie_break)


def news_listing(
    session: Session,
    *,
    search: str | None = None,
    source: str | None = None,
    materiality: str | None = None,
    relevant: bool | None = None,
    unassessed: bool = False,
    ticker: str | None = None,
    since: dt.datetime | None = None,
    sort: NewsSortKey = "published_at",
    direction: SortDirection = "desc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[NewsItem], int]:
    """One page of *every* stored story, and how many match the same predicate.

    The news page's read model. It is deliberately not :func:`recent_news`: that one
    answers "the newest N", so it cannot page, and its filters are the two the JSON API
    happens to expose (a ticker, a materiality floor). This one filters, counts and
    slices in SQL, so the total the pager prints is the whole matching set rather than
    the page -- the defect `tests/test_news_paging.py` records for the instrument page.

    ``unassessed`` is a separate argument from ``relevant`` because "no classifier has
    judged this" is not "judged not relevant". ``relevant is None`` is a state the model
    keeps distinct on purpose, and one that a URL cannot express through a boolean.

    The rows come back as :class:`~awltux.db.NewsItem` objects, not as the ticker's
    serialised dicts: the page needs the appraisals too, and it attaches those itself so
    that exactly one place decides which appraisal a story's row shows.
    """
    conditions: list[Any] = []
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(NewsItem.title.ilike(pattern), NewsItem.source.ilike(pattern))
        )
    if source:
        conditions.append(NewsItem.source == source)
    if materiality:
        conditions.append(NewsItem.materiality == materiality)
    if unassessed:
        conditions.append(NewsItem.relevant.is_(None))
    elif relevant is not None:
        conditions.append(NewsItem.relevant.is_(relevant))
    if ticker:
        conditions.append(mentions_ticker(ticker))
    if since is not None:
        conditions.append(NewsItem.published_at >= since)

    total = session.execute(
        select(func.count()).select_from(NewsItem).where(*conditions)
    ).scalar_one()

    statement: Select = (
        select(NewsItem)
        .where(*conditions)
        .order_by(*_news_order(sort, direction))
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(statement).scalars().all()), int(total)


def news_source_counts(session: Session) -> list[tuple[str, int]]:
    """How many stories each feed contributed, busiest first.

    Unbounded rather than capped at the busiest N: the source filter's options are also
    what validates the URL, and a value missing from them is *ignored* rather than
    applied (`filters.FilterSet.parse`). A cap would therefore make a long-tail source
    unaddressable -- quietly, and only for the reader who went looking for it.

    Measured 2026-10-09 on the live database there are five: google_news (26,580),
    yahoo_rss (1,202), marketaux (88), edgar (13) and finnhub (1). If the feeds ever
    multiply past a dropdown, the answer is a search box rather than a cap.
    """
    rows = session.execute(
        select(NewsItem.source, func.count())
        .group_by(NewsItem.source)
        .order_by(func.count().desc(), NewsItem.source)
    ).all()
    return [(name, int(count)) for name, count in rows]


def news_materiality_counts(session: Session) -> list[tuple[str | None, int]]:
    """How many stories sit at each materiality level, unassessed included.

    Raw ``(level, count)`` pairs in no particular order, because the order the control
    shows is a severity question and that belongs in the presentation layer
    (``filters.materiality_options``), not here.
    """
    rows = session.execute(
        select(NewsItem.materiality, func.count()).group_by(NewsItem.materiality)
    ).all()
    return [(level, int(count)) for level, count in rows]


def sector_group_counts(session: Session) -> list[tuple[str | None, int]]:
    """How many in-universe instruments sit in each coarse sector.

    ``None`` is a real key, exactly as :func:`sector_counts` documents for the
    industry string: 185 in-universe instruments have neither a SIC code nor a sector
    string, and the index has to be able to offer them or a third of the universe is
    unreachable from the sector pages.
    """
    rows = session.execute(
        select(Instrument.sector_group, func.count())
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .group_by(Instrument.sector_group)
    ).all()
    return [(group, count) for group, count in rows]


def sector_news(session: Session, name: str, *, limit: int = 25) -> list[tuple[Any, Any]]:
    """Recent stories tagged with a sector, each with its *sector* appraisal.

    Scoped to the subject, which is the whole point of the per-subject appraisal: a
    story that also names a company has a different verdict for the company, and the
    sector page must show the sector's.
    """
    tickers: list[tuple[NewsItem, Any]] = []
    rows = list(
        session.execute(
            select(NewsItem)
            .where(NewsItem.relevant.is_(True))
            .order_by(desc(NewsItem.published_at))
            .limit(400)
        ).scalars().all()
    )
    tagged = [row for row in rows if name in (row.sectors or [])]
    appraisals = appraisals_for(session, tagged, subject=("sector", name))
    for row in tagged[:limit]:
        tickers.append((row, appraisals.get(row.id)))
    return tickers


def sector_sentiment_series(session: Session, name: str, *, days: int = 60) -> list[dict[str, Any]]:
    """One sector's sentiment series, oldest first. Empty when it has none yet."""
    series = sector_sentiment(session, days=days)
    return series.get(name, [])


#: Points the sector chart draws. The same 400 the index is built over, so the line is the
#: whole series rather than a truncated view of it.
SECTOR_INDEX_POINTS = 400


def sector_price_index(
    session: Session, name: str, *, limit: int = SECTOR_INDEX_POINTS
) -> list[dict[str, Any]]:
    """One sector's stored price index, oldest first, in the chart's own shape.

    Read from `sector_price_index` rather than derived here: deriving it means reading every
    constituent's bars (measured 2026-10-08: 20,753 rows and 135 ms for Information
    Technology, 61,728 and 445 ms for the unclassified bucket) and this page re-renders on a
    column sort. `sector_index` rebuilds it after the prices land.

    `level` is the field, not `close`: the number is an index level rebased to 100, and
    calling it a price would invite a reader to compare it with a share price.
    """
    rows = session.execute(
        select(SectorPriceIndex)
        .where(SectorPriceIndex.sector == name)
        .order_by(desc(SectorPriceIndex.date))
        .limit(limit)
    ).scalars().all()
    return [
        {
            "date": row.date.isoformat(),
            "level": row.level,
            "contributors": row.contributors,
        }
        for row in reversed(rows)
    ]


def sector_index_basis(session: Session, name: str) -> dict[str, Any] | None:
    """What the index's 100 is anchored to, and how many instruments are behind the last point.

    Returned separately from the series because it describes the whole line rather than any
    point on it -- and because a level printed without its base is the kind of number this
    module refuses to hand a template.
    """
    row = session.execute(
        select(SectorPriceIndex)
        .where(SectorPriceIndex.sector == name)
        .order_by(desc(SectorPriceIndex.date))
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "base_date": row.base_date.isoformat(),
        "contributors": row.contributors,
        "as_of": row.date.isoformat(),
        "computed_at": row.computed_at,
    }


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


def sector_counts(session: Session) -> list[tuple[str | None, int]]:
    """How many instruments in the universe sit in each sector.

    ``None`` is a real key here, not a gap: it counts the instruments whose sector
    has never been resolved. Returning it rather than dropping the row is what lets
    the caller offer them as a choice -- filtering them out would make a third of
    the universe unreachable by any sector control.

    Returned as plain rows so this module keeps to SQL; turning them into dropdown
    entries is a presentation decision (:func:`awltux.web.filters.sector_options`).
    """
    rows = session.execute(
        select(Instrument.sector, func.count())
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .group_by(Instrument.sector)
    ).all()
    return [(sector, count) for sector, count in rows]


def universe_size(session: Session) -> int:
    """How many instruments are in the analysed universe.

    Its own query because two callers want the one number without the rest of
    :func:`universe_stats`: the recommendations table needs it to explain an empty
    result, and a page change re-renders that table on its own. :func:`universe_stats`
    calls this rather than repeating the count, so the two cannot disagree.
    """
    return session.execute(
        select(func.count()).select_from(Instrument).where(Instrument.in_universe.is_(True))
    ).scalar_one()


def universe_stats(session: Session) -> dict[str, Any]:
    """Headline counters for the dashboard header."""
    total = universe_size(session)
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

#: Markers put on the price chart at most. The plot is 180px tall and a marker is a dot
#: with a letter on it, so past this they stop being readable, let alone informative.
MAX_CHART_MARKERS = 30

#: What a marker is, and the letter the chart draws for it. `average` is not an execution:
#: it is the broker's cost basis, used when no individual trade is stored.
MARKER_LETTERS = {"buy": "B", "sell": "S", "average": "A"}


def price_markers(
    history: list[dict[str, Any]],
    trades: list[TradeRow],
    instrument: Instrument | None,
) -> list[dict[str, Any]]:
    """Where the reader's own executions fall on the price line.

    The chart drew the market and nothing else, so the one thing a reader who holds the
    instrument wants to see -- what they paid against what it costs now -- was only ever in
    a table beside it.

    **Placed on a bar, not on the trade's own date.** A fill can land on a weekend or a
    holiday, and the plot's x axis is the stored bar dates, so each marker is snapped to the
    nearest bar -- see `_bar_on_or_after` for which way each edge resolves.

    **The price is the execution price**, which may sit outside the stored series' range;
    `app.js` widens the axis to include it rather than hiding the cost.
    """
    if not history:
        return []
    first_day, last_day = history[0]["date"], history[-1]["date"]

    markers = []
    for trade in trades:
        when = trade.executed_at
        side = (trade.side or "").upper()
        if when is None or trade.fill_price is None or side not in ("BUY", "SELL"):
            continue
        day = _bar_on_or_after(history, when.date(), first_day, last_day)
        if day is None:
            continue
        markers.append(
            {
                "date": day,
                "price": float(trade.fill_price),
                "letter": MARKER_LETTERS[side.lower()],
            }
        )

    # Only when nothing individual is stored. A position whose buys predate the order
    # history -- or that arrived by transfer -- still has a date and a price, and a chart
    # with no marker at all would say the position does not exist.
    if not markers and instrument is not None and instrument.position_average_price:
        opened = instrument.position_opened_at
        day = _bar_on_or_after(
            history,
            opened.date() if opened else dt.date.fromisoformat(last_day),
            first_day,
            last_day,
        )
        if day is not None:
            markers.append(
                {
                    "date": day,
                    "price": float(instrument.position_average_price),
                    "letter": MARKER_LETTERS["average"],
                }
            )

    # `trades` arrives newest execution first, so the cap keeps the most recent ones.
    return markers[:MAX_CHART_MARKERS]


def _bar_on_or_after(
    history: list[dict[str, Any]], day: dt.date, first_day: str, last_day: str
) -> str | None:
    """The bar a marker sits on: the first one on or after ``day``.

    **A trade newer than the last stored bar takes the last bar.** Prices are stored
    end-of-day, so a fill made today has no bar yet, and dropping it would hide the most
    recent -- and most interesting -- execution on the chart. The right edge is a day or two
    out at most, which the legend says.

    A trade older than the first bar is dropped instead: the left edge is up to 400 bars
    back, and snapping an old buy onto it would park it at a date it was never near.
    """
    if day.isoformat() < first_day:
        return None
    if day.isoformat() > last_day:
        return last_day
    for bar in history:
        if bar["date"] >= day.isoformat():
            return bar["date"]
    return last_day


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

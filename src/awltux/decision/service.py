"""Decision orchestration: one instrument, from stored evidence to a stored call.

The pipeline for each instrument is fixed and auditable:

1. Assemble the evidence from the database (valuation, prices, accounts,
   sentiment, news).
2. Build the canonical state and hash it.
3. Ask each configured engine in priority order, falling through on failure and
   **recording why** it fell through.
4. Score the answers into a composite.
5. Run the risk gate, which names the single binding rule if it refuses.
6. Persist an immutable :class:`~awltux.db.models.DecisionRun`.

Nothing here is inferred later: everything the decision depended on is written
down at decision time, including which engine answered and whether its
probabilities were calibrated.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from awltux.analysis.fundamental import build_snapshot
from awltux.analysis.state import build_state
from awltux.analysis.technical import analyse
from awltux.config import Settings, get_settings
from awltux.db import (
    DecisionRun,
    Filing,
    FundamentalPeriod,
    Instrument,
    NewsItem,
    PriceBar,
    SentimentSeries,
    ValuationRun,
    utcnow,
)
from awltux.db.session import release_write_lock
from awltux.decision.composite import compute_both
from awltux.decision.engine import (
    DecisionEngine,
    DecisionEngineError,
    DecisionResponse,
    EngineUnavailable,
)
from awltux.decision.gate import build_context, evaluate
from awltux.decision.questions import build_questions, question_metadata

logger = logging.getLogger(__name__)

APP_VERSION = "0.1.0"

#: News older than this is not "recent" for decision purposes.
NEWS_WINDOW_DAYS = 30


@dataclass(slots=True)
class DecisionStats:
    attempted: int = 0
    decided: int = 0
    skipped: int = 0
    long_term_suggestions: int = 0
    short_term_suggestions: int = 0
    both_horizons: int = 0
    conflicts: int = 0
    by_engine: dict[str, int] = None  # type: ignore[assignment]
    horizon_fit: dict[str, int] = None  # type: ignore[assignment]
    failures: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.by_engine = self.by_engine or {}
        self.horizon_fit = self.horizon_fit or {}
        self.failures = self.failures or []

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "decided": self.decided,
            "skipped": self.skipped,
            "long_term_suggestions": self.long_term_suggestions,
            "short_term_suggestions": self.short_term_suggestions,
            "both_horizons": self.both_horizons,
            "conflicts": self.conflicts,
            "by_engine": self.by_engine,
            "horizon_fit": self.horizon_fit,
            "failures": self.failures[:25],
        }


# --------------------------------------------------------------------------- #
# engine selection
# --------------------------------------------------------------------------- #


def build_engines(settings: Settings) -> dict[str, DecisionEngine]:
    from awltux.decision.deepseek_engine import DeepSeekDecisionEngine
    from awltux.decision.jev import JevEngine
    from awltux.decision.offline import OfflineEngine

    return {
        "jev": JevEngine(settings),
        "deepseek": DeepSeekDecisionEngine(settings),
        "offline": OfflineEngine(),
    }


def run_engines(
    *,
    state: dict[str, Any],
    state_text: str,
    questions: dict[str, Any],
    settings: Settings,
    engines: dict[str, DecisionEngine] | None = None,
) -> tuple[DecisionResponse | None, str | None, list[str]]:
    """Try each engine in priority order.

    Returns ``(response, fallback_reason, notes)``. The first engine that succeeds
    wins; every earlier failure is recorded so a decision made by a fallback
    engine always carries the reason JEV did not answer.
    """
    engines = engines or build_engines(settings)
    notes: list[str] = []
    skipped: list[tuple[str, str]] = []

    for name in settings.decision.engine_priority:
        engine = engines.get(name)
        if engine is None:
            skipped.append((name, "unknown engine in engine_priority"))
            continue
        if not engine.available:
            skipped.append((name, "not configured"))
            continue
        try:
            response = engine.decide(
                state=state, state_text=state_text, questions=questions
            )
        except EngineUnavailable as exc:
            skipped.append((name, str(exc)))
            continue
        except DecisionEngineError as exc:
            skipped.append((name, str(exc)))
            logger.warning("engine %s failed: %s", name, exc)
            continue
        except Exception as exc:  # never let an engine bug stop the run
            skipped.append((name, f"{type(exc).__name__}: {exc}"))
            logger.exception("engine %s raised unexpectedly", name)
            continue

        fallback_reason = None
        if name != settings.decision.engine_priority[0] and skipped:
            fallback_reason = "; ".join(f"{engine_name}: {why}" for engine_name, why in skipped)
            notes.append(f"decided by fallback engine {name} ({fallback_reason})")

        return response, fallback_reason, notes

    return None, "every configured engine was unavailable or failed", notes


# --------------------------------------------------------------------------- #
# evidence assembly
# --------------------------------------------------------------------------- #


def _latest_valuation(session: Session, ticker: str) -> ValuationRun | None:
    return session.execute(
        select(ValuationRun)
        .where(ValuationRun.instrument_t212_ticker == ticker)
        .order_by(desc(ValuationRun.as_of))
        .limit(1)
    ).scalar_one_or_none()


def _latest_sentiment(session: Session, scope_type: str, scope_id: str) -> float | None:
    row = session.execute(
        select(SentimentSeries)
        .where(SentimentSeries.scope_type == scope_type)
        .where(SentimentSeries.scope_id == scope_id)
        .order_by(desc(SentimentSeries.date))
        .limit(1)
    ).scalar_one_or_none()
    return row.score if row else None


def _recent_news(session: Session, ticker: str, limit: int = 12) -> list[NewsItem]:
    cutoff = utcnow() - dt.timedelta(days=NEWS_WINDOW_DAYS)
    rows = session.execute(
        select(NewsItem)
        .where(NewsItem.published_at >= cutoff)
        .order_by(desc(NewsItem.published_at))
        .limit(400)
    ).scalars().all()
    matched = [row for row in rows if ticker in (row.tickers or [])]
    return matched[:limit]


def _last_filing(session: Session, ticker: str) -> Filing | None:
    return session.execute(
        select(Filing)
        .where(Filing.instrument_t212_ticker == ticker)
        .order_by(desc(Filing.filed_at))
        .limit(1)
    ).scalar_one_or_none()


def _bars(session: Session, ticker: str) -> list[PriceBar]:
    return list(
        session.execute(
            select(PriceBar)
            .where(PriceBar.instrument_t212_ticker == ticker)
            .order_by(PriceBar.date.asc())
        ).scalars().all()
    )


def _portfolio_context(
    session: Session, settings: Settings, instrument: Instrument
) -> dict[str, Any]:
    """Position/sector weights, from Trading 212 when it is configured.

    Returns ``portfolio_known=False`` when the account cannot be read. That flag
    is the important part: Trading 212 issues keys with scopes, and a
    ``metadata``-only key cannot read positions at all. An *unreadable* empty
    portfolio is indistinguishable in the numbers from a genuinely empty one, so
    the gate treats it as unverified rather than reporting limits as enforced.
    """
    context: dict[str, Any] = {
        "open_positions": 0.0,
        "current_weight": 0.0,
        "sector_weight": 0.0,
        "portfolio_known": False,
    }
    if not settings.env.t212_configured:
        return context

    try:
        from awltux.providers.t212 import T212Provider

        provider = T212Provider(settings)
        positions = provider.get_positions()
        summary = provider.get_account_summary()
    except Exception as exc:
        logger.debug("portfolio context unavailable: %s", exc)
        return context

    # The read succeeded, so the numbers below mean something.
    context["portfolio_known"] = True

    total = 0.0
    if isinstance(summary, dict):
        total = float(summary.get("totalValue") or summary.get("invested") or 0.0)

    context["open_positions"] = float(len(positions))
    if total <= 0:
        # Positions are visible but the account value is not, so percentage
        # limits still cannot be computed. Report the count, not the weights.
        context["portfolio_known"] = False
        return context

    held_by_ticker: dict[str, float] = {}
    for position in positions:
        ticker = (position.get("instrument") or {}).get("ticker")
        value = ((position.get("walletImpact") or {}).get("currentValue")) or 0.0
        if ticker:
            held_by_ticker[str(ticker)] = float(value)

    context["current_weight"] = held_by_ticker.get(instrument.t212_ticker, 0.0) / total

    if instrument.sector:
        sector_instruments = {
            row.t212_ticker
            for row in session.execute(
                select(Instrument).where(Instrument.sector == instrument.sector)
            ).scalars().all()
        }
        context["sector_weight"] = (
            sum(value for ticker, value in held_by_ticker.items() if ticker in sector_instruments)
            / total
        )
    return context


# --------------------------------------------------------------------------- #
# the pipeline
# --------------------------------------------------------------------------- #


def decide_instrument(
    session: Session,
    instrument: Instrument,
    *,
    settings: Settings | None = None,
    engines: dict[str, DecisionEngine] | None = None,
    force: bool = False,
) -> DecisionRun | None:
    """Produce and store one decision. Returns ``None`` if it could not be made."""
    settings = settings or get_settings()

    bars = _bars(session, instrument.t212_ticker)
    if not bars:
        logger.debug("%s: no price history, skipping", instrument.t212_ticker)
        return None

    valuation_run = _latest_valuation(session, instrument.t212_ticker)
    periods = list(
        session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == instrument.t212_ticker)
            .order_by(FundamentalPeriod.period_end.asc())
        ).scalars().all()
    )

    closes = [bar.close for bar in bars if bar.close]
    volumes = [bar.volume or 0.0 for bar in bars]
    technical = analyse(closes, volumes)
    fundamentals = build_snapshot(periods)

    sentiment_score = _latest_sentiment(session, "instrument", instrument.t212_ticker)
    sector_score = (
        _latest_sentiment(session, "sector", instrument.sector)
        if instrument.sector
        else None
    )
    news = _recent_news(session, instrument.t212_ticker)
    filing = _last_filing(session, instrument.t212_ticker)

    valuation = None
    if valuation_run is not None:
        valuation = _valuation_result_from_row(valuation_run)

    state = build_state(
        instrument=instrument,
        valuation=valuation,
        technical=technical,
        fundamentals=fundamentals,
        sentiment_score=sentiment_score,
        sector_sentiment=sector_score,
        news=news,
        extracted_facts=_extracted_facts(filing),
        filing_summary=_filing_summary(filing),
        max_tokens=settings.decision.jev_max_state_tokens,
    )

    questions = build_questions()
    response, fallback_reason, engine_notes = run_engines(
        state=state.payload,
        state_text=state.text,
        questions=questions,
        settings=settings,
        engines=engines,
    )

    if response is None:
        logger.warning("%s: no engine could decide (%s)", instrument.t212_ticker, fallback_reason)
        return None

    long_composite, short_composite = compute_both(response, settings=settings)

    portfolio = _portfolio_context(session, settings, instrument)
    shared_context = {
        "price_at": dt.datetime.combine(bars[-1].date, dt.time(0, 0), tzinfo=dt.UTC),
        "valuation_at": valuation_run.as_of if valuation_run else None,
        "last_filing_at": filing.filed_at if filing else None,
        "median_daily_turnover_gbp": instrument.median_daily_turnover_gbp,
        "open_positions": int(portfolio["open_positions"]),
        "current_weight": portfolio["current_weight"],
        "sector_weight": portfolio["sector_weight"],
        "portfolio_known": bool(portfolio["portfolio_known"]),
        "min_engine": settings.decision.min_engine_for_suggestion,
    }

    long_verdict = evaluate(
        response,
        long_composite,
        build_context(**shared_context),
        horizon="long_term",
        settings=settings,
    )

    # The tactical gate needs the setup score, which comes from the decision's own
    # answers rather than from the state: it is a judgement, and requiring it
    # before a tactical call can be actionable is what stops one resting on
    # nothing but an opinion about momentum.
    short_verdict = evaluate(
        response,
        short_composite,
        build_context(
            **shared_context,
            setup_score=response.score("short_term_setup"),
        ),
        horizon="short_term",
        settings=settings,
    )

    long_answer = response.get("long_term_action")
    short_answer = response.get("short_term_action")
    horizon_fit = response.choice("horizon_fit")

    decision = DecisionRun(
        instrument_t212_ticker=instrument.t212_ticker,
        valuation_run_id=valuation_run.id if valuation_run else None,
        created_at=utcnow(),
        state=state.payload,
        state_sha256=state.sha256,
        state_tokens_est=state.token_estimate,
        questions={
            "definitions": questions,
            "metadata": question_metadata(),
            "truncation": {"truncated": state.truncated, "dropped": state.dropped},
            "horizons": {
                name: definition.model_dump(mode="json")
                for name, definition in (
                    ("long_term", settings.horizons.long_term),
                    ("short_term", settings.horizons.short_term),
                )
            },
        },
        engine=response.engine,
        model_id=response.model_id,
        uncalibrated=response.uncalibrated,
        fallback_reason=fallback_reason,
        answers={name: answer.as_dict() for name, answer in response.answers.items()},
        narrative=_narrative(
            response, long_composite, long_verdict, short_composite, short_verdict, engine_notes
        ),
        evidence={
            "notes": response.notes,
            "fallback_reason": fallback_reason,
            "state_truncation": state.dropped,
            "filing_id": filing.id if filing else None,
            "news_ids": [item.id for item in news],
        },
        # --- long term (primary) ---
        composite=long_composite.as_dict(),
        composite_score=long_composite.score,
        long_term_action=response.choice("long_term_action"),
        confidence=long_answer.confidence if long_answer else None,
        gate=long_verdict.as_dict(),
        gate_allowed=long_verdict.is_suggestion,
        # --- short term ---
        short_term_composite=short_composite.as_dict(),
        short_term_composite_score=short_composite.score,
        short_term_action=response.choice("short_term_action"),
        short_term_confidence=short_answer.confidence if short_answer else None,
        short_term_gate=short_verdict.as_dict(),
        short_term_gate_allowed=short_verdict.is_suggestion,
        horizon_fit=horizon_fit,
        # Disagreement between either verdict and its own scores is surfaced.
        conflict_flag=long_composite.conflict or short_composite.conflict,
        llm_call_ids=response.llm_call_ids,
        app_version=APP_VERSION,
    )
    session.add(decision)
    session.flush()
    return decision


def _valuation_result_from_row(run: ValuationRun):
    """Rebuild a :class:`ValuationResult` from a stored run.

    Reconstructing from stored JSON (rather than keeping the object around) means
    the decision uses exactly what was persisted, so a replay cannot diverge.
    """
    from awltux.analysis.valuation import MethodResult, ValuationResult

    outputs = run.model_outputs or {}
    result = ValuationResult(
        status=str(outputs.get("status") or run.status or "ok"),
        price=run.price,
        currency=run.currency,
        fair_value_base=run.fair_value_base,
        fair_value_low=run.fair_value_low,
        fair_value_high=run.fair_value_high,
        margin_of_safety=run.margin_of_safety,
        valuation_confidence=run.valuation_confidence,
        inputs=run.inputs or {},
        notes=list(outputs.get("notes") or []),
    )
    for method in outputs.get("methods") or []:
        if not isinstance(method, dict):
            continue
        result.methods.append(
            MethodResult(
                name=str(method.get("method") or "unknown"),
                fair_value_per_share=method.get("fair_value_per_share"),
                applicable=bool(method.get("applicable")),
                reason=str(method.get("reason") or ""),
                inputs=method.get("inputs") or {},
            )
        )
    return result


def _extracted_facts(filing: Filing | None) -> dict[str, Any] | None:
    if filing is None or not isinstance(filing.parsed, dict):
        return None
    facts = filing.parsed.get("extraction") or filing.parsed
    if not isinstance(facts, dict):
        return None
    # Never present uncited material as evidence.
    return {
        "source": filing.source,
        "filing_type": filing.filing_type,
        "filed_at": filing.filed_at.isoformat() if filing.filed_at else None,
        "url": filing.url,
        **{key: value for key, value in facts.items() if key != "llm_call_id"},
    }


def _filing_summary(filing: Filing | None) -> str | None:
    if filing is None or not isinstance(filing.parsed, dict):
        return None
    summary = filing.parsed.get("summary")
    if isinstance(summary, dict):
        parts = [
            f"{key.replace('_', ' ')}: {value}"
            for key, value in summary.items()
            if value and key != "llm_call_id"
        ]
        return "\n".join(parts)[:4000] or None
    return str(summary)[:4000] if summary else None


def _narrative(
    response: DecisionResponse,
    long_composite,
    long_verdict,
    short_composite,
    short_verdict,
    engine_notes: list[str],
) -> str:
    """Assemble the stored explanation from what actually happened.

    Built from the recorded facts rather than generated prose, so the explanation
    cannot drift from the decision it describes. A DeepSeek-authored narrative can
    be layered on top (see ``llm.narrative``), but this one is always present.
    """
    lines: list[str] = []
    lines.append(f"Decided by the {response.engine} engine.")
    if response.model_id:
        lines.append(f"Model: {response.model_id}.")
    if response.uncalibrated:
        lines.append(
            "The probabilities attached to this decision are the model's own "
            "self-reported certainty, not calibrated frequencies."
        )

    fit = response.choice("horizon_fit")
    if fit:
        lines.append(f"The engine judges the opportunity to suit: {fit.replace('_', ' ')}.")

    for label, composite, verdict, action_question in (
        ("LONG TERM (months to years)", long_composite, long_verdict, "long_term_action"),
        ("SHORT TERM (days to weeks)", short_composite, short_verdict, "short_term_action"),
    ):
        action = response.choice(action_question)
        lines.append("")
        lines.append(f"{label}: {action or 'no call'}.")
        if composite.score is not None:
            lines.append(f"  Composite score: {composite.score:.1f}/100.")
        if composite.conflict:
            lines.append(
                "  The action disagrees with the composite of the model's own "
                "scores; read the individual answers rather than the headline."
            )
        if verdict.is_suggestion:
            weight = (
                f" Suggested position weight {verdict.suggested_weight:.1%}."
                if verdict.suggested_weight
                else ""
            )
            lines.append(f"  The risk gate allowed this as an actionable suggestion.{weight}")
        else:
            lines.append(f"  The risk gate did not produce a suggestion: {verdict.reason}")

    lines.append("")
    lines.append(
        "The short-term view is a swing read on daily bars, not intraday, and "
        "cannot support day trading."
    )
    lines.extend(engine_notes)
    return "\n".join(line for line in lines if line)


def decide_universe(
    session: Session,
    *,
    settings: Settings | None = None,
    tickers: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Decide for every instrument in the universe (or an explicit list)."""
    settings = settings or get_settings()
    stats = DecisionStats()

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    if settings.app.require_resolved_mapping:
        statement = statement.where(Instrument.yahoo_symbol.is_not(None))
    instruments = list(session.execute(statement).scalars().all())
    if limit:
        instruments = instruments[:limit]

    # Build the engines once: constructing a client per instrument would create
    # an HTTP connection pool per decision.
    engines = build_engines(settings)
    try:
        for instrument in instruments:
            stats.attempted += 1
            try:
                decision = decide_instrument(
                    session, instrument, settings=settings, engines=engines
                )
            except Exception as exc:
                stats.failures.append(f"{instrument.t212_ticker}: {exc}")
                logger.exception("decision failed for %s", instrument.t212_ticker)
                continue

            if decision is None:
                stats.skipped += 1
                continue

            stats.decided += 1
            stats.by_engine[decision.engine] = stats.by_engine.get(decision.engine, 0) + 1
            if decision.gate_allowed:
                stats.long_term_suggestions += 1
            if decision.short_term_gate_allowed:
                stats.short_term_suggestions += 1
            if decision.gate_allowed and decision.short_term_gate_allowed:
                stats.both_horizons += 1
            if decision.horizon_fit:
                stats.horizon_fit[decision.horizon_fit] = (
                    stats.horizon_fit.get(decision.horizon_fit, 0) + 1
                )
            if decision.conflict_flag:
                stats.conflicts += 1

            # Release the write lock between instruments. Deciding one instrument
            # can make several model calls, so a sweep of the universe would hold
            # a single transaction across hundreds of network round trips -- which
            # locked every other writer out for the duration.
            release_write_lock(session)
    finally:
        for engine in engines.values():
            close = getattr(engine, "close", None)
            if callable(close):
                # A failure to close a pooled client must not mask the run result.
                with contextlib.suppress(Exception):
                    close()

    session.flush()
    logger.info("decision run: %s", stats.as_dict())
    return stats.as_dict()

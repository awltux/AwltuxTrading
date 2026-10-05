"""The risk gate: may this decision become a suggestion?

Deliberately a separate layer from the decision itself. The decision engine says
what it thinks; the gate decides whether that opinion is allowed to reach the user
as an actionable call. Keeping them apart means a model cannot widen its own
mandate, and every refusal is explainable by one named rule.

Order matters, and it is: *can we trust the inputs* -> *can we trust the answer* ->
*is the portfolio able to act*. A refusal always names the **single binding rule**
rather than emitting a score, because "confidence 0.54" is not actionable while
"refused: confidence below the 0.70 floor" is.

**Requirements differ by horizon**, and that is not a detail. A tactical call does
not need a fresh discounted cash flow, but it does need current bars and actual
momentum evidence. Applying the long-term staleness limits to it would refuse good
tactical calls for an irrelevant reason; removing them from the long-term path
would let a month-old valuation masquerade as a current one.

**Confidence floors differ by engine, not by horizon.** They are about how far the
number can be trusted, which has nothing to do with what it is about.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from awltux.config import Settings, get_settings
from awltux.decision.composite import ACTION_QUESTION, CompositeResult
from awltux.decision.engine import ENGINE_TRUST, DecisionResponse

logger = logging.getLogger(__name__)

Horizon = str  # "long_term" | "short_term"

#: Actions that constitute an actionable suggestion. HOLD asserts nothing and
#: AVOID is a refusal to engage, so neither ever becomes a suggestion.
SUGGESTION_ACTIONS = frozenset({"strong_buy", "buy", "reduce", "sell"})

#: Actions that imply adding to a position, for portfolio-limit checks.
OPENING_ACTIONS = frozenset({"strong_buy", "buy"})


@dataclass(slots=True)
class GateContext:
    """Everything the gate needs that is not in the decision itself."""

    price_age_seconds: float | None = None
    valuation_age_seconds: float | None = None
    filing_age_seconds: float | None = None
    has_filing: bool = False
    median_daily_turnover_gbp: float | None = None
    #: The tactical setup score, required before a short-term call can be
    #: actionable. Read from the decision's own answers.
    setup_score: float | None = None
    # Portfolio state for concentration limits.
    open_positions: int = 0
    current_weight: float = 0.0
    sector_weight: float = 0.0
    #: Whether the portfolio could actually be read. Trading 212 issues keys with
    #: scopes, and a ``metadata``-only key cannot read positions -- so an empty
    #: portfolio and an *unreadable* one look identical in the numbers. They are
    #: not the same thing, and the gate must not report limits as enforced when it
    #: cannot see them.
    portfolio_known: bool = True
    min_engine: str = "offline"


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(slots=True)
class GateVerdict:
    horizon: str = "long_term"
    allowed: bool = False
    binding_rule: str | None = None
    reason: str = ""
    is_suggestion: bool = False
    suggested_weight: float | None = None
    checks: list[Check] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "allowed": self.allowed,
            "is_suggestion": self.is_suggestion,
            "binding_rule": self.binding_rule,
            "reason": self.reason,
            "suggested_weight": self.suggested_weight,
            "checks": [check.as_dict() for check in self.checks],
        }


def _age_or_none(when: dt.datetime | None) -> float | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return (dt.datetime.now(dt.UTC) - when).total_seconds()


def build_context(
    *,
    price_at: dt.datetime | None,
    valuation_at: dt.datetime | None,
    last_filing_at: dt.datetime | None = None,
    median_daily_turnover_gbp: float | None = None,
    setup_score: float | None = None,
    open_positions: int = 0,
    current_weight: float = 0.0,
    sector_weight: float = 0.0,
    portfolio_known: bool = True,
    min_engine: str = "offline",
) -> GateContext:
    """Assemble a context from timestamps and portfolio state."""
    return GateContext(
        price_age_seconds=_age_or_none(price_at),
        valuation_age_seconds=_age_or_none(valuation_at),
        filing_age_seconds=_age_or_none(last_filing_at),
        has_filing=last_filing_at is not None,
        median_daily_turnover_gbp=median_daily_turnover_gbp,
        setup_score=setup_score,
        open_positions=open_positions,
        current_weight=current_weight,
        sector_weight=sector_weight,
        portfolio_known=portfolio_known,
        min_engine=min_engine,
    )


def confidence_floor_for(engine: str, settings: Settings) -> float:
    """The confidence bar for an engine, on the scale that engine actually uses.

    Three different quantities are called "confidence" here, and treating them as
    one number would either overstate the rule engine or hobble it:

    * **JEV** returns calibrated probabilities, so the ordinary floor applies.
    * **DeepSeek** returns self-reported certainty, which is not calibrated, so it
      must clear a higher bar.
    * **Offline** reports no probabilities at all -- its number describes how good
      the evidence is. Judging it against a calibration floor above its ceiling
      would make the no-keys mode silently unable to ever suggest anything.
    """
    config = settings.gate
    if engine == "jev":
        return config.min_confidence
    if engine == "offline":
        return config.min_confidence_rule_engine
    return config.min_confidence_fallback_engine


def _confidence_basis(engine: str) -> str:
    if engine == "jev":
        return "calibrated"
    if engine == "offline":
        return "evidence quality, not a probability"
    return "uncalibrated, self-reported"


def evaluate(
    response: DecisionResponse,
    composite: CompositeResult,
    context: GateContext,
    *,
    horizon: Horizon = "long_term",
    settings: Settings | None = None,
) -> GateVerdict:
    """Run every check in order; the first failure is the binding rule."""
    settings = settings or get_settings()
    config = settings.gate
    requirements = config.for_horizon(horizon)
    checks: list[Check] = []

    def record(name: str, passed: bool, detail: str) -> bool:
        checks.append(Check(name, passed, detail))
        return passed

    def refuse(rule: str, reason: str) -> GateVerdict:
        return GateVerdict(
            horizon=horizon,
            allowed=False,
            binding_rule=rule,
            reason=reason,
            is_suggestion=False,
            checks=checks,
        )

    action_question = ACTION_QUESTION.get(horizon, "long_term_action")
    action_answer = response.get(action_question)
    action = action_answer.value if action_answer else None
    confidence = action_answer.confidence if action_answer else None

    # --- 1. engine trust ---------------------------------------------------
    required_trust = ENGINE_TRUST.get(context.min_engine, 1)
    actual_trust = response.trust
    if not record(
        "engine_trust",
        actual_trust >= required_trust,
        f"{response.engine} (trust {actual_trust}) vs required {context.min_engine} "
        f"(trust {required_trust})",
    ):
        return refuse(
            "engine_trust",
            f"decision came from {response.engine}, below the configured minimum "
            f"of {context.min_engine}",
        )

    # --- 2. data freshness -------------------------------------------------
    if not record(
        "price_freshness",
        context.price_age_seconds is not None
        and context.price_age_seconds <= requirements.max_price_age_seconds,
        _age_text(context.price_age_seconds, requirements.max_price_age_seconds),
    ):
        return refuse(
            "price_stale",
            f"price data is {_human_age(context.price_age_seconds)} old "
            f"(limit for {horizon.replace('_', ' ')} is "
            f"{_human_age(requirements.max_price_age_seconds)})",
        )

    if requirements.require_valuation and not record(
        "valuation_freshness",
        context.valuation_age_seconds is not None
        and context.valuation_age_seconds <= requirements.max_valuation_age_seconds,
        _age_text(context.valuation_age_seconds, requirements.max_valuation_age_seconds),
    ):
        return refuse(
            "valuation_stale",
            f"valuation is {_human_age(context.valuation_age_seconds)} old "
            f"(limit {_human_age(requirements.max_valuation_age_seconds)})",
        )

    if requirements.require_filing and not record(
        "filing_presence",
        context.has_filing
        and context.filing_age_seconds is not None
        and context.filing_age_seconds <= requirements.max_filing_age_seconds,
        "no usable filing" if not context.has_filing
        else _age_text(context.filing_age_seconds, requirements.max_filing_age_seconds),
    ):
        return refuse("no_filing", "no published accounts within the permitted window")

    # --- 3. confidence -----------------------------------------------------
    confidence_floor = confidence_floor_for(response.engine, settings)
    if not record(
        "confidence",
        confidence is not None and confidence >= confidence_floor,
        f"confidence {confidence if confidence is not None else 'absent'} "
        f"vs floor {confidence_floor} ({_confidence_basis(response.engine)})",
    ):
        return refuse(
            "confidence_below_floor",
            f"confidence {confidence:.0%} is below the {confidence_floor:.0%} floor "
            f"for a {response.engine} decision"
            if confidence is not None
            else f"no confidence was reported for {action_question}",
        )

    # --- 4. probability mass on the chosen option --------------------------
    top_probability = action_answer.top_probability if action_answer else None
    if top_probability is not None and not record(
        "top_probability",
        top_probability >= config.min_top_probability,
        f"top probability {top_probability:.0%} vs floor {config.min_top_probability:.0%}",
    ):
        return refuse(
            "probability_below_floor",
            f"the chosen action carries only {top_probability:.0%} of the "
            f"probability mass (floor {config.min_top_probability:.0%})",
        )

    # --- 5. is it actionable at all ----------------------------------------
    if action is None:
        record("action_present", False, f"no {action_question} answer returned")
        return refuse("no_action", f"the decision returned no {action_question}")

    if action not in SUGGESTION_ACTIONS:
        record("action_actionable", False, f"{action} is not an actionable suggestion")
        return GateVerdict(
            horizon=horizon,
            allowed=True,  # the decision stands; it is simply not a trade suggestion
            binding_rule=None,
            reason=f"{action} does not produce a trade suggestion",
            is_suggestion=False,
            checks=checks,
        )
    record("action_actionable", True, f"{action} is actionable")

    # --- 6. horizon-specific evidence --------------------------------------
    # A tactical call needs a measured setup. Without this, a short-term
    # suggestion could rest on nothing but a model's opinion about momentum.
    if requirements.min_setup_score is not None:
        setup = context.setup_score
        if not record(
            "setup_evidence",
            setup is not None and setup >= requirements.min_setup_score,
            f"setup score {setup if setup is not None else 'absent'} vs minimum "
            f"{requirements.min_setup_score}",
        ):
            return refuse(
                "setup_too_weak",
                f"the tactical setup scores {setup if setup is not None else 'nothing'}"
                f", below the required {requirements.min_setup_score}",
            )

    # --- 7. liquidity ------------------------------------------------------
    turnover = context.median_daily_turnover_gbp
    if turnover is None:
        record("liquidity", False, "median daily turnover is unknown")
        return refuse(
            "liquidity_unknown",
            "daily turnover could not be established, so position size cannot be judged",
        )
    if not record(
        "liquidity",
        turnover >= config.min_daily_turnover_gbp,
        f"turnover £{turnover:,.0f} vs floor £{config.min_daily_turnover_gbp:,.0f}",
    ):
        return refuse(
            "illiquid",
            f"median daily turnover of £{turnover:,.0f} is below the "
            f"£{config.min_daily_turnover_gbp:,.0f} floor",
        )

    # --- 8. portfolio concentration ----------------------------------------
    if action in OPENING_ACTIONS:
        if not context.portfolio_known:
            # Not a refusal: the app is advisory-only, and blocking every
            # suggestion because a key lacks a scope would make it useless. But
            # the limits genuinely were *not* checked, and saying so is the
            # difference between an honest tool and a misleading one.
            record(
                "portfolio_limits",
                False,
                "NOT VERIFIED: the portfolio could not be read (the Trading 212 "
                "key likely lacks the 'portfolio' scope), so position count and "
                "concentration limits were not enforced",
            )
        else:
            if not record(
                "max_positions",
                context.open_positions < config.max_positions,
                f"{context.open_positions} open vs limit {config.max_positions}",
            ):
                return refuse(
                    "max_positions",
                    f"portfolio already holds {context.open_positions} positions "
                    f"(limit {config.max_positions})",
                )

            if not record(
                "position_weight",
                context.current_weight < config.max_weight_per_name,
                f"current weight {context.current_weight:.1%} vs cap "
                f"{config.max_weight_per_name:.1%}",
            ):
                return refuse(
                    "position_concentration",
                    f"{context.current_weight:.1%} is already at the "
                    f"{config.max_weight_per_name:.1%} per-name cap",
                )

            if not record(
                "sector_weight",
                context.sector_weight < config.max_weight_per_sector,
                f"sector weight {context.sector_weight:.1%} vs cap "
                f"{config.max_weight_per_sector:.1%}",
            ):
                return refuse(
                    "sector_concentration",
                    f"sector exposure would reach {context.sector_weight:.1%}, at the "
                    f"{config.max_weight_per_sector:.1%} cap",
                )

    # --- 9. conflict with the composite ------------------------------------
    # Not a refusal: a disagreement is information, and suppressing it would hide
    # the most interesting decisions. It is recorded and surfaced.
    if composite.conflict:
        record(
            "composite_agreement",
            False,
            "the action disagrees with the composite of the model's own scores",
        )
    else:
        record("composite_agreement", True, "action agrees with the composite")

    suggested = _suggested_weight(response, composite, context, settings, action_question)
    if suggested is not None:
        record("sizing", True, f"suggested position weight {suggested:.1%}")

    return GateVerdict(
        horizon=horizon,
        allowed=True,
        binding_rule=None,
        reason="passed every gate",
        is_suggestion=True,
        suggested_weight=suggested,
        checks=checks,
    )


def _suggested_weight(
    response: DecisionResponse,
    composite: CompositeResult,
    context: GateContext,
    settings: Settings,
    action_question: str,
) -> float | None:
    """Indicative position size, capped by the per-name limit.

    Scaled by confidence and composite score, then reduced to leave room within
    the sector cap. Advisory only -- the app never places an order.
    """
    config = settings.gate
    answer = response.get(action_question)
    confidence = answer.confidence if answer else None
    if confidence is None:
        confidence = 0.5
    score = (composite.score or 50.0) / 100.0

    raw = config.max_weight_per_name * confidence * (0.5 + 0.5 * score)

    sector_room = max(config.max_weight_per_sector - context.sector_weight, 0.0)
    return round(max(0.0, min(raw, config.max_weight_per_name, sector_room)), 4)


def _human_age(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.0f}h"
    return f"{seconds / 86400:.0f}d"


def _age_text(age: float | None, limit: float) -> str:
    if age is None:
        return "age unknown"
    return f"{_human_age(age)} old (limit {_human_age(limit)})"

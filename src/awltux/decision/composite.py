"""Composite scoring: turn typed answers into rankable numbers, per horizon.

Two horizons are scored by the same machinery but with **different weights**, and
that is the whole point: if both used the same weights they would produce the same
ranking and the second one would be decoration.

The distinction that matters:

* **Long term** is anchored to arithmetic. The deterministic margin of safety
  carries the largest weight, so the ranking rests on something checkable rather
  than on judgement alone.
* **Short term** is anchored to the measured setup and its downside risk. Valuation
  still contributes — a cheap stock has less far to fall — but deliberately does
  not drive it, or the tactical view would just be the investment view renamed.

The score exists to *sort* the dashboard. The model's action is the call; this is
the ordering. When the two disagree, the disagreement is flagged rather than
smoothed away.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from awltux.config import Settings, get_settings
from awltux.decision.engine import DecisionResponse
from awltux.decision.questions import QUESTIONS_BY_NAME

logger = logging.getLogger(__name__)

Horizon = Literal["long_term", "short_term"]

#: Choice answers mapped onto a 0..1 desirability scale.
#:
#: ``sentiment_regime`` is deliberately momentum-aligned: euphoric scores high
#: because both horizons here are trend-tolerant. Its weight is small precisely
#: because a contrarian reading would invert it, and that is a judgement call a
#: user can change in configuration rather than one hidden in this table.
CHOICE_SCORES: dict[str, dict[str, float]] = {
    "valuation_verdict": {
        "deeply_undervalued": 1.00,
        "undervalued": 0.75,
        "fairly_valued": 0.50,
        "overvalued": 0.25,
        "deeply_overvalued": 0.00,
    },
    "earnings_trend": {
        "improving": 1.00,
        "stable": 0.60,
        "volatile": 0.40,
        "deteriorating": 0.00,
    },
    "news_materiality": {
        "material_positive": 1.00,
        "mild_positive": 0.70,
        "neutral": 0.50,
        "mild_negative": 0.30,
        "material_negative": 0.00,
    },
    "sentiment_regime": {
        "euphoric": 0.90,
        "positive": 0.75,
        "neutral": 0.50,
        "negative": 0.30,
        "fearful": 0.15,
    },
    "horizon_fit": {
        "both": 1.00,
        "long_term": 0.70,
        "short_term": 0.60,
        "neither": 0.00,
    },
}

#: Questions where a HIGHER score means MORE risk, so they must be flipped before
#: being treated as desirability.
INVERTED_SCORES = frozenset({"balance_sheet_risk", "short_term_drawdown_risk"})

#: Action desirability, used only to detect disagreement with the composite.
ACTION_SCORES: dict[str, float] = {
    "strong_buy": 1.00,
    "buy": 0.75,
    "hold": 0.50,
    "reduce": 0.30,
    "sell": 0.15,
    "avoid": 0.00,
}

#: A gap this large between the action and the composite is worth flagging.
CONFLICT_THRESHOLD = 0.35

#: The question that carries each horizon's verdict.
ACTION_QUESTION: dict[str, str] = {
    "long_term": "long_term_action",
    "short_term": "short_term_action",
}


@dataclass(slots=True)
class CompositeResult:
    horizon: str = "long_term"
    score: float | None = None
    components: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    action: str | None = None
    action_score: float | None = None
    conflict: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "score": self.score,
            "components": self.components,
            "weights": self.weights,
            "missing": self.missing,
            "action": self.action,
            "action_score": self.action_score,
            "conflict": self.conflict,
            "conflict_threshold": CONFLICT_THRESHOLD,
            "notes": self.notes,
        }


def normalise_answer(name: str, answer: Any, settings: Settings) -> float | None:
    """Map one answer onto 0..1, or ``None`` if it cannot be placed on the scale."""
    if answer is None:
        return None

    if name in CHOICE_SCORES:
        value = getattr(answer, "value", answer)
        return CHOICE_SCORES[name].get(str(value))

    numeric = answer.numeric if hasattr(answer, "numeric") else None
    if numeric is None:
        return None

    if name == "margin_of_safety":
        return max(0.0, min(1.0, numeric / 4.0))

    if answer.type == "score" or name in INVERTED_SCORES:
        definition = QUESTIONS_BY_NAME.get(name)
        levels = definition.levels if definition else 5
        denominator = max(levels - 1, 1)
        normalised = max(0.0, min(1.0, numeric / denominator))
        return 1.0 - normalised if name in INVERTED_SCORES else normalised

    return None


def compute_composite(
    response: DecisionResponse,
    *,
    horizon: Horizon = "long_term",
    settings: Settings | None = None,
) -> CompositeResult:
    """Weight the normalised answers into a single ranking score for ``horizon``."""
    settings = settings or get_settings()
    weights = settings.composite.weights_for(horizon)
    result = CompositeResult(horizon=horizon)

    weighted_total = 0.0
    weight_used = 0.0

    for name, weight in weights.items():
        if weight <= 0:
            continue
        answer = response.answers.get(name)
        if answer is None:
            result.missing.append(name)
            continue
        normalised = normalise_answer(name, answer, settings)
        if normalised is None:
            result.missing.append(name)
            continue
        result.components[name] = round(normalised, 4)
        result.weights[name] = weight
        weighted_total += normalised * weight
        weight_used += weight

    if weight_used > 0:
        # Renormalise across the questions actually answered, so a missing
        # component does not drag the score towards zero.
        result.score = round(weighted_total / weight_used * 100.0, 2)

    action = response.choice(ACTION_QUESTION[horizon])
    result.action = action
    if action:
        result.action_score = ACTION_SCORES.get(action)
        if result.score is not None and result.action_score is not None:
            gap = abs(result.score / 100.0 - result.action_score)
            if gap >= CONFLICT_THRESHOLD:
                result.conflict = True
                result.notes.append(
                    f"the {horizon.replace('_', ' ')} action ({action}) sits "
                    f"{gap:.0%} away from the composite of its own scores; worth "
                    "reading the individual answers"
                )

    if result.missing:
        result.notes.append("no answer for: " + ", ".join(sorted(result.missing)))
    return result


def compute_both(
    response: DecisionResponse, *, settings: Settings | None = None
) -> tuple[CompositeResult, CompositeResult]:
    """Score both horizons in one pass.

    Returns ``(long_term, short_term)``. A single call site for both keeps them
    from being computed with different settings by accident.
    """
    settings = settings or get_settings()
    return (
        compute_composite(response, horizon="long_term", settings=settings),
        compute_composite(response, horizon="short_term", settings=settings),
    )


def explain(result: CompositeResult) -> str:
    """Human-readable breakdown for the decision receipt."""
    label = result.horizon.replace("_", " ")
    if result.score is None:
        return f"{label}: no scoreable answers were returned."
    parts = [
        f"{name.replace('_', ' ')} {value:.2f} (weight {result.weights.get(name, 0):.2f})"
        for name, value in sorted(result.components.items())
    ]
    return f"{label} composite {result.score:.1f}/100 from " + "; ".join(parts)

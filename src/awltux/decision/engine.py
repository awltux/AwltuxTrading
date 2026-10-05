"""The decision-engine contract.

Every engine -- JEV, DeepSeek, or the deterministic offline one -- returns the
same :class:`DecisionResponse`. That is what makes them interchangeable, and it
is also what makes provenance enforceable: each response records which engine and
model produced it, and whether its probabilities are calibrated.

The answer shape mirrors JEV's three primitives exactly:

``choice``  one of a fixed set of options, with a probability for each
``noul``    a yes/no question, answered as a probability in 0..1
``score``   a position on an ordered scale, with a distribution over the levels
"""

from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal

QuestionType = Literal["choice", "noul", "score"]

#: Engine identifiers, in descending order of trustworthiness. ``jev`` answers
#: are calibrated; ``deepseek`` answers are model-estimated and labelled as such;
#: ``offline`` answers are deterministic rules with no probabilities at all.
ENGINE_JEV = "jev"
ENGINE_DEEPSEEK = "deepseek"
ENGINE_OFFLINE = "offline"

ENGINE_TRUST: dict[str, int] = {ENGINE_JEV: 3, ENGINE_DEEPSEEK: 2, ENGINE_OFFLINE: 1}


class DecisionEngineError(RuntimeError):
    """An engine failed. The caller should fall through to the next engine."""

    def __init__(self, engine: str, message: str, *, retryable: bool = True) -> None:
        self.engine = engine
        self.retryable = retryable
        super().__init__(f"[{engine}] {message}")


class EngineUnavailable(DecisionEngineError):
    """The engine is not configured (no API key), so do not retry it."""

    def __init__(self, engine: str, reason: str) -> None:
        super().__init__(engine, reason, retryable=False)


@dataclass(slots=True)
class Answer:
    """One question's answer."""

    question: str
    type: QuestionType
    value: Any
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    legend: dict[str, str] | None = None

    @property
    def top_probability(self) -> float | None:
        """Probability mass on the winning option, which the gate thresholds on.

        Distinct from ``confidence``: confidence measures the *shape* of the
        distribution, this measures the winner's share. A 0.55/0.45 split has
        low confidence but the winner still has 0.55.
        """
        if not self.probabilities:
            return None
        return max(self.probabilities.values())

    @property
    def numeric(self) -> float | None:
        """The answer as a number, for composite scoring."""
        if self.type == "score":
            try:
                return float(self.value)
            except (TypeError, ValueError):
                return None
        if self.type == "noul":
            try:
                return float(self.value)
            except (TypeError, ValueError):
                return None
        return None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "value": self.value}
        if self.type == "choice":
            payload["choice"] = self.value
        elif self.type == "noul":
            payload["noul"] = self.value
        elif self.type == "score":
            payload["score"] = self.value
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.probabilities:
            payload["probabilities"] = self.probabilities
        if self.legend:
            payload["legend"] = self.legend
        return payload


@dataclass(slots=True)
class DecisionResponse:
    """A complete set of answers, with the provenance that makes it auditable."""

    answers: dict[str, Answer]
    engine: str
    model_id: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    raw: dict[str, Any] | None = None
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    notes: list[str] = field(default_factory=list)
    llm_call_ids: list[int] = field(default_factory=list)

    @property
    def uncalibrated(self) -> bool:
        """True when the probabilities are estimates rather than calibrated.

        JEV is trained for calibration; a language model emulating the same
        interface is not, and the UI must not present the two as equivalent.
        """
        return self.engine != ENGINE_JEV

    @property
    def trust(self) -> int:
        return ENGINE_TRUST.get(self.engine, 0)

    def get(self, question: str) -> Answer | None:
        return self.answers.get(question)

    def choice(self, question: str) -> str | None:
        answer = self.answers.get(question)
        if answer is None or answer.type != "choice":
            return None
        return str(answer.value) if answer.value is not None else None

    def score(self, question: str) -> float | None:
        answer = self.answers.get(question)
        return answer.numeric if answer is not None else None

    def noul(self, question: str) -> float | None:
        answer = self.answers.get(question)
        if answer is None or answer.type != "noul":
            return None
        return answer.numeric

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "model_id": self.model_id,
            "uncalibrated": self.uncalibrated,
            "answers": {name: answer.as_dict() for name, answer in self.answers.items()},
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "notes": self.notes,
        }


class DecisionEngine(abc.ABC):
    """Interface every decision engine implements."""

    name: str = "base"

    @property
    @abc.abstractmethod
    def available(self) -> bool:
        """Whether this engine can run at all (typically: is it configured?)."""

    @abc.abstractmethod
    def decide(
        self,
        *,
        state: dict[str, Any],
        state_text: str,
        questions: dict[str, Any],
    ) -> DecisionResponse:
        """Answer ``questions`` about ``state``.

        Raises :class:`EngineUnavailable` if not configured, or
        :class:`DecisionEngineError` on failure. Callers fall through to the next
        engine in the priority list.
        """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name} available={self.available}>"

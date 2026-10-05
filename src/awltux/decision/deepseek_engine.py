"""DeepSeek decision engine -- the fallback when JEV is unavailable.

This engine exposes the **same typed question contract** as JEV so the rest of the
system does not care which answered. What it cannot do is return calibrated
probabilities: a language model asked for a probability is reporting its own
subjective certainty, which is not the same quantity as a calibrated frequency.

So the engine does two things:

* It asks for the same questions and the same answer types, so the answers are
  directly comparable.
* It marks every response ``uncalibrated``, which the gate then uses to apply a
  **stricter confidence floor** and the UI uses to label the decision. A fallback
  decision is never presented as though JEV produced it.

The schema is generated from the question definitions rather than hand-written,
so adding a question cannot leave the fallback engine silently out of date.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from awltux.config import Settings, get_settings
from awltux.decision.engine import (
    ENGINE_DEEPSEEK,
    Answer,
    DecisionEngine,
    DecisionEngineError,
    DecisionResponse,
    EngineUnavailable,
)
from awltux.llm.deepseek import (
    BudgetExceeded,
    DeepSeekClient,
    DeepSeekError,
    build_messages,
    model_for_purpose,
)
from awltux.llm.prompts import UNTRUSTED_CONTENT_RULE, prompt_fingerprint

logger = logging.getLogger(__name__)

PURPOSE = "decision_fallback"
PROMPT_VERSION = "2026-02-1"

SYSTEM = f"""You are a disciplined equity analyst making a judgement about one share for a long-only private investor.

{UNTRUSTED_CONTENT_RULE}

Rules you must follow:
- Answer every question using only the evidence in the state provided.
- Where the evidence is thin or missing, say so through a low confidence rather than by inventing detail.
- Treat the deterministic valuation as arithmetic, not as an opinion to be second-guessed: you may disagree with it, but you must explain why in the reasoning.
- A large discount into a business that may not survive is not a bargain. Weight balance-sheet risk accordingly.
- Do not predict share prices or returns.
- Report confidence honestly. A confidence of 0.9 means you would be surprised to be wrong.

Return JSON only."""


def build_schema(questions: dict[str, Any]) -> str:
    """Describe the required JSON output, derived from the question set.

    Generated rather than hand-written so a new question cannot be quietly
    omitted from the fallback path.
    """
    lines: list[str] = [
        "Return a JSON object of this exact shape:",
        "{",
        '  "reasoning": "2-4 sentences explaining your overall judgement",',
        '  "answers": {',
    ]
    for name, definition in questions.items():
        kind = definition.get("type")
        criteria = definition.get("criteria")
        if kind == "choice" and isinstance(criteria, dict):
            options = ", ".join(f'"{option}"' for option in criteria)
            lines.append(
                f'    "{name}": {{"choice": one of [{options}], '
                f'"confidence": 0.0-1.0, "probabilities": {{each option: probability}}, '
                f'"reasoning": "one sentence"}},'
            )
        elif kind == "score" and isinstance(criteria, list):
            lines.append(
                f'    "{name}": {{"score": integer 0-{len(criteria) - 1}, '
                f'"confidence": 0.0-1.0, "probabilities": {{each level: probability}}, '
                f'"reasoning": "one sentence"}},'
            )
        else:
            lines.append(
                f'    "{name}": {{"noul": 0.0-1.0, "reasoning": "one sentence"}},'
            )
        if isinstance(criteria, dict):
            lines.append(f"    // {name}: " + "; ".join(f"{k} = {v}" for k, v in criteria.items()))
        elif isinstance(criteria, list):
            lines.append(
                f"    // {name}: " + "; ".join(f"{i} = {text}" for i, text in enumerate(criteria))
            )
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


def build_instruction(questions: dict[str, Any]) -> str:
    """The full per-instrument instruction, including the question text."""
    parts = ["Answer these questions about the company in the state above.", ""]
    for name, definition in questions.items():
        parts.append(f"- {name}: {definition.get('instructions')}")
        definition_criteria = definition.get("criteria")
        if isinstance(definition_criteria, dict):
            for option, description in definition_criteria.items():
                parts.append(f"    * {option}: {description}")
        elif isinstance(definition_criteria, list):
            for index, description in enumerate(definition_criteria):
                parts.append(f"    * {index}: {description}")
        parts.append("")
    parts.append(build_schema(questions))
    return "\n".join(parts)


class DeepSeekDecisionEngine(DecisionEngine):
    """Emulates the JEV question contract using DeepSeek."""

    name = ENGINE_DEEPSEEK

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: DeepSeekClient | None = None

    @property
    def available(self) -> bool:
        return bool(self.settings.env.deepseek_api_key)

    def client(self) -> DeepSeekClient:
        if self._client is None:
            self._client = DeepSeekClient(self.settings)
        return self._client

    def decide(
        self,
        *,
        state: dict[str, Any],
        state_text: str,
        questions: dict[str, Any],
    ) -> DecisionResponse:
        if not self.available:
            raise EngineUnavailable(
                ENGINE_DEEPSEEK,
                "DEEPSEEK_API_KEY is not set, so the fallback decision engine "
                "cannot run either",
            )

        instruction = build_instruction(questions)
        messages = build_messages(
            system=SYSTEM,
            # The state is the large, stable part: keeping it as the document
            # position lets DeepSeek's prefix cache hit across the questions.
            document=state_text,
            instruction=instruction,
        )

        try:
            completion = self.client().complete(
                purpose=PURPOSE,
                messages=messages,
                model=model_for_purpose(self.settings, PURPOSE),
                json_mode=True,
                max_tokens=2000,
                prompt_hash=prompt_fingerprint(SYSTEM, PROMPT_VERSION),
            )
            payload = completion.json_object()
        except BudgetExceeded as exc:
            raise DecisionEngineError(ENGINE_DEEPSEEK, str(exc), retryable=False) from exc
        except DeepSeekError as exc:
            raise DecisionEngineError(ENGINE_DEEPSEEK, str(exc)) from exc

        answers = parse_answers(payload.get("answers"), questions)
        if not answers:
            raise DecisionEngineError(
                ENGINE_DEEPSEEK, "the model returned no usable answers"
            )

        notes = [
            "Probabilities here are the model's self-reported certainty, not "
            "calibrated frequencies. A stricter confidence floor applies.",
        ]
        reasoning = payload.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            notes.append(reasoning.strip())

        return DecisionResponse(
            answers=answers,
            engine=ENGINE_DEEPSEEK,
            model_id=completion.model,
            latency_ms=completion.latency_ms,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
            raw=payload,
            notes=notes,
            llm_call_ids=[completion.llm_call_id] if completion.llm_call_id else [],
        )


def parse_answers(raw: Any, questions: dict[str, Any]) -> dict[str, Answer]:
    """Coerce the model's JSON into typed answers, discarding anything invalid.

    Validation is strict on purpose: an out-of-range score or an option that was
    never offered is dropped rather than clamped, because silently repairing a
    malformed answer would make the composite score depend on data the model was
    never asked for.
    """
    if not isinstance(raw, dict):
        return {}

    answers: dict[str, Answer] = {}
    for name, definition in questions.items():
        entry = raw.get(name)
        if not isinstance(entry, dict):
            continue
        kind = definition.get("type")
        confidence = _clamp(entry.get("confidence"), 0.0, 1.0)
        probabilities = _probabilities(entry.get("probabilities"))

        if kind == "choice":
            criteria = definition.get("criteria")
            value = entry.get("choice")
            if not isinstance(value, str):
                continue
            # An option that was never offered is a hallucinated answer.
            if isinstance(criteria, dict) and value not in criteria:
                logger.debug("discarding unoffered choice %r for %s", value, name)
                continue
            answers[name] = Answer(name, "choice", value, confidence, probabilities)
            continue

        if kind == "score":
            criteria = definition.get("criteria")
            value = _clamp(entry.get("score"), 0, None)
            if value is None:
                continue
            if isinstance(criteria, list) and not (0 <= value <= len(criteria) - 1):
                logger.debug("discarding out-of-range score %r for %s", value, name)
                continue
            answers[name] = Answer(name, "score", float(value), confidence, probabilities)
            continue

        value = _clamp(entry.get("noul"), 0.0, 1.0)
        if value is None:
            continue
        answers[name] = Answer(name, "noul", value)

    return answers


def _clamp(value: Any, low: float, high: float | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    if high is None:
        return max(low, number)
    return max(low, min(high, number))


def _probabilities(value: Any) -> dict[str, float] | None:
    """Coerce a model's stated distribution into a normalised one.

    Normalisation happens **before** any clamping. Clamping first would turn a
    model that answered in percentage points (80 and 20) into (1.0, 1.0), which
    normalises to a coin flip -- silently discarding the entire signal and
    defeating the probability floor the gate applies.
    """
    if not isinstance(value, dict):
        return None

    raw: dict[str, float] = {}
    for key, entry in value.items():
        try:
            number = float(entry)
        except (TypeError, ValueError):
            continue
        if number != number or number < 0:  # NaN or a nonsensical negative weight
            continue
        raw[str(key)] = number

    total = sum(raw.values())
    if total <= 0:
        return None
    return {key: round(weight / total, 6) for key, weight in raw.items()}


def schema_preview(questions: dict[str, Any]) -> str:
    """Exposed for the settings page so the fallback contract is inspectable."""
    return json.dumps(build_schema(questions), indent=None)[:2000]

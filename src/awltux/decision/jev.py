"""JEV (TypeSafe AI) decision engine -- the primary engine.

Endpoint and semantics, from the official reference:

* ``POST https://api.typesafe.ai/v1/systemone`` with ``Authorization: Bearer``.
* Body is ``{model, state, questions}``; the response is
  ``{model, answers, usage}`` where each answer is one of the three primitives.
* ``confidence`` is derived from the probability distribution (1 when all mass is
  on one option, 0 when spread evenly). ``noul`` answers carry no confidence,
  because the probability *is* the uncertainty.
* The response echoes the **versioned** model id that answered, which is recorded
  on every decision so an alias moving underneath us is detectable after the
  fact.
* Rate limits are enforced both in tokens/second and requests/second, and a
  breach returns 429. The client retries with backoff.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from awltux.config import Settings, get_settings
from awltux.decision.engine import (
    ENGINE_JEV,
    Answer,
    DecisionEngine,
    DecisionEngineError,
    DecisionResponse,
    EngineUnavailable,
)
from awltux.decision.questions import QuestionDef
from awltux.providers.http import HttpClient, ProviderError

logger = logging.getLogger(__name__)

ENDPOINT = "/v1/systemone"
MODELS_ENDPOINT = "/v1/models"
SOURCE = "typesafe"


class JevEngine(DecisionEngine):
    """Calls the real JEV model. Calibrated probabilities, ~70-500ms per call."""

    name = ENGINE_JEV

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: HttpClient | None = None

    # ----------------------------------------------------------------- client
    @property
    def available(self) -> bool:
        return bool(self.settings.env.typesafe_api_key)

    def client(self) -> HttpClient:
        if self._client is None:
            if not self.available:
                raise EngineUnavailable(
                    ENGINE_JEV,
                    "TYPESAFE_API_KEY is not set; JEV is in gated early access "
                    "(https://console.typesafe.ai/keys)",
                )
            key = self.settings.env.require("TypeSafe AI", "typesafe_api_key")
            self._client = HttpClient(
                SOURCE,
                settings=self.settings,
                base_url="https://api.typesafe.ai",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------ models
    def list_models(self) -> list[str]:
        """Names this account may send in the ``model`` field."""
        payload = self.client().get_json(MODELS_ENDPOINT, cache_ttl=3600.0)
        if isinstance(payload, dict):
            data = payload.get("data") or payload.get("models") or []
        elif isinstance(payload, list):
            data = payload
        else:
            data = []
        names: list[str] = []
        for entry in data:
            if isinstance(entry, dict) and entry.get("id"):
                names.append(str(entry["id"]))
            elif isinstance(entry, str):
                names.append(entry)
        return names

    # ------------------------------------------------------------------ decide
    def decide(
        self,
        *,
        state: dict[str, Any],
        state_text: str,
        questions: dict[str, Any],
    ) -> DecisionResponse:
        if not self.available:
            raise EngineUnavailable(
                ENGINE_JEV,
                "TYPESAFE_API_KEY is not set; JEV is in gated early access",
            )

        model = self.settings.decision.jev_model
        body = {"model": model, "state": state, "questions": questions}

        started = time.perf_counter()
        try:
            # POSTs are never cached: this is a live judgement, not a resource.
            result = self.client().post(
                ENDPOINT, json_body=body, retries=self.settings.llm.max_retries
            )
        except ProviderError as exc:
            status = getattr(exc, "status", None)
            raise DecisionEngineError(
                ENGINE_JEV,
                str(exc),
                retryable=status in (None, 429, 500, 502, 503, 504),
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            payload = result.json()
        except Exception as exc:
            raise DecisionEngineError(
                ENGINE_JEV, f"response was not valid JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise DecisionEngineError(ENGINE_JEV, "response was not a JSON object")

        answers = _parse_answers(payload.get("answers"), questions)
        if not answers:
            raise DecisionEngineError(ENGINE_JEV, "response contained no answers")

        usage = payload.get("usage") or {}
        return DecisionResponse(
            answers=answers,
            engine=ENGINE_JEV,
            # Echo the *versioned* id, not the alias we asked for.
            model_id=str(payload.get("model") or model),
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw=payload,
            notes=_notes(payload, questions, answers),
        )


def _notes(
    payload: dict[str, Any],
    questions: dict[str, Any],
    answers: dict[str, Answer],
) -> list[str]:
    """Record anything about the response a reviewer would want to know."""
    notes: list[str] = []
    missing = [name for name in questions if name not in answers]
    if missing:
        notes.append(f"model returned no answer for: {', '.join(missing)}")
    if not payload.get("usage"):
        notes.append("response carried no usage block")
    return notes


def _parse_answers(raw: Any, questions: dict[str, Any]) -> dict[str, Answer]:
    """Convert the JEV answer shape into our internal form.

    Tolerant of the documented variants (``choice``/``noul``/``score`` keys, the
    ``legend`` on score answers, and the JavaScript SDK's ``probability`` field
    for boolean questions) because being strict here would turn a cosmetic API
    change into a total decision outage.
    """
    if not isinstance(raw, dict):
        return {}

    answers: dict[str, Answer] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue

        declared_type = entry.get("type")
        confidence = _as_float(entry.get("confidence"))
        probabilities = _as_probabilities(entry.get("probabilities"))

        if "noul" in entry or declared_type == "noul" or "probability" in entry:
            value = entry.get("noul", entry.get("probability"))
            answers[name] = Answer(
                question=name,
                type="noul",
                value=_as_float(value),
                probabilities=probabilities,
            )
            continue

        if "choice" in entry or declared_type == "choice":
            answers[name] = Answer(
                question=name,
                type="choice",
                value=entry.get("choice"),
                confidence=confidence,
                probabilities=probabilities,
            )
            continue

        if "score" in entry or declared_type == "score":
            legend = entry.get("legend")
            answers[name] = Answer(
                question=name,
                type="score",
                value=_as_float(entry.get("score")),
                confidence=confidence,
                probabilities=probabilities,
                legend=({str(k): str(v) for k, v in legend.items()} if isinstance(legend, dict) else None),
            )
            continue

        logger.debug("unrecognised answer shape for %r: %r", name, list(entry)[:6])

    return answers


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_probabilities(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, float] = {}
    for key, raw in value.items():
        number = _as_float(raw)
        if number is not None:
            out[str(key)] = number
    return out or None


def question_defs() -> tuple[QuestionDef, ...]:
    from awltux.decision.questions import QUESTION_DEFS

    return QUESTION_DEFS

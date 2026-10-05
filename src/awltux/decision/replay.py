"""Replaying a stored decision.

Replay is what makes the ledger more than a log. A stored decision is only
*provable* if you can put the exact same state and the exact same questions back
to the engine and see what it says now.

Three outcomes are possible and all of them are informative:

* **identical** -- the engine is deterministic on this input, so the recorded
  answer is reproducible.
* **changed** -- the model moved. Either the versioned model id changed under us,
  or the engine is non-deterministic. The recorded model id is compared to the
  replayed one to tell those apart.
* **unavailable** -- the engine cannot run now (key removed, budget spent), which
  is reported rather than being reported as a disagreement.

Replay never mutates the original decision. It is an observation, not a
correction.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from awltux.config import get_settings
from awltux.db import DecisionRun
from awltux.decision.engine import DecisionEngine
from awltux.decision.service import build_engines, run_engines

logger = logging.getLogger(__name__)

#: Score answers that differ by less than this are treated as unchanged. Model
#: score answers are continuous (2.97 on a 0-4 scale), so exact equality would
#: report noise as drift.
SCORE_TOLERANCE = 0.05


def _answer_view(answer: Any) -> dict[str, Any]:
    return answer if isinstance(answer, dict) else {}


def _extract_value(name: str, answer: dict[str, Any]) -> Any:
    answer_type = answer.get("type")
    if answer_type == "choice" or "choice" in answer:
        return answer.get("choice", answer.get("value"))
    if answer_type == "score" or "score" in answer:
        return answer.get("score", answer.get("value"))
    if answer_type == "noul" or "noul" in answer:
        return answer.get("noul", answer.get("value"))
    return answer.get("value")


def compare_answers(
    recorded: dict[str, Any], replayed: dict[str, Any]
) -> dict[str, Any]:
    """Diff two answer maps. Reports per-question agreement and confidence moves."""
    recorded = recorded or {}
    replayed = replayed or {}

    unchanged: list[str] = []
    changed: list[dict[str, Any]] = []
    missing: list[str] = []
    added: list[str] = []

    for name in sorted(set(recorded) | set(replayed)):
        old = _answer_view(recorded.get(name))
        new = _answer_view(replayed.get(name))

        if not new:
            missing.append(name)
            continue
        if not old:
            added.append(name)
            continue

        old_value = _extract_value(name, old)
        new_value = _extract_value(name, new)

        same: bool
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            same = abs(float(old_value) - float(new_value)) <= SCORE_TOLERANCE
        else:
            same = old_value == new_value

        if same:
            unchanged.append(name)
            continue

        delta: Any = None
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            delta = round(float(new_value) - float(old_value), 4)

        changed.append(
            {
                "question": name,
                "recorded": old_value,
                "replayed": new_value,
                "delta": delta,
                "recorded_confidence": old.get("confidence"),
                "replayed_confidence": new.get("confidence"),
            }
        )

    total = len(unchanged) + len(changed)
    return {
        "unchanged": unchanged,
        "changed": changed,
        "missing": missing,
        "added": added,
        "agreement": (len(unchanged) / total) if total else None,
    }


def replay_decision(
    session: Session,
    decision_id: int,
    *,
    engines: dict[str, DecisionEngine] | None = None,
) -> dict[str, Any]:
    """Re-run a stored decision and report what, if anything, moved."""
    decision = session.get(DecisionRun, decision_id)
    if decision is None:
        raise KeyError(f"unknown decision {decision_id}")

    settings = get_settings()
    engines = engines or build_engines(settings)

    stored_questions = decision.questions or {}
    questions = stored_questions.get("definitions") or stored_questions
    if not isinstance(questions, dict) or not questions:
        raise KeyError(f"decision {decision_id} has no stored questions to replay")

    import json

    state_text = json.dumps(decision.state or {}, sort_keys=True, separators=(",", ":"), default=str)

    # Replay against the engine that produced the decision, so a difference means
    # the engine moved rather than that a different engine answered.
    original_priority = list(settings.decision.engine_priority)
    try:
        settings.decision.engine_priority = [decision.engine] + [
            name for name in original_priority if name != decision.engine
        ]
        response, _fallback, _notes = run_engines(
            state=decision.state or {},
            state_text=state_text,
            questions=questions,
            settings=settings,
            engines=engines,
        )
    finally:
        settings.decision.engine_priority = original_priority

    if response is None:
        return {
            "decision_id": decision_id,
            "instrument": decision.instrument_t212_ticker,
            "status": "engine_unavailable",
            "recorded_engine": decision.engine,
            "recorded_model": decision.model_id,
            "message": (
                f"the {decision.engine} engine could not run, so this decision "
                "could not be reproduced"
            ),
        }

    diff = compare_answers(
        decision.answers or {},
        {name: answer.as_dict() for name, answer in response.answers.items()},
    )

    model_changed = bool(decision.model_id and response.model_id and decision.model_id != response.model_id)
    agreed = not diff["changed"] and not diff["missing"]

    if agreed:
        status = "reproduced"
    elif model_changed:
        status = "model_version_changed"
    else:
        status = "answers_changed"

    return {
        "decision_id": decision_id,
        "instrument": decision.instrument_t212_ticker,
        "status": status,
        "recorded_engine": decision.engine,
        "replayed_engine": response.engine,
        "recorded_model": decision.model_id,
        "replayed_model": response.model_id,
        "model_version_changed": model_changed,
        "recorded_state_sha256": decision.state_sha256,
        # Both horizons are reported, because a replay that reproduces one and not
        # the other is the interesting case.
        "recorded_actions": {
            "long_term": decision.long_term_action,
            "short_term": decision.short_term_action,
        },
        "replayed_actions": {
            "long_term": response.choice("long_term_action"),
            "short_term": response.choice("short_term_action"),
        },
        "answers": diff,
        "note": (
            "The recorded decision is immutable; this replay is an observation "
            "about whether the engine still produces the same answer."
        ),
    }

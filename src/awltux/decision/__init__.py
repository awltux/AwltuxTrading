"""The decision layer.

Layering, and why it is split this way:

``engine``    the typed answer contract every engine implements
``questions`` the atomic questions put to the model
``jev``       the calibrated decision model (primary)
``deepseek_engine``  a language-model emulation of the same contract (fallback)
``offline``   deterministic rules (works with no keys, and is the replay control)
``composite`` the ranking score used to sort the dashboard
``gate``      the deterministic rule that decides whether a call is actionable
``service``   the pipeline that runs all of the above and stores the result
``replay``    re-runs a stored decision to test whether it reproduces

The decision and the permission to act on it are deliberately different layers,
so a model cannot widen its own mandate.
"""

from awltux.decision.composite import CompositeResult, compute_composite
from awltux.decision.deepseek_engine import DeepSeekDecisionEngine
from awltux.decision.engine import (
    ENGINE_DEEPSEEK,
    ENGINE_JEV,
    ENGINE_OFFLINE,
    Answer,
    DecisionEngine,
    DecisionEngineError,
    DecisionResponse,
    EngineUnavailable,
)
from awltux.decision.gate import GateContext, GateVerdict, build_context, evaluate
from awltux.decision.jev import JevEngine
from awltux.decision.offline import OfflineEngine
from awltux.decision.questions import QUESTION_DEFS, build_questions, question_metadata

__all__ = [
    "ENGINE_DEEPSEEK",
    "ENGINE_JEV",
    "ENGINE_OFFLINE",
    "QUESTION_DEFS",
    "Answer",
    "CompositeResult",
    "DecisionEngine",
    "DecisionEngineError",
    "DecisionResponse",
    "DeepSeekDecisionEngine",
    "EngineUnavailable",
    "GateContext",
    "GateVerdict",
    "JevEngine",
    "OfflineEngine",
    "build_context",
    "build_questions",
    "compute_composite",
    "evaluate",
    "question_metadata",
]

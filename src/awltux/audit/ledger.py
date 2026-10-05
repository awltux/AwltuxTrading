"""The decision ledger: integrity checks over stored decisions.

Decisions are append-only, so the ledger's job is not to manage them but to
*verify* them:

* **Hash integrity** -- the stored state must still hash to the recorded
  ``state_sha256``. If it does not, the row has been altered (or a bug is
  corrupting states) and the decision can no longer be trusted as evidence.
* **Completeness** -- a decision that claims to have been produced by an engine
  must record which model answered, and whether its probabilities were
  calibrated. A missing model id makes drift undetectable.
* **Chain** -- the sequence of decisions for one instrument, so a reviewer can
  see how a view evolved rather than only its latest state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from awltux.analysis.state import state_hash
from awltux.db import DecisionRun, LLMCall

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IntegrityIssue:
    decision_id: int
    instrument: str
    kind: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "instrument": self.instrument,
            "kind": self.kind,
            "detail": self.detail,
        }


@dataclass(slots=True)
class LedgerReport:
    checked: int = 0
    ok: int = 0
    issues: list[IntegrityIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "ok": self.ok,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def verify_decision(decision: DecisionRun) -> list[IntegrityIssue]:
    """Check one decision's self-consistency."""
    issues: list[IntegrityIssue] = []
    instrument = decision.instrument_t212_ticker

    recomputed = state_hash(decision.state or {})
    if recomputed != decision.state_sha256:
        issues.append(
            IntegrityIssue(
                decision.id,
                instrument,
                "hash_mismatch",
                f"stored state hashes to {recomputed[:16]}… but "
                f"{decision.state_sha256[:16]}… was recorded",
            )
        )

    if not decision.engine:
        issues.append(
            IntegrityIssue(decision.id, instrument, "no_engine", "engine was not recorded")
        )
    if decision.engine == "jev" and not decision.model_id:
        issues.append(
            IntegrityIssue(
                decision.id,
                instrument,
                "no_model_id",
                "a JEV decision without a versioned model id cannot detect drift",
            )
        )
    if decision.long_term_action is None:
        issues.append(
            IntegrityIssue(
                decision.id, instrument, "no_long_term_action",
                "no long-term action was recorded",
            )
        )
    if decision.short_term_action is None:
        issues.append(
            IntegrityIssue(
                decision.id, instrument, "no_short_term_action",
                "no short-term action was recorded; both horizons are expected",
            )
        )
    if decision.gate is None:
        issues.append(
            IntegrityIssue(
                decision.id, instrument, "no_gate", "the long-term gate verdict was not recorded"
            )
        )
    if decision.short_term_gate is None:
        issues.append(
            IntegrityIssue(
                decision.id, instrument, "no_short_term_gate",
                "the short-term gate verdict was not recorded",
            )
        )
    if not decision.answers:
        issues.append(
            IntegrityIssue(decision.id, instrument, "no_answers", "no model answers stored")
        )
    if decision.engine != "jev" and not decision.uncalibrated:
        issues.append(
            IntegrityIssue(
                decision.id,
                instrument,
                "uncalibrated_flag_missing",
                f"a {decision.engine} decision is not marked uncalibrated",
            )
        )
    return issues


def verify_ledger(session: Session, *, limit: int = 500) -> LedgerReport:
    """Verify the most recent decisions. Used by the operations page."""
    report = LedgerReport()
    decisions = session.execute(
        select(DecisionRun).order_by(DecisionRun.created_at.desc()).limit(limit)
    ).scalars().all()

    for decision in decisions:
        report.checked += 1
        issues = verify_decision(decision)
        if issues:
            report.issues.extend(issues)
        else:
            report.ok += 1
    return report


def decision_chain(session: Session, ticker: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """How the view on one instrument has changed over time."""
    rows = session.execute(
        select(DecisionRun)
        .where(DecisionRun.instrument_t212_ticker == ticker)
        .order_by(DecisionRun.created_at.desc())
        .limit(limit)
    ).scalars().all()

    chain: list[dict[str, Any]] = []
    for row in rows:
        margin = None
        valuation = (row.state or {}).get("valuation") or {}
        if isinstance(valuation, dict):
            margin = valuation.get("margin_of_safety")
        chain.append(
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "engine": row.engine,
                "model_id": row.model_id,
                "long_term_action": row.long_term_action,
                "short_term_action": row.short_term_action,
                "horizon_fit": row.horizon_fit,
                "confidence": row.confidence,
                "short_term_confidence": row.short_term_confidence,
                "composite_score": row.composite_score,
                "short_term_composite_score": row.short_term_composite_score,
                "margin_of_safety": margin,
                "gate_allowed": row.gate_allowed,
                "short_term_gate_allowed": row.short_term_gate_allowed,
                "binding_rule": (row.gate or {}).get("binding_rule") if row.gate else None,
                "short_term_binding_rule": (
                    (row.short_term_gate or {}).get("binding_rule")
                    if row.short_term_gate
                    else None
                ),
                "state_sha256": row.state_sha256[:16],
            }
        )
    return chain


def decision_cost(session: Session, decision: DecisionRun) -> dict[str, Any]:
    """Attribute model spend to a single decision."""
    calls = []
    if decision.llm_call_ids:
        calls = session.execute(
            select(LLMCall).where(LLMCall.id.in_(decision.llm_call_ids))
        ).scalars().all()
    return {
        "llm_calls": len(calls),
        "input_tokens": sum(call.input_tokens or 0 for call in calls),
        "output_tokens": sum(call.output_tokens or 0 for call in calls),
        "cost_usd": round(sum(call.cost_usd or 0.0 for call in calls), 6),
    }


def audit_summary(session: Session) -> dict[str, Any]:
    """Headline ledger figures for the dashboard."""
    total = session.query(DecisionRun).count()
    report = verify_ledger(session, limit=200)
    engines: dict[str, int] = {}
    for engine, count in session.execute(
        select(DecisionRun.engine, func.count()).group_by(DecisionRun.engine)
    ).all():
        engines[engine or "unknown"] = count

    return {
        "total_decisions": total,
        "verified": report.checked,
        "clean": report.ok,
        "issues": len(report.issues),
        "by_engine": engines,
    }

"""JSON API.

Deliberately thin: the dashboard is server-rendered, so these endpoints exist for
automation, for the live ticker, and for the operational actions (triggering a
job, replaying a decision) that do not belong in a GET.

Every payload carries provenance. A consumer of ``/api/recommendations`` must be
able to tell which engine decided, whether its probabilities were calibrated,
and whether the risk gate allowed the call.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from awltux.config import get_settings, redacted_dump
from awltux.db import DecisionRun, Instrument, session_scope
from awltux.web import queries

router = APIRouter(prefix="/api", tags=["api"])


class JobRunRequest(BaseModel):
    wait: bool = True


def _row_to_dict(row: queries.RecommendationRow) -> dict[str, Any]:
    """Flatten a recommendation, keeping both horizons explicitly separate."""
    return {
        "ticker": row.ticker,
        "name": row.name,
        "sector": row.sector,
        "currency": row.currency,
        "price": row.price,
        "change_pct": row.change_pct,
        "fair_value": row.fair_value,
        "fair_value_low": row.fair_value_low,
        "fair_value_high": row.fair_value_high,
        "margin_of_safety": row.margin_of_safety,
        # Which horizon the evidence actually supports, independent of either call.
        "horizon_fit": row.horizon_fit,
        "long_term": {
            "action": row.action,
            "composite_score": row.composite_score,
            "confidence": row.confidence,
            "gate_allowed": row.gate_allowed,
            "gate_binding_rule": row.gate_reason,
        },
        "short_term": {
            "action": row.short_term_action,
            "composite_score": row.short_term_score,
            "confidence": row.short_term_confidence,
            "gate_allowed": row.short_term_gate_allowed,
            "gate_binding_rule": row.short_term_gate_reason,
            "setup_score": row.setup_score,
            "drawdown_risk": row.drawdown_risk,
        },
        "decision": {
            "engine": row.engine,
            "uncalibrated": row.uncalibrated,
            "conflict": row.conflict,
            "at": row.decision_at.isoformat() if row.decision_at else None,
        },
        "valuation": {"at": row.valuation_at.isoformat() if row.valuation_at else None},
        "sentiment": row.sentiment,
        "price_at": row.price_at.isoformat() if row.price_at else None,
        "is_held": row.is_held,
    }


@router.get("/recommendations", summary="Sortable recommendations, both horizons")
def recommendations(
    sort: Literal[
        "composite_score", "short_term_score", "margin_of_safety", "confidence",
        "short_term_confidence", "action", "short_term_action", "name",
        "change_pct", "sentiment", "freshness", "horizon_fit",
    ] = "composite_score",
    direction: Literal["asc", "desc"] = "desc",
    action: str | None = None,
    engine: str | None = None,
    horizon: Literal["long_term", "short_term"] = "long_term",
    horizon_fit: str | None = None,
    view: Literal["all", "suggestions", "held"] = "all",
    q: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Every item carries both verdicts.

    ``horizon`` only selects which verdict the ``action`` filter and the
    actionable-only view apply to; both are always returned, because the point of
    separating them is that a consumer can see them disagree.
    """
    with session_scope() as session:
        rows, total = queries.recommendations(
            session,
            sort=sort,
            direction=direction,
            action=action,
            engine=engine,
            horizon=horizon,
            horizon_fit=horizon_fit,
            only_suggestions=(view == "suggestions"),
            only_held=(view == "held"),
            search=q,
            limit=limit,
            offset=offset,
        )
    settings = get_settings()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "filter_horizon": horizon,
        "horizons": {
            "long_term": settings.horizons.long_term.model_dump(mode="json"),
            "short_term": settings.horizons.short_term.model_dump(mode="json"),
        },
        "items": [_row_to_dict(row) for row in rows],
        "disclaimer": (
            "Advisory only. Not financial advice. Short term means a swing horizon "
            "on daily bars, not day trading."
        ),
    }


@router.get("/instruments/{ticker}", summary="Full instrument detail")
def instrument(ticker: str) -> dict[str, Any]:
    with session_scope() as session:
        detail = queries.instrument_detail(session, ticker)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"unknown instrument {ticker}")
        instrument_row: Instrument = detail["instrument"]
        decision: DecisionRun | None = detail["decision"]
        valuation = detail["valuation"]

        return {
            "instrument": {
                "t212_ticker": instrument_row.t212_ticker,
                "isin": instrument_row.isin,
                "name": instrument_row.name,
                "short_name": instrument_row.short_name,
                "currency": instrument_row.currency_code,
                "exchange": instrument_row.exchange_name,
                "sector": instrument_row.sector,
                "industry": instrument_row.industry,
                "sector_source": instrument_row.sector_source,
                "yahoo_symbol": instrument_row.yahoo_symbol,
                "sec_cik": instrument_row.sec_cik,
                "ch_company_number": instrument_row.ch_company_number,
                "mapping_confidence": instrument_row.mapping_confidence,
                "in_universe": instrument_row.in_universe,
                "is_held": instrument_row.is_held,
            },
            "valuation": (
                {
                    "as_of": valuation.as_of.isoformat(),
                    "price": valuation.price,
                    "currency": valuation.currency,
                    "fair_value_low": valuation.fair_value_low,
                    "fair_value_base": valuation.fair_value_base,
                    "fair_value_high": valuation.fair_value_high,
                    "margin_of_safety": valuation.margin_of_safety,
                    "valuation_confidence": valuation.valuation_confidence,
                    "methods_applied": valuation.methods_applied,
                    "status": valuation.status,
                    "model_outputs": valuation.model_outputs,
                    "inputs": valuation.inputs,
                    "engine_version": valuation.engine_version,
                }
                if valuation
                else None
            ),
            "decision": (
                {
                    "id": decision.id,
                    "created_at": decision.created_at.isoformat(),
                    "engine": decision.engine,
                    "model_id": decision.model_id,
                    "uncalibrated": decision.uncalibrated,
                    "fallback_reason": decision.fallback_reason,
                    "state_sha256": decision.state_sha256,
                    "state_tokens_est": decision.state_tokens_est,
                    "answers": decision.answers,
                    "horizon_fit": decision.horizon_fit,
                    "conflict_flag": decision.conflict_flag,
                    "long_term": {
                        "action": decision.long_term_action,
                        "composite": decision.composite,
                        "composite_score": decision.composite_score,
                        "confidence": decision.confidence,
                        "gate": decision.gate,
                        "gate_allowed": decision.gate_allowed,
                    },
                    "short_term": {
                        "action": decision.short_term_action,
                        "composite": decision.short_term_composite,
                        "composite_score": decision.short_term_composite_score,
                        "confidence": decision.short_term_confidence,
                        "gate": decision.short_term_gate,
                        "gate_allowed": decision.short_term_gate_allowed,
                    },
                    "narrative": decision.narrative,
                    "evidence": decision.evidence,
                }
                if decision
                else None
            ),
            "filings": [
                {
                    "source": f.source,
                    "type": f.filing_type,
                    "filed_at": f.filed_at.isoformat() if f.filed_at else None,
                    "url": f.url,
                    "status": f.status,
                }
                for f in detail["filings"]
            ],
            "news": [
                {
                    "title": n.title,
                    "url": n.url,
                    "published_at": n.published_at.isoformat() if n.published_at else None,
                    "materiality": n.materiality,
                    "direction": n.direction,
                    "sentiment": n.sentiment_score,
                    "source": n.source,
                }
                for n in detail["news"]
            ],
        }


@router.get("/decisions/{decision_id}/receipt", summary="Provable decision receipt")
def decision_receipt(decision_id: int) -> dict[str, Any]:
    """The full provenance chain for one decision.

    Returns the canonical state, the question set, the raw answers, and the risk
    gate's verdict -- everything needed to audit or replay the decision without
    trusting the summary.
    """
    with session_scope() as session:
        decision = session.get(DecisionRun, decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="unknown decision")
        return {
            "id": decision.id,
            "instrument": decision.instrument_t212_ticker,
            "created_at": decision.created_at.isoformat(),
            "engine": decision.engine,
            "model_id": decision.model_id,
            "uncalibrated": decision.uncalibrated,
            "fallback_reason": decision.fallback_reason,
            "state": decision.state,
            "state_sha256": decision.state_sha256,
            "questions": decision.questions,
            "answers": decision.answers,
            "horizon_fit": decision.horizon_fit,
            "conflict_flag": decision.conflict_flag,
            "long_term": {
                "action": decision.long_term_action,
                "composite": decision.composite,
                "composite_score": decision.composite_score,
                "confidence": decision.confidence,
                "gate": decision.gate,
                "gate_allowed": decision.gate_allowed,
            },
            "short_term": {
                "action": decision.short_term_action,
                "composite": decision.short_term_composite,
                "composite_score": decision.short_term_composite_score,
                "confidence": decision.short_term_confidence,
                "gate": decision.short_term_gate,
                "gate_allowed": decision.short_term_gate_allowed,
            },
            "evidence": decision.evidence,
            "narrative": decision.narrative,
            "app_version": decision.app_version,
            "llm_call_ids": decision.llm_call_ids,
        }


@router.post("/decisions/{decision_id}/replay", summary="Replay a stored decision")
def replay_decision(decision_id: int, request: Request) -> dict[str, Any]:
    """Re-run a stored decision against its recorded engine and compare.

    Detects drift: if the model's answers no longer match the recorded ones, the
    engine version moved under us or the prompt changed, and the difference is
    reported rather than hidden.
    """
    from awltux.decision.replay import replay_decision as _replay

    with session_scope() as session:
        try:
            return _replay(session, decision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sectors/sentiment", summary="Sector sentiment time series")
def sectors(days: int = Query(60, ge=1, le=730)) -> dict[str, Any]:
    with session_scope() as session:
        data = queries.sector_sentiment(session, days=days)
    return {"days": days, "sectors": data}


@router.get("/jobs", summary="Scheduler job status")
def jobs(request: Request) -> dict[str, Any]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return {"running": False, "jobs": [], "in_flight": []}

    from awltux.db import session_scope
    from awltux.scheduler.jobs import running_jobs

    with session_scope() as session:
        in_flight = sorted(running_jobs(session))
    return {
        "running": not scheduler.paused,
        "jobs": scheduler.status(),
        # Which jobs are executing right now, from the open run rows rather than
        # from anything the browser remembers. A tab that reloads mid-run has no
        # other way to know, and a button offering to start a job that is already
        # running is worse than no button.
        "in_flight": in_flight,
    }


@router.post("/jobs/{job_id}/run", summary="Trigger a job now")
def run_job(job_id: str, request: Request) -> dict[str, Any]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler is not running")
    try:
        result = scheduler.run_now(job_id, wait=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "job": job_id,
        "items_seen": result.items_seen if result else 0,
        "items_written": result.items_written if result else 0,
        "detail": result.detail if result else {},
    }


@router.get("/settings", summary="Effective configuration (secrets redacted)")
def settings_view() -> dict[str, Any]:
    settings = get_settings()
    return {
        "env": redacted_dump(settings),
        "yaml": settings.yaml.model_dump(mode="json"),
    }


@router.get("/health/summary", summary="Compact health for the dashboard header")
def health_summary() -> dict[str, Any]:
    from awltux.db import healthcheck

    return {"database": healthcheck(), "at": dt.datetime.now(dt.UTC).isoformat()}

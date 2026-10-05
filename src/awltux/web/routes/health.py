"""Health and readiness endpoints.

``/healthz`` is what the container healthcheck hits, so it must stay cheap and
must not touch providers. Provider *configuration* is reported, but no provider
is contacted -- a health endpoint that can fail because a third party is down is
not a health endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from awltux import __version__
from awltux.config import get_settings
from awltux.db import healthcheck
from awltux.providers.t212 import T212Provider

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness and database readiness")
def healthz() -> dict[str, object]:
    database = healthcheck()
    return {
        "ok": bool(database.get("ok")),
        "version": __version__,
        "database": database,
    }


@router.get("/api/health", summary="Detailed health including scheduler and providers")
def api_health(request: Request) -> dict[str, object]:
    settings = get_settings()
    scheduler = getattr(request.app.state, "scheduler", None)
    t212 = T212Provider(settings)

    # Read the *cached* capability probe. Health must stay cheap and must not
    # touch a provider: an endpoint that can fail because a third party is down
    # is not a health endpoint. The probe is refreshed by the instruments job.
    capabilities: dict[str, object] | None = None
    if t212.configured:
        from awltux.db import session_scope
        from awltux.ingest.universe import cached_t212_capabilities

        try:
            with session_scope() as session:
                capabilities = cached_t212_capabilities(session)
        except Exception:  # pragma: no cover - only on a broken database
            capabilities = None

    return {
        "ok": True,
        "version": __version__,
        "database": healthcheck(),
        "scheduler": {
            "running": bool(scheduler and not scheduler.paused),
            "paused": bool(scheduler.paused) if scheduler else True,
            "jobs": scheduler.status() if scheduler else [],
        },
        "providers": {
            "trading212": {
                "configured": t212.configured,
                "environment": settings.env.t212_env,
                # Surfaced prominently: advisory-only unless explicitly unlocked.
                "orders_allowed": (
                    settings.env.t212_env != "live" or settings.env.allow_live_orders
                ),
                "capabilities": capabilities,
            },
            "deepseek": {"configured": settings.env.deepseek_configured},
            "jev": {"configured": settings.env.jev_configured},
            "sec_edgar": {"configured": bool(settings.env.sec_user_agent)},
            "companies_house": {"configured": bool(settings.env.companies_house_api_key)},
            "finnhub": {"configured": bool(settings.env.finnhub_api_key)},
            "marketaux": {"configured": bool(settings.env.marketaux_api_key)},
            # Groups stories covering one event. Reported with its model and whether
            # a credential is present, because "configured" here means the endpoint
            # is set -- a local Ollama needs no key, and a hosted one needs one that
            # this cannot check without spending a request.
            "embeddings": {
                "configured": settings.news.embeddings.configured,
                "endpoint": settings.news.embeddings.base_url or None,
                "model": settings.news.embeddings.model,
                "credential": bool(
                    settings.news.embeddings.credential(settings.env)
                ),
            },
        },
        "decision": {
            "engine_priority": settings.decision.engine_priority,
            "min_engine_for_suggestion": settings.decision.min_engine_for_suggestion,
        },
        "horizons": {
            "long_term": settings.horizons.long_term.model_dump(mode="json"),
            "short_term": settings.horizons.short_term.model_dump(mode="json"),
        },
    }

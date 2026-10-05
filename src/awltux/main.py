"""FastAPI application: dashboard, JSON API, and the background scheduler.

Startup order matters and is deliberate:

1. logging (so everything after it is captured, and redacted)
2. database (so a broken volume fails fast and visibly)
3. scheduler (so ingest begins writing into a schema that already exists)

The scheduler is started in the background so the HTTP server binds and can
report health while the first ingest is still running.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from awltux import __version__
from awltux.config import redacted_dump, reload_settings
from awltux.db import healthcheck, init_db, reset_engine
from awltux.logging_setup import configure_logging
from awltux.providers.http import BudgetGuard
from awltux.scheduler import SchedulerService
from awltux.scheduler.registry import build_job_specs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = reload_settings()
    configure_logging(settings.env.log_level)

    logger.info("AwltuxTrading %s starting", __version__)
    logger.info("configuration: %s", redacted_dump(settings))

    try:
        init_db(settings)
        logger.info("database ready at %s", settings.db_path)
    except Exception:
        logger.exception("database initialisation failed -- check the /data volume")
        raise

    scheduler = SchedulerService(build_job_specs(settings))
    app.state.scheduler = scheduler
    app.state.settings = settings
    try:
        scheduler.start()
    except Exception:
        # A scheduler problem must not stop the dashboard from coming up: the
        # UI is how the failure gets diagnosed.
        logger.exception("scheduler failed to start; dashboard remains available")

    try:
        yield
    finally:
        logger.info("AwltuxTrading shutting down")
        try:
            scheduler.shutdown(wait=False)
            # Checkpoint the in-memory rate-limit counters before the engine goes
            # away, so a restart resumes each provider's budget rather than
            # resetting it and immediately over-spending the free tier.
            BudgetGuard.flush_all()
        finally:
            reset_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AwltuxTrading",
        version=__version__,
        description=(
            "Background share valuation and market-sentiment advisor for "
            "Trading 212. Advisory only -- not financial advice."
        ),
        lifespan=lifespan,
    )

    from awltux.web.routes import api, dashboard, health, news

    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(news.router)
    app.include_router(dashboard.router)

    _mount_static(app)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/dashboard")

    return app


def _mount_static(app: FastAPI) -> None:
    from pathlib import Path

    static_dir = Path(__file__).parent / "web" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


app = create_app()


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request, exc: Exception) -> JSONResponse:
    """Last-resort handler so an unhandled error returns JSON, not an HTML dump."""
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": type(exc).__name__, "detail": str(exc)},
    )


def health_payload() -> dict[str, object]:
    """Shared by the router and the CLI."""
    return {"ok": True, "version": __version__, "database": healthcheck()}

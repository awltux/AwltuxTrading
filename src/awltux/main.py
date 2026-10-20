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
from collections.abc import AsyncIterator, Awaitable, Callable
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
from awltux.timezones import ZONE_COOKIE, display_zone, resolve_zone
from awltux.web.cache import TTLCache

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
    # One cache per app rather than per module: the test suite builds an app per test, and a
    # module-level cache would serve one test's page to the next one's request.
    app.state.page_cache = TTLCache()

    _close_interrupted_work()

    if settings.env.scheduler_enabled:
        try:
            scheduler.start()
        except Exception:
            # A scheduler problem must not stop the dashboard from coming up: the
            # UI is how the failure gets diagnosed.
            logger.exception("scheduler failed to start; dashboard remains available")
    else:
        logger.info("scheduler disabled by configuration; no jobs will run")

    try:
        yield
    finally:
        logger.info("AwltuxTrading shutting down")
        try:
            # Stop scheduling, then give what is already running a bounded chance to
            # finish. `shutdown(wait=False)` on its own abandons a job mid-batch and
            # leaves its run open, which the next start then closes as interrupted --
            # honest, but still lost work on every upgrade.
            #
            # Bounded, and shorter than the container's stop grace period, because the
            # container is going to stop whether this returns or not: waiting longer
            # only turns a clean upgrade into a SIGKILL with extra steps. A long job
            # is meant to be headed off by `awltux quiet` before the rebuild, not by
            # this.
            budget = settings.env.shutdown_drain_seconds
            if budget > 0:
                remaining = scheduler.drain(timeout=budget)
                if remaining:
                    logger.warning(
                        "shutdown: %s still running after %.0fs and will be "
                        "interrupted; run `awltux quiet` before upgrading to avoid this",
                        ", ".join(remaining),
                        budget,
                    )
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

    from awltux.web.routes import api, dashboard, health, news, research

    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(news.router)
    app.include_router(research.router)
    app.include_router(dashboard.router)

    _mount_static(app)
    app.add_middleware(DisplayZoneMiddleware)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/dashboard")

    return app


def _close_interrupted_work() -> None:
    """Fail whatever the previous process left open, before anything new is scheduled.

    Two kinds of row, one rule: a row saying *running* whose process is gone is not work in
    progress. For a job run it is a batch that never finished; for a deep-dive it is worse
    than lost work, because that row is the subject's own guard -- left behind, it would refuse
    every later run about that company until the staleness window passed, so a restart would
    silently make one company un-researchable.

    Owned here rather than by either module because **the order matters**: both have to happen
    before the scheduler starts, or a sweep could close a run this process has just opened.
    """
    from awltux.research.service import close_orphaned_research
    from awltux.scheduler.jobs import close_orphaned_runs

    close_orphaned_runs()
    close_orphaned_research()


class DisplayZoneMiddleware:
    """Resolve the viewer's time zone once per request.

    Pure ASGI rather than ``BaseHTTPMiddleware`` on purpose: the latter runs the
    downstream app in a separate task, and a ``ContextVar`` set around it is not
    reliably visible to a *synchronous* endpoint running in the threadpool. Since
    the whole point is that the templates can pick the zone up without being told,
    the context has to survive into the worker thread -- which it does when the
    middleware calls the app in its own context.

    Nothing here touches the response. It only decides which clock the rendered
    times will use, from the cookie the browser sets, the configured zone, or UTC
    in that order.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        configured = None
        settings = getattr(scope.get("app"), "state", None)
        settings = getattr(settings, "settings", None)
        if settings is not None:
            configured = settings.app.timezone

        with display_zone(resolve_zone(_cookie(scope), configured)):
            await self.app(scope, receive, send)


def _cookie(scope) -> str | None:
    """The zone cookie, read straight off the raw headers.

    Read here rather than through ``Request`` because this runs before the router
    and the value is needed for every response, including static files.
    """
    prefix = ZONE_COOKIE.encode() + b"="
    for key, value in scope.get("headers") or ():
        if key == b"cookie":
            for part in value.split(b";"):
                part = part.strip()
                if part.startswith(prefix):
                    from urllib.parse import unquote

                    return unquote(part[len(prefix):].decode("latin-1"))
    return None


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

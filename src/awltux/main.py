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
from starlette.middleware.gzip import GZipMiddleware

from awltux import __version__
from awltux.config import redacted_dump, reload_settings
from awltux.db import healthcheck, init_db, reset_engine
from awltux.logging_setup import configure_logging
from awltux.providers.http import BudgetGuard
from awltux.scheduler import SchedulerService
from awltux.scheduler.control import RemoteScheduler, SchedulerUnavailable
from awltux.scheduler.registry import build_job_specs
from awltux.timezones import ZONE_COOKIE, display_zone, resolve_zone
from awltux.web.cache import TTLCache

logger = logging.getLogger(__name__)

#: Responses below this size are left uncompressed.
#:
#: The compression costs CPU and a few dozen bytes of framing, so an answer that is already
#: small comes out *larger*. 1 kB keeps every JSON API reply and every redirect plain while
#: still compressing the pages, the chart script and the stylesheet.
MIN_GZIP_BYTES = 1000


def _scheduler_for(settings) -> SchedulerService | RemoteScheduler:
    """The scheduler this process should use: the real one, or a proxy to the other process.

    Three cases, and they are deliberately not inferred from each other:

    * a control URL is configured -> the scheduler runs elsewhere, so proxy to it. This is what
      the container does, and it is what makes ``--workers`` safe: four web workers each build an
      app, and none of them starts a job runner.
    * no control URL -> this process owns it, exactly as before.
    * a control URL *and* ``scheduler_enabled`` -> refused rather than guessed, because both
      answers would be a scheduler and the app cannot tell which one the operator meant.
    """
    url = settings.env.scheduler_control_url
    if url and settings.env.scheduler_enabled:
        raise RuntimeError(
            "AWLTUX_SCHEDULER_ENABLED is true and AWLTUX_SCHEDULER_CONTROL_URL is set: this "
            "process would run a scheduler while also asking another one. Set "
            "AWLTUX_SCHEDULER_ENABLED=false in the web process, or drop the control URL."
        )
    if url:
        return RemoteScheduler(url, settings=settings)
    return SchedulerService(build_job_specs(settings))


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

    scheduler = _scheduler_for(settings)
    app.state.scheduler = scheduler
    app.state.settings = settings
    # One cache per app rather than per module: the test suite builds an app per test, and a
    # module-level cache would serve one test's page to the next one's request.
    app.state.page_cache = TTLCache()

    if isinstance(scheduler, RemoteScheduler):
        # The scheduler is another process: this one serves pages and asks it the questions.
        # It also does **not** close orphaned run rows -- the scheduler process does that before
        # it starts (see `awltux.cli.cmd_schedule`), because with several workers each one would
        # otherwise mark a job the scheduler is *still running* as interrupted at startup.
        logger.info("scheduler runs as a separate process at %s", scheduler.base_url)
    else:
        # This process owns the runs, so it owns the sweep that fails the ones a previous
        # process left open. Before `start()`, or a fresh run could be closed by it.
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
    # Compress on the way out. Added last, so it is the outermost layer and sees every
    # response -- static files and rendered pages alike. A page here is mostly repeated
    # markup (the instrument page runs to hundreds of kilobytes of table and tooltip text),
    # which is what gzip is good at. `text/event-stream` is excluded by the middleware
    # itself: a compressed event stream cannot be flushed frame by frame.
    app.add_middleware(GZipMiddleware, minimum_size=MIN_GZIP_BYTES)

    @app.exception_handler(SchedulerUnavailable)
    async def _scheduler_unavailable(request, exc: SchedulerUnavailable):
        """503 rather than 500: the answer is true and the fix is visible.

        This is what the routes already returned when no scheduler was configured, so the page
        and any script reading it see one shape whether the scheduler is absent or unreachable.
        Only the pages that ask the scheduler are affected -- an instrument page never does, so
        the dashboard keeps working while the scheduler process is down.
        """
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
        )

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

"""The scheduler as a separate process, and the proxy the web tier uses to reach it.

**Why this exists.** One uvicorn process is one interpreter, and the work of rendering a page is
CPU-bound Python that threads cannot share: measured 2026-10-20, the instrument page is 69-87 ms
warm single and **6.3 s each** at seven-at-once, while static files and `/api/quiet` stay linear.
The cure is more *processes*, and more processes cannot happen while the web app owns the
scheduler: `create_app`'s lifespan starts one, so four uvicorn workers would be four schedulers
running the same jobs.

So the scheduler moves into a process of its own (``awltux schedule``) that serves a small control
API on loopback, and the web workers hold a :class:`RemoteScheduler` speaking to it. Every route
keeps calling ``request.app.state.scheduler`` exactly as before — the proxy is the same shape as
the service, which is the whole reason the routes, the templates and their tests do not change.

**What is *not* in-process any more**, and therefore what this had to add: the quiet/pause state,
the in-flight job list and "run this now". Those are reads and calls, not cached copies — the
scheduler process remains the single owner of all of it.

**Loopback and unauthenticated, on purpose.** The control port is bound to `127.0.0.1` inside the
container, so it is not reachable from the LAN the dashboard itself may be published on. It must
never be published: it can start jobs that spend provider and model budget.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query

from awltux.scheduler.jobs import JobResult, JobSpec

logger = logging.getLogger(__name__)

#: How long an ordinary control call may take. The scheduler answers from memory in
#: microseconds; a second is generous and a timeout means the process is gone.
CONTROL_TIMEOUT_SECONDS = 5.0

#: How long a *run* may take. Not a safety valve on the job — the job's own budget is — but a
#: bound on a hung HTTP connection, and it has to exceed the longest job this app runs
#: (`decision` takes about two hours).
RUN_TIMEOUT_SECONDS = 6 * 60 * 60.0


class SchedulerUnavailable(RuntimeError):
    """The scheduler process is not answering.

    Its own exception rather than an ``HTTPException`` because it is raised from a client, not a
    route: `main.create_app` maps it to 503, which is what the routes already return when no
    scheduler is configured at all.
    """


def create_control_app(service: Any) -> FastAPI:
    """The scheduler's own API, served on loopback by ``awltux schedule``.

    No docs, no OpenAPI: it is an internal control surface with one client, and publishing its
    schema would advertise a port that must not be reachable from anywhere else.
    """
    app = FastAPI(
        title="awltux scheduler control",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {"ok": True, "paused": service.paused}

    @app.get("/status")
    def status() -> dict[str, Any]:
        return {"paused": service.paused, "jobs": service.status()}

    @app.get("/quiet")
    def quiet_status() -> dict[str, Any]:
        return service.quiet_status()

    @app.post("/quiet")
    def quiet(wait: float = Query(0.0, ge=0.0, le=3_600.0)) -> dict[str, Any]:
        state = service.quiet()
        if wait > 0:
            stragglers = service.wait_for_idle(wait)
            state = service.quiet_status()
            if stragglers:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "still running after the wait; not safe to rebuild yet",
                        **state,
                    },
                )
        return state

    @app.delete("/quiet")
    def unquiet() -> dict[str, Any]:
        return service.unquiet()

    @app.post("/run/{job_id}")
    def run(job_id: str) -> dict[str, Any]:
        try:
            result = service.run_now(job_id, wait=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "job": job_id,
            "items_seen": result.items_seen if result else 0,
            "items_written": result.items_written if result else 0,
            "detail": result.detail if result else {},
        }

    return app


class RemoteScheduler:
    """The web tier's view of the scheduler process: the same calls, over loopback.

    The registry-derived methods (:meth:`specs`, :meth:`get`) are answered **locally**, because
    `build_job_specs` is a pure function of settings and every worker can compute the same list.
    Everything the scheduler owns -- what is scheduled, what is running, what is quiet -- is a
    call, never a copy, so a request for the truth gets the truth.
    """

    def __init__(
        self,
        base_url: str,
        *,
        settings: Any = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._settings = settings
        self._client = client or httpx.Client(timeout=CONTROL_TIMEOUT_SECONDS)

    # ------------------------------------------------------------------ transport
    def _call(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                timeout=timeout or CONTROL_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise SchedulerUnavailable(
                f"the scheduler process at {self.base_url} is not answering ({exc})"
            ) from exc
        if response.status_code >= 400:
            raise SchedulerUnavailable(
                f"the scheduler process answered {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    # ------------------------------------------------------------------ state
    @property
    def paused(self) -> bool:
        return bool(self._call("GET", "/status")["paused"])

    @property
    def quiet_since(self) -> str | None:
        return self._call("GET", "/quiet").get("quiet_since")

    def status(self) -> list[dict[str, object]]:
        return list(self._call("GET", "/status")["jobs"])

    def quiet_status(self) -> dict[str, Any]:
        return dict(self._call("GET", "/quiet"))

    # ----------------------------------------------------------------- actions
    def quiet(self) -> dict[str, Any]:
        """Ask the scheduler to stop taking work.

        The *waiting* stays on this side on purpose: `api.request_quiet` already polls
        ``quiet_status`` and turns a straggler into a 409, and one waiting mechanism is better
        than two that can disagree about what "idle" means.
        """
        return dict(self._call("POST", "/quiet"))

    def unquiet(self) -> dict[str, Any]:
        return dict(self._call("DELETE", "/quiet"))

    def wait_for_idle(self, seconds: float) -> list[str]:
        """Poll until nothing is running, or the deadline passes. Returns what is left."""
        import time

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            state = self.quiet_status()
            if not state.get("running"):
                return []
            time.sleep(0.5)
        return list(self.quiet_status().get("running") or [])

    def run_now(self, job_id: str, *, wait: bool = True) -> JobResult | None:
        payload = self._call(
            "POST", f"/run/{job_id}", timeout=RUN_TIMEOUT_SECONDS if wait else None
        )
        return JobResult(
            items_seen=int(payload.get("items_seen") or 0),
            items_written=int(payload.get("items_written") or 0),
            detail=dict(payload.get("detail") or {}),
        )

    # ------------------------------------------------------- registry, answered here
    def specs(self) -> list[JobSpec]:
        from awltux.config import get_settings
        from awltux.scheduler.registry import build_job_specs

        return build_job_specs(self._settings or get_settings())

    def get(self, job_id: str) -> JobSpec | None:
        return next((spec for spec in self.specs() if spec.id == job_id), None)

    # ----------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """Nothing to start: the scheduler process owns its own lifecycle."""

    def shutdown(self, wait: bool = False) -> None:
        """Nothing to stop, and deliberately so -- a web worker exiting must not stop the
        scheduler, which would take every other worker's jobs down with it."""

    def drain(self, timeout: float = 0.0) -> list[str]:
        """Report what is still running; the scheduler process does its own draining."""
        return self.wait_for_idle(timeout) if timeout > 0 else list(
            self.quiet_status().get("running") or []
        )

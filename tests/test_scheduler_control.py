"""The scheduler's own process, and the proxy the web workers hold.

Measured 2026-10-20, which is why the split exists: one interpreter renders one instrument page
in 69-87 ms and seven at once at 6.3 s each, while static files stay linear. More processes is
the fix, and more processes needs the scheduler to stop living inside the web app -- otherwise
every uvicorn worker's lifespan starts its own job runner.

Two halves, tested separately: the control app's endpoints (a service, driven over ASGI) and the
proxy's mapping (a transport that records what it was asked).
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from awltux.main import _scheduler_for
from awltux.scheduler.control import RemoteScheduler, create_control_app
from awltux.scheduler.jobs import JobResult, JobSpec
from awltux.scheduler.service import SchedulerService


def _noop() -> None:
    pass


class _FakeService:
    """The five things the control API asks a scheduler for."""

    def __init__(self) -> None:
        self.paused = False
        self.quiet_flag = False
        self.quiet_calls = 0
        self.unquiet_calls = 0
        self.running: list[str] = []

    def status(self):
        return [{"id": "x", "next_run": None, "interval_seconds": 60}]

    def quiet_status(self):
        return {
            "quiet": self.quiet_flag,
            "running": list(self.running),
            "idle": not self.running,
        }

    def quiet(self):
        self.quiet_calls += 1
        self.quiet_flag = True
        self.paused = True
        return self.quiet_status()

    def unquiet(self):
        self.unquiet_calls += 1
        self.quiet_flag = False
        self.paused = False
        return self.quiet_status()

    def wait_for_idle(self, seconds: float):
        return list(self.running)

    def run_now(self, job_id: str, *, wait: bool = True):
        if job_id != "known":
            raise KeyError(f"unknown job {job_id!r}")
        return JobResult(items_seen=3, items_written=2, detail={"job": job_id})


class TestTheControlApp:
    def _client(self) -> tuple[TestClient, _FakeService]:
        service = _FakeService()
        return TestClient(create_control_app(service)), service

    def test_status_reports_paused_and_the_jobs(self):
        client, _ = self._client()

        body = client.get("/status").json()

        assert body["paused"] is False
        assert body["jobs"] == [{"id": "x", "next_run": None, "interval_seconds": 60}]

    def test_quiet_and_unquiet_round_trip(self):
        client, service = self._client()

        assert client.post("/quiet").json()["quiet"] is True
        assert service.quiet_calls == 1
        assert client.get("/status").json()["paused"] is True

        assert client.delete("/quiet").json()["quiet"] is False
        assert service.unquiet_calls == 1

    def test_a_wait_that_expires_is_a_409_naming_the_stragglers(self):
        client, service = self._client()
        service.running = ["decision"]

        response = client.post("/quiet", params={"wait": 0.1})

        assert response.status_code == 409
        assert "not safe to rebuild" in response.text

    def test_run_returns_the_result_and_404s_an_unknown_job(self):
        client, _ = self._client()

        assert client.post("/run/known").json() == {
            "job": "known",
            "items_seen": 3,
            "items_written": 2,
            "detail": {"job": "known"},
        }
        assert client.post("/run/nope").status_code == 404

    def test_healthz_does_not_touch_the_jobs(self):
        """The container's healthcheck must not depend on the scheduler's schedule."""
        client, _ = self._client()

        assert client.get("/healthz").json()["ok"] is True


class TestTheProxy:
    def _proxy(self, handler) -> RemoteScheduler:
        return RemoteScheduler(
            "http://scheduler.test",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    def test_it_asks_the_scheduler_process(self):
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={"paused": False, "jobs": []})

        proxy = self._proxy(handler)

        assert proxy.status() == []
        assert proxy.paused is False
        assert seen == [("GET", "/status"), ("GET", "/status")]

    def test_quiet_posts_and_unquiet_deletes(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(f"{request.method} {request.url.path}")
            return httpx.Response(200, json={"quiet": True, "running": [], "idle": True})

        proxy = self._proxy(handler)

        proxy.quiet()
        proxy.unquiet()

        assert seen == ["POST /quiet", "DELETE /quiet"]

    def test_a_run_becomes_a_job_result(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/run/decision"
            return httpx.Response(
                200,
                json={"job": "decision", "items_seen": 5, "items_written": 2, "detail": {"a": 1}},
            )

        result = self._proxy(handler).run_now("decision")

        assert result is not None
        assert (result.items_seen, result.items_written) == (5, 2)
        assert result.detail == {"a": 1}

    def test_an_unreachable_scheduler_is_a_named_failure(self):
        """A dead scheduler must read as that, not as a 500 in the page.

        `main.create_app` maps it to 503, which is the answer the routes already gave when no
        scheduler was configured.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        proxy = self._proxy(handler)

        with pytest.raises(Exception) as caught:
            proxy.status()

        assert "not answering" in str(caught.value)

    def test_the_registry_is_answered_locally(self, settings):
        """`specs()` and `get()` are a pure function of settings, so every worker can answer."""

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not called
            raise AssertionError("the registry must not be fetched over the control API")

        proxy = RemoteScheduler(
            "http://scheduler.test",
            settings=settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

        specs = proxy.specs()
        assert specs and all(isinstance(spec, JobSpec) for spec in specs)
        assert proxy.get(specs[0].id) is not None
        assert proxy.get("not-a-job") is None


class TestWhichSchedulerTheAppBuilds:
    def _settings(self, settings, **env):
        return settings.model_copy(
            update={"env": settings.env.model_copy(update=env)}
        )

    def test_a_control_url_means_the_scheduler_is_elsewhere(self, settings):
        configured = self._settings(
            settings, scheduler_enabled=False, scheduler_control_url="http://127.0.0.1:8099"
        )

        built = _scheduler_for(configured)

        assert isinstance(built, RemoteScheduler), "the web tier must not own a job runner"
        assert built.base_url == "http://127.0.0.1:8099"

    def test_no_control_url_means_this_process_owns_it(self, settings):
        built = _scheduler_for(self._settings(settings, scheduler_control_url=None))

        assert isinstance(built, SchedulerService)

    def test_both_at_once_is_refused_rather_than_guessed(self, settings):
        """Two answers would be two schedulers, and the app cannot pick one for the operator."""
        contradictions = self._settings(
            settings, scheduler_enabled=True, scheduler_control_url="http://127.0.0.1:8099"
        )

        with pytest.raises(RuntimeError, match="AWLTUX_SCHEDULER_ENABLED"):
            _scheduler_for(contradictions)

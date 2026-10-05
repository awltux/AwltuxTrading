"""The CLI's job runner, and its preference for asking the server.

`awltux job` used to always run in its own process. Against a live server that
means two connections to one SQLite file, and the loser gets "database is locked"
— observed with `price_eod`, which holds the write lock across rate-limit sleeps.
Delegation is the fix; a direct run has to remain the fallback, because working
with no server running is half the point of the CLI.
"""

from __future__ import annotations

import pytest

from awltux import cli


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("boom", request=None, response=None)


class TestBaseUrl:
    @pytest.mark.parametrize("host", ["0.0.0.0", "::", ""])
    def test_a_bind_address_is_mapped_to_loopback(self, settings, host):
        """0.0.0.0 means "listen everywhere", not "connect here"."""
        settings.env.host = host
        assert cli._local_base_url(settings).startswith("http://127.0.0.1:")

    def test_a_real_host_is_kept(self, settings):
        settings.env.host = "10.0.0.5"
        assert "10.0.0.5" in cli._local_base_url(settings)


class TestDelegation:
    def test_a_healthy_server_takes_the_job(self, settings, monkeypatch):
        seen: dict = {}

        def fake_post(url, **kwargs):
            seen["url"] = url
            return _Response(200, {"job": "retention", "detail": {"removed": {"quotes": 3}}})

        monkeypatch.setattr("httpx.post", fake_post)
        result = cli._run_via_server(settings, "retention")

        assert result is not None
        assert result["detail"]["removed"]["quotes"] == 3
        assert seen["url"].endswith("/api/jobs/retention/run")

    def test_nothing_listening_means_run_it_here(self, settings, monkeypatch):
        import httpx

        def refuse(*_a, **_k):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("httpx.post", refuse)
        assert cli._run_via_server(settings, "retention") is None

    def test_an_unknown_job_on_the_server_falls_back(self, settings, monkeypatch):
        monkeypatch.setattr("httpx.post", lambda *a, **k: _Response(404))
        assert cli._run_via_server(settings, "nope") is None

    def test_a_server_error_is_reported_not_silently_swallowed(self, settings, monkeypatch, capsys):
        monkeypatch.setattr("httpx.post", lambda *a, **k: _Response(500))
        result = cli._run_via_server(settings, "retention")
        assert result is not None and "error" in result
        assert "server refused" in capsys.readouterr().err


class TestCmdJob:
    def test_the_default_is_to_delegate(self, settings, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            cli, "_run_via_server", lambda *a, **k: calls.append("delegate") or {"detail": {}}
        )
        monkeypatch.setattr(
            "awltux.scheduler.jobs.execute_job", lambda *a, **k: calls.append("local")
        )

        assert cli.main(["job", "retention"]) == 0
        assert calls == ["delegate"]

    def test_direct_skips_the_server(self, settings, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(cli, "_run_via_server", lambda *a, **k: calls.append("delegate"))
        monkeypatch.setattr(
            "awltux.scheduler.jobs.execute_job", lambda *a, **k: calls.append("local")
        )

        assert cli.main(["job", "retention", "--direct"]) == 0
        assert calls == ["local"]

    def test_an_unknown_job_is_rejected_without_touching_the_server(self, monkeypatch, capsys):
        called: list[str] = []
        monkeypatch.setattr(cli, "_run_via_server", lambda *a, **k: called.append("delegate"))

        assert cli.main(["job", "not-a-job"]) == 2
        assert called == []
        assert "unknown job" in capsys.readouterr().err

    def test_a_server_refusal_does_not_fall_through_to_a_local_run(self, settings, monkeypatch):
        """If the server answered and refused, a second attempt here would take the
        write lock the server is already using — the exact contention being fixed."""
        calls: list[str] = []
        monkeypatch.setattr(cli, "_run_via_server", lambda *a, **k: {"error": "boom"})
        monkeypatch.setattr(
            "awltux.scheduler.jobs.execute_job", lambda *a, **k: calls.append("local")
        )

        assert cli.main(["job", "retention"]) == 0
        assert calls == [], "must not run locally after the server answered"

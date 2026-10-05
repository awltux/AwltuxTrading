"""Diagnostics, tested without touching the network.

``run_diagnosis(live=False)`` must be usable as a preflight check in a hermetic
environment, so it is tested that way. The credential-description helper gets
particular attention: it exists to help debug a rejected key *without* printing
the key, and a regression there would leak secrets into logs and CI output.
"""

from __future__ import annotations

import pytest

from awltux.config import Settings
from awltux.doctor import Diagnosis, _describe_secret, run_diagnosis


class TestDiagnosisAggregation:
    def test_worst_status_ranks_fail_above_warn_and_ok(self):
        diagnosis = Diagnosis()
        diagnosis.add("a", "ok", "")
        diagnosis.add("b", "warn", "")
        assert diagnosis.worst == "warn"
        diagnosis.add("c", "fail", "")
        assert diagnosis.worst == "fail"

    def test_skipped_checks_do_not_count_as_success(self):
        """An unconfigured provider must not make the overall status look fine."""
        diagnosis = Diagnosis()
        diagnosis.add("a", "skip", "")
        diagnosis.add("b", "skip", "")
        assert diagnosis.worst == "skip"

    def test_serialises_for_json_output(self):
        diagnosis = Diagnosis()
        diagnosis.add("x", "ok", "fine")
        payload = diagnosis.as_dict()
        assert payload["status"] == "ok"
        assert payload["checks"][0]["check"] == "x"


class TestSecretRedaction:
    def test_reports_length_and_character_classes_but_not_the_value(self):
        secret = "Abc123Xyz789SecretValue"
        description = _describe_secret("key", secret)
        assert str(len(secret)) in description
        assert "upper" in description and "lower" in description and "digit" in description
        # The value itself, and any meaningful slice of it, must not appear.
        assert secret not in description
        assert secret[:6] not in description

    def test_flags_leading_or_trailing_whitespace(self):
        """The classic ``.env`` corruption, and invisible in a ``repr``."""
        description = _describe_secret("key", "  abcdef  ")
        assert "whitespace" in description

    def test_flags_unexpected_characters(self):
        description = _describe_secret("key", "abc$def!")
        assert "unexpected characters" in description

    def test_handles_an_unset_value(self):
        assert "not set" in _describe_secret("key", "")


class TestOfflineDiagnosis:
    def test_reports_local_state_without_any_network_call(self, settings: Settings):
        """Patch httpx to explode, proving the offline path really is offline."""
        import httpx

        def explode(*_args, **_kwargs):
            raise AssertionError("the offline diagnosis must not make a network call")

        original_get = httpx.get
        httpx.get = explode
        try:
            diagnosis = run_diagnosis(settings, live=False)
        finally:
            httpx.get = original_get

        names = {check.name for check in diagnosis.checks}
        assert "scheduler" in names
        assert "decision_engines" in names
        # No provider checks should have run.
        assert not any(name.startswith("trading212") for name in names)

    def test_reports_the_scheduler_registry(self, settings: Settings):
        diagnosis = run_diagnosis(settings, live=False)
        scheduler = next(c for c in diagnosis.checks if c.name == "scheduler")
        # With no credentials, the two Trading 212 jobs are disabled but the rest
        # are not, so the app is still useful out of the box.
        assert "jobs enabled" in scheduler.detail
        assert scheduler.status == "ok"

    def test_reports_the_engine_priority_so_fallbacks_are_visible(self, settings: Settings):
        diagnosis = run_diagnosis(settings, live=False)
        engines = next(c for c in diagnosis.checks if c.name == "decision_engines")
        assert "jev" in engines.detail and "offline" in engines.detail


class TestCredentialAbsenceIsActionable:
    def test_an_unconfigured_provider_is_skipped_with_a_hint(self, settings: Settings):
        """Skipping must still tell the user what they are missing, not just be quiet."""
        from awltux.doctor import check_trading212

        diagnosis = Diagnosis()
        check_trading212(diagnosis, settings)
        check = next(c for c in diagnosis.checks if c.name == "trading212")
        assert check.status == "skip"
        assert check.hint and "universe" in check.hint

    @pytest.mark.parametrize(
        "check_name",
        ["deepseek", "jev", "companies_house"],
    )
    def test_other_unconfigured_providers_are_skipped_with_hints(
        self, settings: Settings, check_name: str
    ):
        from awltux.doctor import (
            check_companies_house,
            check_deepseek,
            check_jev,
        )

        diagnosis = Diagnosis()
        {
            "deepseek": check_deepseek,
            "jev": check_jev,
            "companies_house": check_companies_house,
        }[check_name](diagnosis, settings)

        check = next(c for c in diagnosis.checks if c.name == check_name)
        assert check.status == "skip"
        assert check.hint


class TestEgressAddresses:
    """A dual-stack host presents different addresses per family.

    That is how an IP allowlist silently fails: you allowlist the IPv4 address,
    the client connects over IPv6, and the key is rejected with a plain 401 that
    looks nothing like a network problem.
    """

    def test_reports_both_families_separately(self, settings: Settings, monkeypatch):
        import httpx

        from awltux.doctor import egress_addresses

        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text

        class FakeClient:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def get(self, url: str):
                return FakeResponse("203.0.113.7" if "api64" not in url else "2001:db8::1")

        monkeypatch.setattr(httpx, "Client", FakeClient)
        addresses = egress_addresses(settings)
        assert addresses["ipv4"] == "203.0.113.7"
        assert addresses["ipv6"] == "2001:db8::1"

    def test_a_failed_lookup_is_reported_as_unknown_rather_than_wrong(
        self, settings: Settings, monkeypatch
    ):
        import httpx

        from awltux.doctor import egress_addresses

        class ExplodingClient:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def get(self, url: str):
                raise ConnectionError("no route")

        monkeypatch.setattr(httpx, "Client", ExplodingClient)
        addresses = egress_addresses(settings)
        assert addresses == {"ipv4": None, "ipv6": None}


class TestIpv4Pinning:
    def test_it_is_off_by_default(self, settings: Settings):
        """Pinning is a workaround, not a sensible default for everyone."""
        assert settings.env.force_ipv4 is False

    def test_the_http_client_pins_when_asked(self, settings: Settings, monkeypatch):
        """The setting must reach the client that actually makes the calls."""
        import httpx

        from awltux.providers.http import HttpClient

        captured: dict = {}
        original = httpx.HTTPTransport

        def spy(*args, **kwargs):
            captured.update(kwargs)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "HTTPTransport", spy)
        settings.env.force_ipv4 = True

        client = HttpClient("test_provider", settings=settings, base_url="https://example.test")
        try:
            assert captured.get("local_address") == "0.0.0.0"
        finally:
            client.close()

    def test_no_transport_is_created_when_not_pinned(self, settings: Settings, monkeypatch):
        import httpx

        from awltux.providers.http import HttpClient

        captured: dict = {}
        original = httpx.HTTPTransport

        def spy(*args, **kwargs):
            captured.update(kwargs)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "HTTPTransport", spy)
        assert settings.env.force_ipv4 is False

        client = HttpClient("test_provider", settings=settings, base_url="https://example.test")
        try:
            assert "local_address" not in captured
        finally:
            client.close()

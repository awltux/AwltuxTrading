"""The test suite must never reach a live provider.

This file exists because it actually happened. With a populated `.env`, the
decision tests silently called the live Trading 212 API: ``decide_universe()``
defaults to ``get_settings()``, and ``awltux.decision.service`` holds its own
module-level reference to it, so patching only ``awltux.config`` left the real
configuration in play. The symptom was ~33 seconds per test while the code waited
on a request timeout -- a slow suite rather than a failing one, which is exactly
the kind of defect that survives review.

These tests make the guarantee explicit and break loudly if the isolation is
weakened, rather than relying on one assertion buried inside a fixture.
"""

from __future__ import annotations

import sys

import pytest

from awltux.config import Settings
from awltux.config import get_settings as real_get_settings

CREDENTIAL_ATTRS = (
    "t212_api_key",
    "t212_api_secret",
    "deepseek_api_key",
    "typesafe_api_key",
    "companies_house_api_key",
    "finnhub_api_key",
    "marketaux_api_key",
    "alphavantage_api_key",
    "reddit_client_id",
    "reddit_client_secret",
)


class TestNoCredentials:
    @pytest.mark.parametrize("attribute", CREDENTIAL_ATTRS)
    def test_every_credential_is_empty(self, settings: Settings, attribute: str):
        """Whatever the developer's environment or `.env` holds."""
        value = getattr(settings.env, attribute)
        assert value is None or value.get_secret_value() == "", (
            f"{attribute} is populated in the test environment; the suite could "
            "make live calls"
        )

    def test_providers_report_as_unconfigured(self, settings: Settings):
        assert settings.env.t212_configured is False
        assert settings.env.deepseek_configured is False
        assert settings.env.jev_configured is False

    def test_live_orders_are_not_enabled(self, settings: Settings):
        assert settings.env.t212_env == "demo"
        assert settings.env.allow_live_orders is False


class TestGetSettingsIsPatchedEverywhere:
    """:func:`get_settings` is imported by name in many modules.

    Each such module holds its own reference, so a patch that misses one of them
    silently reintroduces the real configuration on whichever code path uses it.
    """

    def test_awltux_modules_are_all_patched(self, settings: Settings):
        leaked: list[str] = []
        for name, module in list(sys.modules.items()):
            if not name.startswith("awltux") or module is None:
                continue
            resolver = getattr(module, "get_settings", None)
            if resolver is None:
                continue
            resolved = resolver()
            if resolved is not settings:
                leaked.append(name)

        assert not leaked, (
            "these modules still resolve the real configuration: "
            + ", ".join(sorted(leaked))
        )

    def test_the_decision_service_resolves_test_settings(self, settings: Settings):
        """The specific leak that caused the live API calls."""
        from awltux.decision import service

        assert service.get_settings() is settings

    def test_the_ingest_and_provider_layers_resolve_test_settings(self, settings: Settings):
        from awltux.analysis import fx, sentiment, valuation
        from awltux.ingest import fundamentals, news, prices, universe
        from awltux.llm import deepseek

        for module in (fx, sentiment, valuation, fundamentals, news, prices, universe, deepseek):
            resolver = getattr(module, "get_settings", None)
            if resolver is not None:
                assert resolver() is settings, module.__name__

    def test_real_get_settings_is_not_the_test_settings(self, settings: Settings):
        """Sanity: the isolation is doing something, not trivially passing."""
        assert real_get_settings() is not settings


class TestNoNetworkReachability:
    def test_the_data_directory_is_the_temporary_one(self, settings: Settings, temp_dir):
        assert settings.data_dir == temp_dir / "data"
        # The URL is built with POSIX separators so SQLite accepts it on every
        # platform, so compare normalised forms rather than the raw strings.
        assert settings.data_dir.as_posix() in settings.database_url

    def test_engine_priority_starts_with_jev_so_gaps_are_visible(self, settings: Settings):
        """The offline engine is last, which is why a missing key must fall through
        rather than silently change which engine answers."""
        assert settings.decision.engine_priority == ["jev", "deepseek", "offline"]

"""Shared test fixtures.

Every test runs against a temporary data directory and a fresh SQLite database,
and with an explicit ``EnvSettings`` that does **not** read a developer's ``.env``.
That last point matters: a test that silently picks up a real API key would take
a different code path on a different machine, which is how "it passes locally"
happens.

The temporary directory is created explicitly under the repository rather than
via pytest's ``tmp_path``. ``tmp_path`` builds its base directory with restrictive
permissions and garbage-collects stale numbered directories, which a file-access
sandbox denies; creating the directory ourselves keeps the suite runnable inside
that sandbox without weakening what it tests.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from awltux.config import EnvSettings, Settings, build_settings
from awltux.db import reset_engine, session_scope
from awltux.db.session import init_db

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_ROOT / "config" / "config.yaml"
#: Scratch space for the suite. Inside the workspace so the sandbox permits it.
TMP_ROOT = REPO_ROOT / ".tests-tmp"


@pytest.fixture(scope="session")
def config_file() -> Path:
    assert CONFIG_FILE.exists(), f"missing config at {CONFIG_FILE}"
    return CONFIG_FILE


@pytest.fixture
def temp_dir() -> Iterator[Path]:
    """An isolated directory that is always removed afterwards.

    Created with :meth:`Path.mkdir` rather than :func:`tempfile.mkdtemp`. On
    Windows, ``mkdtemp`` applies a 0o700 mode that yields an ACL the file-access
    sandbox cannot write into, so any subdirectory creation inside it fails. Using
    the default permissions avoids that entirely.
    """
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TMP_ROOT / f"run-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def settings(temp_dir: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Isolated settings pointing at a temporary data directory.

    Two independent guarantees, because a test suite that quietly reaches a live
    provider is worse than one that fails:

    1. **No credentials, whatever the environment holds.** Every credential field
       is forced to ``None`` explicitly. Relying on ``_env_file=None`` alone is not
       enough: ``pydantic-settings`` still reads real ``AWLTUX_*`` environment
       variables, so a developer with a populated ``.env`` (or exported vars) would
       otherwise run the suite against their live broker account. That is not
       hypothetical -- it happened here, and showed up as ~33s per decision test
       while the code waited on a Trading 212 request timeout.

    2. **No stale ``get_settings`` references.** ``get_settings`` is a module-level
       import in a dozen modules, so patching only ``awltux.config`` would leave
       most of them resolving the real configuration. Every loaded ``awltux``
       module that holds a reference is patched.
    """
    data_dir = temp_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    env = EnvSettings(
        _env_file=None,
        data_dir=data_dir,
        config_file=config_file,
        log_level="WARNING",
        # Explicitly clear every credential. See the docstring.
        t212_api_key=None,
        t212_api_secret=None,
        deepseek_api_key=None,
        typesafe_api_key=None,
        companies_house_api_key=None,
        finnhub_api_key=None,
        marketaux_api_key=None,
        alphavantage_api_key=None,
        reddit_client_id=None,
        reddit_client_secret=None,
        # Fal's credential, and it must be cleared here for the same reason as the
        # rest: `FAL_KEY` is an ordinary environment variable that a developer may
        # well have exported, and a suite that quietly spent their embeddings quota
        # would be reaching a live provider without saying so.
        falai_key=None,
        t212_env="demo",
        allow_live_orders=False,
        # No job runner in the test process. A background job writes `ingest_run`
        # rows, which made page-count assertions depend on whether one had fired,
        # and the scheduler thread outlived the temporary database it was writing
        # to. The dashboard is still the real application; only the timers are off.
        scheduler_enabled=False,
    )
    resolved = build_settings(env)

    # Belt and braces: if any of these ever becomes true, tests will start making
    # live calls. Fail loudly here instead.
    assert not resolved.env.t212_configured, "tests must not reach a live T212 account"
    assert not resolved.env.deepseek_configured, "tests must not spend DeepSeek credit"
    assert not resolved.env.jev_configured, "tests must not call JEV"

    _patch_get_settings(monkeypatch, resolved)

    reset_engine()
    init_db(resolved)
    yield resolved
    reset_engine()


def _patch_get_settings(monkeypatch: pytest.MonkeyPatch, resolved: Settings) -> None:
    """Point every module-level ``get_settings`` reference at the test settings."""
    import sys

    patched = 0
    for name, module in list(sys.modules.items()):
        if not name.startswith("awltux") or module is None:
            continue
        if hasattr(module, "get_settings"):
            monkeypatch.setattr(module, "get_settings", lambda: resolved, raising=False)
            patched += 1
        if hasattr(module, "reload_settings"):
            monkeypatch.setattr(module, "reload_settings", lambda: resolved, raising=False)

    # A regression guard, deliberately loose: at this point only the modules this
    # particular run has imported exist, so a high threshold would fail when a
    # single test file is executed alone. The thorough check -- that *every*
    # loaded awltux module resolves the test settings -- lives in
    # tests/test_isolation.py, which imports them all explicitly.
    assert patched >= 1, "no awltux module exposes a patchable get_settings"


@pytest.fixture
def session(settings: Settings) -> Iterator:
    with session_scope() as scope:
        yield scope


@pytest.fixture
def client(settings, monkeypatch):
    """A TestClient whose lifespan resolves to the test configuration.

    Lives here rather than in one module because more than one module now drives a
    real request: the page tests span the dashboard, the news pages and the
    prediction ledger, and a fixture that only one file can reach invites either
    duplication or a test that quietly runs against the wrong settings.

    ``reload_settings`` is imported into ``awltux.main`` at module load, so the
    reference there has to be patched as well as the one in ``awltux.config`` --
    otherwise startup would rebuild the real settings and ignore the fixture.
    """
    from fastapi.testclient import TestClient

    import awltux.config as config_module
    import awltux.db.session as session_module
    import awltux.main as main_module

    monkeypatch.setattr(config_module, "reload_settings", lambda: settings)
    monkeypatch.setattr(main_module, "reload_settings", lambda: settings)
    monkeypatch.setattr(session_module, "get_settings", lambda: settings)

    with TestClient(main_module.create_app()) as test_client:
        yield test_client


@pytest.fixture
def universe_instrument(session):
    """One instrument in the analysed universe.

    Most page tests need somewhere for a row to point; they do not need the
    decision and valuation rows the dashboard's own fixture builds, and reusing
    that fixture would tie unrelated pages to the decision pipeline.
    """
    from tests.helpers import make_instrument

    session.add(make_instrument("TEST_US_EQ", name="Test Industries", sector="Industrials"))
    session.flush()
    return "TEST_US_EQ"


# Re-exported so tests can `from tests.conftest import ...` or use the helpers
# module directly; both resolve to the same builders.
from tests.helpers import (  # noqa: E402
    healthy_metrics,
    make_bars,
    make_instrument,
    make_period,
    trending_closes,
)

__all__ = [
    "healthy_metrics",
    "make_bars",
    "make_instrument",
    "make_period",
    "trending_closes",
]

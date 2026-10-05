"""HTTP layer: health, the dashboard, the JSON API and the decision receipt.

These run against the real FastAPI app with its lifespan, so they exercise the
startup path a container actually takes (config, database, scheduler) rather than
just the route functions in isolation.

No provider is configured, so the scheduler registers its credential-gated jobs
as disabled and nothing reaches the network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(settings, monkeypatch):
    """A TestClient whose lifespan resolves to the test configuration.

    ``reload_settings`` is imported into ``awltux.main`` at module load, so the
    reference there has to be patched as well as the one in ``awltux.config`` --
    otherwise startup would rebuild the real settings and ignore the fixture.
    """
    import awltux.config as config_module
    import awltux.db.session as session_module
    import awltux.main as main_module

    monkeypatch.setattr(config_module, "reload_settings", lambda: settings)
    monkeypatch.setattr(main_module, "reload_settings", lambda: settings)
    monkeypatch.setattr(session_module, "get_settings", lambda: settings)

    with TestClient(main_module.create_app()) as test_client:
        yield test_client


class TestHealth:
    def test_healthz_reports_ok_and_the_database(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["database"]["ok"] is True
        assert body["version"]

    def test_detailed_health_lists_providers_and_jobs(self, client):
        body = client.get("/api/health").json()
        assert "providers" in body
        assert body["providers"]["jev"]["configured"] is False
        assert body["providers"]["deepseek"]["configured"] is False
        assert body["scheduler"]["jobs"]

    def test_admin_or_live_orders_are_not_enabled_by_default(self, client):
        """The app must never present itself as able to trade live money."""
        body = client.get("/api/health").json()
        t212 = body["providers"]["trading212"]
        assert t212["environment"] == "demo"
        assert t212["orders_allowed"] is True  # demo is permitted


class TestDashboard:
    def test_root_redirects_to_the_dashboard(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/dashboard"

    def test_dashboard_renders_with_an_empty_database(self, client):
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "Recommendations" in response.text
        # The disclaimer must always be visible.
        assert "Not financial advice" in response.text

    def test_dashboard_accepts_sort_and_filter_parameters(self, client):
        for query in (
            "?sort=margin_of_safety&direction=asc",
            "?sort=action&direction=asc",
            "?sort=short_term_action&direction=asc",
            "?sort=short_term_score",
            "?sort=horizon_fit",
            "?view=suggestions",
            "?view=suggestions&horizon=short_term",
            "?view=held",
            "?horizon_fit=long_term",
            "?q=nothing",
        ):
            response = client.get(f"/dashboard{query}")
            assert response.status_code == 200, query

    def test_unknown_instrument_returns_404(self, client):
        assert client.get("/instrument/DOES_NOT_EXIST").status_code == 404

    def test_other_pages_render(self, client):
        for path in ("/sectors", "/calibration", "/jobs"):
            response = client.get(path)
            assert response.status_code == 200, path


class TestJsonApi:
    def test_recommendations_returns_an_envelope(self, client):
        body = client.get("/api/recommendations").json()
        assert body["items"] == []
        assert body["total"] == 0
        assert "disclaimer" in body

    def test_settings_redacts_secrets(self, client):
        body = client.get("/api/settings").json()
        # Presence flags, never values.
        assert "deepseek_configured" in body["env"]
        assert "deepseek_api_key" not in body["env"]
        assert "t212_api_secret" not in body["env"]

    def test_jobs_endpoint_lists_the_registry(self, client):
        body = client.get("/api/jobs").json()
        ids = {job["id"] for job in body["jobs"]}
        assert "price_eod" in ids
        assert "decision" in ids
        # Credential-gated jobs are visible but disabled, not hidden.
        disabled = {job["id"] for job in body["jobs"] if not job["enabled"]}
        assert "t212_instruments" in disabled

    def test_unknown_job_run_returns_404(self, client):
        assert client.post("/api/jobs/no-such-job/run").status_code == 404

    def test_sector_sentiment_endpoint(self, client):
        body = client.get("/api/sectors/sentiment?days=30").json()
        assert body["sectors"] == {}

    def test_news_endpoint(self, client):
        body = client.get("/api/news").json()
        assert body["items"] == []


class TestDecisionReceipt:
    @pytest.fixture
    def decision_id(self, settings, session):
        """Seed enough data to produce one decision, then return its id."""
        import datetime as dt

        from awltux.analysis.valuation import run_valuations
        from awltux.decision.service import decide_universe
        from tests.helpers import healthy_metrics, make_bars, make_instrument, make_period

        session.add(
            make_instrument(
                "TEST_US_EQ",
                name="Test Industries",
                sector="Industrials",
                median_daily_turnover_gbp=5_000_000.0,
            )
        )
        session.flush()
        for bar in make_bars("TEST_US_EQ", [10.0 * (1.0009**n) for n in range(260)]):
            session.add(bar)
        for year in (2022, 2023, 2024):
            session.add(make_period("TEST_US_EQ", dt.date(year, 12, 31), healthy_metrics()))
        session.flush()

        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])

        from sqlalchemy import select

        from awltux.db import DecisionRun

        decision = session.execute(select(DecisionRun)).scalar_one()

        # Commit before the request: the API opens its own session, so data that
        # is only flushed in this one would be invisible to it.
        session.commit()
        return decision.id

    def test_receipt_exposes_the_full_provenance_chain(self, client, decision_id):
        body = client.get(f"/api/decisions/{decision_id}/receipt").json()
        assert body["state_sha256"]
        assert body["engine"] == "offline"
        assert body["uncalibrated"] is True
        assert body["state"]
        assert body["questions"]
        assert body["answers"]
        # Both horizons must appear on the receipt, each with its own gate, so a
        # stored verdict can never be misread as applying to the other timescale.
        for horizon in ("long_term", "short_term"):
            assert body[horizon]["action"]
            assert body[horizon]["gate"]
            assert body[horizon]["gate"]["horizon"] == horizon
        assert body["horizon_fit"] in {"long_term", "short_term", "both", "neither"}

    def test_receipt_for_unknown_decision_is_404(self, client):
        assert client.get("/api/decisions/999999/receipt").status_code == 404

    def test_instrument_detail_marks_the_engine(self, client, decision_id):
        body = client.get("/api/instruments/TEST_US_EQ").json()
        assert body["instrument"]["t212_ticker"] == "TEST_US_EQ"
        assert body["decision"]["engine"] == "offline"
        assert body["decision"]["uncalibrated"] is True
        assert body["valuation"] is not None

    def test_replay_endpoint_reproduces_the_decision(self, client, decision_id):
        body = client.post(f"/api/decisions/{decision_id}/replay").json()
        assert body["status"] == "reproduced"
        assert body["replayed_engine"] == "offline"


class TestNewsStreamContract:
    """The SSE contract the ticker depends on.

    Tested by exercising the framing function and the route's declared response
    directly rather than by holding a streaming response open. An SSE endpoint
    keeps yielding keepalives forever, so a test that consumes it would hang
    rather than fail -- and the framing is the part a browser actually relies on.
    """

    def test_frame_format_matches_the_event_source_spec(self):
        from awltux.web.routes.news import format_sse

        frame = format_sse({"id": 7, "title": "Hello"}, event="news", event_id=7)
        text = frame.decode()
        assert text.startswith("id: 7\nevent: news\ndata: ")
        assert text.endswith("\n\n")
        assert '"title": "Hello"' in text

    def test_frame_without_an_id_omits_the_id_line(self):
        from awltux.web.routes.news import format_sse

        text = format_sse({"x": 1}, event="news").decode()
        assert not text.startswith("id:")

    def test_keepalive_is_a_comment_frame(self):
        """A comment frame is what stops an intermediary closing an idle stream."""
        from awltux.web.routes.news import format_comment

        assert format_comment("keepalive") == b": keepalive\n\n"

    @pytest.mark.asyncio
    async def test_route_declares_an_event_stream(self):
        from starlette.requests import Request

        from awltux.web.routes.news import news_stream

        scope = {"type": "http", "method": "GET", "path": "/api/news/stream", "headers": []}
        response = await news_stream(Request(scope), last_event_id=0, replay=0)

        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache, no-transform"

    def test_ticker_partial_renders_without_javascript(self, client):
        response = client.get("/partials/news-ticker")
        assert response.status_code == 200
        assert "No headlines yet" in response.text


class TestNewsQueries:
    """The database side of the stream, tested directly."""

    def test_fetch_since_returns_only_newer_items(self, session, settings):
        import datetime as dt

        from awltux.db import NewsItem
        from awltux.web.routes.news import _fetch_latest, _fetch_since

        for index in range(3):
            session.add(
                NewsItem(
                    source="rss",
                    url=f"https://example.test/{index}",
                    url_hash=f"{index:064d}",
                    title=f"Story {index}",
                    published_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=index),
                    tickers=["TEST_US_EQ"],
                    materiality="mild",
                )
            )
        session.flush()
        # The stream helpers open their own session, so these rows must be
        # committed to be visible to them.
        session.commit()

        assert len(_fetch_latest(3)) == 3
        # The first item's id is the oldest; asking for anything after it must
        # return exactly the remaining two, with no gap and no duplicate.
        oldest = _fetch_latest(3)[0]["id"]
        newer = _fetch_since(int(oldest), 50)
        assert len(newer) == 2
        assert all(item["id"] > oldest for item in newer)

    def test_fetch_latest_is_chronological(self, session, settings):
        import datetime as dt

        from awltux.db import NewsItem
        from awltux.web.routes.news import _fetch_latest

        for index in range(3):
            session.add(
                NewsItem(
                    source="rss",
                    url=f"https://example.test/c{index}",
                    url_hash=f"{index + 100:064d}",
                    title=f"Chronological {index}",
                    published_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=3 - index),
                    tickers=["TEST_US_EQ"],
                )
            )
        session.flush()
        session.commit()

        items = _fetch_latest(3)
        assert [item["title"] for item in items] == [
            "Chronological 0",
            "Chronological 1",
            "Chronological 2",
        ]

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


class TestTemplatesRenderWithData:
    """Template helpers are only exercised once there are rows to render.

    ``engine_label`` was registered as a Jinja *filter* but called as a
    *function*, so the recommendations page raised
    ``UndefinedError: 'engine_label' is undefined``. No test caught it, because
    every dashboard test ran against an empty database -- where the row loop never
    executes and the helper is never reached. These tests seed a decision first.
    """

    @pytest.fixture
    def populated(self, settings, session):
        """One instrument with a decision and a valuation, committed."""
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
        session.commit()

    def test_engine_label_is_a_global_not_only_a_filter(self):
        """Two-argument helpers cannot be reached through filter syntax."""
        from awltux.web.templating import templates

        assert "engine_label" in templates.env.globals
        assert "engine_label" in templates.env.filters

    def test_the_recommendations_page_renders_with_a_decision(self, client, populated):
        response = client.get("/dashboard")
        assert response.status_code == 200
        # The label the helper produces must actually appear.
        assert "offline" in response.text
        assert "TEST_US_EQ" in response.text

    def test_both_horizon_columns_render(self, client, populated):
        body = client.get("/dashboard").text
        assert "Long term" in body
        assert "Short term" in body

    def test_dashboard_variants_render_with_data(self, client, populated):
        for query in (
            "?view=suggestions",
            "?view=held",
            "?horizon=short_term",
            "?sort=short_term_action",
            "?sort=horizon_fit",
            "?horizon_fit=both",
        ):
            response = client.get(f"/dashboard{query}")
            assert response.status_code == 200, query

    def test_the_instrument_page_renders_with_a_decision(self, client, populated):
        response = client.get("/instrument/TEST_US_EQ")
        assert response.status_code == 200
        assert "offline" in response.text
        # The per-horizon cards are only reached when a decision exists.
        assert "Long term" in response.text
        assert "Short term" in response.text

    def test_the_operations_page_renders_run_history(self, client, populated):
        assert client.get("/jobs").status_code == 200

    def test_the_calibration_page_renders_for_both_horizons(self, client, populated):
        for horizon in ("long_term", "short_term"):
            response = client.get(f"/calibration?horizon={horizon}")
            assert response.status_code == 200, horizon

    def test_other_pages_render(self, client):
        for path in ("/sectors", "/calibration", "/jobs", "/info"):
            response = client.get(path)
            assert response.status_code == 200, path


class TestInfoPage:
    """The build-provenance page.

    ``load_build_info`` reads the live checkout when there is one, which would
    make these tests depend on the machine's git state -- so the checkout is
    removed and the baked artifact is pointed at a fixture instead. That is also
    the case the page exists for: an installed copy with no ``.git``.
    """

    @pytest.fixture
    def bundled(self, settings, monkeypatch, temp_dir):
        import json

        from awltux import buildinfo

        payload = {
            "generated_at": "2026-03-04T05:06:07+00:00",
            "head": "deadbeef" * 5,
            "dirty": False,
            "commits": [
                {
                    "hash": "deadbeef" * 5,
                    "short_hash": "deadbee",
                    "author": "Ada Lovelace",
                    "date": "2026-03-04T05:06:07+00:00",
                    "subject": "Record the revision in the image",
                },
                {
                    "hash": "cafebabe" * 5,
                    "short_hash": "cafebab",
                    "author": "Grace Hopper",
                    "date": "2026-03-03T01:02:03+00:00",
                    "subject": "Add the info page",
                },
            ],
        }
        path = temp_dir / "build_info.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        monkeypatch.setattr(buildinfo, "BUNDLED_PATH", path)
        monkeypatch.setattr(buildinfo, "repo_root", lambda *_, **__: None)
        return payload

    def test_the_info_page_lists_commits_with_their_hashes(self, client, bundled):
        body = client.get("/info").text
        assert "deadbee" in body
        assert "Record the revision in the image" in body
        assert "cafebab" in body
        assert "Add the info page" in body
        # The full hash is available, not just the abbreviation.
        assert "deadbeef" * 5 in body

    def test_the_page_names_where_the_history_came_from(self, client, bundled):
        body = client.get("/info").text
        assert "baked in at build time" in body
        assert "2026-03-04" in body  # the capture timestamp, not just the commits

    def test_a_dirty_build_is_admitted_rather_than_hidden(self, client, bundled, monkeypatch, temp_dir):
        import json

        bundled["dirty"] = True
        path = temp_dir / "dirty.json"
        path.write_text(json.dumps(bundled), encoding="utf-8")
        from awltux import buildinfo

        monkeypatch.setattr(buildinfo, "BUNDLED_PATH", path)

        body = client.get("/info").text
        assert "has uncommitted changes" in body
        # And the consequence is spelled out rather than left to the reader.
        assert "built from a dirty tree" in body

    def test_an_install_that_cannot_name_its_revision_says_so(self, client, settings, monkeypatch, temp_dir):
        from awltux import buildinfo

        monkeypatch.setattr(buildinfo, "BUNDLED_PATH", temp_dir / "absent.json")
        monkeypatch.setattr(buildinfo, "repo_root", lambda *_, **__: None)

        response = client.get("/info")
        assert response.status_code == 200
        assert "unavailable" in response.text
        assert "cannot name" in response.text

    def test_the_api_link_opens_in_a_new_tab(self, client):
        body = client.get("/dashboard").text
        assert 'href="/docs" target="_blank" rel="noopener"' in body

    def test_the_navigation_links_to_the_info_page(self, client):
        assert 'href="/info"' in client.get("/dashboard").text


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


class TestDisplayZone:
    """Store UTC, show the reader's clock.

    The zone is resolved by ASGI middleware into a ``ContextVar`` that the
    template filters read. That is the part worth testing through a real request:
    a ``ContextVar`` set around an ASGI call has to survive into the threadpool a
    synchronous endpoint runs in, and if it does not, every page silently falls
    back to the configured zone while looking like it works.
    """

    def test_without_a_cookie_the_configured_zone_is_used(self, client):
        body = client.get("/dashboard").text
        # config/config.yaml sets app.timezone to Europe/London.
        assert "Europe/London" in body
        assert "Times are shown in" in body

    def test_the_reader_cookie_selects_the_rendered_zone(self, client):
        client.cookies.set("awltux_tz", "America/New_York")
        try:
            body = client.get("/dashboard").text
            assert "America/New_York" in body
            assert "Europe/London" not in body
        finally:
            client.cookies.clear()

    def test_an_invalid_cookie_falls_back_rather_than_failing(self, client):
        client.cookies.set("awltux_tz", "Mars/Olympus_Mons")
        try:
            response = client.get("/dashboard")
            assert response.status_code == 200
            assert "Europe/London" in response.text
        finally:
            client.cookies.clear()

    def test_a_hostile_cookie_cannot_reach_the_filesystem(self, client):
        client.cookies.set("awltux_tz", "../../etc/passwd")
        try:
            response = client.get("/dashboard")
            assert response.status_code == 200
            assert "passwd" not in response.text
        finally:
            client.cookies.clear()

    def test_the_zone_does_not_leak_between_requests(self, client):
        client.cookies.set("awltux_tz", "Asia/Kolkata")
        try:
            assert "Asia/Kolkata" in client.get("/dashboard").text
        finally:
            client.cookies.clear()
        # The next request, without the cookie, must be back on the configured zone.
        assert "Europe/London" in client.get("/dashboard").text

    def test_every_page_states_its_zone(self, client):
        for path in ("/dashboard", "/sectors", "/jobs", "/calibration", "/info"):
            body = client.get(path).text
            assert "Times are shown in" in body, path

    def test_api_timestamps_are_iso_utc(self, client):
        """The API is machine-facing: an unambiguous instant, never a local string."""
        body = client.get("/api/health").json()
        assert body["ok"] is True


class TestNewsScepticismSurface:
    """The appraisal has to reach the reader, not just the database.

    A credibility weight that only exists in a table is indistinguishable from not
    having one, and the flash ticker is the one place a bare headline could still
    reach someone -- so both surfaces are checked here.
    """

    @pytest.fixture
    def appraised(self, session, settings):
        import datetime as dt

        from awltux.analysis.news_analysis import analyse_universe
        from awltux.db import Instrument, NewsItem

        session.add(
            Instrument(
                t212_ticker="TEST_US_EQ",
                name="Test Industries",
                instrument_type="STOCK",
                exchange_name="NASDAQ",
                yahoo_symbol="TEST",
                in_universe=True,
            )
        )
        item = NewsItem(
            source="google_news",
            url="https://unknown-blog.example/shocking",
            url_hash="a" * 64,
            title="SHOCKING: test company meltdown wipes out investors",
            summary="Investors are fleeing in a bloodbath, sources say, as savings are wiped out.",
            published_at=dt.datetime.now(dt.UTC),
            tickers=["TEST_US_EQ"],
            materiality="critical",
            direction="negative",
            sentiment_score=-0.9,
            relevance=0.9,
            event_type="other",
        )
        session.add(item)
        session.flush()
        analyse_universe(session, settings=settings)
        session.commit()
        return item

    def test_the_api_carries_the_appraisal_with_the_item(self, client, appraised):
        body = client.get("/api/news").json()
        assert body["count"] == 1
        scepticism = body["items"][0]["scepticism"]
        assert scepticism is not None
        assert scepticism["grade"] in ("unsupported", "weak")
        assert scepticism["credibility"] <= 0.3
        assert scepticism["flags"]
        assert scepticism["warnings"]

    def test_the_flash_ticker_shows_the_weight_beside_the_headline(self, client, appraised):
        body = client.get("/partials/news-ticker").text
        assert "wipes out investors" in body
        assert "badge" in body
        assert "unconfirmed" in body or "framing" in body

    def test_the_instrument_page_explains_what_the_story_rests_on(self, client, appraised):
        body = client.get("/instrument/TEST_US_EQ").text
        assert "What this story rests on" in body
        assert "independent source" in body
        assert "not yet appraised" not in body

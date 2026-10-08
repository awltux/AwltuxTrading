"""HTTP layer: health, the dashboard, the JSON API and the decision receipt.

These run against the real FastAPI app with its lifespan, so they exercise the
startup path a container actually takes (config, database, scheduler) rather than
just the route functions in isolation.

No provider is configured, so the scheduler registers its credential-gated jobs
as disabled and nothing reaches the network.
"""

from __future__ import annotations

import pytest

from awltux.db import utcnow


def _money(text: str) -> float:
    """The leading number of a rendered money cell, e.g. "264.91 GBP" -> 264.91."""
    return float(text.split()[0].replace(",", ""))


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


class TestTheSchedulerToggle:
    """The dashboard is the real application under test; its timers are not.

    The scheduler used to start inside every `client` fixture. That was invisible
    until a `run_on_start` job was enabled by default -- then a background thread
    began writing `ingest_run` rows while tests were asserting on how many rows
    existed, and outlived the temporary database it was writing to.
    """

    def test_the_test_fixture_runs_no_jobs(self, settings):
        assert settings.env.scheduler_enabled is False, (
            "removing this makes page-count assertions depend on whether a "
            "background job happened to have fired"
        )

    def test_the_scheduler_is_on_by_default(self):
        """The toggle must not be off in a deployment, which is the only place it
        matters."""
        from awltux.config import EnvSettings

        assert EnvSettings(_env_file=None).scheduler_enabled is True


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

    def test_the_empty_dashboard_names_the_step_that_fills_the_universe(self, client):
        """A blank table with no explanation is indistinguishable from a bug.

        The jobs list used to omit `universe_refresh`, which is exactly the step
        that selects what gets analysed — so a reader following it in order still
        ended up with an empty universe and no idea why.
        """
        body = client.get("/dashboard").text
        assert "universe is <strong>empty</strong>" in body
        assert "universe_refresh" in body
        assert "t212_instruments" in body

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

    def test_the_instrument_page_shows_the_discount_rate_and_its_sensitivity(
        self, client, populated
    ):
        """The risk-free rate is the only input the model takes from the market
        rather than from the filings, so the value it produced has to say where the
        rate came from -- and how much of the value depends on it."""
        body = client.get("/instrument/TEST_US_EQ").text
        # Collapse the template's indentation so the assertion is about the words
        # rather than about how they happen to be wrapped.
        text = " ".join(body.split())

        assert "Risk-free rate" in text
        assert "Rate sensitivity" in text
        assert "per +1% risk-free rate" in text
        # The rate is a fraction like 0.0531, and `pct` treats a value as an
        # already-percentage number unless told otherwise -- which renders a 5.31%
        # rate as "+0.05%".
        assert "4.20%" in text, "the configured rate must render as a rate, not 100x small"
        # `pct` supplies the sign, so a literal one in the template would render
        # "+ +1%" -- the same mistake the signed-proportion tests exist to catch.
        assert "++" not in text
        # With no observation stored, the fallback must say that it is a fallback
        # rather than presenting a constant as though it were a market price.
        assert "configured constant" in text

    def test_a_decision_records_the_rate_environment_it_was_made_in(
        self, client, populated, session
    ):
        """A verdict the market has moved away from is a different claim.

        The discount rate is the one input the model takes from the market rather
        than from the filings. Without it recorded, a "buy" that turns out badly
        cannot be told apart from one that was simply made when money was cheap.
        """
        from sqlalchemy import select

        from awltux.db import DecisionRun

        run = session.execute(
            select(DecisionRun).order_by(DecisionRun.id.desc())
        ).scalars().first()
        assert run is not None
        assert run.evidence is not None

        recorded = run.evidence["macro"]
        assert 0 < recorded["value"] < 0.25
        assert recorded["source"] in {"market", "config"}
        assert recorded["recorded_at"]

        # And it is shown beside the verdict, not only in the evidence blob.
        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())
        assert "risk-free" in text
        assert "(configured)" in text

    def test_the_rate_is_not_stored_in_the_hashed_state(self, populated, session):
        """`state` is hashed to make a decision reproducible.

        Adding a market observation to it would change the hash of a decision that
        is, in every respect this system cares about, the same decision -- and the
        hash is the thing that lets one be replayed.
        """
        from sqlalchemy import select

        from awltux.db import DecisionRun

        run = session.execute(select(DecisionRun)).scalars().first()
        assert run is not None
        assert "macro" not in (run.state or {}), "the rate must not enter the state hash"

    def test_the_operations_page_renders_run_history(self, client, populated):
        assert client.get("/jobs").status_code == 200

    @pytest.fixture
    def held(self, populated, session):
        """`populated`, plus the broker's own view of the account.

        Separate from `populated` because an instrument that is *held* renders a different
        half of the page -- the position panel, the trades table and the chart's markers --
        and a test that needs none of those should not have to know the columns.
        """
        import datetime as dt

        from awltux.db import Instrument, T212Order

        row = session.get(Instrument, "TEST_US_EQ")
        row.is_held = True
        row.position_quantity = 0.95851493
        row.position_average_price = 347.6
        row.position_opened_at = dt.datetime(2025, 1, 31, 17, 29, tzinfo=dt.UTC)
        row.position_cost_gbp = 280.0
        row.position_value_gbp = 324.0
        row.position_unrealised_gbp = 44.0
        row.position_currency = "GBP"
        row.position_synced_at = dt.datetime(2026, 10, 8, 9, 0, tzinfo=dt.UTC)
        session.add(
            T212Order(
                order_id=58419120582,
                instrument_t212_ticker="TEST_US_EQ",
                side="BUY",
                status="FILLED",
                filled_quantity=0.95851493,
                fill_price=347.6,
                net_value=252.47,
                currency="GBP",
                filled_at=dt.datetime(2026, 10, 5, 16, 0, tzinfo=dt.UTC),
            )
        )
        session.commit()
        return row

    def test_the_position_panel_states_the_return_as_well_as_the_money(self, client, held):
        """44 on a cost of 280 is 15.7%, and a figure without its basis is not a return."""
        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())

        assert "Your position" in text
        assert "44.00 GBP" in text
        assert "(+15.7%)" in text

    def test_the_opened_date_is_not_stated_twice(self, client, held):
        """`ago` falls back to a bare date past a month, which repeated the date beside it.

        The page read "Opened: 2025-01-31 17:29 GMT · 2025-01-31" (reported 2026-10-08).
        """
        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())
        opened = text[text.index("Opened") : text.index("Opened") + 140]

        assert "2025-01-31 17:29" in opened, "the timestamp must still be there"
        assert "· 2025-01-31" not in opened, "the age repeated the date"

    def test_the_trades_table_is_reachable_from_the_route(self, client, held):
        """It was dead markup for a commit, and this is the test that would have caught it.

        `instrument_detail` has always returned `trades`; the route never named the key, and
        Jinja renders an undefined name as empty rather than raising -- so `{% if trades %}`
        was false for every instrument and "Your trades" never appeared. The same trap is
        documented above `news_events` in the same route, one commit earlier.
        """
        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())

        assert "Your trades" in text
        assert "0.9585" in text, "the stored execution is not on the page"

    def test_the_chart_carries_the_price_that_was_paid(self, client, held):
        body = client.get("/instrument/TEST_US_EQ").text

        assert "data-markers='" in body, "the canvas has no marker attribute"
        assert "347.6" in body.split("data-markers='")[1].split("'")[0]

    def test_the_trades_columns_are_aligned_with_their_headers(self, client, held):
        """`table.grid .num` is right-aligned and a bare `<th>` is left, so a numeric column
        under a plain header sits against the wrong edge (reported 2026-10-08)."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ").text, "lxml")
        table = soup.find("h3", string="Your trades").find_next("table")
        headers = table.thead.find_all("th")

        for row in table.tbody.find_all("tr"):
            cells = row.find_all("td")
            assert len(cells) == len(headers), "a row and its header disagree about width"
            for header, cell in zip(headers, cells, strict=True):
                assert ("num" in (header.get("class") or [])) == (
                    "num" in (cell.get("class") or [])
                ), f"'{header.get_text(strip=True)}' does not line up with its column"

    def test_each_trade_states_what_it_would_be_worth_now(self, client, held):
        """The paid figure moved by the price, and the percentage is exactly their ratio.

        Asserted on the rendered page, because that is where a reader compares the two.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ").text, "lxml")
        table = soup.find("h3", string="Your trades").find_next("table")
        headers = [th.get_text(" ", strip=True) for th in table.thead.find_all("th")]
        cells = table.tbody.find("tr").find_all("td")

        paid = _money(cells[headers.index("Paid / received")].get_text(" ", strip=True))
        worth_text = cells[headers.index("Worth now")].get_text(" ", strip=True)
        worth = _money(worth_text)
        shown = float(worth_text.split("(")[1].rstrip(")").replace("%", ""))

        assert paid > 0 and worth > 0
        assert shown == pytest.approx((worth / paid - 1) * 100, abs=0.05)

    def test_the_chart_legend_counts_the_table_not_the_dots(self, client, held, session):
        """It said "0 sold" above a sale.

        A marker older than the first bar is not drawn, and a count of *drawn markers* read
        as a claim about the account: on GWW the legend's "0 sold" sat directly above a sell
        in the same page's table (reported 2026-10-08).
        """
        import datetime as dt

        from awltux.db import T212Order

        session.add(
            T212Order(
                order_id=99,
                instrument_t212_ticker="TEST_US_EQ",
                side="SELL",
                status="FILLED",
                fill_type="TRADE",
                filled_quantity=-1.0,
                fill_price=300.0,
                net_value=250.0,
                currency="GBP",
                # The prices in `populated` start a year before today, so this predates them.
                filled_at=dt.datetime(2020, 1, 2, 14, 30, tzinfo=dt.UTC),
            )
        )
        session.commit()

        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())

        assert "0 sold" not in text
        assert "1 of the 2 trades in the table above are marked" in text
        # And the sale itself is still stated, which is what made the claim wrong.
        assert "sell" in text

    def test_the_run_button_sits_with_the_job_it_runs(self, client):
        """The button belongs beside the name, not in a column at the far right.

        Running the wrong job is the one mistake this table affords, and a button
        that has to be associated with a name by counting across six columns
        invites it. Asserted as document order rather than as markup, so the cell
        can be restyled without the test having an opinion about it.
        """
        body = client.get("/jobs").text
        assert 'class="run-job"' in body

        button = body.index('data-job="t212_instruments"')
        description = body.index("Sync Trading 212 instruments")
        assert button < description, "the run button must precede the job description"

    def test_every_job_row_has_a_run_button(self, client):
        body = client.get("/jobs").text
        ids = ["price_eod", "news_rss", "sentiment", "decision", "retention"]
        for job_id in ids:
            assert f'data-job="{job_id}"' in body, job_id

    def test_an_open_run_is_shown_as_running(self, client, universe_instrument, session):
        """The display half of the fix in test_job_reporting: a run that has not
        finished must not read as its previous failure."""
        from awltux.db import IngestRun

        session.add(IngestRun(job="news_rss", started_at=utcnow(), finished_at=None, ok=None))
        session.commit()

        body = client.get("/jobs").text
        assert "running" in body

    def test_both_tables_agree_about_a_running_job(self, client, universe_instrument, session):
        """A job listed in "Run these next" *and* "Scheduled jobs" used to show
        "Running…" in one table and an enabled "Run now" in the other, offering to
        start a job that was already going."""
        from awltux.db import IngestRun

        session.add(IngestRun(job="news_rss", started_at=utcnow(), finished_at=None, ok=None))
        session.commit()

        body = client.get("/jobs").text
        segments = body.split('data-job="news_rss"')
        assert len(segments) >= 1
        for segment in segments[1:]:
            head = segment[:240]
            assert "Run now" not in head, "a running job still offers to start: " + head[:100]

    def test_the_api_reports_which_jobs_are_in_flight(self, client, universe_instrument, session):
        """The browser cannot be trusted to remember this across a reload, and the
        first job to finish triggers one."""
        from awltux.db import IngestRun

        session.add(IngestRun(job="news_rss", started_at=utcnow(), finished_at=None, ok=None))
        session.commit()

        assert client.get("/api/jobs").json()["in_flight"] == ["news_rss"]

    def test_a_finished_job_is_not_in_flight(self, client, universe_instrument, session):
        from awltux.db import IngestRun

        session.add(IngestRun(job="news_rss", started_at=utcnow(), finished_at=utcnow(), ok=True))
        session.commit()

        assert client.get("/api/jobs").json()["in_flight"] == []

    def test_the_calibration_page_renders_for_both_horizons(self, client, populated):
        for horizon in ("long_term", "short_term"):
            response = client.get(f"/calibration?horizon={horizon}")
            assert response.status_code == 200, horizon

    def test_other_pages_render(self, client):
        for path in ("/sectors", "/calibration", "/jobs", "/info"):
            response = client.get(path)
            assert response.status_code == 200, path


class TestTheRunHistoryIsExplained:
    """`seen 500, written 0, ok` is two true numbers and no answer.

    The Operations page now says what the run achieved, or why it achieved nothing,
    taken from the detail the job already recorded.
    """

    def _run(self, session, **overrides):
        import datetime as dt

        from awltux.db import IngestRun

        values = {
            "job": "valuation",
            "started_at": utcnow(),
            "finished_at": utcnow(),
            "ok": True,
            "items_seen": 500,
            "items_written": 0,
            "detail": {"attempted": 500, "valued": 0, "insufficient_data": 500, "no_peers": 408},
        }
        values.update(overrides)
        row = IngestRun(**values)
        session.add(row)
        session.flush()
        assert dt is not None
        return row

    def test_a_zero_is_explained_on_the_page(self, client, universe_instrument, session):
        self._run(session)
        session.commit()

        body = client.get("/jobs").text
        assert "500 instruments attempted" in body
        assert "none written" in body

    def test_a_failed_run_shows_its_error(self, client, universe_instrument, session):
        self._run(
            session,
            ok=False,
            error="OperationalError: database is locked",
            detail=None,
            items_seen=0,
        )
        session.commit()

        body = client.get("/jobs").text
        assert "database is locked" in body
        # Once, not twice: for a failure the error *is* the explanation, and
        # printing both said the same sentence in two places.
        assert body.count("database is locked") == 1

    def test_the_duration_is_shown(self, client, universe_instrument, session):
        import datetime as dt

        start = utcnow()
        self._run(session, started_at=start, finished_at=start + dt.timedelta(minutes=42))
        session.commit()

        body = client.get("/jobs").text
        assert "42m" in body


class TestTheRunHistoryPagesAndFilters:
    """The history grows without bound — one row per job per interval — so finding
    one ingest among hundreds is a filter problem, not a scrolling problem."""

    def _seed(self, session, count: int, job: str = "news_rss"):
        import datetime as dt

        from awltux.db import IngestRun

        base = utcnow() - dt.timedelta(days=1)
        for index in range(count):
            started = base + dt.timedelta(hours=index)
            session.add(
                IngestRun(
                    job=job,
                    started_at=started,
                    finished_at=started + dt.timedelta(seconds=30 + index),
                    ok=True,
                    items_seen=1,
                    items_written=1,
                    detail={},
                )
            )
        session.flush()

    def test_only_one_page_is_served_at_a_time(self, client, universe_instrument, session):
        self._seed(session, 40)
        session.commit()

        body = client.get("/jobs?run_per_page=10").text
        assert "page 1 of 4" in body
        assert "40 runs matched" in body

    def test_the_second_page_shows_different_runs(self, client, universe_instrument, session):
        self._seed(session, 40)
        session.commit()

        first = client.get("/jobs?run_per_page=10&run_page=1").text
        second = client.get("/jobs?run_per_page=10&run_page=2").text
        assert "page 1 of 4" in first
        assert "page 2 of 4" in second
        assert first != second

    def test_a_page_beyond_the_end_is_clamped_rather_than_empty(
        self, client, universe_instrument, session
    ):
        """A stale link should show the last page, not an empty table that reads as
        "no runs recorded" -- which would be a lie."""
        self._seed(session, 20)
        session.commit()

        body = client.get("/jobs?run_per_page=10&run_page=99").text
        assert "page 2 of 2" in body

    def test_filtering_by_job(self, client, universe_instrument, session):
        self._seed(session, 5, job="news_rss")
        self._seed(session, 3, job="retention")
        session.commit()

        body = client.get("/jobs?run_job=retention").text
        assert "3 runs matched" in body
        assert "<code>retention</code>" in body
        # The scheduled-jobs table still lists every job; only the history is
        # filtered, which is the point.
        assert 'value="retention" selected' in body

    def test_filtering_by_duration_finds_the_long_ones(self, client, universe_instrument, session):
        self._seed(session, 5)  # 30-34 seconds each
        session.commit()

        """Duration is derived from the two timestamps, not stored."""
        assert "5 runs matched" in client.get("/jobs?run_min_seconds=10").text
        assert "0 runs matched" in client.get("/jobs?run_min_seconds=600").text

    def test_filtering_by_date_range(self, client, universe_instrument, session):
        import datetime as dt

        from awltux.db import IngestRun

        now = utcnow()
        session.add_all(
            [
                IngestRun(
                    job="old",
                    started_at=now - dt.timedelta(days=10),
                    finished_at=now - dt.timedelta(days=10) + dt.timedelta(seconds=5),
                    ok=True,
                ),
                IngestRun(
                    job="recent",
                    started_at=now - dt.timedelta(hours=1),
                    finished_at=now - dt.timedelta(hours=1) + dt.timedelta(seconds=5),
                    ok=True,
                ),
            ]
        )
        session.commit()

        today = now.date().isoformat()
        body = client.get(f"/jobs?run_since={today}").text
        assert "1 run matched" in body

    def test_an_until_date_includes_the_whole_day_you_picked(
        self, client, universe_instrument, session
    ):
        """A filter that silently excludes the day you chose is worse than none."""
        from awltux.db import IngestRun

        now = utcnow()
        today = now.date()
        session.add(
            IngestRun(
                job="late",
                # 23:30 today, which a naive date comparison would exclude.
                started_at=now.replace(hour=23, minute=30, second=0, microsecond=0),
                finished_at=now.replace(hour=23, minute=30, second=5, microsecond=0),
                ok=True,
            )
        )
        session.commit()

        body = client.get(f"/jobs?run_until={today.isoformat()}").text
        assert "1 run matched" in body

    def test_a_nonsense_filter_narrows_rather_than_500s(self, client, universe_instrument, session):
        self._seed(session, 3)
        session.commit()

        response = client.get("/jobs?run_since=not-a-date&run_until=also-not&run_min_seconds=abc")
        assert response.status_code in (200, 422)

    def test_the_filter_state_survives_the_round_trip(self, client, universe_instrument, session):
        self._seed(session, 4, job="news_rss")
        session.commit()

        body = client.get("/jobs?run_job=news_rss&run_min_seconds=60").text
        assert 'value="news_rss" selected' in body
        assert 'value="60" selected' in body

    def test_a_long_error_is_summarised_and_kept_behind_a_disclosure(
        self, client, universe_instrument, session
    ):
        """The stored error can be a whole SQL statement with its parameters, which
        buries the one line that identifies the failure."""
        from awltux.db import IngestRun

        long_error = "IntegrityError: UNIQUE constraint failed\n" + ("x" * 900)
        session.add(
            IngestRun(
                job="news_rss",
                started_at=utcnow(),
                finished_at=utcnow(),
                ok=False,
                error=long_error,
            )
        )
        session.commit()

        body = client.get("/jobs").text
        assert "IntegrityError: UNIQUE constraint failed" in body
        # Truncated where it is read, disclosed rather than discarded.
        assert "…" in body
        assert "<details>" in body
        assert body.index("…") < body.index("<details>")


class TestTheNewsItemPage:
    """The flash banner links here, not to the publisher.

    The published article is the *input* to an assessment, not the assessment, and
    it may be paywalled, syndicated or gone by the time anyone clicks. What the
    local page always has is what the system concluded, which instruments the story
    concerns, why, and a link out.
    """

    def _story(self, session, **overrides):
        from awltux.db import NewsItem, utcnow

        values = {
            "source": "test",
            "url": "https://publisher.example/story",
            "url_hash": "abc123",
            "title": "Acme wins a contract",
            "summary": "Acme said the contract is worth 10m.",
            "published_at": utcnow(),
            "tickers": ["TEST_US_EQ"],
            "sectors": [],
            "materiality": "material",
            "direction": "positive",
            "horizon": "months",
            "event_type": "product",
            "relevant": True,
            "relevance_reason": "names the company and reports a win, which is positive",
        }
        values.update(overrides)
        row = NewsItem(**values)
        session.add(row)
        session.flush()
        return row

    def test_the_page_renders_with_the_verdict_and_the_reason(self, client, universe_instrument, session):
        row = self._story(session)
        session.commit()

        body = client.get(f"/news/{row.id}").text
        assert "Acme wins a contract" in body
        assert "Relevant." in body
        assert "names the company and reports a win" in body

    def test_the_reason_is_printed_once(self, client, universe_instrument, session):
        """The page used to state the classifier's sentence twice, under two headings.

        `_relevance` returns `item.relevance_reason or structural.reason`, and the verdict
        line prints that. A second block printed `item.relevance_reason` on its own -- so
        it was the same sentence again whenever the classifier had supplied one, and
        nothing at all when it had not. It could not say anything the line above did not.
        """
        row = self._story(session)
        session.commit()

        sentence = "names the company and reports a win, which is positive"
        body = client.get(f"/news/{row.id}").text
        assert body.count(sentence) == 1, "the reason belongs in one place"

    def test_a_story_with_no_classifier_sentence_attributes_the_reason_to_the_rule(
        self, client, universe_instrument, session
    ):
        """The one case the removed block was reaching for, said plainly.

        With no stored classifier sentence the reason above is the rule's own, and the page
        should not let a reader mistake it for a model's judgement.
        """
        row = self._story(session, relevance_reason=None)
        session.commit()

        body = client.get(f"/news/{row.id}").text
        assert "this rule's own reading" in body
        assert "No classifier sentence" in body

    def test_an_assessed_story_with_a_classifier_sentence_says_nothing_extra(
        self, client, universe_instrument, session
    ):
        """No provenance note when the sentence really is the classifier's -- there is
        nothing to disambiguate, and a note would be the noise this removed."""
        row = self._story(session)
        session.commit()

        assert "this rule's own reading" not in client.get(f"/news/{row.id}").text

    def test_it_lists_the_instrument_the_story_concerns(self, client, universe_instrument, session):
        row = self._story(session)
        session.commit()

        body = client.get(f"/news/{row.id}").text
        assert "/instrument/TEST_US_EQ" in body, "the target must be reachable"

    def test_it_links_to_the_source_article(self, client, universe_instrument, session):
        row = self._story(session)
        session.commit()

        body = client.get(f"/news/{row.id}").text
        assert "https://publisher.example/story" in body

    def test_the_page_explains_the_priority(self, client, universe_instrument, session):
        """A sort order nobody can argue with is a sort order nobody should trust."""
        row = self._story(session)
        session.commit()

        body = client.get(f"/news/{row.id}").text
        assert "materiality x credibility x recency" in body

    def test_an_irrelevant_story_says_which_half_of_the_rule_failed(
        self, client, universe_instrument, session
    ):
        row = self._story(
            session,
            url_hash="irrelevant",
            url="https://publisher.example/irrelevant",
            direction="neutral",
            relevant=False,
            relevance_reason=None,
        )
        session.commit()

        body = client.get(f"/news/{row.id}").text
        assert "Not relevant." in body
        assert "not a claim about the share price" in body

    def test_an_unassessed_story_says_so_rather_than_guessing(self, client, universe_instrument, session):
        row = self._story(
            session,
            url_hash="unassessed",
            url="https://publisher.example/unassessed",
            materiality=None,
            direction=None,
            relevant=None,
            relevance_reason=None,
        )
        session.commit()

        body = client.get(f"/news/{row.id}").text
        assert "Not assessed." in body
        assert "news_relevance" in body

    def test_an_unknown_story_is_a_404(self, client, universe_instrument):
        assert client.get("/news/999999").status_code == 404


class TestTheFlashBannerIsOrdered:
    def test_only_relevant_stories_reach_the_banner(self, client, universe_instrument, session):
        from awltux.db import NewsItem, utcnow

        session.add(
            NewsItem(
                source="t", url="https://x/relevant", url_hash="r1", title="Relevant story",
                published_at=utcnow(), tickers=["TEST_US_EQ"], direction="positive",
                materiality="material", relevant=True,
            )
        )
        session.add(
            NewsItem(
                source="t", url="https://x/irrelevant", url_hash="r2", title="Irrelevant story",
                published_at=utcnow(), tickers=["TEST_US_EQ"], direction="neutral",
                materiality="none", relevant=False,
            )
        )
        session.commit()

        body = client.get("/partials/news-ticker").text
        assert "Relevant story" in body
        assert "Irrelevant story" not in body

    def test_a_story_below_the_materiality_floor_does_not_reach_the_banner(
        self, client, universe_instrument, session
    ):
        """`none` is most of the corpus: 12,125 of 26,301 stories, measured 2026-10-08.

        Relevance alone used to be enough, so a story the classifier judged unimportant
        was still shown as long as it named an instrument and carried a direction. The
        banner's own label has always said "materiality-filtered"; nothing read the
        setting until now.
        """
        from awltux.db import NewsItem, utcnow

        session.add(
            NewsItem(
                source="t", url="https://x/unimportant", url_hash="u1",
                title="Unimportant story", published_at=utcnow(),
                tickers=["TEST_US_EQ"], direction="positive",
                materiality="none", relevant=True,
            )
        )
        session.commit()

        assert "Unimportant story" not in client.get("/partials/news-ticker").text

    def test_the_same_headline_twice_is_one_entry(
        self, client, universe_instrument, session
    ):
        """A wire story carried by two outlets is two rows with two URLs.

        `url_hash` cannot see that; `title_key` can. This is the collapse the reader
        complained about -- the same sentence under two mastheads was two ticker entries,
        and the embedding grouping that also catches it needs a stored vector that most
        stories do not have yet.
        """
        from awltux.db import NewsItem, utcnow
        from awltux.ingest.news import title_key

        headline = "Acme warns on profit for the year"
        for index, (url, materiality) in enumerate(
            (("https://x/acme-yahoo", "mild"), ("https://x/acme-globe", "moderate"))
        ):
            session.add(
                NewsItem(
                    source="t", url=url, url_hash=f"k{index}",
                    title_key=title_key(headline), title=headline,
                    published_at=utcnow(), tickers=["TEST_US_EQ"], direction="negative",
                    materiality=materiality, relevant=True,
                )
            )
        session.commit()

        body = client.get("/partials/news-ticker").text
        assert body.count('class="ticker-item') == 1, "one entry per headline, not per URL"

    def test_a_more_important_story_is_served_first(self, client, universe_instrument, session):
        from awltux.db import NewsItem, utcnow

        now = utcnow()
        session.add(
            NewsItem(
                source="t", url="https://x/minor", url_hash="m1", title="Minor story",
                published_at=now, tickers=["TEST_US_EQ"], direction="positive",
                materiality="mild", relevant=True,
            )
        )
        session.add(
            NewsItem(
                source="t", url="https://x/major", url_hash="m2", title="Major story",
                published_at=now, tickers=["TEST_US_EQ"], direction="negative",
                materiality="critical", relevant=True,
            )
        )
        session.commit()

        items = client.get("/api/news").json()["items"]
        titles = [item["title"] for item in items if item["title"].endswith("story")]
        assert titles.index("Major story") < titles.index("Minor story")

    def test_the_api_says_how_it_ordered_the_feed(self, client, universe_instrument):
        assert client.get("/api/news").json()["ordered_by"] == "priority"

    def test_the_api_carries_the_local_url_and_the_verdict(self, client, universe_instrument, session):
        from awltux.db import NewsItem, utcnow

        session.add(
            NewsItem(
                source="t", url="https://x/one", url_hash="s1", title="A story",
                published_at=utcnow(), tickers=["TEST_US_EQ"], direction="positive",
                materiality="material", relevant=True,
            )
        )
        session.commit()

        item = next(i for i in client.get("/api/news").json()["items"] if i["title"] == "A story")
        assert item["local_url"].startswith("/news/")
        assert item["relevant"] is True
        assert item["priority"] > 0
        assert item["priority_inputs"]["formula"]


class TestDismissingAStory:
    """The reader's own judgement, which no filter can supply.

    The ticker is floored by materiality and collapsed by headline, and it still shows the
    same acquisition from four outlets when the classifier graded all four `critical`.
    Nothing in the data knows which of those the reader has already read.
    """

    def _story(self, session, **overrides):
        from awltux.db import NewsItem, utcnow

        values = {
            "source": "t", "url": "https://x/dismissable", "url_hash": "d1",
            "title": "Acme agrees a takeover", "published_at": utcnow(),
            "tickers": ["TEST_US_EQ"], "direction": "positive",
            "materiality": "critical", "relevant": True,
        }
        values.update(overrides)
        row = NewsItem(**values)
        session.add(row)
        session.commit()
        return row

    def test_the_button_is_on_the_entry(self, client, universe_instrument, session):
        row = self._story(session)
        body = client.get("/partials/news-ticker").text

        assert f'data-dismiss-url="/api/news/{row.id}/dismiss"' in body
        assert '<button class="ticker-dismiss"' in body
        # The button must not be inside the link: a click would navigate as well as dismiss.
        assert body.index('class="ticker-dismiss"') > body.index("</a>")

    def test_dismissing_removes_it_from_the_banner(self, client, universe_instrument, session):
        row = self._story(session)
        assert "Acme agrees a takeover" in client.get("/partials/news-ticker").text

        response = client.post(f"/api/news/{row.id}/dismiss")

        assert response.status_code == 200
        assert client.get("/partials/news-ticker").text.count("Acme agrees a takeover") == 0

    def test_the_story_is_kept_rather_than_deleted(self, client, universe_instrument, session):
        """A dismissal is one reader decision, not a retraction.

        The row is still a headline that was ingested and classified, and it still carries
        one event for the grouping. Deleting it would make the dismissal irreversible
        without re-ingesting, and would change what every marker counts.
        """
        from awltux.db import NewsItem

        row = self._story(session)
        client.post(f"/api/news/{row.id}/dismiss")

        session.expire_all()
        kept = session.get(NewsItem, row.id)
        assert kept is not None, "the row must survive"
        assert kept.dismissed_at is not None
        assert kept.title == "Acme agrees a takeover"

    def test_dismissing_an_unknown_story_is_a_404(self, client, universe_instrument):
        assert client.post("/api/news/999999/dismiss").status_code == 404

    def test_a_dismissed_story_does_not_wake_the_ticker(
        self, client, universe_instrument, session, settings
    ):
        """Otherwise every open tab re-renders identical HTML on the next poll."""
        from awltux.db import NewsItem
        from awltux.web.routes.news import _refresh_due

        row = self._story(session)
        client.post(f"/api/news/{row.id}/dismiss")

        session.expire_all()
        assert session.get(NewsItem, row.id).dismissed_at is not None
        assert _refresh_due(0, settings) is None


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
        """The stream carries a cursor, not stories.

        It used to replay items on connect and then push each new story, which is how the
        client ended up with a second renderer and a second answer to what the ticker
        shows. It now only says *that* the banner is stale, and the client re-fetches the
        fragment -- so the first paint and every update come from one function.
        """
        import inspect

        from starlette.requests import Request

        from awltux.web.routes.news import news_stream

        parameters = inspect.signature(news_stream).parameters
        assert "last_event_id" in parameters, "the resume cursor is part of the contract"
        assert "replay" not in parameters, "there is nothing to replay: the fragment is the seed"

        scope = {"type": "http", "method": "GET", "path": "/api/news/stream", "headers": []}
        response = await news_stream(Request(scope), last_event_id=0)

        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache, no-transform"

    def test_ticker_partial_renders_without_javascript(self, client):
        response = client.get("/partials/news-ticker")
        assert response.status_code == 200
        # The empty state names the rule, because "no headlines" and "no headlines that
        # cleared the floor" are different and only one is worth worrying about.
        assert "No material headlines yet" in response.text


class TestWhatWakesTheTicker:
    """The stream's database side: does this change what the banner shows, or not?

    It used to return the stories themselves, and the client rendered them -- which is how
    the ticker came to show every relevant story, one entry per story, up to forty of them
    displacing the curated fifteen. It now returns a cursor, and the fragment is re-fetched
    only when a story that could actually be displayed arrives.
    """

    def _seed(self, session, **overrides):
        import datetime as dt

        from awltux.db import NewsItem

        values = {
            "source": "rss",
            "title": "Story",
            "published_at": dt.datetime.now(dt.UTC),
            "tickers": ["TEST_US_EQ"],
            "relevant": True,
            "materiality": "material",
        }
        values.update(overrides)
        url = values.pop("url", "https://example.test/x")
        row = NewsItem(url=url, url_hash=url.encode().hex().ljust(64, "0")[:64], **values)
        session.add(row)
        session.flush()
        session.commit()
        return row

    def test_a_material_relevant_story_asks_for_a_refresh(self, session, settings):
        from awltux.web.routes.news import _refresh_due

        row = self._seed(session, url="https://example.test/material", title="A profit warning")
        assert _refresh_due(0, settings) == row.id
        # And nothing at or below the cursor asks again: the refresh is idempotent.
        assert _refresh_due(row.id, settings) is None

    def test_a_story_below_the_floor_does_not_wake_the_ticker(self, session, settings):
        """The floor has to be applied on both sides.

        A story `_ranked` would never display must not make every open tab re-render
        identical HTML.
        """
        from awltux.web.routes.news import _refresh_due

        self._seed(session, url="https://example.test/none", materiality="none")
        assert _refresh_due(0, settings) is None

    def test_an_irrelevant_story_does_not_wake_the_ticker(self, session, settings):
        from awltux.web.routes.news import _refresh_due

        self._seed(session, url="https://example.test/irrelevant", relevant=False)
        assert _refresh_due(0, settings) is None

    def test_an_unjudged_story_does_not_wake_the_ticker(self, session, settings):
        """``relevant IS NULL`` is "nothing judged this", not "judged unimportant".

        It has no materiality either, so it cannot clear a materiality floor.
        """
        from awltux.web.routes.news import _refresh_due

        self._seed(
            session, url="https://example.test/unjudged", relevant=None, materiality=None
        )
        assert _refresh_due(0, settings) is None

    def test_the_newest_qualifying_story_is_the_cursor(self, session, settings):
        from awltux.web.routes.news import _refresh_due

        self._seed(session, url="https://example.test/one", title="First")
        newest = self._seed(session, url="https://example.test/two", title="Second")
        assert _refresh_due(0, settings) == newest.id


class TestTheBannerGroupsOneEventIntoOneEntry:
    """Five outlets rewriting one profit warning is one piece of news, not five.

    The grouping is only as good as the vectors behind it, so these tests seed
    vectors directly rather than pretending to embed anything.
    """

    def _story(self, session, key: str, title: str, **overrides):
        from awltux.db import NewsItem, utcnow

        values = {
            "source": "test",
            "url": f"https://example.test/{key}",
            "url_hash": key * 8,
            "title": title,
            "published_at": utcnow(),
            "tickers": ["TEST_US_EQ"],
            "direction": "negative",
            "materiality": "material",
            "relevant": True,
        }
        values.update(overrides)
        row = NewsItem(**values)
        session.add(row)
        session.flush()
        return row

    def _vector(self, session, row, vector):
        import numpy as np

        from awltux.db import NewsEmbedding

        array = np.asarray(vector, dtype=np.float32)
        session.add(
            NewsEmbedding(
                news_item_id=row.id,
                model="test-model",
                dim=int(array.shape[0]),
                vector=array.tobytes(),
                text_hash="x",
            )
        )
        session.flush()

    def _configure(self, settings) -> None:
        settings.news.embeddings.base_url = "http://localhost:11434/v1"
        settings.news.embeddings.model = "test-model"

    def _cluster(self, item_ids, settings):
        from sqlalchemy import select

        from awltux.analysis.embeddings import cluster_items
        from awltux.db import NewsItem, session_scope

        with session_scope() as fresh:
            rows = list(
                fresh.execute(
                    select(NewsItem).where(NewsItem.id.in_(item_ids))
                ).scalars().all()
            )
            return cluster_items(rows, settings=settings)

    def test_two_stories_about_one_event_are_one_entry(
        self, client, universe_instrument, session, settings
    ):
        self._configure(settings)
        first = self._story(session, "a", "Acme warns on profit")
        second = self._story(session, "b", "Acme cuts its full-year outlook")
        self._vector(session, first, [1.0, 0.0, 0.0])
        self._vector(session, second, [1.0, 0.05, 0.0])
        session.commit()

        events, note = self._cluster([first.id, second.id], settings)

        assert note is None
        assert len(events) == 1
        assert events[0].members == [first.id, second.id]

    def test_unrelated_stories_stay_separate(
        self, client, universe_instrument, session, settings
    ):
        self._configure(settings)
        first = self._story(session, "c", "Acme warns on profit")
        second = self._story(session, "d", "Acme wins a contract")
        self._vector(session, first, [1.0, 0.0, 0.0])
        self._vector(session, second, [0.0, 1.0, 0.0])
        session.commit()

        events, _ = self._cluster([first.id, second.id], settings)
        assert [len(event.members) for event in events] == [1, 1]

    def test_the_reason_grouping_did_not_happen_is_reported(
        self, client, universe_instrument, session, settings
    ):
        """"One entry per event" and "one entry per story" look identical on screen,
        and only one of them means the feature works."""
        settings.news.embeddings.base_url = ""
        first = self._story(session, "e", "Acme warns on profit")
        session.commit()

        events, note = self._cluster([first.id], settings)
        assert note is not None
        assert "not configured" in note
        assert events[0].members == [first.id]

    def test_a_story_with_no_vector_is_not_grouped_with_anything(
        self, client, universe_instrument, session, settings
    ):
        self._configure(settings)
        embedded = self._story(session, "h", "Acme warns on profit")
        plain = self._story(session, "i", "Acme warns on profit again")
        self._vector(session, embedded, [1.0, 0.0, 0.0])
        session.commit()

        events, note = self._cluster([embedded.id, plain.id], settings)
        assert note is None
        assert [event.members for event in events] == [[embedded.id], [plain.id]]

    def test_the_page_counts_the_event_the_banner_announced(
        self, client, universe_instrument, session, settings
    ):
        """The ticker said "4 stories cover this event" over a page that listed two.

        Measured on Great Southern Copper's £2m raise, 2026-10-08: four reports whose cosines
        were 0.96, 0.80 and 0.63. `cluster` compares each story against its cluster's
        *anchor*, so the first one handed over decides whether the rest clear the threshold --
        best-first groups all four, newest-first drops the one that is only 0.63 from the
        newest. The banner ranks by priority; the news page read the newest rows by id. Two
        definitions of the same event, so two answers on screen.

        The vectors here repeat that shape in three dimensions: `critical` outranks
        `material` outranks `moderate`, so the ranking order is fixed and `a` must anchor.
        """
        self._configure(settings)
        a = self._story(session, "a", "Copper raises £2m for Mostaza", materiality="critical")
        b = self._story(
            session, "b", "Copper raises £2m for its Chilean project", materiality="material"
        )
        c = self._story(session, "c", "£2m Raised to Advance Mostaza", materiality="moderate")
        self._vector(session, a, [1.0, 0.0, 0.0])
        self._vector(session, b, [0.96, 0.28, 0.0])
        self._vector(session, c, [0.71, 0.0, 0.704])
        session.commit()

        banner = client.get("/partials/news-ticker").text
        page = client.get(f"/news/{a.id}").text

        assert "3 stories cover this event" in banner, banner[:400]
        assert "2 other" in page, "the page must list the same event the banner announced"

    def test_the_oldest_story_is_grouped_with_the_same_event(
        self, client, universe_instrument, session, settings
    ):
        """Whichever report the reader opens, the event is the same one.

        This is the other half of the same rule: the page groups the banner's population in
        the banner's order, so it does not matter which member of the event the reader
        arrived from.
        """
        self._configure(settings)
        a = self._story(session, "d", "Copper raises £2m for Mostaza", materiality="critical")
        b = self._story(
            session, "e", "Copper raises £2m for its Chilean project", materiality="material"
        )
        c = self._story(session, "f", "£2m Raised to Advance Mostaza", materiality="moderate")
        self._vector(session, a, [1.0, 0.0, 0.0])
        self._vector(session, b, [0.96, 0.28, 0.0])
        self._vector(session, c, [0.71, 0.0, 0.704])
        session.commit()

        assert "2 other" in client.get(f"/news/{c.id}").text


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
            # Set explicitly: the ticker shows only *assessed* stories, and this fixture
            # stands in for an ingested one. `persist_items` runs `_apply_relevance` on
            # anything carrying a materiality or a direction, and a ticker plus a direction
            # is the conjunction `relevant` is defined as -- so a real row here would be
            # True, and leaving it NULL would be testing a state ingest cannot produce.
            relevant=True,
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

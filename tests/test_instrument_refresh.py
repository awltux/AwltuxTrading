"""Refreshing one instrument: the lease, the sequence, and the button.

The feature exists because a call can be shown for a company most of whose inputs have
never been fetched, and the reader's question is *what would you say if you actually had
the data?*. What these tests protect:

* **The lease is a lease.** Held while a refresh runs, expired rather than permanent when
  a process dies, and taken over rather than respected once it has. A lock that never
  expires removes an instrument from every sweep for ever; one that is respected after
  expiry lets two refreshes write the same rows.
* **The sequence is derived from the declared pipeline.** `JobSpec.depends_on` already
  says what runs before what; a second hand-written order would agree today and disagree
  after the next job is added, and it would fail as a wrong answer rather than an error.
  The two declared overrides are asserted as overrides.
* **The button does not run a pipeline in the request.** It starts a thread and returns,
  so a refresh that takes minutes does not leave the browser with an abandoned request.
"""

from __future__ import annotations

import datetime as dt
import time

from awltux.ingest import lease
from awltux.ingest.lease import acquire
from awltux.scheduler.jobs import JobResult
from tests.helpers import make_instrument


def _seed(session, ticker: str = "TEST_US_EQ", **overrides) -> None:
    overrides.setdefault("sec_cik", "0000000001")
    session.add(make_instrument(ticker, **overrides))
    session.flush()


class TestTheLease:
    def test_taking_it_twice_gives_the_second_caller_nothing(self, session):
        """The whole point: one refresh per instrument, and the refusal is ordinary."""
        _seed(session)

        first = acquire(session, "TEST_US_EQ")
        second = acquire(session, "TEST_US_EQ")

        assert first is not None
        assert second is None

    def test_a_held_lease_is_reported_as_locked(self, session):
        _seed(session)
        acquire(session, "TEST_US_EQ")

        assert lease.locked_tickers(session) == {"TEST_US_EQ"}

    def test_releasing_it_frees_the_instrument(self, session):
        _seed(session)
        row = acquire(session, "TEST_US_EQ")

        lease.release(session, "TEST_US_EQ", token=row.token, state="done")
        session.commit()

        assert lease.locked_tickers(session) == set()
        assert acquire(session, "TEST_US_EQ") is not None

    def test_only_the_holder_may_release(self, session):
        """A refresh whose TTL expired must not unlock the run that replaced it."""
        _seed(session)
        row = acquire(session, "TEST_US_EQ")

        lease.release(session, "TEST_US_EQ", token="not-the-token", state="done")
        session.commit()

        assert lease.locked_tickers(session) == {"TEST_US_EQ"}
        assert row.token != "not-the-token"

    def test_an_expired_lease_is_taken_over_rather_than_respected(self, session):
        """Otherwise a killed container removes the instrument from every sweep for ever.

        The tokens are compared as strings taken *before* the second acquisition: the row
        is one ORM object, so a second `acquire` rewrites the token on the object the
        first call returned, and comparing the objects would compare a thing to itself.
        """
        _seed(session)
        past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
        first = acquire(session, "TEST_US_EQ", now=past).token

        second = acquire(session, "TEST_US_EQ").token

        assert second is not None
        assert second != first

    def test_an_expired_lease_is_not_reported_as_locked(self, session):
        _seed(session)
        past = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
        acquire(session, "TEST_US_EQ", now=past)

        assert lease.locked_tickers(session) == set()

    def test_a_heartbeat_renews_and_is_visible_to_others(self, session):
        """Committed, not merely remembered: the other process is the reader that matters."""
        _seed(session)
        token = acquire(
            session, "TEST_US_EQ", now=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=25)
        ).token

        assert lease.heartbeat(session, "TEST_US_EQ", token=token) is True

        session.commit()
        assert lease.locked_tickers(session) == {"TEST_US_EQ"}

    def test_a_heartbeat_after_a_takeover_reports_that_it_lost(self, session):
        """So the old refresh stops instead of writing under a lock it no longer holds."""
        _seed(session)
        stale = acquire(session, "TEST_US_EQ").token
        winner = acquire(
            session, "TEST_US_EQ", now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
        )

        assert winner is not None
        assert lease.heartbeat(session, "TEST_US_EQ", token=stale) is False

    def test_stale_rows_are_marked_expired_rather_than_left_running(self, session):
        """A reader is shown `state`, and a stale "running" reads as a hung job."""
        _seed(session)
        acquire(session, "TEST_US_EQ", now=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2))

        assert lease.expire_stale(session) == 1
        session.commit()

        assert lease.current(session, "TEST_US_EQ").state == lease.EXPIRED

    def test_a_step_is_recorded_against_the_holder_only(self, session):
        _seed(session)
        row = acquire(session, "TEST_US_EQ")

        lease.record_step(
            session, "TEST_US_EQ", token=row.token, step="prices", note="4 bars", ok=True
        )
        lease.record_step(
            session, "TEST_US_EQ", token="someone-else", step="news", note="nope", ok=False
        )
        session.commit()

        steps = lease.current(session, "TEST_US_EQ").steps
        assert [entry["step"] for entry in steps] == ["prices"]


class TestExcludingTheLockedInstrument:
    def test_a_sweep_selection_leaves_the_locked_instrument_out(self, session):
        """The requirement, at the one line every sweep needs.

        `decision` is the sharpest case because it slices an in-memory list by `limit`
        afterwards -- so a check placed after the load would still spend one of the
        sweep's slots on an instrument it must not touch, and the next instrument in
        line would not get its turn.
        """
        from sqlalchemy import select

        from awltux.db import Instrument

        _seed(session, "LOCKED_US_EQ")
        _seed(session, "FREE_US_EQ")
        acquire(session, "LOCKED_US_EQ")

        statement = lease.exclude_locked(select(Instrument), session)

        assert {row.t212_ticker for row in session.execute(statement).scalars()} == {
            "FREE_US_EQ"
        }

    def test_nothing_locked_leaves_the_selection_alone(self, session):
        """A no-op when nothing is held, which is almost always."""
        from sqlalchemy import select

        from awltux.db import Instrument

        _seed(session, "ONE_US_EQ")
        _seed(session, "TWO_US_EQ")

        statement = lease.exclude_locked(select(Instrument), session)

        assert len(session.execute(statement).scalars().all()) == 2

    def test_the_price_targets_skip_a_locked_instrument(self, session):
        """Through the real selection, not just the helper."""
        from awltux.ingest.prices import load_price_targets

        _seed(session, "LOCKED_US_EQ", yahoo_symbol="LOCKED")
        _seed(session, "FREE_US_EQ", yahoo_symbol="FREE")
        acquire(session, "LOCKED_US_EQ")
        session.commit()

        targets = load_price_targets(session)

        assert targets.symbols == ["FREE"]

    def test_a_scoped_price_load_is_not_filtered_by_the_lease(self, session):
        """The refresh *is* the holder, so filtering it out would refuse to work."""
        from awltux.ingest.prices import load_price_targets

        _seed(session, "LOCKED_US_EQ", yahoo_symbol="LOCKED")
        acquire(session, "LOCKED_US_EQ")
        session.commit()

        assert load_price_targets(session, only=["LOCKED_US_EQ"]).symbols == ["LOCKED"]

    def test_a_story_is_locked_when_any_of_its_instruments_is(self, session):
        """The JSON list, where there is no column to narrow on."""
        assert lease.touches_locked(["A_US_EQ", "B_US_EQ"], {"B_US_EQ"}) is True
        assert lease.touches_locked(["A_US_EQ"], {"B_US_EQ"}) is False
        assert lease.touches_locked(None, {"B_US_EQ"}) is False
        assert lease.touches_locked(["A_US_EQ"], set()) is False

    def test_the_filings_sweep_never_asks_the_provider_about_a_locked_instrument(
        self, session, settings
    ):
        """Through the real selection. The provider call is the cost this saves, so the
        assertion is on the CIKs asked for rather than on a row count."""
        from awltux.ingest.edgar import sync_filings

        _seed(session, "FREE_US_EQ", sec_cik="0000000002")
        _seed(session, "LOCKED_US_EQ", sec_cik="0000000001")
        acquire(session, "LOCKED_US_EQ")
        session.commit()
        asked: list[str] = []

        class Provider:
            def get_recent_filings(self, cik, *, limit: int = 40):
                asked.append(str(cik))
                return []

            def get_sic(self, cik):
                return None, None

        sync_filings(session, settings=settings, provider=Provider())

        assert asked == ["0000000002"]

    def test_the_report_download_skips_a_locked_instrument(self, session, settings):
        """Both halves of `shareholder_reports`: the discovery walk and the download. The
        download half is the one that writes `Filing.raw_path`, so it is the sharper of
        the two -- the query carries `Filing.instrument_t212_ticker`, not `Instrument`."""
        from awltux.db import Filing
        from awltux.ingest.documents import deepen_annual_history, pending_annual_reports

        _seed(session, "FREE_US_EQ", sec_cik="0000000002")
        _seed(session, "LOCKED_US_EQ", sec_cik="0000000001")
        for ticker in ("FREE_US_EQ", "LOCKED_US_EQ"):
            session.add(
                Filing(
                    instrument_t212_ticker=ticker,
                    source="edgar",
                    filing_type="10-K",
                    url=f"https://sec.test/{ticker}.htm",
                    status="pending",
                )
            )
        acquire(session, "LOCKED_US_EQ")
        session.commit()
        asked: list[str] = []

        class Provider:
            def get_annual_filings(self, cik, *, since, limit: int = 6):
                asked.append(str(cik))
                return []

        deepen_annual_history(session, settings=settings, provider=Provider())
        queued = pending_annual_reports(session)

        assert asked == ["0000000002"]
        assert [row.instrument_t212_ticker for row in queued] == ["FREE_US_EQ"]

    def test_the_uk_walk_never_asks_about_a_locked_instrument(self, session, settings):
        from awltux.ingest.fundamentals import resolve_uk_companies

        _seed(
            session,
            "FREE_US_EQ",
            exchange_name="LSE",
            yahoo_symbol="FREE.L",
            ch_company_number=None,
        )
        _seed(
            session,
            "LOCKED_US_EQ",
            exchange_name="LSE",
            yahoo_symbol="LOCKED.L",
            ch_company_number=None,
        )
        acquire(session, "LOCKED_US_EQ")
        session.commit()
        asked: list[str] = []

        class Provider:
            configured = True

            def search_companies(self, name: str, **kwargs):
                asked.append(name)
                return []

        resolve_uk_companies(session, settings=settings, provider=Provider())

        assert asked == ["Apple Inc"]

    def test_the_sentiment_sweep_leaves_the_locked_instrument_out(self, session, settings):
        """No news and no bars, so nothing is written -- but the *count* is the instrument
        list the sweep built, and that is what the lease narrows."""
        from awltux.analysis.sentiment import aggregate_all

        _seed(session, "FREE_US_EQ")
        _seed(session, "LOCKED_US_EQ")
        acquire(session, "LOCKED_US_EQ")
        session.commit()

        stats = aggregate_all(session, settings=settings, tickers=None)

        assert stats["instruments_seen"] == 1

    def test_the_appraisal_sweep_skips_a_locked_instrument_story(self, session, settings):
        """Through `analyse_universe`, whose selection is a news window rather than an
        instrument query -- so the instrument list is a JSON column and the filter is a
        predicate over what was loaded."""
        from awltux.analysis import news_analysis
        from awltux.db import NewsItem

        _seed(session, "FREE_US_EQ")
        _seed(session, "LOCKED_US_EQ")
        session.add(
            NewsItem(
                source="test",
                url="https://news.test/free",
                url_hash="free",
                title="Free Co wins a contract",
                published_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
                tickers=["FREE_US_EQ"],
                sectors=[],
                direction="positive",
                materiality="high",
            )
        )
        session.add(
            NewsItem(
                source="test",
                url="https://news.test/locked",
                url_hash="locked",
                title="Locked Co wins a contract",
                published_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
                tickers=["LOCKED_US_EQ"],
                sectors=[],
                direction="positive",
                materiality="high",
            )
        )
        acquire(session, "LOCKED_US_EQ")
        session.commit()

        report = news_analysis.analyse_universe(session, settings=settings)

        assert report["examined"] == 1, "the locked story is not even examined"

    def test_the_relevance_backfill_skips_a_locked_instrument_story(self, session, monkeypatch):
        """Through the job, which opens its own session -- so the row has to be committed
        before it runs, for the reason `AGENTS.md` gives about page tests."""
        from awltux.db import NewsItem
        from awltux.ingest import jobs

        _seed(session, "FREE_US_EQ")
        _seed(session, "LOCKED_US_EQ")
        session.add(
            NewsItem(
                source="test",
                url="https://news.test/free",
                url_hash="free",
                title="Free Co wins a contract",
                published_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
                tickers=["FREE_US_EQ"],
                sectors=[],
                direction="positive",
                materiality="high",
            )
        )
        session.add(
            NewsItem(
                source="test",
                url="https://news.test/locked",
                url_hash="locked",
                title="Locked Co wins a contract",
                published_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
                tickers=["LOCKED_US_EQ"],
                sectors=[],
                direction="positive",
                materiality="high",
            )
        )
        acquire(session, "LOCKED_US_EQ")
        session.commit()

        jobs.assess_news_relevance()

        session.expire_all()
        verdicts = {
            item.url_hash: item.relevant
            for item in session.query(NewsItem).all()
        }
        assert verdicts["free"] is True
        assert verdicts["locked"] is None


class TestTheSequence:
    def test_it_contains_the_pipeline_stages_that_need_a_company(self):
        from awltux.ingest import refresh

        assert set(refresh.step_ids()) == {
            "symbol_resolution",
            "price_eod",
            "filings_edgar",
            "shareholder_reports",
            "document_parsing",
            "xbrl_statements",
            "fundamentals",
            "uk_companies",
            "news_rss",
            "news_relevance",
            "news_analysis",
            "sentiment",
            "valuation",
            "decision",
        }

    def test_it_excludes_the_global_and_housekeeping_jobs(self):
        """A scoped run cannot fetch one instrument's universe membership."""
        from awltux.ingest import refresh

        assert not {
            "t212_instruments",
            "universe_refresh",
            "macro_rates",
            "price_intraday",
            "edgar_events",
            "calibration",
            "retention",
        } & set(refresh.step_ids())

    def test_the_order_agrees_with_the_declared_dependencies(self):
        """Derived from `depends_on`, so a new job cannot leave this list stale.

        Checked as "every declared dependency of a step appears before it", which is the
        property that matters, rather than against one exact ordering -- `dependency_order`
        breaks ties by declaration order and a reshuffle of the registry is not a bug.
        """
        from awltux.ingest import refresh
        from awltux.scheduler.registry import build_job_specs

        declared = {spec.id: spec.depends_on for spec in build_job_specs()}
        order = list(refresh.step_ids())

        for job in order:
            if job in refresh.OVERRIDES:
                continue
            for dependency in declared.get(job, ()):
                if dependency in order:
                    assert order.index(dependency) < order.index(job), (
                        f"{job} needs {dependency}, which runs after it"
                    )

    def test_the_overrides_are_at_the_front_and_are_declared(self):
        """The declared exception, asserted as one so it cannot quietly grow."""
        from awltux.ingest import refresh

        order = list(refresh.step_ids())

        assert order[:2] == ["symbol_resolution", "price_eod"]
        assert refresh.OVERRIDES == ("symbol_resolution", "price_eod")

    def test_document_parsing_follows_the_download_and_precedes_the_decision(self):
        """Its input is what the download wrote; its output is what the gate reads."""
        from awltux.ingest import refresh

        order = list(refresh.step_ids())

        assert order.index("shareholder_reports") < order.index("document_parsing")
        assert order.index("document_parsing") < order.index("decision")


class TestRunningTheSequence:
    def _fake(self, calls: list, *, fail: str | None = None):
        from awltux.ingest.refresh import Step

        def make(job: str):
            def run(scope):
                calls.append((job, tuple(scope)))
                if job == fail:
                    raise ValueError(f"{job} exploded")
                return JobResult(items_seen=1, items_written=1, note=f"{job} done")

            return Step(job=job, label=job, run=run)

        return [make("prices"), make("news"), make("decision")]

    def test_every_step_is_called_with_the_one_instrument(self, session):
        from awltux.ingest import refresh

        _seed(session)
        row = acquire(session, "TEST_US_EQ")
        calls: list = []

        outcome = refresh.run(
            session, "TEST_US_EQ", token=row.token, steps_to_run=self._fake(calls)
        )

        assert calls == [("prices", ("TEST_US_EQ",)), ("news", ("TEST_US_EQ",)), ("decision", ("TEST_US_EQ",))]
        assert outcome["steps_done"] == 3

    def test_a_failing_step_does_not_stop_the_rest(self, session):
        """The pipeline is a chain of independent fetches: a Yahoo failure says nothing
        about whether EDGAR will answer, and stopping would make the button useless
        exactly when the data is in its worst state."""
        from awltux.ingest import refresh

        _seed(session)
        row = acquire(session, "TEST_US_EQ")
        calls: list = []

        outcome = refresh.run(
            session,
            "TEST_US_EQ",
            token=row.token,
            steps_to_run=self._fake(calls, fail="news"),
        )

        assert [job for job, _ in calls] == ["prices", "news", "decision"]
        results = outcome["results"]
        assert [entry["ok"] for entry in results] == [True, False, True]
        assert "exploded" in results[1]["note"]

    def test_a_lost_lease_stops_the_run_rather_than_writing_under_it(self, session):
        from awltux.ingest import refresh

        _seed(session)
        stale = acquire(session, "TEST_US_EQ").token
        # Somebody else takes it over, as an expired TTL would allow.
        acquire(session, "TEST_US_EQ", now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1))
        calls: list = []

        outcome = refresh.run(
            session, "TEST_US_EQ", token=stale, steps_to_run=self._fake(calls)
        )

        assert outcome["stopped"] == "lease lost"
        assert calls == []

    def test_each_step_is_recorded_for_the_page_to_read(self, session):
        from awltux.ingest import refresh

        _seed(session)
        row = acquire(session, "TEST_US_EQ")

        refresh.run(session, "TEST_US_EQ", token=row.token, steps_to_run=self._fake([]))
        session.commit()

        recorded = lease.current(session, "TEST_US_EQ")
        assert [entry["step"] for entry in recorded.steps] == ["prices", "news", "decision"]
        assert all(entry["ok"] for entry in recorded.steps)


class TestTheScopedJobWrappers:
    def test_a_scoped_run_lifts_the_rotation_ration(self, session, monkeypatch):
        """A rationed batch of two is not "refresh this one": the instrument could be
        rationed out of the very run that asked for it."""
        from awltux.ingest import jobs

        seen: dict = {}

        def fake_sync(session_, **kwargs):
            seen.update(kwargs)

            class Report:
                tickers_attempted = 1
                periods_written = 1

                def as_dict(self):
                    return {}

            return Report()

        monkeypatch.setattr("awltux.ingest.fundamentals.sync_fundamentals", fake_sync)
        monkeypatch.setattr(jobs, "empty_universe_note", lambda session: None)
        _seed(session)
        session.commit()

        jobs.sync_fundamentals_job(tickers=["TEST_US_EQ"])

        assert seen["tickers"] == ["TEST_US_EQ"]
        assert seen["limit"] is None, "the per-run rotation must not apply to a scope"

    def test_the_universe_run_still_rations(self, session, monkeypatch):
        from awltux.ingest import jobs

        seen: dict = {}

        def fake_sync(session_, **kwargs):
            seen.update(kwargs)

            class Report:
                tickers_attempted = 0
                periods_written = 0

                def as_dict(self):
                    return {}

            return Report()

        monkeypatch.setattr("awltux.ingest.fundamentals.sync_fundamentals", fake_sync)
        monkeypatch.setattr(jobs, "empty_universe_note", lambda session: None)
        _seed(session)
        session.commit()

        jobs.sync_fundamentals_job()

        assert seen["tickers"] is None
        assert seen["limit"] and seen["limit"] >= 1


class TestTheButton:
    def test_the_page_offers_it(self, client, session):
        _seed(session)
        session.commit()

        body = client.get("/instrument/TEST_US_EQ?tab=refresh").text

        assert 'action="/instrument/TEST_US_EQ/refresh"' in body
        assert "Refresh now" in body
        assert "never been refreshed on its own" in body

    def test_pressing_it_starts_a_refresh_and_redirects(self, client, session, monkeypatch):
        """A thread, not the request. A refresh takes minutes, and a request that long is
        one the browser abandons while the work carries on."""
        from awltux.ingest import refresh

        _seed(session)
        session.commit()
        calls: list = []

        def fake_step(scope):
            calls.append(tuple(scope))
            return JobResult(note="did it")

        monkeypatch.setattr(
            refresh, "_steps_from_registry", lambda: (refresh.Step("prices", "Prices", fake_step),)
        )

        response = client.post("/instrument/TEST_US_EQ/refresh", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"].startswith(
            "/instrument/TEST_US_EQ?tab=refresh&refresh=started"
        )

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = lease.current(session, "TEST_US_EQ")
            session.expire_all()
            state = lease.current(session, "TEST_US_EQ")
            if state is not None and state.state != "running":
                break
            time.sleep(0.05)

        assert calls == [("TEST_US_EQ",)]
        assert lease.current(session, "TEST_US_EQ").state == "done"

    def test_the_run_names_the_instrument_the_log_page_must_offer_back(
        self, client, session, monkeypatch
    ):
        """Reported from the page: pressing Refresh and following the live log landed on a
        page whose only way back was Operations.

        Every instrument's refresh writes to the *same* log file under the same job id, so
        the job id cannot say which company the log belongs to. The run row carries it from
        the moment it starts -- which is when the log is being watched.
        """
        from sqlalchemy import desc, select

        from awltux.db import IngestRun
        from awltux.ingest import refresh
        from awltux.scheduler import scoped

        _seed(session)
        session.commit()
        monkeypatch.setattr(
            refresh,
            "_steps_from_registry",
            lambda: (refresh.Step("prices", "Prices", lambda scope: JobResult(note="did it")),),
        )

        client.post("/instrument/TEST_US_EQ/refresh", follow_redirects=False)

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            session.expire_all()
            state = lease.current(session, "TEST_US_EQ")
            if state is not None and state.state != "running":
                break
            time.sleep(0.05)

        run = session.execute(
            select(IngestRun)
            .where(IngestRun.job == scoped.REFRESH_JOB)
            .order_by(desc(IngestRun.id))
            .limit(1)
        ).scalar_one()
        assert run.detail["target"] == "TEST_US_EQ"

        body = client.get(f"/jobs/{scoped.REFRESH_JOB}/log").text
        assert 'href="/instrument/TEST_US_EQ"' in body

        # And the run history says which company, because every refresh shares the job id:
        # three refresh runs were listed as three identical rows on 2026-10-08.
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(client.get("/jobs").text, "lxml")
        row = next(
            tr
            for tr in soup.find_all("tr")
            if tr.find("a", href=f"/jobs/{scoped.REFRESH_JOB}/log")
        )
        assert "TEST_US_EQ" in row.get_text(" ", strip=True)

    def test_pressing_it_twice_refuses_the_second(self, client, session, monkeypatch):
        """A refusal is an ordinary outcome of pressing a button twice, not an error."""
        from awltux.ingest import refresh

        _seed(session)
        session.commit()
        started = {"n": 0}
        release = {"now": False}

        def fake_step(scope):
            started["n"] += 1
            while not release["now"]:
                time.sleep(0.01)
            return JobResult(note="done")

        monkeypatch.setattr(
            refresh, "_steps_from_registry", lambda: (refresh.Step("prices", "Prices", fake_step),)
        )

        first = client.post("/instrument/TEST_US_EQ/refresh", follow_redirects=False)
        second = client.post("/instrument/TEST_US_EQ/refresh", follow_redirects=False)

        assert first.status_code == 303
        assert second.headers["location"].endswith("?tab=refresh&refresh=refused")

        # The first refresh is on another thread, so wait for it to reach the step rather
        # than assuming it got there before the second press.
        deadline = time.monotonic() + 10
        while started["n"] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        release["now"] = True

        assert started["n"] == 1

    def test_an_unknown_instrument_refuses_rather_than_starting(self, client, session):
        from awltux.scheduler import scoped

        outcome = scoped.start("NOT_AN_INSTRUMENT")

        assert outcome.ok is False
        assert lease.current(session, "NOT_AN_INSTRUMENT") is None

    def test_the_page_reports_a_refresh_that_ran(self, client, session):
        _seed(session)
        session.commit()
        row = acquire(session, "TEST_US_EQ")
        lease.record_step(
            session, "TEST_US_EQ", token=row.token, step="price_eod", note="40 bars", ok=True
        )
        lease.record_step(
            session, "TEST_US_EQ", token=row.token, step="xbrl_statements", note="HTTP 403", ok=False
        )
        lease.release(session, "TEST_US_EQ", token=row.token, state="done", note="1 of 2 steps")
        session.commit()

        body = client.get("/instrument/TEST_US_EQ?tab=refresh").text

        assert "price_eod" in body
        assert "40 bars" in body
        assert "did not complete" in body
        assert "HTTP 403" in body
        assert "/jobs/instrument_refresh/log" in body

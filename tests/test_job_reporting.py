"""A job that did nothing must say *why*.

`news_rss` reported `written: 0` and looked identical whether it had polled the
whole universe and found no news, or had nothing to poll because the universe was
empty. The second case is a setup problem the operator can fix in a minute; the
first is a normal quiet day. Reporting them the same way wastes that minute.

These tests cover the explanation, and the two distinct causes behind it.
"""

from __future__ import annotations

import pytest

from awltux.db import Instrument, session_scope, utcnow
from awltux.ingest.jobs import empty_universe_note, universe_is_empty
from awltux.scheduler.jobs import JobResult
from tests.helpers import make_instrument


class TestUniverseDetection:
    def test_an_empty_database_is_reported_as_empty(self, session):
        assert universe_is_empty(session) is True

    def test_instruments_outside_the_universe_still_count_as_empty(self, session):
        """The distinction that caused the confusing zero."""
        session.add(make_instrument("TEST_US_EQ", in_universe=False))
        session.flush()
        assert universe_is_empty(session) is True

    def test_an_excluded_instrument_does_not_populate_the_universe(self, session):
        session.add(make_instrument("TEST_US_EQ", in_universe=True, excluded=True))
        session.flush()
        assert universe_is_empty(session) is True

    def test_a_populated_universe_is_not_empty(self, session):
        session.add(make_instrument("TEST_US_EQ", in_universe=True))
        session.flush()
        assert universe_is_empty(session) is False


class TestExplanation:
    def test_nothing_stored_at_all_points_at_the_instruments_job(self, session):
        note = empty_universe_note(session)
        assert note is not None
        assert "t212_instruments" in note
        assert "Trading 212 API key" in note

    def test_stored_but_unselected_points_at_the_universe_job(self, session):
        """A different fix, so a different message."""
        session.add(make_instrument("TEST_US_EQ", in_universe=False))
        session.flush()
        note = empty_universe_note(session)
        assert note is not None
        assert "universe_refresh" in note
        assert "1 instruments are stored" in note

    def test_a_populated_universe_needs_no_explanation(self, session):
        session.add(make_instrument("TEST_US_EQ", in_universe=True))
        session.flush()
        assert empty_universe_note(session) is None


class TestJobResultsCarryTheNote:
    def test_a_job_result_serialises_its_note_into_the_detail(self):
        """The detail is what reaches the run history, so the note must be there."""
        result = JobResult(note="nothing to do: empty universe", detail={"fetched": 0})
        payload = result.as_dict()
        assert payload["note"] == "nothing to do: empty universe"
        assert payload["fetched"] == 0

    def test_a_job_with_no_note_does_not_claim_one(self):
        assert "note" not in JobResult(detail={"fetched": 5}).as_dict()

    def test_news_rss_explains_an_empty_universe_rather_than_reporting_zero(
        self, session, settings, monkeypatch
    ):
        """End to end on the job the operator actually ran."""
        from awltux.ingest import jobs as ingest_jobs

        # No instruments at all.
        assert session.query(Instrument).count() == 0

        result = ingest_jobs.ingest_news_rss()

        assert result.items_written == 0
        assert result.note is not None
        assert "t212_instruments" in result.note

    def test_filings_explain_a_book_with_no_sec_ciks(
        self, session, settings, monkeypatch
    ):
        """A London-only book legitimately has no EDGAR filings."""
        from awltux.ingest import edgar as edgar_module
        from awltux.ingest import jobs as ingest_jobs

        session.add(make_instrument("VODl_EQ", yahoo_symbol="VOD.L", exchange_name="LSE"))
        session.flush()

        # Stub the network so this stays offline.
        monkeypatch.setattr(
            edgar_module,
            "resolve_ciks",
            lambda session, **kwargs: edgar_module.EdgarSyncReport(),
        )

        result = ingest_jobs.sync_filings()
        assert result.note is not None
        assert "Companies House" in result.note

    @pytest.mark.parametrize(
        "job_name",
        ["ingest_edgar_events", "sync_fundamentals_job"],
    )
    def test_other_universe_driven_jobs_explain_themselves(
        self, session, settings, job_name: str
    ):
        from awltux.ingest import jobs as ingest_jobs

        result = getattr(ingest_jobs, job_name)()
        assert result.note is not None, f"{job_name} reported a bare zero"


class TestARunningJobIsVisibleWhileItRuns:
    """A run row used to be written only when the job *finished*.

    So a job taking forty minutes was invisible for forty minutes, and the newest
    thing on the Operations page was the *previous* run's error. That is exactly
    how a stale failure gets read as a current one -- it happened here, with a
    news run that was working normally reported as failing because the last
    completed run of that job had failed an hour earlier.
    """

    def _spec(self, func):
        from awltux.scheduler.jobs import JobSpec

        return JobSpec(id="probe", func=func, interval_seconds=60)

    def _newest(self):
        from sqlalchemy import desc, select

        from awltux.db import IngestRun

        with session_scope() as session:
            return session.execute(
                select(IngestRun).order_by(desc(IngestRun.id)).limit(1)
            ).scalar_one()

    def test_the_run_row_exists_with_a_null_result_mid_run(self, settings):
        from awltux.scheduler.jobs import JobResult, execute_job

        seen: dict[str, object] = {}

        def func():
            row = self._newest()
            seen["ok"] = row.ok
            seen["finished_at"] = row.finished_at
            return JobResult(items_seen=3, items_written=2)

        execute_job(self._spec(func))

        assert seen["ok"] is None, "the template renders a NULL ok as 'running'"
        assert seen["finished_at"] is None

    def test_the_same_row_is_closed_out_at_the_end(self, settings):
        from awltux.scheduler.jobs import JobResult, execute_job

        def func():
            return JobResult(items_seen=3, items_written=2)

        execute_job(self._spec(func))

        row = self._newest()
        assert row.ok is True
        assert row.finished_at is not None
        assert row.items_seen == 3
        assert row.items_written == 2

    def test_only_one_row_is_written_per_run(self, settings):
        """Opening and closing must not turn one run into two history entries."""
        from sqlalchemy import func as sql_func
        from sqlalchemy import select

        from awltux.db import IngestRun
        from awltux.scheduler.jobs import JobResult, execute_job

        execute_job(self._spec(lambda: JobResult()))

        with session_scope() as session:
            count = session.execute(select(sql_func.count()).select_from(IngestRun)).scalar_one()
        assert count == 1

    def test_a_failing_job_records_the_error_on_the_open_row(self, settings):
        from awltux.scheduler.jobs import execute_job

        def func():
            raise RuntimeError("provider exploded")

        execute_job(self._spec(func))

        row = self._newest()
        assert row.ok is False
        assert "provider exploded" in row.error
        assert row.finished_at is not None

    def test_a_run_that_could_not_be_opened_is_still_recorded(self, settings, monkeypatch):
        """The fallback: losing the open must not lose the history entry."""
        from awltux.scheduler import jobs as jobs_module
        from awltux.scheduler.jobs import JobResult, execute_job

        monkeypatch.setattr(jobs_module, "start_run", lambda job_id, started: None)
        execute_job(self._spec(lambda: JobResult(items_written=1)))

        row = self._newest()
        assert row.ok is True
        assert row.items_written == 1


class TestInterruptedRunsAreClosed:
    """A run left open by a process that died must not look like a running job.

    If it does, the Operations page disables that job's button forever and says it
    is running -- hiding the fact that the work never finished. The deployment
    restarts often enough that this is the normal case, not an edge one.
    """

    def _open_run(self, job: str = "news_rss"):
        from awltux.db import IngestRun

        with session_scope() as session:
            row = IngestRun(job=job, started_at=utcnow(), finished_at=None, ok=None)
            session.add(row)
            session.flush()
            return row.id

    def test_an_open_run_is_marked_interrupted_at_startup(self, settings):
        from awltux.scheduler.jobs import close_orphaned_runs

        run_id = self._open_run()

        assert close_orphaned_runs() == 1

        from awltux.db import IngestRun

        with session_scope() as session:
            row = session.get(IngestRun, run_id)
            assert row.finished_at is not None
            assert row.ok is False
            assert "interrupted" in row.error

    def test_it_does_not_touch_a_run_that_finished(self, settings):
        from awltux.db import IngestRun
        from awltux.scheduler.jobs import close_orphaned_runs

        with session_scope() as session:
            session.add(
                IngestRun(job="retention", started_at=utcnow(), finished_at=utcnow(), ok=True)
            )

        assert close_orphaned_runs() == 0

        with session_scope() as session:
            row = session.query(IngestRun).filter_by(job="retention").one()
            assert row.ok is True
            assert row.error is None

    def test_an_existing_error_is_kept_alongside_the_interruption(self, settings):
        from awltux.db import IngestRun
        from awltux.scheduler.jobs import close_orphaned_runs

        with session_scope() as session:
            row = IngestRun(
                job="news_rss", started_at=utcnow(), finished_at=None, ok=None, error="earlier"
            )
            session.add(row)
            session.flush()
            run_id = row.id

        close_orphaned_runs()

        with session_scope() as session:
            row = session.get(IngestRun, run_id)
            assert "earlier" in row.error
            assert "interrupted" in row.error


class TestRunningJobs:
    """What the Operations page reads to decide which buttons to disable."""

    def test_an_open_run_means_the_job_is_running(self, settings):
        from awltux.db import IngestRun
        from awltux.scheduler.jobs import running_jobs

        with session_scope() as session:
            session.add(IngestRun(job="news_rss", started_at=utcnow(), finished_at=None, ok=None))

        with session_scope() as session:
            assert running_jobs(session) == {"news_rss"}

    def test_a_finished_run_is_not_running(self, settings):
        from awltux.db import IngestRun
        from awltux.scheduler.jobs import running_jobs

        with session_scope() as session:
            session.add(
                IngestRun(job="news_rss", started_at=utcnow(), finished_at=utcnow(), ok=True)
            )

        with session_scope() as session:
            assert running_jobs(session) == set()

    def test_a_job_running_twice_is_reported_once(self, settings):
        from awltux.db import IngestRun
        from awltux.scheduler.jobs import running_jobs

        with session_scope() as session:
            for _ in range(2):
                session.add(
                    IngestRun(job="news_rss", started_at=utcnow(), finished_at=None, ok=None)
                )

        with session_scope() as session:
            assert running_jobs(session) == {"news_rss"}

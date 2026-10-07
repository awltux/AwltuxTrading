"""A long job is asked to stop, and leaves at a boundary it chose.

The problem this exists for is `awltux quiet`, which pauses scheduling and then waits
for what is already running. Pausing stops the *next* run starting and does nothing for
the walk over thousands of rows that is already halfway through -- so the wait was as
long as the job, and `news_rss` walks the universe for hours. Every deploy was
therefore a kill, and a killed run is closed as `interrupted` and repeated next start,
which spends the provider budget twice.

The tests below pin the three properties that make the ask usable rather than a
half-measure, and each of them is something a plausible implementation gets wrong:

* a job leaves **between items**, so the work already committed stays committed;
* a run that stopped is **not recorded as successful**, because "successful" is what
  catch-up reads to decide a job is up to date -- but its wording says it was asked to
  stop rather than that something failed;
* the request is **withdrawn** by `unquiet`, because a process left holding one stops
  at the first checkpoint of every later run and says nothing about why.
"""

from __future__ import annotations

import pytest

from awltux.db import IngestRun
from awltux.scheduler import progress
from awltux.scheduler.jobs import JobSpec, execute_job
from awltux.scheduler.service import SchedulerService


def _job(func, job_id: str = "probe") -> JobSpec:
    return JobSpec(id=job_id, func=func, interval_seconds=3600)


class TestLeavingAtABoundary:
    def test_a_job_leaves_between_items_with_the_earlier_ones_kept(self):
        """The whole point: a stop must save work, not repeat it."""
        done: list[int] = []

        def work() -> None:
            for index in range(100):
                if progress.stop_requested():
                    raise progress.Stopped(f"{index} of 100")
                done.append(index)
                if index == 3:
                    progress.request_stop()

        execute_job(_job(work))

        assert done == [0, 1, 2, 3], "the items finished before the check are kept"

    def test_the_last_line_of_the_log_says_where_it_stopped(self):
        """A log whose final line is an earlier item reads as a job still going."""

        def work() -> None:
            progress.request_stop()
            progress.checkpoint("item 1 of 10")
            raise AssertionError("checkpoint should have raised")

        execute_job(_job(work))
        text, _, _ = progress.read("probe")

        assert "PROGRESS item 1 of 10" in text
        assert text.splitlines()[-1].startswith("=== stopped"), text.splitlines()[-1]
        assert "item 1 of 10" in text.splitlines()[-1]

    def test_a_checkpoint_outside_a_run_still_honours_the_flag(self):
        """A job is callable from a test or a script with no run open.

        `note` is a no-op there, and `checkpoint` has to stay usable for the same
        reason -- it must not depend on a log being open -- but the flag is the
        scheduler's, so a stop requested is still a stop.
        """
        progress.checkpoint("no run active")  # must not raise

        progress.request_stop()
        with pytest.raises(progress.Stopped):
            progress.checkpoint("no run active")

    def test_a_job_that_never_checks_is_unaffected(self):
        """The mechanism is opt-in, so a job with no boundary keeps working."""
        ran = []

        def work() -> None:
            progress.request_stop()
            ran.append("finished")

        execute_job(_job(work))

        assert ran == ["finished"]

    def test_progress_alone_does_not_stop_a_job(self):
        """`note` is the log; only `checkpoint` looks at the flag."""
        done = []

        def work() -> None:
            progress.request_stop()
            for index in range(3):
                progress.note(f"item {index}")
                done.append(index)

        execute_job(_job(work))

        assert done == [0, 1, 2]


class TestHowAStoppedRunIsRecorded:
    def _run(self, session) -> IngestRun:
        return (
            session.query(IngestRun)
            .filter(IngestRun.job == "probe")
            .order_by(IngestRun.id.desc())
            .first()
        )

    def test_it_is_not_recorded_as_successful(self, session):
        """`ok` is what catch-up reads. A stopped run has not done its work.

        Counting it as successful would silently skip the rest of the job until its
        next interval, which for `news_rss` is an hour of unwalked universe.
        """

        def work() -> None:
            progress.request_stop()
            progress.checkpoint("2 of 100 instruments")

        execute_job(_job(work))

        row = self._run(session)
        assert row.ok is False
        assert row.error is not None
        assert row.detail["stopped"] is True
        assert row.detail["stopped_at"] == "2 of 100 instruments"

    def test_the_wording_says_it_was_asked_rather_than_that_it_failed(self, session):
        """A deploy that quiets five jobs must not paint five failures."""

        def work() -> None:
            progress.request_stop()
            progress.checkpoint("2 of 100 instruments")

        execute_job(_job(work))

        row = self._run(session)
        assert row.error.startswith("stopped: ")
        assert "a stop was requested" in row.error
        assert "Error" not in row.error and "Exception" not in row.error

    def test_the_progress_log_closes_as_stopped_not_ok(self):
        def work() -> None:
            progress.request_stop()
            progress.checkpoint("2 of 100")

        execute_job(_job(work))
        text, _, _ = progress.read("probe")

        assert text.splitlines()[-1].startswith("=== stopped")
        assert "=== ok" not in text

    def test_a_failure_is_still_a_failure(self, session):
        """The new branch must not swallow the old one."""

        def work() -> None:
            raise ValueError("provider said no")

        execute_job(_job(work))

        row = self._run(session)
        assert row.error == "ValueError: provider said no"
        assert "stopped" not in (row.detail or {})

    def test_an_unchecked_run_is_still_successful(self, session):
        execute_job(_job(lambda: None))

        row = self._run(session)
        assert row.ok is True
        assert row.error is None


class TestTheRequestItself:
    def test_it_is_monotonic_until_withdrawn(self):
        """A job already past a checkpoint still stops at the next one."""
        assert progress.stop_requested() is False

        progress.request_stop()
        progress.request_stop()

        assert progress.stop_requested() is True
        progress.clear_stop()
        assert progress.stop_requested() is False

    def test_a_second_start_clears_a_request_left_by_an_earlier_one(self, monkeypatch):
        """A service quieted and restarted in-process must not inherit the pause.

        The flag lives in this module, so a fresh *process* is clean by construction --
        but `start()` is also reached by a service object that was quieted and then
        started again, and that one would stop every job at its first checkpoint while
        reporting itself healthy.
        """
        service = SchedulerService.__new__(SchedulerService)
        service._quiet_since = None
        service._paused = False
        service._specs = {}
        service._scheduler = _InertScheduler()
        monkeypatch.setattr(service, "pending_catch_ups", lambda: [])
        progress.request_stop()

        service.start()

        assert progress.stop_requested() is False


class _InertScheduler:
    """Enough of the APScheduler surface for `start()` to run without a thread."""

    running = False

    def add_job(self, *args, **kwargs) -> None:
        pass

    def start(self, paused: bool = False) -> None:
        pass

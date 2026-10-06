"""Triggers that came due while the process was not running.

The machine this runs on is switched off overnight, and that is the failure these
tests exist for. The scheduler's triggers are anchored to process start and its job
store is in memory, so a trigger due at 02:00 while the machine is off does not fire
*late* -- it never fires. On the next start the interval is recomputed from *now*, so a
daily job's next fire is a day after the machine came back, and a machine that is off
every night never runs its daily jobs at all.

Measured on the live database before the fix: ``news_rss`` has an hourly interval and
had gone **23.7 hours** without a run, and **eight of twenty-one** registered jobs were
past their interval at the same instant.

The rule is tested as a pure function first, because on an empty database nearly every
job is *blocked* rather than idle and a test written against real data would be
exercising a different branch from the one it claims to.
"""

from __future__ import annotations

import datetime as dt
import time

import pytest

from awltux.scheduler.catchup import catch_up_for, catch_ups
from awltux.scheduler.jobs import JobSpec, last_successful_runs
from awltux.scheduler.service import SchedulerService

HOUR = 3600


def _noop() -> None:
    pass


def _spec(**overrides) -> JobSpec:
    fields = {"id": "x", "func": _noop, "interval_seconds": HOUR}
    fields.update(overrides)
    return JobSpec(**fields)


class TestTheRule:
    """When a job is owed a run, as a function of its history and its interval."""

    def test_a_job_inside_its_interval_is_not_behind(self):
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        assert catch_up_for("x", now - dt.timedelta(minutes=30), HOUR, now) is None

    def test_a_job_past_its_interval_is_behind(self):
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        last = now - dt.timedelta(minutes=90)

        owed = catch_up_for("x", last, HOUR, now)

        assert owed is not None
        assert owed.job_id == "x"
        assert owed.missed == 1
        assert owed.due_at == last + dt.timedelta(seconds=HOUR)
        assert owed.last_success == last

    def test_exactly_one_interval_late_counts_as_missed(self):
        """The boundary is ``>=`` the interval, not ``>`` it.

        An hourly job whose last run was exactly an hour ago is due *now*, and the
        distinction matters because the alternative is a job that is never quite due.
        """
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        owed = catch_up_for("x", now - dt.timedelta(seconds=HOUR), HOUR, now)

        assert owed is not None
        assert owed.missed == 1
        assert owed.due_at == now

    def test_a_job_that_never_ran_is_not_behind(self):
        """Nothing was missed, because there was no schedule yet to miss.

        This is the line between catching up and bootstrapping. A fresh database must
        not have every job fire at once on first start -- that stampede is what
        ``run_on_start`` and the first-run spread exist to avoid -- so a job with no
        history keeps the ordinary randomised first run.
        """
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        assert catch_up_for("x", None, HOUR, now) is None

    def test_a_week_off_collapses_into_one_run(self):
        """The collation: 168 missed triggers are answered by one run.

        Replaying them would spend 168 times the provider budget to reach the state a
        single run already reaches, which is why APScheduler's ``coalesce`` is on and
        why the count is recorded rather than acted on.
        """
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        last = now - dt.timedelta(days=7)

        owed = catch_up_for("x", last, HOUR, now)

        assert owed is not None
        assert owed.missed == 168

    def test_the_due_time_is_the_last_missed_trigger(self):
        """Not the first one, because that is what keeps the job on its old phase.

        Scheduled at the *first* missed trigger an hourly job would be re-anchored a
        day in the past and would then fire again immediately; the run is answered at
        the last, and the next fire is one interval on from there.
        """
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        last = now - dt.timedelta(hours=23, minutes=30)

        owed = catch_up_for("x", last, HOUR, now)

        assert owed is not None
        assert owed.missed == 23
        assert owed.scheduled_at == last + dt.timedelta(hours=1), "the first missed one"
        assert owed.due_at == last + dt.timedelta(hours=23), "the last missed one"
        # The defining property: the next trigger is still in the future, so this
        # catch-up cannot become a hot loop.
        assert owed.due_at + dt.timedelta(seconds=HOUR) > now

    def test_a_long_outage_falls_back_to_the_last_missed_trigger(self):
        """The enumeration is bounded, and both branches give the same run.

        Scheduling at the first missed trigger makes APScheduler enumerate the whole
        backlog and coalesce it down to one run. That is free for a night off and
        unbounded in principle, so past ``MAX_ENUMERATED_MISSES`` the last missed
        trigger is used instead -- which coalesces to the same single run.
        """
        from awltux.scheduler.catchup import MAX_ENUMERATED_MISSES, next_run_time_for

        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)

        just_under = catch_up_for("x", now - dt.timedelta(hours=MAX_ENUMERATED_MISSES), HOUR, now)
        over = catch_up_for("x", now - dt.timedelta(hours=MAX_ENUMERATED_MISSES + 10), HOUR, now)

        assert just_under is not None and over is not None
        assert next_run_time_for(just_under) == just_under.scheduled_at
        assert next_run_time_for(over) == over.due_at
        # The invariant either branch shares: the trigger the run *answers* is always
        # within one interval of now, which is what stops the job firing again at once.
        for owed in (just_under, over):
            assert owed.due_at <= now
            assert owed.due_at + dt.timedelta(seconds=HOUR) > now
            assert owed.missed * HOUR == (owed.due_at - owed.last_success).total_seconds()

    def test_the_overdue_time_is_a_fact_about_the_start(self):
        """Measured against the instant of the decision, and against the *first*
        unanswered trigger, so it grows with how long the job has been away."""
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)

        one_interval = catch_up_for("x", now - dt.timedelta(minutes=90), HOUR, now)
        three = catch_up_for("x", now - dt.timedelta(hours=3), HOUR, now)

        assert one_interval is not None and three is not None
        assert one_interval.overdue_by == dt.timedelta(minutes=30)
        assert three.overdue_by == dt.timedelta(hours=2)
        assert three.overdue_by > one_interval.overdue_by
        assert three.as_of == now

    def test_the_cause_says_the_count_and_the_last_run(self):
        """It is the first line of the run's log, so it has to be self-contained."""
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        owed = catch_up_for("news_rss", now - dt.timedelta(hours=24), HOUR, now)

        assert owed is not None
        assert "24 trigger(s)" in owed.cause
        assert "2026-10-05 09:00Z" in owed.cause
        assert "running once" in owed.cause

    @pytest.mark.parametrize("interval", [0, -1])
    def test_a_non_positive_interval_is_refused(self, interval):
        """A zero interval would either divide by zero or make everything overdue."""
        now = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
        assert catch_up_for("x", now - dt.timedelta(days=1), interval, now) is None


class TestWhatIsOwed:
    """Which jobs get a catch-up, over a set of specs."""

    def _now(self):
        return dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)

    def test_a_run_on_start_job_is_not_caught_up(self):
        """It runs on every start anyway, so a catch-up would be a second run of it.

        That is not a hypothetical: ``t212_instruments`` is ``run_on_start`` and its
        history on the live database holds **62 runs against a daily interval**, all
        of them restarts.
        """
        now = self._now()
        specs = [_spec(id="daily", run_on_start=True)]
        last_runs = {"daily": now - dt.timedelta(days=3)}

        assert catch_ups(specs, last_runs, now) == []

    def test_a_disabled_job_is_not_caught_up(self):
        """Disabled means the credential is missing, not that the job is overdue."""
        now = self._now()
        specs = [_spec(id="off", enabled=False)]
        last_runs = {"off": now - dt.timedelta(days=3)}

        assert catch_ups(specs, last_runs, now) == []

    def test_a_job_with_no_history_is_not_caught_up(self):
        now = self._now()
        assert catch_ups([_spec(id="fresh")], {}, now) == []

    def test_a_job_inside_its_interval_is_not_caught_up(self):
        now = self._now()
        assert catch_ups([_spec(id="current")], {"current": now - dt.timedelta(minutes=5)}, now) == []

    def test_the_most_overdue_job_is_first(self):
        """Stalest data first: the only priority that needs nobody to maintain it.

        And the order is not decorative. APScheduler works through due jobs in
        ascending due-time order (``MemoryJobStore.get_due_jobs`` breaks at the first
        job that is not due), and the catch-up is scheduled *at* the first missed
        trigger -- so the ordering returned here is the ordering the single
        ``MAX_CONCURRENT_JOBS`` worker actually works through.
        """
        now = self._now()
        specs = [_spec(id="recently_stale"), _spec(id="very_stale")]
        last_runs = {
            "recently_stale": now - dt.timedelta(hours=2),
            "very_stale": now - dt.timedelta(days=3),
        }

        owed = catch_ups(specs, last_runs, now)

        assert [one.job_id for one in owed] == ["very_stale", "recently_stale"]
        # The claim above, made checkable: the list order is the scheduled order.
        scheduled = [one.scheduled_at for one in owed]
        assert scheduled == sorted(scheduled)

    def test_jobs_due_at_the_same_instant_keep_registry_order(self):
        """Sorted is stable, so a tie falls back to the pipeline order the registry is
        written in rather than to whatever the dict happened to hold."""
        now = self._now()
        specs = [_spec(id="first"), _spec(id="second")]
        last_runs = {"first": now - dt.timedelta(hours=1), "second": now - dt.timedelta(hours=1)}

        assert [one.job_id for one in catch_ups(specs, last_runs, now)] == ["first", "second"]


class TestTheRunHistory:
    def test_it_reports_when_each_job_last_started(self, session):
        """The read the whole feature rests on, and the normalisation it needs.

        SQLite returns naive datetimes however the column was declared, and a naive
        value compared against an aware "now" raises. That failure would land at
        startup, which is the one moment it cannot be tolerated.
        """
        from awltux.db import IngestRun

        older = dt.datetime.now(dt.UTC) - dt.timedelta(hours=5)
        newer = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
        session.add(IngestRun(job="a", started_at=older, finished_at=older, ok=True))
        session.add(IngestRun(job="a", started_at=newer, finished_at=newer, ok=True))
        session.add(IngestRun(job="b", started_at=older, finished_at=older, ok=True))
        session.commit()

        times = last_successful_runs(session)

        assert set(times) == {"a", "b"}
        assert times["a"].tzinfo is not None, "a naive value cannot be compared to now"
        assert abs((times["a"] - newer).total_seconds()) < 1, "must be the most recent run"
        assert times["a"] > times["b"]

    def test_a_job_that_never_ran_is_absent_rather_than_defaulted(self, session):
        """Absent is what "no schedule was missed" looks like; a default would invent
        a history and make every fresh job look overdue."""
        assert last_successful_runs(session) == {}

    def test_a_failed_run_does_not_count_as_work_done(self, session):
        """The central claim of the function, and why it is not "last attempt".

        This process is restarted by every deploy, so a run killed mid-write is the
        common case rather than the rare one -- ``news_analysis`` alone was killed by
        three of them. Counting an attempt as work done would leave that job's stories
        unappraised until its next interval came round, a day later.
        """
        from awltux.db import IngestRun

        succeeded = dt.datetime.now(dt.UTC) - dt.timedelta(hours=6)
        failed = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        session.add(IngestRun(job="a", started_at=succeeded, finished_at=succeeded, ok=True))
        session.add(IngestRun(job="a", started_at=failed, finished_at=failed, ok=False))
        session.commit()

        times = last_successful_runs(session)

        assert abs((times["a"] - succeeded).total_seconds()) < 1, (
            "the recent failure masked the older success"
        )

    def test_a_run_that_is_still_open_does_not_count(self, session):
        """``ok`` is NULL while a run is in flight, and an open run has produced
        nothing yet. At startup these have already been closed as interrupted by
        ``close_orphaned_runs``; this is the belt to that brace."""
        from awltux.db import IngestRun

        session.add(
            IngestRun(
                job="a",
                started_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
                finished_at=None,
                ok=None,
            )
        )
        session.commit()

        assert last_successful_runs(session) == {}

    def test_a_job_that_has_only_ever_failed_is_absent(self, session):
        """So it is not caught up on every start before it has ever worked.

        It keeps the ordinary spread first run instead, which is what stops a job with
        a permanently broken provider from being retried on every restart while the
        rest of the pipeline waits behind the single worker.
        """
        from awltux.db import IngestRun

        when = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
        session.add(IngestRun(job="a", started_at=when, finished_at=when, ok=False))
        session.commit()

        assert last_successful_runs(session) == {}


class TestOnStart:
    """The behaviour: a restart picks the work back up."""

    @pytest.fixture
    def recorder(self, monkeypatch):
        """Replace the real job body, so nothing reaches a provider or a database."""
        import awltux.scheduler.service as service_module

        ran: list[tuple] = []
        monkeypatch.setattr(service_module, "execute_job", lambda *args: ran.append(args))
        return ran

    @staticmethod
    def _await(ran, count=1, timeout=5.0):
        deadline = time.monotonic() + timeout
        while len(ran) < count and time.monotonic() < deadline:
            time.sleep(0.05)

    def test_a_stale_job_runs_when_the_service_starts(self, session, recorder):
        """The whole point: the machine comes back and the missed trigger is answered."""
        from awltux.db import IngestRun

        started = dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)
        session.add(
            IngestRun(job="late", started_at=started, finished_at=started, ok=True)
        )
        session.commit()

        service = SchedulerService([_spec(id="late")])
        service.start()
        try:
            self._await(recorder)
        finally:
            service.shutdown(wait=False)

        assert len(recorder) == 1, "a job three hours past an hourly interval must run"
        assert recorder[0][0].id == "late"
        assert "catching up" in recorder[0][1]

    def test_it_runs_once_and_not_for_every_missed_trigger(self, session, recorder):
        """Three days off is three days of missed triggers and still one run."""
        from awltux.db import IngestRun

        started = dt.datetime.now(dt.UTC) - dt.timedelta(days=3)
        session.add(
            IngestRun(job="late", started_at=started, finished_at=started, ok=True)
        )
        session.commit()

        service = SchedulerService([_spec(id="late")])
        service.start()
        try:
            self._await(recorder)
            time.sleep(0.5)
        finally:
            service.shutdown(wait=False)

        assert len(recorder) == 1, f"72 missed triggers produced {len(recorder)} runs"

    def test_it_does_not_fire_again_immediately(self, session, recorder):
        """The anti-hot-loop assertion, and the reason the due time is the *last*
        missed trigger rather than the first: scheduled at the first, an hourly job
        would be a day past due and would fire again the moment the worker was free."""
        from awltux.db import IngestRun

        started = dt.datetime.now(dt.UTC) - dt.timedelta(hours=23, minutes=30)
        session.add(
            IngestRun(job="late", started_at=started, finished_at=started, ok=True)
        )
        session.commit()

        service = SchedulerService([_spec(id="late")])
        service.start()
        try:
            self._await(recorder)
            time.sleep(0.5)
            next_run = next(row["next_run"] for row in service.status() if row["id"] == "late")
        finally:
            service.shutdown(wait=False)

        assert len(recorder) == 1, "the catch-up became a loop"
        assert dt.datetime.fromisoformat(next_run) > dt.datetime.now(dt.UTC), (
            "the next trigger must not be in the past"
        )

    def test_a_job_whose_last_run_failed_runs_again_on_start(self, session, recorder):
        """The deploy case, and the reason the history is read for *successes*.

        A rebuild interrupts whatever is running; the new process closes that run as
        interrupted and, without this, would then consider the job up to date for a
        whole interval. Anchoring on the last successful run is what turns an
        interrupted run into one that is simply repeated.
        """
        from awltux.db import IngestRun

        succeeded = dt.datetime.now(dt.UTC) - dt.timedelta(hours=30)
        interrupted = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        session.add(
            IngestRun(job="late", started_at=succeeded, finished_at=succeeded, ok=True)
        )
        session.add(
            IngestRun(
                job="late",
                started_at=interrupted,
                finished_at=interrupted,
                ok=False,
                error="interrupted: the process restarted while this run was in progress",
            )
        )
        session.commit()

        service = SchedulerService([_spec(id="late")])
        service.start()
        try:
            self._await(recorder)
        finally:
            service.shutdown(wait=False)

        assert len(recorder) == 1, (
            "a run killed by a restart must be picked up, not counted as done"
        )

    def test_a_current_job_keeps_its_spread_first_run(self, session, recorder):
        """A job that ran a minute ago is not behind, so nothing changes for it."""
        from awltux.db import IngestRun

        started = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        session.add(
            IngestRun(job="current", started_at=started, finished_at=started, ok=True)
        )
        session.commit()

        service = SchedulerService([_spec(id="current")])
        service.start()
        try:
            time.sleep(0.5)
        finally:
            service.shutdown(wait=False)

        assert recorder == [], "a job inside its interval must not be caught up"

    def test_a_job_with_no_history_does_not_fire_on_start(self, recorder):
        """A fresh database must not start its whole pipeline at once.

        Bootstrapping is what ``run_on_start`` declares, job by job, and a job that has
        never run has missed nothing.
        """
        service = SchedulerService([_spec(id="fresh")])
        service.start()
        try:
            time.sleep(0.5)
        finally:
            service.shutdown(wait=False)

        assert recorder == []

    def test_the_status_says_which_jobs_are_behind(self, session, recorder):
        """Shown rather than left as a timestamp the reader must compare to a clock.

        Derived from the run history, and that is the fix for a bug this test would
        otherwise have passed straight through. The first version compared `next_run`
        against the clock, which is wrong because **APScheduler advances `next_run_time`
        when a job is handed to the executor, not when it starts**. Measured on the
        first live catch-up: ten jobs were queued behind the single worker, all had a
        `next_run` in the future, and `news_relevance` was 183 minutes past a one-hour
        interval -- so the badge that existed to explain the queue never appeared once.
        """
        from awltux.db import IngestRun

        behind_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=3)
        current_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        session.add(IngestRun(job="behind", started_at=behind_at, finished_at=behind_at, ok=True))
        session.add(IngestRun(job="current", started_at=current_at, finished_at=current_at, ok=True))
        session.commit()

        service = SchedulerService(
            [_spec(id="behind"), _spec(id="current"), _spec(id="fresh")]
        )
        service.start()
        try:
            rows = {row["id"]: row for row in service.status()}

            assert rows["behind"]["overdue"] is True
            assert rows["current"]["overdue"] is False
            # Never succeeded, so nothing was missed -- the same rule the scheduler
            # applies, not a second one invented for the page.
            assert rows["fresh"]["overdue"] is False

            # The defect this replaces: the badge must not depend on the clock.
            assert dt.datetime.fromisoformat(rows["behind"]["next_run"]) > dt.datetime.now(
                dt.UTC
            ), "the queued job's next_run is in the future, which is why it was missed"
        finally:
            service.shutdown(wait=False)

    def test_a_hidden_failure_to_read_the_history_does_not_break_the_page(self, monkeypatch):
        """An unreadable run table is a missing badge, not a 500 on /jobs."""
        import awltux.scheduler.service as service_module

        def explode(*_args, **_kwargs):
            raise RuntimeError("the run table is unreadable")

        monkeypatch.setattr(service_module, "last_successful_runs", explode)

        service = SchedulerService([_spec(id="x")])
        service.start()
        try:
            assert service.status()[0]["overdue"] is False
        finally:
            service.shutdown(wait=False)

    def test_an_unreadable_history_catches_nothing_up_rather_than_failing_startup(
        self, monkeypatch
    ):
        """A broken query is a reason to run the normal schedule, not to refuse to
        start. The alternative is a container that will not come up until the
        database is repaired by hand."""
        import awltux.scheduler.service as service_module

        def explode(*_args, **_kwargs):
            raise RuntimeError("the run table is unreadable")

        monkeypatch.setattr(service_module, "last_successful_runs", explode)

        service = SchedulerService([_spec(id="x")])
        assert service.pending_catch_ups() == []

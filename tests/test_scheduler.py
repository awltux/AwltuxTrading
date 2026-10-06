"""The scheduler actually schedules.

There was no test file for this, and that is the point: a scheduler that registers
jobs and then never fires them passed the entire suite. `_schedule` passed
``next_run_time=None``, which APScheduler reads as *"add this job paused"*, so every
job without ``run_on_start`` -- sixteen of nineteen -- was silently dead from the
moment it was written.

The two symptoms a reader saw were one bug from two directions: no runs in the
history, and an empty "next run" column. These tests assert the property directly.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.config import Settings
from awltux.scheduler.jobs import JobSpec
from awltux.scheduler.registry import build_job_specs
from awltux.scheduler.service import SchedulerService
from awltux.web.templating import fmt_interval


def _noop() -> None:
    pass


@pytest.fixture
def quiet_jobs(monkeypatch):
    """Stop the scheduler executing anything.

    Starting the real registry would fire its ``run_on_start`` jobs immediately, and
    those make provider calls -- which the suite must never do. The specs still get
    scheduled, which is what these tests are about.
    """
    import awltux.scheduler.service as service_module

    monkeypatch.setattr(service_module, "execute_job", lambda spec: None)


class TestEveryEnabledJobIsScheduled:
    def test_none_is_left_paused(self, settings: Settings, quiet_jobs):
        """The regression test for the bug: 16 of 19 jobs were added paused.

        Asserted over the *real* registry rather than a fixture list, so a new job
        that forgets nothing in particular is still covered.
        """
        service = SchedulerService(build_job_specs(settings))
        service.start()
        try:
            rows = service.status()
            enabled = [row for row in rows if row["enabled"]]
            assert len(enabled) > 3, "the registry is too small for this to prove anything"

            never = [row["id"] for row in enabled if row["next_run"] is None]
            assert not never, (
                "these jobs are registered but will never fire, because they are "
                f"paused rather than scheduled: {never}"
            )
        finally:
            service.shutdown(wait=False)

    def test_a_disabled_job_is_not_scheduled(self, quiet_jobs):
        """Disabled means disabled, and it is what a missing credential looks like."""
        spec = JobSpec(id="off", func=_noop, interval_seconds=60, enabled=False)
        service = SchedulerService([spec])
        service.start()
        try:
            assert service.status()[0]["next_run"] is None
        finally:
            service.shutdown(wait=False)


class TestTheCadence:
    """One hour is the floor, and jobs are spread across it."""

    def test_nothing_runs_faster_than_the_floor(self, settings: Settings):
        """Asserted against the built registry, not against `config.yaml`.

        A default in `ScheduleConfig` is the last line of defence: a job added with an
        interval of 45 seconds would spend provider quota confirming that nothing had
        changed, and the page would advertise a schedule nobody intended.
        """
        from awltux.scheduler.service import MIN_INTERVAL_SECONDS

        fast = [
            (spec.id, spec.interval_seconds)
            for spec in build_job_specs(settings)
            if spec.enabled and spec.interval_seconds < MIN_INTERVAL_SECONDS
        ]
        assert not fast, f"these run faster than the one-hour floor: {fast}"

    def test_the_first_runs_are_spread_rather_than_simultaneous(self, quiet_jobs):
        """The point of the spread: nineteen hourly jobs must not collide.

        Measured over the real registry, because the failure is a property of the set
        -- any single job looks fine on its own.
        """
        service = SchedulerService(build_job_specs())
        service.start()
        try:
            runs = [
                row["next_run"]
                for row in service.status()
                if row["enabled"] and row["next_run"] is not None
            ]
        finally:
            service.shutdown(wait=False)

        assert len(runs) >= 10, "too few jobs to judge a spread"
        assert len(set(runs)) == len(runs), (
            "two jobs share a first run; the spread is not being applied"
        )

        times = sorted(dt.datetime.fromisoformat(value) for value in runs)
        span = (times[-1] - times[0]).total_seconds()
        assert span > 60, f"the whole schedule starts within {span:.0f}s of itself"

    def test_the_spread_is_not_the_only_thing_keeping_them_apart(self, quiet_jobs):
        """A job with a long interval still waits at most an hour for its first run,
        so a fresh container converges rather than trickling in over a week."""
        from awltux.scheduler.service import FIRST_RUN_SPREAD_SECONDS

        spec = JobSpec(id="daily", func=_noop, interval_seconds=86400)
        service = SchedulerService([spec])
        before = dt.datetime.now(dt.UTC)
        service.start()
        try:
            next_run = dt.datetime.fromisoformat(service.status()[0]["next_run"])
        finally:
            service.shutdown(wait=False)

        assert (next_run - before).total_seconds() <= FIRST_RUN_SPREAD_SECONDS + 5


class TestWhenAJobFirstRuns:
    def test_without_run_on_start_the_first_run_is_inside_the_spread(self, quiet_jobs):
        """It does not fire at "now", and it does not wait a whole interval.

        The first run lands somewhere in the spread window and every run after it is
        one interval on, which is what keeps the printed schedule true.
        """
        spec = JobSpec(id="later", func=_noop, interval_seconds=600)
        service = SchedulerService([spec])
        before = dt.datetime.now(dt.UTC)
        service.start()
        try:
            next_run = dt.datetime.fromisoformat(service.status()[0]["next_run"])
        finally:
            service.shutdown(wait=False)

        waited = (next_run - before).total_seconds()
        assert 0 < waited <= 600, f"expected a spread first run, got {waited:.0f}s"

    def test_run_on_start_fires_without_waiting_its_interval(self, monkeypatch):
        """Asserted by observing the run, not the clock.

        A job scheduled for "now" fires *during* `start()`, so by the time the status
        is read its next run is already one interval away -- reading the clock here
        would test the opposite of what it looks like.
        """
        import time

        import awltux.scheduler.service as service_module

        ran: list[str] = []
        monkeypatch.setattr(service_module, "execute_job", lambda spec: ran.append(spec.id))

        spec = JobSpec(id="now", func=_noop, interval_seconds=86400, run_on_start=True)
        service = SchedulerService([spec])
        service.start()
        try:
            deadline = time.monotonic() + 5
            while not ran and time.monotonic() < deadline:
                time.sleep(0.05)
        finally:
            service.shutdown(wait=False)

        assert ran == ["now"]

    def test_without_run_on_start_it_does_not_fire_on_startup(self, monkeypatch):
        """The other half, and the one that was broken: a fresh container should not
        begin its whole ingest pipeline the moment it comes up."""
        import time

        import awltux.scheduler.service as service_module

        ran: list[str] = []
        monkeypatch.setattr(service_module, "execute_job", lambda spec: ran.append(spec.id))

        spec = JobSpec(id="later", func=_noop, interval_seconds=86400, run_on_start=False)
        service = SchedulerService([spec])
        service.start()
        try:
            time.sleep(0.5)
        finally:
            service.shutdown(wait=False)

        assert ran == []

    def test_a_start_delay_is_honoured(self, quiet_jobs):
        """Jobs scheduled for "now" all fire together, so one that reads a sibling's
        output needs to be able to wait for it."""
        spec = JobSpec(
            id="after", func=_noop, interval_seconds=600, run_on_start=True,
            start_delay_seconds=900,
        )
        service = SchedulerService([spec])
        before = dt.datetime.now(dt.UTC)
        service.start()
        try:
            next_run = dt.datetime.fromisoformat(service.status()[0]["next_run"])
        finally:
            service.shutdown(wait=False)

        waited = (next_run - before).total_seconds()
        assert 880 <= waited <= 920, f"expected the delay, got {waited:.0f}s"


class TestTheIntervalColumn:
    """It must state the schedule the job actually has.

    The page rendered every interval as minutes rounded to a whole number, so the
    forty-five-second job printed "1.0m" -- which is how its total silence came to
    look like a job that was running every minute.
    """

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (45, "45s"),        # the one that printed "1.0m"
            (60, "60s"),
            (89, "89s"),
            (300, "5m"),
            (3600, "1h"),
            (21600, "6h"),
            (86400, "1d"),
            (604800, "7d"),     # printed "10080.0m"
        ],
    )
    def test_it_reads_in_the_unit_that_makes_sense(self, seconds, expected):
        assert fmt_interval(seconds) == expected

    def test_a_non_numeric_interval_is_visibly_unknown(self):
        assert fmt_interval(None) == "—"
        assert fmt_interval("soon") == "—"


class TestTheSkipRule:
    """The rule itself, as a pure function of a spec and a job's status.

    Tested directly rather than through whatever state a database happens to be in:
    on an empty database nearly every job is *blocked* rather than idle, so a test
    written against real data would be exercising a different branch from the one it
    claims to.
    """

    def _status(self, **overrides):
        from awltux.scheduler.dependencies import JobStatus

        return JobStatus(id="x", description="", **overrides)

    def _spec(self, **overrides):
        return JobSpec(id="x", func=_noop, interval_seconds=3600, **overrides)

    def test_a_blocked_job_waits(self):
        from awltux.scheduler.jobs import skip_reason

        reason = skip_reason(self._spec(), self._status(never_ran=["news_rss"]))
        assert reason is not None
        assert "waiting for" in reason and "news_rss" in reason

    def test_an_idle_backfill_is_skipped(self):
        from awltux.scheduler.jobs import skip_reason

        reason = skip_reason(
            self._spec(backfill=True),
            self._status(outstanding=0, reason="nothing left to resolve"),
        )
        assert reason is not None
        assert "nothing outstanding" in reason
        assert "nothing left to resolve" in reason

    def test_a_backfill_with_work_runs(self):
        from awltux.scheduler.jobs import skip_reason

        assert skip_reason(self._spec(backfill=True), self._status(outstanding=12)) is None

    def test_a_refresh_with_nothing_outstanding_still_runs(self):
        """The distinction the flag exists for: its coverage reads zero precisely
        when it is working, so skipping it would freeze what it maintains."""
        from awltux.scheduler.jobs import skip_reason

        assert skip_reason(self._spec(), self._status(outstanding=0)) is None

    def test_a_job_with_no_coverage_notion_always_runs(self):
        """A poller fetches what has not been published yet, which is by definition
        not in the database to be counted."""
        from awltux.scheduler.jobs import skip_reason

        assert skip_reason(self._spec(backfill=True), self._status(outstanding=None)) is None

    def test_an_unknown_status_runs_rather_than_skipping(self):
        """Silence is not evidence that there is nothing to do."""
        from awltux.scheduler.jobs import skip_reason

        assert skip_reason(self._spec(backfill=True), None) is None


class TestTheGuardInPlace:
    def test_a_job_waits_for_a_dependency_that_has_produced_nothing(self, settings, session):
        """`news_analysis` appraises stored stories; with none stored it would spend
        a model call per story to discover there are no stories."""
        from awltux.scheduler.jobs import guard_reason

        spec = next(s for s in build_job_specs() if s.id == "news_analysis")
        reason = guard_reason(spec)

        assert reason is not None
        assert "waiting for" in reason
        assert "news_rss" in reason

    def test_a_skipped_run_is_recorded_rather_than_silent(self, settings, session):
        """The history must show the job fired and chose to do nothing.

        A gap cannot be told apart from a scheduler that is not firing, which is the
        bug this whole change came from: sixteen jobs were registered as paused and
        their absence from the history looked like a quiet system.
        """
        from sqlalchemy import desc, select

        from awltux.db import IngestRun, session_scope
        from awltux.scheduler.jobs import execute_job

        spec = next(s for s in build_job_specs() if s.id == "news_analysis")
        result = execute_job(spec)

        assert result is not None
        assert (result.note or "").startswith("skipped:")

        with session_scope() as scope:
            row = scope.execute(
                select(IngestRun)
                .where(IngestRun.job == "news_analysis")
                .order_by(desc(IngestRun.id))
                .limit(1)
            ).scalar_one()
            assert row.ok is True
            assert row.finished_at is not None
            assert "skipped" in (row.detail or {}).get("note", "")


class TestDraining:
    """Quieting the container before an upgrade replaces it."""

    def test_draining_pauses_so_no_new_work_starts(self, quiet_jobs):
        service = SchedulerService([JobSpec(id="x", func=_noop, interval_seconds=3600)])
        service.start()
        try:
            assert not service.paused
            service.drain(timeout=0.1)
            assert service.paused, "a drain that keeps handing out work is not a drain"
        finally:
            service.shutdown(wait=False)

    def test_draining_returns_immediately_when_nothing_is_running(self, quiet_jobs):
        import time

        service = SchedulerService([])
        service.start()
        try:
            started = time.monotonic()
            assert service.drain(timeout=30) == []
            assert time.monotonic() - started < 1, "it should not wait out its budget"
        finally:
            service.shutdown(wait=False)

    def test_it_reports_a_straggler_when_the_budget_runs_out(self, settings, session):
        """An open run row is what a running job looks like from outside the process.

        Which is the point: the record survives the process, so the drain can see
        work this process did not start and an operator can see what was abandoned.
        """
        import time

        from awltux.db import IngestRun

        session.add(
            IngestRun(
                job="straggler",
                started_at=dt.datetime.now(dt.UTC),
                finished_at=None,
                ok=None,
            )
        )
        session.commit()

        service = SchedulerService([])
        started = time.monotonic()
        remaining = service.drain(timeout=1.0)
        waited = time.monotonic() - started

        assert remaining == ["straggler"]
        assert waited >= 0.9, "it should have waited out its budget for the straggler"

    def test_the_budget_fits_inside_the_container_grace_period(self, settings: Settings):
        """Otherwise Docker kills the container first and the wait is theatre.

        Checked across the two files because the failure is a silent drift between
        them: raising the drain budget without raising the grace period looks like it
        should work and does not.
        """
        import re
        from pathlib import Path

        compose = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        match = re.search(r"stop_grace_period:\s*(\d+)s", compose)
        assert match, "docker-compose.yml no longer declares a stop grace period"

        grace = int(match.group(1))
        budget = settings.env.shutdown_drain_seconds
        assert 0 < budget < grace, f"drain budget {budget}s must sit under {grace}s"


class TestQuieting:
    """`awltux quiet` -- stopping work *before* the rebuild, not during shutdown.

    The drain is bounded because it has to be, so a job that outruns it is killed
    mid-write. Quieting asks earlier and waits for as long as it takes, which is why
    these tests care that "quiet" and "idle" are different answers: pausing stops the
    next job, and does nothing about the one already writing.
    """

    def test_quieting_pauses_and_reports_what_is_still_running(self, quiet_jobs, session):
        from awltux.db import IngestRun

        session.add(
            IngestRun(
                job="refresh_prices",
                started_at=dt.datetime.now(dt.UTC),
                finished_at=None,
                ok=None,
            )
        )
        session.commit()

        service = SchedulerService([])
        status = service.quiet()

        assert status["quiet"] is True
        assert status["running"] == ["refresh_prices"]
        assert status["idle"] is False, (
            "quiet is not the same as safe to rebuild; the write is still in flight"
        )

    def test_a_quiet_container_with_nothing_running_is_idle(self, quiet_jobs):
        service = SchedulerService([])
        status = service.quiet()

        assert status["quiet"] is True
        assert status["running"] == []
        assert status["idle"] is True

    def test_unquiet_resumes_scheduling(self, quiet_jobs):
        """An abandoned upgrade must not leave a container that never works again."""
        service = SchedulerService([])
        service.start()
        try:
            service.quiet()
            assert service.paused

            status = service.unquiet()
            assert status["quiet"] is False
            assert status["quiet_since"] is None
            assert not service.paused
        finally:
            service.shutdown(wait=False)

    def test_quiet_is_not_reported_before_it_is_asked_for(self, quiet_jobs):
        """Otherwise every Operations page shows a warning nobody triggered."""
        service = SchedulerService([])
        status = service.quiet_status()

        assert status["quiet"] is False
        assert status["idle"] is False

    def test_the_quiet_endpoints_round_trip(self, client):
        """The CLI has no other way to reach the running scheduler.

        A second process cannot pause the first one's threads, and running the job
        locally instead would contend for SQLite's write lock with the server that is
        already writing -- the same reason `awltux job` delegates.
        """
        assert client.get("/api/quiet").json()["quiet"] is False

        posted = client.post("/api/quiet").json()
        assert posted["quiet"] is True
        assert "idle" in posted

        assert client.get("/api/quiet").json()["quiet"] is True

        assert client.delete("/api/quiet").json()["quiet"] is False
        assert client.get("/api/quiet").json()["quiet"] is False

    def test_a_wait_that_times_out_is_a_refusal_not_a_success(self, client, session):
        """409, so a script that only reads the status code cannot rebuild anyway.

        The failure this prevents: an upgrade that prints "quieted", ignores a job
        still writing, and kills it -- which is the lost work quiet exists to avoid.
        """
        from awltux.db import IngestRun

        session.add(
            IngestRun(
                job="shareholder_reports",
                started_at=dt.datetime.now(dt.UTC),
                finished_at=None,
                ok=None,
            )
        )
        session.commit()

        response = client.post("/api/quiet", params={"wait": 0.2})

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["running"] == ["shareholder_reports"]
        assert detail["idle"] is False


class TestQuietWaitsForTheJob:
    """`awltux quiet` has no deadline by default, and that is the whole point.

    The first version defaulted to fifteen minutes. The first real job it met was
    `news_analysis`, which is bounded at forty model calls and still runs 14 to 39
    minutes; quiet returned exit 3, the rebuild went ahead, and the run was killed
    and closed as interrupted. That is the outcome the command exists to prevent,
    so a default shorter than the jobs it waits for is not a safety valve -- it is
    the failure, on a timer.
    """

    @staticmethod
    def _args(timeout: float = 0.0, poll: float = 0.0):
        import argparse

        return argparse.Namespace(timeout=timeout, poll=poll)

    def _server(self, monkeypatch, states):
        """A server that reports each state in turn, then repeats the last."""
        import awltux.cli as cli

        calls: list[str] = []
        remaining = list(states)

        def fake(_settings, method, path):
            calls.append(f"{method} {path}")
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]

        monkeypatch.setattr(cli, "_ask_server", fake)
        monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
        return calls

    def test_the_default_is_to_wait_rather_than_to_give_up(self):
        import awltux.cli as cli

        parser = cli.build_parser()
        quiet = parser._subparsers._group_actions[0].choices["quiet"]
        timeout = next(
            action for action in quiet._actions if action.dest == "timeout"
        )
        assert timeout.default == 0.0, (
            "a finite default shorter than the jobs being waited for fails exactly "
            "when it is needed"
        )

    def test_it_keeps_waiting_until_nothing_is_running(self, monkeypatch):
        import awltux.cli as cli

        # The POST consumes the first state, so three "running" replies are needed
        # before the loop sees an idle one: the point is that it keeps asking.
        calls = self._server(
            monkeypatch,
            [
                {"quiet": True, "idle": False, "running": ["news_analysis"]},
                {"quiet": True, "idle": False, "running": ["news_analysis"]},
                {"quiet": True, "idle": False, "running": ["news_analysis"]},
                {"quiet": True, "idle": True, "running": []},
            ],
        )

        assert cli.cmd_quiet(self._args()) == 0
        assert calls.count("GET /api/quiet") == 3, "it kept asking rather than giving up"

    def test_a_finite_timeout_still_gives_up_and_says_so(self, monkeypatch, capsys):
        import awltux.cli as cli

        self._server(
            monkeypatch, [{"quiet": True, "idle": False, "running": ["decision"]}]
        )
        # A clock that jumps past the deadline on the second read.
        ticks = iter([0.0, 0.0, 999.0, 999.0])

        monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))

        assert cli.cmd_quiet(self._args(timeout=5.0)) == 3
        assert "waiting for decision" in capsys.readouterr().err

    def test_a_failed_quiet_does_not_claim_success(self, monkeypatch, capsys):
        """Exit 3 is the only signal a deploying script can read."""
        import awltux.cli as cli

        self._server(monkeypatch, [{"quiet": True, "idle": False, "running": ["x"]}])
        ticks = iter([0.0, 0.0, 999.0, 999.0])
        monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))

        assert cli.cmd_quiet(self._args(timeout=1.0)) == 3
        assert "Safe to rebuild" not in capsys.readouterr().out

    def test_a_server_that_goes_away_ends_the_wait(self, monkeypatch, capsys):
        """The one way an unbounded wait can hang for ever.

        Waiting with no deadline means the only thing that ends it is an answer.
        A gone server is not a job still running, and holding the last answer it
        gave would wait for ever on a process that no longer exists.
        """
        import awltux.cli as cli

        replies = iter(
            [
                {"quiet": True, "idle": False, "running": ["decision"]},  # the POST
                None,
                None,
                None,
            ]
        )
        monkeypatch.setattr(cli, "_ask_server", lambda *a, **k: next(replies, None))
        monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)

        assert cli.cmd_quiet(self._args()) == 2
        assert "stopped answering" in capsys.readouterr().err

    def test_a_single_dropped_poll_is_ridden_out(self, monkeypatch):
        """One missed request is not a dead server."""
        import awltux.cli as cli

        replies = iter(
            [
                {"quiet": True, "idle": False, "running": ["decision"]},
                None,
                {"quiet": True, "idle": True, "running": []},
            ]
        )
        monkeypatch.setattr(cli, "_ask_server", lambda *a, **k: next(replies, None))
        monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)

        assert cli.cmd_quiet(self._args()) == 0


class TestTheElapsedLabel:
    def test_it_reads_the_way_a_person_says_it(self):
        import awltux.cli as cli

        assert cli._elapsed(8) == "8s"
        assert cli._elapsed(59) == "59s"
        assert cli._elapsed(60) == "1m00s"
        assert cli._elapsed(130) == "2m10s"
        assert cli._elapsed(826) == "13m46s"
        assert cli._elapsed(3900) == "1h05m"

    def test_the_label_covers_the_job_that_broke_the_timeout(self):
        """news_analysis measured 14 to 39 minutes; the label must not read `1m`."""
        import awltux.cli as cli

        assert cli._elapsed(2351) == "39m11s"


class TestTheOperationsPage:
    def test_it_does_not_round_a_schedule_into_a_lie(self, client):
        """Every interval the page prints must be the interval the job has.

        The page once rendered minutes rounded to a whole number, so a job running
        every 45 seconds printed "1.0m" and a weekly one printed "10080.0m". The
        first made a dead job look like a busy one, which is how its silence went
        unnoticed for a day.
        """
        from awltux.scheduler.registry import build_job_specs

        body = client.get("/jobs").text
        assert "1.0m" not in body, "the old rounded rendering"
        assert "10080.0m" not in body

        for spec in build_job_specs():
            if not spec.enabled:
                continue
            expected = fmt_interval(spec.interval_seconds)
            assert f">{expected}<" in body, (
                f"{spec.id} runs every {spec.interval_seconds}s and the page must "
                f"say {expected!r}"
            )

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

    # The real signature, ``cause`` included. A job that is owed a catch-up is scheduled with
    # its cause as a second positional argument (`SchedulerService._job_args`), so a stub
    # taking only ``spec`` passes while nothing is overdue and raises inside APScheduler the
    # moment one is -- which is a fact about the run history, not about the code under test.
    monkeypatch.setattr(service_module, "execute_job", lambda spec, cause=None: None)


class TestEveryEnabledJobIsScheduled:
    def test_none_is_left_paused(self, settings: Settings, quiet_jobs):
        """The regression test for the bug: 16 of 19 jobs were added paused.

        Asserted over the *real* registry rather than a fixture list, so a new job
        that forgets nothing in particular is still covered.

        Manual-only jobs are excluded, and the exclusion is spelled out rather than
        left to ``enabled``: in this suite every credential is ``None``, so a
        manual job is registered *disabled* and would pass this assertion by being
        skipped -- which is the vacuous pass that would let a manual job be
        accidentally scheduled in production. `test_a_manual_job_is_never_scheduled`
        is the half that holds without a credential.
        """
        service = SchedulerService(build_job_specs(settings))
        service.start()
        try:
            rows = service.status()
            enabled = [row for row in rows if row["enabled"] and not row["manual_only"]]
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
            if spec.enabled
            and spec.interval_seconds is not None
            and spec.interval_seconds < MIN_INTERVAL_SECONDS
        ]
        assert not fast, f"these run faster than the one-hour floor: {fast}"

    def test_the_news_pipeline_is_daily(self, settings: Settings):
        """The poll and everything that reads it, asserted so it is not quietly undone.

        Measured 2026-10-16, which is what makes this a decision rather than a preference:
        the poll's own provider allowance is 2,000 requests per UTC day and one walk of the
        universe spends about that, so **129 of the last 133 runs ended within two seconds
        with `stopped: [rss] budget spent`**. The runs between had nothing to fetch, and the
        four jobs downstream had nothing to read, so hourly was 23 no-ops a day either way.

        `news_sectors` is deliberately *not* in this list: it polls eleven feeds, reads
        neither the universe nor the poll's output, and is cheap. Its cadence is its own.
        """
        daily = 86_400
        intervals = {spec.id: spec.interval_seconds for spec in build_job_specs(settings)}

        for job in ("news_rss", "news_analysis", "news_relevance", "news_embeddings", "sentiment"):
            assert intervals[job] == daily, (
                f"{job} runs every {intervals[job]}s: the news pipeline is a daily one, "
                "because that is what the feeds' daily allowance pays for"
            )

    def test_a_manual_job_is_never_scheduled(self, quiet_jobs):
        """No trigger, no first run, and a run only when the button is pressed.

        Built here rather than read from the registry, because the registry's manual
        job is disabled in this suite -- every credential is ``None`` -- and an
        assertion that only holds for a credentialed deployment proves nothing.
        """
        spec = JobSpec(id="on_demand", func=_noop)
        service = SchedulerService([spec])
        service.start()
        try:
            row = service.status()[0]
            assert row["enabled"] is True, "enabled is what keeps the Run now button live"
            assert row["manual_only"] is True
            assert row["interval_seconds"] is None
            assert row["next_run"] is None, "a manual job was given a schedule"
            assert row["overdue"] is False
        finally:
            service.shutdown(wait=False)

    def test_the_registrys_repair_is_manual_only(self, settings: Settings):
        """The fact itself, asserted without a credential in sight.

        Its interval is the whole mechanism, and in this suite the job is registered
        disabled -- so every other assertion about it is skipped, and a change that
        put it back on a timer would pass the rest of the file.
        """
        from awltux.scheduler.registry import build_job_specs

        repair = next(spec for spec in build_job_specs(settings) if spec.id == "filing_summaries")
        assert repair.manual_only
        assert repair.interval_seconds is None
        assert repair.backfill, "an on-demand job must be able to say it has nothing to do"
        assert repair.requires == ("DEEPSEEK_API_KEY",)

    def test_every_scheduled_job_runs_daily(self, settings: Settings):
        """Asked for 2026-10-23: *"All the jobs can be downgraded to 1d trigger rate."*

        Asserted over the real registry, so a job added later at an hourly cadence fails here
        rather than quietly running 24 times when the rest of the pipeline runs once. The
        manual-only repair is excluded by `scheduled`: it has no cadence at all, by design.
        """
        daily = 86_400
        offenders = [
            (spec.id, spec.interval_seconds)
            for spec in build_job_specs(settings)
            if spec.scheduled and spec.interval_seconds != daily
        ]
        assert not offenders, f"these do not run once a day: {offenders}"

    def test_every_dependency_sits_shallower_than_its_dependent(self, settings: Settings):
        """The schedule's phase is derived from this, so it is the ordering property itself.

        Asserted on depths rather than on `next_run`, because a `run_on_start` job fires during
        `start()` and its next run is then a whole day out -- comparing live next-run times
        between a job that has already run and one that has not says nothing about order.
        """
        from awltux.scheduler.service import dependency_depth

        specs = build_job_specs(settings)
        depths = dependency_depth(specs)
        by_id = {spec.id: spec for spec in specs}
        wrong = [
            (spec.id, dep)
            for spec in specs
            for dep in spec.depends_on
            if dep in by_id and depths[dep] >= depths[spec.id]
        ]

        assert not wrong, f"these are not scheduled after the jobs they depend on: {wrong}"
        assert max(depths.values()) >= 2, "the registry is too flat to prove anything"

    def test_the_phase_is_a_few_minutes_per_level(self, quiet_jobs):
        """Wide enough to order the schedule, narrow enough to stay inside the day."""
        from awltux.scheduler.service import DEPTH_PHASE_SECONDS, dependency_depth

        depths = dependency_depth(build_job_specs())
        assert max(depths.values()) >= 2, "the registry has no depth to test the phase with"
        assert 60 <= DEPTH_PHASE_SECONDS <= 3_600
        assert max(depths.values()) * DEPTH_PHASE_SECONDS < 86_400 / 2, (
            "the deepest job would start more than half a day after the shallowest"
        )


class TestWhenAJobFirstRuns:
    def test_without_run_on_start_the_first_run_is_one_phase_away(self, quiet_jobs):
        """It does not fire at "now" when it sits below something, and it does not wait a
        whole interval either: a job's first run is its dependency depth times the phase.
        """
        from awltux.scheduler.service import DEPTH_PHASE_SECONDS

        before = dt.datetime.now(dt.UTC)
        spec = JobSpec(id="later", func=_noop, interval_seconds=86_400)
        root = JobSpec(id="root", func=_noop, interval_seconds=86_400)
        service = SchedulerService([root, spec])
        service.start()
        try:
            first = dt.datetime.fromisoformat(service.status()[0]["next_run"])
        finally:
            service.shutdown(wait=False)

        # `later` has no dependency, so it is depth 0 like `root`: it fires at once.
        assert (first - before).total_seconds() <= 5

        depth_two = JobSpec(id="later", func=_noop, interval_seconds=86_400, depends_on=("root",))
        service = SchedulerService([root, depth_two])
        started = dt.datetime.now(dt.UTC)
        service.start()
        try:
            row = next(row for row in service.status() if row["id"] == "later")
            waited = (dt.datetime.fromisoformat(row["next_run"]) - started).total_seconds()
        finally:
            service.shutdown(wait=False)

        assert DEPTH_PHASE_SECONDS - 5 <= waited <= DEPTH_PHASE_SECONDS + 5

    def test_run_on_start_fires_without_waiting_its_interval(self, monkeypatch):
        """Asserted by observing the run, not the clock.

        A job scheduled for "now" fires *during* `start()`, so by the time the status
        is read its next run is already one interval away -- reading the clock here
        would test the opposite of what it looks like.
        """
        import time

        import awltux.scheduler.service as service_module

        ran: list[str] = []
        monkeypatch.setattr(
            service_module, "execute_job", lambda spec, cause=None: ran.append(spec.id)
        )

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

    def test_quieting_asks_the_running_jobs_to_stop(self, quiet_jobs):
        """Pausing stops the next run starting; the ask is what stops the current one.

        Without it the wait is as long as the job. `news_rss` walks the universe for
        hours, so quiet was never quiet -- it was only early, and the rebuild still
        killed the run.
        """
        from awltux.scheduler import progress

        service = SchedulerService([])
        assert progress.stop_requested() is False

        status = service.quiet()

        assert progress.stop_requested() is True
        assert status["stopping"] is True

    def test_unquiet_withdraws_the_stop_request(self, quiet_jobs):
        """A job left holding a stop request leaves at the first checkpoint of every
        later run, so an upgrade called off would leave a container doing no work."""
        from awltux.scheduler import progress

        service = SchedulerService([])
        service.start()
        try:
            service.quiet()
            assert progress.stop_requested() is True

            status = service.unquiet()

            assert progress.stop_requested() is False
            assert status["stopping"] is False
        finally:
            service.shutdown(wait=False)

    def test_draining_asks_as_well_as_waits(self, quiet_jobs):
        """The bounded drain is the last line of defence; the ask makes it cheap.

        A drain that only waited would spend its whole budget on a job that would have
        stopped in seconds had anyone asked it to.
        """
        from awltux.scheduler import progress

        service = SchedulerService([])
        service.drain(timeout=0.1)

        assert progress.stop_requested() is True

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


class TestTheQueue:
    """A trigger queues a job; one dispatcher runs the queue in dependency order.

    Asked for 2026-10-23, with the daily cadence: *"the triggers should happen in dependency
    order and wait for the dependency to finish first."* These are the rules that make that
    true, tested against the queue and the picker directly rather than by waiting on threads:
    the ordering is a decision about the set of runnable jobs, and it is deterministic.
    """

    def _service(self, *specs, monkeypatch=None) -> SchedulerService:
        service = SchedulerService(list(specs))
        # No scheduler, no dispatcher: the queue is what is under test, and `_take_runnable`
        # is the whole decision. `start()` would also schedule triggers and start a thread.
        service._depths = __import__(
            "awltux.scheduler.service", fromlist=["dependency_depth"]
        ).dependency_depth(list(specs))
        return service

    def test_a_dependency_is_taken_before_its_dependent(self):
        """Even when the dependent's trigger fired first."""
        root = JobSpec(id="root", func=_noop, interval_seconds=86_400)
        child = JobSpec(
            id="child", func=_noop, interval_seconds=86_400, depends_on=("root",)
        )
        service = self._service(root, child)

        service._enqueue(child, "fired first")
        service._enqueue(root, "fired second")

        assert service.queued() == ["root", "child"]
        assert service._take_runnable().id == "root"
        assert service._take_runnable().id == "child"

    def test_a_job_waits_while_the_job_it_reads_is_running(self):
        """The wait itself: not skipped, not started -- held until the input finishes."""
        root = JobSpec(id="root", func=_noop, interval_seconds=86_400)
        child = JobSpec(
            id="child", func=_noop, interval_seconds=86_400, depends_on=("root",)
        )
        service = self._service(root, child)
        service._enqueue(child, None)

        service._running.add("root")  # a run of the dependency, in flight
        assert service._take_runnable() is None, "the child started under its dependency"

        service._running.discard("root")
        assert service._take_runnable().id == "child"

    def test_a_chain_runs_root_first_even_when_the_tail_fired_first(self):
        """Depth orders the whole chain, not just one link: a grandchild cannot overtake."""
        root = JobSpec(id="root", func=_noop, interval_seconds=86_400)
        child = JobSpec(
            id="child", func=_noop, interval_seconds=86_400, depends_on=("root",)
        )
        grandchild = JobSpec(
            id="grandchild", func=_noop, interval_seconds=86_400, depends_on=("child",)
        )
        service = self._service(root, child, grandchild)

        for spec in (grandchild, child, root):
            service._enqueue(spec, None)

        assert service.queued() == ["root", "child", "grandchild"]
        assert [service._take_runnable().id for _ in range(3)] == [
            "root",
            "child",
            "grandchild",
        ]

    def test_an_unrelated_job_runs_while_one_waits(self):
        """Waiting must not stop the queue: everything that can start, does."""
        root = JobSpec(id="root", func=_noop, interval_seconds=86_400)
        child = JobSpec(
            id="child", func=_noop, interval_seconds=86_400, depends_on=("root",)
        )
        other = JobSpec(id="other", func=_noop, interval_seconds=86_400)
        service = self._service(root, child, other)
        service._enqueue(child, None)
        service._enqueue(other, None)

        assert service._take_runnable().id == "other"
        assert service.queued() == ["child"], "the child is still held, not dropped"

    def test_a_job_is_queued_once_however_often_it_fires(self):
        """What `max_instances=1` and `coalesce` meant when the executor decided it."""
        spec = JobSpec(id="daily", func=_noop, interval_seconds=86_400)
        service = self._service(spec)

        service._enqueue(spec, None)
        service._enqueue(spec, None)

        assert service.queued() == ["daily"]

    def test_a_paused_scheduler_does_not_queue_and_holds_what_it_has(self):
        """Quiet stops new work and keeps the work already due, rather than losing it."""
        spec = JobSpec(id="daily", func=_noop, interval_seconds=86_400)
        service = self._service(spec)
        service._enqueue(spec, None)

        service._paused = True

        assert service._take_runnable() is None, "a paused queue handed out a job"
        assert service.queued() == ["daily"], "the due run was dropped by the pause"

    def test_quieting_reports_what_is_waiting(self):
        spec = JobSpec(id="daily", func=_noop, interval_seconds=86_400)
        service = self._service(spec)
        service._enqueue(spec, None)

        assert service.quiet_status()["queued"] == ["daily"]

    def test_a_job_that_depends_on_an_unregistered_job_is_not_held(self):
        """The registry gates jobs on credentials: a dependency that is not registered cannot
        run, so holding its dependents would hold them for ever."""
        child = JobSpec(
            id="child", func=_noop, interval_seconds=86_400, depends_on=("absent",)
        )
        service = self._service(child)
        service._enqueue(child, None)

        assert service._take_runnable().id == "child"

    def test_the_dispatcher_runs_the_queue_in_order(self, monkeypatch):
        """End to end through the thread, because the loop is what wires the picker to a run."""
        import time

        import awltux.scheduler.service as service_module

        ran: list[str] = []
        monkeypatch.setattr(
            service_module, "execute_job", lambda spec, cause=None: ran.append(spec.id)
        )

        root = JobSpec(id="root", func=_noop)
        child = JobSpec(id="child", func=_noop, depends_on=("root",))
        service = SchedulerService([root, child])
        service._start_dispatcher()
        try:
            service._enqueue(child, None)
            service._enqueue(root, None)
            deadline = time.monotonic() + 5
            while len(ran) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
        finally:
            service.shutdown(wait=False)

        assert ran == ["root", "child"]


class TestOnlyOneJobRunsAtATime:
    """The pool is bounded, because an unbounded one starves the dashboard.

    APScheduler's default pool is ten workers, and `max_instances=1` only stops one
    job overlapping *itself* -- nothing stopped ten different jobs starting together.
    With the scheduler fixed so jobs actually fire, five heavy jobs ran at once and
    the web UI stopped loading.

    Measured on the live container: one thread held **1,826 of the process's 2,212
    CPU seconds (82.6%)**, `/dashboard` took **164 seconds** where it takes 0.95s
    with nothing running, and `/jobs` did not return inside a 180-second timeout.
    The container was using 1.1 of 8 cores with no quota, so this is CPython's GIL
    and not a shortage of CPU -- adding cores would not have helped.
    """

    def test_the_pool_runs_one_job_at_a_time(self, monkeypatch):
        """Asserted by running jobs through the scheduler, not by reading a private
        attribute: the executor is APScheduler's, wrapped, and the attribute holding
        the worker count has changed name between versions. What matters is how many
        jobs run together, so that is what is measured.

        Since 2026-10-23 the serialisation is the dispatcher's: triggers enqueue and one thread
        runs the queue, which is also what makes the dependency ordering possible.
        """
        import threading
        import time

        import awltux.scheduler.service as service_module
        from awltux.scheduler.service import MAX_CONCURRENT_JOBS

        lock = threading.Lock()
        state = {"running": 0, "peak": 0}

        def probe(_spec, _cause=None) -> None:
            with lock:
                state["running"] += 1
                state["peak"] = max(state["peak"], state["running"])
            time.sleep(0.15)
            with lock:
                state["running"] -= 1

        monkeypatch.setattr(service_module, "execute_job", probe)

        specs = [
            JobSpec(id=f"j{index}", func=_noop, interval_seconds=3600) for index in range(4)
        ]
        service = SchedulerService(specs)
        service.start()
        try:
            # The dispatcher waits two seconds after start before taking anything (so a
            # restart's triggers are all queued before the first is chosen); this test is not
            # about that window.
            service._armed_at = 0.0
            due = dt.datetime.now(dt.UTC)
            for spec in specs:
                service._scheduler.modify_job(spec.id, next_run_time=due)
            time.sleep(1.5)
        finally:
            service.shutdown(wait=False)

        assert state["peak"] == 1, (
            f"{state['peak']} jobs ran at once; five at once was the measured failure "
            "and it took the dashboard down with it"
        )
        assert MAX_CONCURRENT_JOBS == 1


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
            # Before the `enabled` skip, deliberately. The one manual job is registered
            # *disabled* in this suite -- every credential is None -- so a check placed
            # after that `continue` would never run, and the page could print a blank
            # interval for it in production without any test noticing.
            if spec.manual_only:
                assert "on demand" in body, (
                    f"{spec.id} has no interval, so the page must say what starts it"
                )
                continue
            if not spec.enabled:
                continue
            expected = fmt_interval(spec.interval_seconds)
            assert f">{expected}<" in body, (
                f"{spec.id} runs every {spec.interval_seconds}s and the page must "
                f"say {expected!r}"
            )

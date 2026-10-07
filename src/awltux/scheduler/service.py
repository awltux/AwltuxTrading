"""Scheduler service: owns the APScheduler instance and the job registry.

The registry is built by :mod:`awltux.scheduler.registry`, which knows how to
turn application settings into concrete :class:`~awltux.scheduler.jobs.JobSpec`
objects. Jobs can also be triggered manually from the dashboard, so the same
function objects are used for both paths.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import time
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from awltux.scheduler import progress
from awltux.scheduler.catchup import CatchUp, catch_ups, next_run_time_for
from awltux.scheduler.jobs import JobSpec, execute_job, last_successful_runs
from awltux.timezones import as_utc

logger = logging.getLogger(__name__)

#: The fastest a job may be scheduled. Nothing in this system needs finer
#: resolution: it is a long-horizon advisory tool, the providers are free tiers with
#: rate limits, and the daily bars it reasons about change once a day.
#:
#: Declared here rather than only in `config.yaml` so a job added later cannot
#: quietly run every 45 seconds. `_schedule` warns when a spec breaks it and
#: `test_scheduler` fails, because a warning in a log nobody reads is not a guard.
MIN_INTERVAL_SECONDS = 3_600

#: How far a job's first run may be pushed out, so that jobs sharing an interval do
#: not all fire on the same tick.
#:
#: Capped at an hour, and at the job's own interval for anything faster. Randomised
#: per job at schedule time rather than fixed in the registry: a hand-picked phase is
#: a number someone has to maintain, and it silently stops spreading anything the
#: moment two jobs are given the same one. With a random offset the guarantee holds
#: for a job added next year by someone who has never read this.
FIRST_RUN_SPREAD_SECONDS = 3_600

#: How often the drain re-reads which jobs are still running, in seconds. Short
#: enough that a job finishing promptly is noticed promptly, long enough not to spin
#: on the database while a long job winds down.
POLL_SECONDS = 0.5


#: How many jobs may run at once.
#:
#: **One, and the default is the finding.** APScheduler's own default is a pool of
#: ten, and `max_instances=1` only stops *one job* overlapping itself -- nothing
#: stops ten different jobs starting together. With the scheduler fixed so that
#: jobs actually fire, that is what happened: five heavy jobs ran concurrently and
#: the dashboard stopped loading.
#:
#: Measured on the live container: the process held **1,826 of its 2,212 CPU
#: seconds in a single thread (82.6%)**, and `/dashboard` took **164 seconds**
#: where it takes 0.95s with nothing running. `/jobs` did not return at all inside
#: a 180-second timeout.
#:
#: **More CPU does not fix this.** The container was using 1.1 of 8 available cores
#: with no quota set, because CPython's GIL lets one thread run Python at a time.
#: Concurrency here buys I/O overlap and costs the responsiveness of everything
#: else in the same process -- including the web UI, which is the only way to see
#: what is happening.
#:
#: Serialising is affordable: this is a long-horizon advisory tool at hourly
#: resolution, `coalesce` already collapses missed runs into one, and a job that
#: waits its turn is a job that has not lost anything. The cost is real and is
#: recorded in ``TODO.md``: a two-hour job delays everything behind it.
MAX_CONCURRENT_JOBS = 1


def _warn_if_below_the_floor(spec: JobSpec) -> None:
    """Say so when a job is scheduled faster than this system is built to poll.

    A warning and not a refusal, because the floor is a judgement about provider
    budgets rather than a hard limit -- but a warning in a log nobody reads is not a
    guard, which is why ``test_scheduler`` fails on the registry too.
    """
    if spec.interval_seconds < MIN_INTERVAL_SECONDS:
        logger.warning(
            "job %s is scheduled every %ss, below the %ss floor; raise it in "
            "config.yaml unless this is deliberate",
            spec.id,
            spec.interval_seconds,
            MIN_INTERVAL_SECONDS,
        )


class SchedulerService:
    """Thin wrapper over APScheduler with a job registry and manual triggers."""

    def __init__(self, specs: list[JobSpec] | None = None) -> None:
        self._scheduler = BackgroundScheduler(
            timezone="UTC",
            # One worker. See MAX_CONCURRENT_JOBS: the pool is the thing that was
            # unbounded, and an unbounded pool starves the web UI it reports to.
            executors={"default": {"type": "threadpool", "max_workers": MAX_CONCURRENT_JOBS}},
            job_defaults={
                "coalesce": True,  # a missed run runs once, not N times
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )
        self._specs: dict[str, JobSpec] = {}
        self._paused = False
        self._quiet_since: dt.datetime | None = None
        if specs:
            for spec in specs:
                self.register(spec)

    # ------------------------------------------------------------- registry
    def register(self, spec: JobSpec) -> None:
        self._specs[spec.id] = spec
        if spec.enabled and self._scheduler.running:
            self._schedule(spec)

    def specs(self) -> list[JobSpec]:
        """The registered specs, in declaration order.

        Registration order is the registry's order, which is written top-to-bottom
        as the pipeline runs, so this doubles as the readable order for the
        Operations page.
        """
        return list(self._specs.values())

    def get(self, job_id: str) -> JobSpec | None:
        return self._specs.get(job_id)

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._scheduler.running:
            return
        # A new process starts with no stop outstanding. The flag lives in the module
        # and a fresh import clears it, but `start` is also reached by a service that
        # was quieted and then restarted in-process, and that one must not inherit a
        # request nobody remembered making -- the same reason `_quiet_since` is not
        # persisted.
        progress.clear_stop()
        # Read once, before anything is scheduled: the answer is a fact about how long
        # the process was away, and a job that fires during this loop would otherwise
        # change the history the remaining jobs are judged against.
        owed = self.pending_catch_ups()
        owed_by_job = {catch_up.job_id: catch_up for catch_up in owed}
        for spec in self._specs.values():
            if spec.enabled:
                self._schedule(spec, owed_by_job.get(spec.id))
        self._scheduler.start(paused=self._paused)
        logger.info(
            "scheduler started with %d jobs (%s)",
            sum(1 for s in self._specs.values() if s.enabled),
            ", ".join(sorted(s.id for s in self._specs.values() if s.enabled)) or "none",
        )
        if owed:
            # Named in one line, because this is the sentence that says the night off
            # cost nothing: without it the morning just looks busy for no stated reason.
            logger.info(
                "catching up %d job(s) whose trigger came due while nothing was "
                "running: %s",
                len(owed),
                ", ".join(
                    f"{catch_up.job_id} ({catch_up.missed} missed)" for catch_up in owed
                ),
            )

    def pending_catch_ups(self, now: dt.datetime | None = None) -> list[CatchUp]:
        """What is owed to each job after the process was not running.

        A failure to read the history means nothing is caught up rather than that
        startup fails: an unreadable run table is a reason to run the normal schedule,
        not a reason to refuse to start. It is logged for the same reason the drain
        logs its own -- a silent empty list is indistinguishable from being up to date.
        """
        from awltux.db import session_scope

        try:
            with session_scope() as session:
                last_successes = last_successful_runs(session)
        except Exception:  # pragma: no cover - an unreadable DB must not stop startup
            logger.exception("could not read the run history; catching nothing up")
            return []
        return catch_ups(self._specs.values(), last_successes, now or dt.datetime.now(dt.UTC))

    def shutdown(self, wait: bool = False) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("scheduler stopped")

    def pause(self) -> None:
        self._paused = True
        if self._scheduler.running:
            self._scheduler.pause()

    def resume(self) -> None:
        self._paused = False
        if self._scheduler.running:
            self._scheduler.resume()

    @property
    def paused(self) -> bool:
        return self._paused

    # --------------------------------------------------------------- quieting
    def quiet(self) -> dict[str, object]:
        """Stop taking on new work, so an upgrade can wait for what is in flight.

        The problem this solves is a rebuild, not a crash. `docker compose up -d`
        sends SIGTERM and the lifespan drains (below), but the drain has to be
        bounded: a job can legitimately run for minutes, and the container is going
        to be stopped whether or not it has finished. So the drain turns a long job
        into a *killed* job -- its run row is left open mid-batch, and the next start
        closes it as interrupted. Since catch-up landed that is no longer lost work:
        an unsuccessful run does not count, so the next start repeats the job. It is
        still worth avoiding, because the repeat spends the provider budget twice.

        Quieting moves that decision earlier and out of the shutdown path. The
        scheduler stops handing out runs, the in-flight ones finish in their own
        time, and the rebuild then finds nothing to interrupt. The database is left
        in a state that needs no repair, which is the whole point: it is the only
        copy of the universe.

        Reversible, because an aborted upgrade must not leave a container that will
        never work again: :meth:`unquiet`. State lives in this process only, so a
        restart clears it -- a restart is itself the upgrade, and the new process
        should not inherit a pause nobody remembered asking for.

        **It also asks the jobs already running to stop**, at their next checkpoint
        (``progress.checkpoint``). Pausing stops new runs starting; it does nothing for
        the walk over thousands of rows that is already halfway through, and that walk
        is the thing the rebuild has to wait for. Without the ask, `news_rss` runs for
        hours and the wait is as long as the job -- so quiet was never actually quiet,
        it was just early. Jobs that have no checkpoint still run to the end, and this
        announcement cannot promise otherwise.
        """
        self.pause()
        self._quiet_since = self._quiet_since or dt.datetime.now(dt.UTC)
        progress.request_stop()
        running = self.running()
        logger.info("quieted; asking %d running job(s) to stop", len(running))
        return self.quiet_status()

    def unquiet(self) -> dict[str, object]:
        """Undo :meth:`quiet` -- resume scheduling, and withdraw the stop request.

        Withdrawing it is not tidiness. A job left holding a stop request stops at the
        first checkpoint of its next run and every run after it, so an upgrade that was
        called off would leave a process that does no work and says nothing about why.
        """
        self._quiet_since = None
        progress.clear_stop()
        self.resume()
        logger.info("resumed; scheduling is live again")
        return self.quiet_status()

    @property
    def quiet_since(self) -> dt.datetime | None:
        return self._quiet_since

    def quiet_status(self) -> dict[str, object]:
        """Whether new work is being refused, and what is still finishing.

        ``idle`` is the question an upgrade script actually asks: quiet *and*
        nothing running. Quiet alone is not safe to rebuild against -- the pause
        stops the next job starting and does nothing about the one already writing.
        """
        running = self.running()
        return {
            "quiet": self._quiet_since is not None,
            "quiet_since": (
                self._quiet_since.isoformat() if self._quiet_since is not None else None
            ),
            # Whether the running jobs have been asked to leave at their next
            # checkpoint. Distinct from `quiet`, which is about new work: a reader
            # watching a long job wants to know the ask was made, because that is what
            # says the wait is bounded by the job's next item rather than by its end.
            "stopping": progress.stop_requested(),
            "running": running,
            "idle": self._quiet_since is not None and not running,
        }

    def running(self) -> list[str]:
        """Jobs with a run open right now, by name.

        Read from the run table rather than from this process's thread bookkeeping:
        an open row is what a *reader* can see, and it survives the process that
        opened it, which is exactly the property that matters when the process is
        about to go away.
        """
        from awltux.db import session_scope
        from awltux.scheduler.jobs import running_jobs

        try:
            with session_scope() as session:
                return sorted(running_jobs(session))
        except Exception:  # pragma: no cover - an unreadable DB is not a reason to hang
            logger.exception("could not read the running jobs")
            return []

    def wait_for_idle(self, timeout: float) -> list[str]:
        """Poll until nothing is running, or the timeout expires. Returns stragglers.

        The loop shared by the shutdown drain and the explicit quiet: both are asking
        the same question of the same table, and only the deadline differs.
        """
        deadline = time.monotonic() + max(timeout, 0.0)
        running = self.running()
        while running and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
            running = self.running()
        return running

    def drain(self, timeout: float) -> list[str]:
        """Stop scheduling, and wait for what is already running. Returns the stragglers.

        **Pausing is not draining.** Pausing stops APScheduler handing out new runs;
        it does nothing about the job already halfway through writing. Those are the
        ones that matter when a container is about to be replaced, because a job
        killed mid-batch leaves its run open and its work half-done -- the next start
        closes the run as interrupted, and catch-up then repeats the job, so what is
        spent is the provider budget rather than the outcome.

        Bounded on purpose. A job here can legitimately run for many minutes and the
        container is going to be stopped whether this returns or not, so waiting
        indefinitely would only convert a clean upgrade into a timeout kill.

        This is the last line of defence, for a SIGTERM nobody warned the process
        about. The intended path is :meth:`quiet` beforehand, which leaves nothing
        for this to interrupt.

        It asks as well as waits, which is the same ask :meth:`quiet` makes: a drain
        that only waited would spend its whole budget on a job that would have stopped
        in seconds had anyone asked it to.
        """
        self.pause()
        progress.request_stop()
        return self.wait_for_idle(timeout)

    # -------------------------------------------------------------- internals
    def _schedule(self, spec: JobSpec, owed: CatchUp | None = None) -> None:
        """Add a job to the scheduler, or pause it, according to the spec.

        **`next_run_time` must be omitted, never set to None.** APScheduler reads an
        explicit ``None`` as *"add this job paused"*, so passing it for a job that is
        not run-on-start registers the job and then never fires it. That is what this
        did, and it meant every job without ``run_on_start`` -- sixteen of nineteen --
        was silently paused from the moment the scheduler was written: no runs in the
        history, and no next run on the Operations page. The two symptoms are the
        same bug seen from two directions. Leaving the argument out is what lets the
        interval trigger compute the first fire time, which is what "every 45
        seconds" is supposed to mean; :meth:`_first_run` says which case applies.

        The first run of everything that is not run-on-start is randomised across the
        hour, so nineteen jobs sharing an hourly interval do not fire on the same
        second and spend their provider budgets together. The offset is applied once,
        as the trigger's start date, rather than as jitter on every fire: jitter would
        let an hourly job land anywhere between thirty and ninety minutes after the
        last run, and the Operations page prints a schedule that would then be untrue.
        """
        _warn_if_below_the_floor(spec)
        now = dt.datetime.now(dt.UTC)
        window = min(spec.interval_seconds, FIRST_RUN_SPREAD_SECONDS)

        trigger = IntervalTrigger(
            seconds=spec.interval_seconds,
            start_date=now + dt.timedelta(seconds=random.uniform(0, window)),
            timezone="UTC",
        )

        self._scheduler.add_job(
            execute_job,
            trigger=trigger,
            args=self._job_args(spec, owed),
            id=spec.id,
            name=spec.description or spec.id,
            replace_existing=True,
            max_instances=spec.max_instances,
            **self._first_run(spec, owed, now),
        )

    @staticmethod
    def _first_run(spec: JobSpec, owed: CatchUp | None, now: dt.datetime) -> dict[str, Any]:
        """When this job first fires, as APScheduler options. Empty means "let it decide".

        Three cases, in the order they take precedence:

        * **Owed a catch-up.** Scheduled *at* the first missed trigger, with
          ``misfire_grace_time`` disabled. Both are load-bearing. The first-missed
          trigger is monotone with how long the job has gone unrun, so the catch-ups
          run stalest-first, and it keeps the job on the phase it already had rather
          than re-anchoring it to the restart; APScheduler's ``coalesce`` then
          collapses the backlog it enumerates into one run and advances the next fire
          time from the last of them. ``misfire_grace_time=None`` is what makes a
          *past* due time run at all -- the 300-second default is measured in the
          executor (``apscheduler/executors/base.py``), and it would discard exactly
          the catch-up this exists to make, because an hourly job that missed a day is
          twenty-three hours past due, not five minutes.
        * **``run_on_start``.** Deliberately ahead of the interval: a fresh container
          should populate its dependencies now rather than one interval from now. The
          spread does not apply -- this is the bootstrap path.
        * **Neither.** Nothing is passed, so the trigger's own start date decides, and
          the job gets its spread first run.
        """
        if owed is not None:
            return {"next_run_time": next_run_time_for(owed), "misfire_grace_time": None}
        if spec.run_on_start:
            return {"next_run_time": now + dt.timedelta(seconds=spec.start_delay_seconds)}
        return {}

    @staticmethod
    def _job_args(spec: JobSpec, owed: CatchUp | None) -> list[Any]:
        """What ``execute_job`` is called with: the spec, and why it fired when it did."""
        return [spec] if owed is None else [spec, owed.cause]

    # --------------------------------------------------------------- manual
    def run_now(self, job_id: str, *, wait: bool = True):
        """Trigger a job immediately (used by the CLI and the dashboard)."""
        spec = self._specs.get(job_id)
        if spec is None:
            raise KeyError(f"unknown job {job_id!r}")
        if wait:
            return execute_job(spec)
        self._scheduler.add_job(execute_job, args=[spec], id=f"{job_id}__manual")
        return None

    def status(self) -> list[dict[str, object]]:
        """Job status for the dashboard's health panel."""
        jobs = {job.id: job for job in self._scheduler.get_jobs()}
        now = dt.datetime.now(dt.UTC)
        behind = self._behind_by_job(now)
        out: list[dict[str, object]] = []
        for spec in self._specs.values():
            job = jobs.get(spec.id)
            next_run = as_utc(job.next_run_time) if job and job.next_run_time else None
            out.append(
                {
                    "id": spec.id,
                    "description": spec.description,
                    "interval_seconds": spec.interval_seconds,
                    "enabled": spec.enabled,
                    "paused": self._paused,
                    # The declared pipeline order, so an API consumer does not have
                    # to read the registry to know what must run first.
                    "needs": list(spec.depends_on),
                    "next_run": next_run.isoformat() if next_run else None,
                    # Derived from the *history*, not from `next_run`, and that is the
                    # whole point of the field. APScheduler advances `next_run_time`
                    # when a job is handed to the executor, not when it starts, so a
                    # catch-up queued behind the single worker already has a next run
                    # in the future while its data is hours stale. Measured on the
                    # first live catch-up: ten jobs were queued, `news_relevance` was
                    # 183 minutes past a one-hour interval, and every one of them read
                    # `next_run` in the future. Asking the same question the scheduler
                    # asks (`catchup.catch_up_for`) is what keeps the page and the
                    # scheduler from disagreeing.
                    "overdue": spec.id in behind,
                }
            )
        return out

    def _behind_by_job(self, now: dt.datetime) -> set[str]:
        """Jobs whose last successful run is more than an interval old.

        A failure to read the history reports nothing as behind: an unreadable run
        table is a missing badge, not a reason for the Operations page to fail.
        """
        from awltux.db import session_scope

        try:
            with session_scope() as session:
                last_successes = last_successful_runs(session)
        except Exception:  # pragma: no cover - an unreadable DB must not break a page
            logger.exception("could not read the run history for the overdue badge")
            return set()
        return {
            catch_up.job_id
            for catch_up in catch_ups(self._specs.values(), last_successes, now)
        }

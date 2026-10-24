"""Scheduler service: owns the APScheduler instance, the job registry, and the run queue.

The registry is built by :mod:`awltux.scheduler.registry`, which knows how to
turn application settings into concrete :class:`~awltux.scheduler.jobs.JobSpec`
objects. Jobs can also be triggered manually from the dashboard, so the same
function objects are used for both paths.

**Triggers enqueue; one dispatcher runs the queue in dependency order.** APScheduler is the
clock and nothing more: each trigger fires a job's *queue* entry, not the job. A single
dispatcher thread then takes the shallowest job whose declared dependencies have finished,
runs it, and looks again -- so a job never begins while something it reads is still running,
and a cycle that comes due together runs in pipeline order rather than in whatever order the
triggers happened to land. See :class:`_Queued` and :meth:`SchedulerService._dispatch_loop`.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from awltux import schedule_time
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

#: How often the dispatcher re-reads the daily trigger time, in seconds.
#:
#: The value lives in the database because the Operations page can change it, and the page runs
#: in a *different process* from the scheduler -- so there is nothing to call and the scheduler
#: has to look. Twenty seconds is well under the resolution of a daily cycle and one primary-key
#: read every twenty seconds is nothing.
SCHEDULE_RECHECK_SECONDS = 20.0

#: How long the dispatcher waits at startup before taking its first job.
#:
#: **A trigger fires a moment after `start()` returns**, and so does a catch-up: without this,
#: whichever trigger landed first was taken and run before the jobs it depends on had even been
#: queued. Measured on the deployed build, 2026-10-23: the first cycle after a restart ran
#: `news_rss` at 17:45:46 and `t212_instruments` at 17:45:54 -- the dependency order the queue
#: exists to enforce, inverted by eight seconds of arming. Two seconds is enough for every
#: trigger to have fired (they are sub-millisecond apart) and invisible to a reader.
STARTUP_GRACE_SECONDS = 2.0

#: How much later in the day each level of the dependency graph fires.
#:
#: Every job is daily (2026-10-23), so what used to be a random spread across the hour is now a
#: *phase*: a job with no dependencies fires at the top of the cycle, its dependents ten minutes
#: later, their dependents ten minutes after that. The dispatcher is what actually guarantees
#: the order; this is what makes the printed schedule and the run history read in pipeline order,
#: so a reader can see why one job is waiting on another rather than inferring it from a graph.
DEPTH_PHASE_SECONDS = 600

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
#: Serialising is affordable: this is a long-horizon advisory tool, `coalesce` already
#: collapses missed runs into one, and a job that waits its turn is a job that has not lost
#: anything. Since 2026-10-23 that wait is *stated* as well as enforced: one dispatcher thread
#: runs the queue, so "one at a time" and "in dependency order" are the same guarantee.
MAX_CONCURRENT_JOBS = 1


def _warn_if_below_the_floor(spec: JobSpec) -> None:
    """Say so when a job is scheduled faster than this system is built to poll.

    A warning and not a refusal, because the floor is a judgement about provider
    budgets rather than a hard limit -- but a warning in a log nobody reads is not a
    guard, which is why ``test_scheduler`` fails on the registry too.
    """
    if spec.interval_seconds is not None and spec.interval_seconds < MIN_INTERVAL_SECONDS:
        logger.warning(
            "job %s is scheduled every %ss, below the %ss floor; raise it in "
            "config.yaml unless this is deliberate",
            spec.id,
            spec.interval_seconds,
            MIN_INTERVAL_SECONDS,
        )


def dependency_depth(specs: list[JobSpec]) -> dict[str, int]:
    """How many jobs deep each spec sits in the declared pipeline.

    A spec with no dependencies is depth 0; one whose dependencies all sit at depth *n* is
    depth *n+1*. It is a pure function of the registry, and it is what the schedule's phase is
    derived from, so a job whose input is a job always fires later in the day than that job.

    A dependency naming a job that is not registered contributes nothing: the registry gates
    jobs on credentials, and a job disabled for a missing key must not push its dependents to a
    phase they can never execute in. A cycle raises, because a phase cannot be computed for one
    and the registry is not allowed to have one (`tests/test_job_dependencies.py` asserts it).
    """
    by_id = {spec.id: spec for spec in specs}
    depths: dict[str, int] = {}

    def depth_of(spec: JobSpec, seen: frozenset[str]) -> int:
        if spec.id in depths:
            return depths[spec.id]
        if spec.id in seen:
            raise ValueError(f"dependency cycle through {spec.id!r}")
        known = [by_id[dep] for dep in spec.depends_on if dep in by_id]
        reached = frozenset(seen | {spec.id})
        depth = 0 if not known else 1 + max(depth_of(dep, reached) for dep in known)
        depths[spec.id] = depth
        return depth

    for spec in specs:
        depth_of(spec, frozenset())
    return depths


@dataclass(slots=True)
class _Queued:
    """One due run waiting for the dispatcher."""

    spec: JobSpec
    cause: str | None
    #: When its trigger came due, which is the tie-break within one dependency depth. The
    #: trigger's due time rather than "now": a catch-up is owed from the moment it missed, and
    #: a job whose trigger fired an hour ago has waited longer than one that fired just now.
    due: dt.datetime
    #: Dependency depth, from :func:`dependency_depth`.
    depth: int

    @property
    def id(self) -> str:
        return self.spec.id



class SchedulerService:
    """Thin wrapper over APScheduler with a job registry and manual triggers."""

    def __init__(
        self, specs: list[JobSpec] | None = None, *, settings: Any = None
    ) -> None:
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
        # The queue, and everything that guards it. One condition variable rather than a
        # queue + a lock + an event: the dispatcher waits on it, a trigger notifies it, and a
        # run finishing notifies it, and every one of those is the same question -- has the
        # set of runnable jobs changed?
        self._condition = threading.Condition()
        self._queue: list[_Queued] = []
        self._depths: dict[str, int] = {}
        self._dispatcher: threading.Thread | None = None
        self._stopping = False
        #: No job is handed out before this, so the first cycle's triggers are all in the queue
        #: before the first one is chosen. See :data:`STARTUP_GRACE_SECONDS`.
        self._armed_at = 0.0
        #: Jobs executing *right now*, by id. At most one from the dispatcher; `run_now(wait=True)`
        #: adds its own for the length of the call, so the ordering rule can see a manual run.
        self._running: set[str] = set()
        # The daily cycle's start, and the zone it is written in. Read once at `start()` and
        # re-read every SCHEDULE_RECHECK_SECONDS so a change made on the Operations page takes
        # effect without a restart -- see `_maybe_reschedule`.
        self._settings = settings
        self._daily_at = ""
        self._zone = dt.UTC
        self._next_recheck = 0.0
        #: What the triggers were last built around, so a change can be noticed.
        self._scheduled_with = ""
        if specs:
            for spec in specs:
                self.register(spec)

    # ------------------------------------------------------------- registry
    def register(self, spec: JobSpec) -> None:
        self._specs[spec.id] = spec
        # Recomputed on registration rather than once: the phase of every job depends on the
        # graph, and a spec added after the scheduler started must land in the right place.
        self._depths = dependency_depth(list(self._specs.values()))
        if spec.scheduled and self._scheduler.running:
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
        self._depths = dependency_depth(list(self._specs.values()))
        self._read_schedule_time()
        self._scheduled_with = self._daily_at
        self._start_dispatcher()
        # Read once, before anything is scheduled: the answer is a fact about how long
        # the process was away, and a job that fires during this loop would otherwise
        # change the history the remaining jobs are judged against.
        owed = self.pending_catch_ups()
        owed_by_job = {catch_up.job_id: catch_up for catch_up in owed}
        for spec in self._specs.values():
            # A manual-only job is registered so it can be run from the Operations page,
            # and registered is all it is: no trigger, no first run, no catch-up. That
            # is the whole of what makes "only when somebody decides" true.
            if spec.scheduled:
                self._schedule(spec, owed_by_job.get(spec.id))
        self._scheduler.start(paused=self._paused)
        scheduled = [spec for spec in self._specs.values() if spec.scheduled]
        logger.info(
            "scheduler started with %d jobs, daily at %s %s (%s)",
            len(scheduled),
            self._daily_at,
            self._zone.key,
            ", ".join(sorted(s.id for s in scheduled)) or "none",
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

    # ----------------------------------------------------------- the daily time
    def _read_schedule_time(self) -> None:
        """Take the time of day in force, and the zone it is written in.

        The override the Operations page writes wins over `config/config.yaml`, and the zone is
        the *installation's* (`app.timezone`) rather than the reader's cookie: a schedule is a
        property of this deployment, and a page opened in another zone must not move it.
        """
        settings = self._settings
        if settings is None:
            from awltux.config import get_settings

            settings = get_settings()
        self._settings = settings
        self._daily_at = schedule_time.effective(settings)
        self._zone = schedule_time.zone_for(settings)

    def _maybe_reschedule(self) -> None:
        """Rebuild the triggers if the daily time was changed on another process.

        The Operations page writes the value to the database, and the scheduler is a *different
        process* -- so nothing can call into it. Re-reading on a timer is the honest alternative:
        at most `SCHEDULE_RECHECK_SECONDS` after a change, every trigger is rebuilt against the
        new anchor (`replace_existing=True`), and the change is logged because a schedule that
        moved without saying so is exactly the kind of silent behaviour this tree avoids.
        """
        self._next_recheck = time.monotonic() + SCHEDULE_RECHECK_SECONDS
        try:
            self._read_schedule_time()
        except Exception:  # pragma: no cover - a bad setting must not stop the clock
            logger.exception("could not re-read the daily trigger time; keeping %s", self._daily_at)
            return
        if self._daily_at == self._scheduled_with:
            return
        logger.info(
            "daily trigger time changed from %s to %s; rebuilding %d trigger(s)",
            self._scheduled_with,
            self._daily_at,
            sum(1 for spec in self._specs.values() if spec.scheduled),
        )
        self._scheduled_with = self._daily_at
        for spec in self._specs.values():
            if spec.scheduled:
                self._schedule(spec)

    def scheduled_daily_at(self) -> str:
        """The time the triggers are currently built around, for the page and the log."""
        return self._scheduled_with

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
        # The dispatcher first: it is what hands work out, and a queue it is still draining
        # while the scheduler goes away would run jobs the caller asked to stop. Queued runs are
        # dropped rather than run -- their triggers have already been counted, and the next
        # start catches up whatever is actually stale (`scheduler/catchup.py`).
        with self._condition:
            self._stopping = True
            self._queue.clear()
            self._condition.notify_all()
        dispatcher, self._dispatcher = self._dispatcher, None
        if dispatcher is not None and wait:
            dispatcher.join(timeout=POLL_SECONDS * 4)
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("scheduler stopped")

    def pause(self) -> None:
        self._paused = True
        if self._scheduler.running:
            self._scheduler.pause()
        with self._condition:
            # The dispatcher checks `_paused` before every pick, and this is what wakes it to
            # check: without the notify it would sit in `wait` and start one more job.
            self._condition.notify_all()

    def resume(self) -> None:
        self._paused = False
        if self._scheduler.running:
            self._scheduler.resume()
        with self._condition:
            self._condition.notify_all()

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

        ``queued`` is what is due and waiting its turn -- either behind the run in progress or
        behind a job it depends on. It is reported because it is *dropped* on shutdown: a reader
        deciding whether to rebuild should be able to see that two runs were waiting rather than
        discover it from the next start's catch-up.
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
            "queued": self.queued(),
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
    def _schedule(
        self, spec: JobSpec, owed: CatchUp | None = None, *, first_run: bool = True
    ) -> None:
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

        **The daily cycle is anchored to a time of day**, not to the process. Every job fires at
        the configured `schedule.daily_at` (06:00 by default, in `app.timezone`) offset by its
        dependency depth: a job with no dependencies starts at the anchor, its dependents ten
        minutes later (:data:`DEPTH_PHASE_SECONDS`), and so on. The value can be changed from the
        Operations page, and :meth:`_maybe_reschedule` rebuilds these triggers when it is.

        It used to be an interval from *now* with a random spread across the hour, which meant the
        cycle drifted to whenever the process last started. With a daily cadence that is the wrong
        thing to anchor: a restart at noon would move the "daily" run to noon.
        """
        interval = spec.interval_seconds
        if interval is None:
            # A manual-only job has no trigger *by definition* -- "no interval" and "no
            # timer" are one fact, not two -- so there is nothing to add. Checked here
            # as well as at the two call sites because this is the function that would
            # otherwise do arithmetic on `None`.
            return
        _warn_if_below_the_floor(spec)
        now = dt.datetime.now(dt.UTC)
        offset = min(
            self._depths.get(spec.id, 0) * DEPTH_PHASE_SECONDS,
            # Half the interval, so a job whose depth would push its first run past its own
            # cadence still fires inside it. Only reachable for a sub-daily interval, which the
            # registry no longer has, but a phase longer than the interval would silently shift
            # the whole schedule.
            max(interval // 2, 0),
        )
        anchor = schedule_time.next_anchor(now, self._daily_at, self._zone)
        # A daily job is anchored to the time of day; anything faster is not part of the daily
        # cycle and simply starts its own interval from now, at its phase.
        start = (
            anchor + dt.timedelta(seconds=offset)
            if interval >= 86_400
            else now + dt.timedelta(seconds=max(offset, 1))
        )

        trigger = IntervalTrigger(
            seconds=interval,
            start_date=start,
            timezone="UTC",
        )

        self._scheduler.add_job(
            # The trigger *queues*; the dispatcher runs. See the module docstring.
            self._enqueue,
            trigger=trigger,
            args=self._job_args(spec, owed),
            id=spec.id,
            name=spec.description or spec.id,
            replace_existing=True,
            max_instances=spec.max_instances,
            **(self._first_run(spec, owed, now) if first_run else {}),
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
        """What the queue entry is created with: the spec, and why it fired when it did."""
        return [spec] if owed is None else [spec, owed.cause]

    # ---------------------------------------------------------------- the queue
    def _enqueue(self, spec: JobSpec, cause: str | None = None) -> None:
        """Put a due run on the queue. The trigger's whole body.

        Cheap and non-blocking on purpose: the caller is APScheduler's executor, and a body
        that ran the job itself is what made a long job delay every trigger behind it.

        **One entry per job.** A job whose previous trigger is still queued or running is not
        queued again -- that is what ``coalesce`` and ``max_instances=1`` used to mean when the
        executor decided it, and it is the same rule here: a daily job that overran its own
        interval should not come back with a second copy of itself the moment the first ends.
        """
        with self._condition:
            if self._stopping or self._paused:
                return
            if spec.id in self._running or any(item.id == spec.id for item in self._queue):
                logger.info("job %s is already queued or running; not queuing it again", spec.id)
                return
            self._queue.append(
                _Queued(
                    spec=spec,
                    cause=cause,
                    due=dt.datetime.now(dt.UTC),
                    depth=self._depths.get(spec.id, 0),
                )
            )
            self._condition.notify_all()

    def _start_dispatcher(self) -> None:
        """Start the thread that runs the queue, if it is not already running."""
        if self._dispatcher is not None and self._dispatcher.is_alive():
            return
        with self._condition:
            self._stopping = False
            self._armed_at = time.monotonic() + STARTUP_GRACE_SECONDS
            self._dispatcher = threading.Thread(
                target=self._dispatch_loop, name="scheduler-dispatch", daemon=True
            )
            self._dispatcher.start()

    def _dispatch_loop(self) -> None:
        """Run queued jobs one at a time, in dependency order, for the life of the process.

        **This loop is the guarantee the queue exists for.** It takes the shallowest job whose
        declared dependencies are neither queued nor running, runs it to completion, and only
        then looks again -- so a job never starts while something it reads is still going, and a
        cycle that came due together runs prices-then-fundamentals-then-valuations rather than in
        whatever order the triggers landed. Nothing is skipped for being early: an unrunnable job
        stays queued, which is the difference between waiting for a dependency and refusing a run.

        It waits on the condition rather than polling hard, and it stops when
        :meth:`shutdown` sets the flag. A paused scheduler holds the queue rather than dropping
        it, so quiet does not lose requests that had already come due.
        """
        while True:
            with self._condition:
                item = None
                while item is None:
                    if self._stopping:
                        return
                    if time.monotonic() >= self._next_recheck:
                        # Outside the lock would be tidier, but the rebuild has to be serialised
                        # against a pick, and a pick is the only thing that reads `_daily_at`.
                        self._maybe_reschedule()
                    if not self._paused:
                        item = self._take_runnable()
                    if item is None:
                        self._condition.wait(POLL_SECONDS)
                self._running.add(item.id)
            try:
                execute_job(item.spec, item.cause)
            except Exception:  # pragma: no cover - execute_job records its own failures
                logger.exception("the dispatcher failed while running %s", item.id)
            finally:
                with self._condition:
                    self._running.discard(item.id)
                    self._condition.notify_all()
                self._reanchor(item.id)

    def _reanchor(self, job_id: str) -> None:
        """Put a job that has just run back onto the daily anchor.

        **A trigger advances from when it last fired, not from the anchor**, so without this a
        run that happened off-anchor takes the job with it: a catch-up at 09:59 would run daily
        at 09:59 for ever, and the daily time would no longer be the daily time. Measured on the
        deployed build the first time the anchor went in -- `news_rss` catch-up at 09:59 and
        `macro_rates` at 10:47 were both scheduled a day on from that instant.

        Rebuilding the trigger is one `add_job(replace_existing=True)` per run, which is nothing
        next to a job that just spent minutes working, and it is skipped when the scheduler is
        going away or the job is not one we scheduled.
        """
        if self._stopping or not self._scheduler.running:
            return
        spec = self._specs.get(job_id)
        if spec is None or not spec.scheduled:
            return
        # Not a first run: `run_on_start` and a catch-up both override `next_run_time` to
        # *now*, and re-applying that after the job has just run is a hot loop -- measured, it
        # fired 75 times in a second.
        self._schedule(spec, first_run=False)

    def _take_runnable(self) -> _Queued | None:
        """Remove and return the next job that may start. Holds the condition.

        Ordered by dependency depth first, then by when the trigger came due: the depth is what
        makes a cycle run in pipeline order, and the due time is the tie-break between jobs that
        are independent of each other -- including a catch-up, which is owed from the moment it
        missed rather than from when the process noticed.

        A paused scheduler hands out nothing, and the check is here rather than only in
        :meth:`_dispatch_loop` because "may anything start now" is a fact about the queue: quiet
        must not lose the work already due, and it must not hand it out either.
        """
        if self._paused or time.monotonic() < self._armed_at:
            return None
        queued_ids = {item.id for item in self._queue}
        busy = queued_ids | self._running
        for item in sorted(self._queue, key=lambda entry: (entry.depth, entry.due)):
            if busy.intersection(item.spec.depends_on):
                continue
            self._queue.remove(item)
            return item
        return None

    def queued(self) -> list[str]:
        """The jobs waiting for the dispatcher, in the order they will be considered."""
        with self._condition:
            return [item.id for item in sorted(self._queue, key=lambda e: (e.depth, e.due))]

    # --------------------------------------------------------------- manual
    def run_now(self, job_id: str, *, wait: bool = True):
        """Trigger a job immediately (used by the CLI and the dashboard).

        ``wait=True`` runs it on this thread and returns its result, which is what the CLI's
        ``--direct`` path and the tests use. ``wait=False`` queues it instead of handing it to
        APScheduler: it then waits for its own dependencies like any other run, which is the
        behaviour the queue exists for -- a manual decision sweep should not read valuations
        that are still being written.
        """
        spec = self._specs.get(job_id)
        if spec is None:
            raise KeyError(f"unknown job {job_id!r}")
        if not wait:
            self._enqueue(spec, "run by hand")
            return None
        with self._condition:
            self._running.add(spec.id)
        try:
            return execute_job(spec)
        finally:
            with self._condition:
                self._running.discard(spec.id)
                self._condition.notify_all()

    def status(self) -> list[dict[str, object]]:
        """Job status for the dashboard's health panel."""
        jobs = {job.id: job for job in self._scheduler.get_jobs()}
        now = dt.datetime.now(dt.UTC)
        behind = self._behind_by_job(now)
        waiting = set(self.queued())
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
                    # True where `interval_seconds` is None: the page must say "on
                    # demand" rather than print an interval of nothing, and a reader
                    # must be able to tell "never fires by itself" from "paused".
                    "manual_only": spec.manual_only,
                    "paused": self._paused,
                    # The declared pipeline order, so an API consumer does not have
                    # to read the registry to know what must run first.
                    "needs": list(spec.depends_on),
                    "next_run": next_run.isoformat() if next_run else None,
                    # Due and waiting for its turn -- behind the run in progress, or behind a
                    # job it depends on. This is the state the queue introduced, and without it
                    # a job that is about to run is indistinguishable from one that is not due.
                    "queued": spec.id in waiting,
                    # Derived from the *history*, not from `next_run`, and that is the
                    # whole point of the field. APScheduler advances `next_run_time`
                    # when a job's trigger fires, not when it starts, so a catch-up queued
                    # behind the single worker already has a next run in the future while its
                    # data is hours stale. Measured on the first live catch-up: ten jobs were
                    # queued, `news_relevance` was 183 minutes past a one-hour interval, and
                    # every one of them read `next_run` in the future. Asking the same question
                    # the scheduler asks (`catchup.catch_up_for`) is what keeps the page and the
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

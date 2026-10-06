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

from awltux.scheduler.jobs import JobSpec, execute_job

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


class SchedulerService:
    """Thin wrapper over APScheduler with a job registry and manual triggers."""

    def __init__(self, specs: list[JobSpec] | None = None) -> None:
        self._scheduler = BackgroundScheduler(
            timezone="UTC",
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
        for spec in self._specs.values():
            if spec.enabled:
                self._schedule(spec)
        self._scheduler.start(paused=self._paused)
        logger.info(
            "scheduler started with %d jobs (%s)",
            sum(1 for s in self._specs.values() if s.enabled),
            ", ".join(sorted(s.id for s in self._specs.values() if s.enabled)) or "none",
        )

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
        closes it as interrupted. Honest, but still lost work.

        Quieting moves that decision earlier and out of the shutdown path. The
        scheduler stops handing out runs, the in-flight ones finish in their own
        time, and the rebuild then finds nothing to interrupt. The database is left
        in a state that needs no repair, which is the whole point: it is the only
        copy of the universe.

        Reversible, because an aborted upgrade must not leave a container that will
        never work again: :meth:`unquiet`. State lives in this process only, so a
        restart clears it -- a restart is itself the upgrade, and the new process
        should not inherit a pause nobody remembered asking for.
        """
        self.pause()
        self._quiet_since = self._quiet_since or dt.datetime.now(dt.UTC)
        running = self.running()
        logger.info("quieted; %d job(s) still running", len(running))
        return self.quiet_status()

    def unquiet(self) -> dict[str, object]:
        """Undo :meth:`quiet` -- resume scheduling."""
        self._quiet_since = None
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
        closes the run as interrupted, which is honest but is still lost work.

        Bounded on purpose. A job here can legitimately run for many minutes and the
        container is going to be stopped whether this returns or not, so waiting
        indefinitely would only convert a clean upgrade into a timeout kill.

        This is the last line of defence, for a SIGTERM nobody warned the process
        about. The intended path is :meth:`quiet` beforehand, which leaves nothing
        for this to interrupt.
        """
        self.pause()
        return self.wait_for_idle(timeout)

    # -------------------------------------------------------------- internals
    def _schedule(self, spec: JobSpec) -> None:
        """Add a job to the scheduler, or pause it, according to the spec.

        **`next_run_time` must be omitted, never set to None.** APScheduler reads an
        explicit ``None`` as *"add this job paused"*, so passing it for a job that is
        not run-on-start registers the job and then never fires it. That is what this
        did, and it meant every job without ``run_on_start`` -- sixteen of nineteen --
        was silently paused from the moment the scheduler was written: no runs in the
        history, and no next run on the Operations page. The two symptoms are the
        same bug seen from two directions.

        Leaving the argument out lets the interval trigger compute the first fire
        time, which is what "every 45 seconds" is supposed to mean.

        The first run of everything that is not run-on-start is randomised across the
        hour, so nineteen jobs sharing an hourly interval do not fire on the same
        second and spend their provider budgets together. The offset is applied once,
        as the trigger's start date, rather than as jitter on every fire: jitter would
        let an hourly job land anywhere between thirty and ninety minutes after the
        last run, and the Operations page prints a schedule that would then be untrue.
        """
        now = dt.datetime.now(dt.UTC)
        window = min(spec.interval_seconds, FIRST_RUN_SPREAD_SECONDS)

        if spec.interval_seconds < MIN_INTERVAL_SECONDS:
            logger.warning(
                "job %s is scheduled every %ss, below the %ss floor; raise it in "
                "config.yaml unless this is deliberate",
                spec.id,
                spec.interval_seconds,
                MIN_INTERVAL_SECONDS,
            )

        trigger = IntervalTrigger(
            seconds=spec.interval_seconds,
            start_date=now + dt.timedelta(seconds=random.uniform(0, window)),
            timezone="UTC",
        )

        options: dict[str, Any] = {}
        if spec.run_on_start:
            # Deliberately *first*, ahead of the interval: a fresh container should
            # populate its dependencies now rather than one interval from now. The
            # spread does not apply -- this is the bootstrap path.
            options["next_run_time"] = now + dt.timedelta(seconds=spec.start_delay_seconds)

        self._scheduler.add_job(
            execute_job,
            trigger=trigger,
            args=[spec],
            id=spec.id,
            name=spec.description or spec.id,
            replace_existing=True,
            max_instances=spec.max_instances,
            **options,
        )

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
        out: list[dict[str, object]] = []
        for spec in self._specs.values():
            job = jobs.get(spec.id)
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
                    "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
                }
            )
        return out

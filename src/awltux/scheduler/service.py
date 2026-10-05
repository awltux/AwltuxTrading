"""Scheduler service: owns the APScheduler instance and the job registry.

The registry is built by :mod:`awltux.scheduler.registry`, which knows how to
turn application settings into concrete :class:`~awltux.scheduler.jobs.JobSpec`
objects. Jobs can also be triggered manually from the dashboard, so the same
function objects are used for both paths.
"""

from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from awltux.scheduler.jobs import JobSpec, execute_job

logger = logging.getLogger(__name__)


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
        if specs:
            for spec in specs:
                self.register(spec)

    # ------------------------------------------------------------- registry
    def register(self, spec: JobSpec) -> None:
        self._specs[spec.id] = spec
        if spec.enabled and self._scheduler.running:
            self._schedule(spec)

    def specs(self) -> list[JobSpec]:
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

    # -------------------------------------------------------------- internals
    def _schedule(self, spec: JobSpec) -> None:
        trigger = IntervalTrigger(
            seconds=spec.interval_seconds,
            jitter=spec.jitter_seconds or None,
            timezone="UTC",
        )
        self._scheduler.add_job(
            execute_job,
            trigger=trigger,
            args=[spec],
            id=spec.id,
            name=spec.description or spec.id,
            replace_existing=True,
            max_instances=spec.max_instances,
            next_run_time=(
                dt.datetime.now(dt.UTC) if spec.run_on_start else None
            ),
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
                    "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
                }
            )
        return out

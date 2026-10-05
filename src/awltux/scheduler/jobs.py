"""A background job spec: what to run, how often, and how to record it."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from awltux.db.models import IngestRun
from awltux.db.session import session_scope

logger = logging.getLogger(__name__)

JobFunc = Callable[[], dict[str, Any] | None]


@dataclass(slots=True)
class JobResult:
    """What a job reports back.

    ``items_seen``/``items_written`` drive the counters, while ``note`` explains a
    zero. A job that legitimately had nothing to do and one that ran and found
    nothing look identical in the numbers, so the distinction is recorded rather
    than left to the reader.
    """

    items_seen: int = 0
    items_written: int = 0
    note: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.detail)
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass(slots=True)
class JobSpec:
    """One scheduled unit of work."""

    id: str
    func: JobFunc
    interval_seconds: int
    description: str = ""
    # Do not run immediately on startup; a fresh container should come up fast
    # and let the dashboard respond before ingest begins.
    run_on_start: bool = False
    # A long ingest must not overlap itself.
    max_instances: int = 1
    # Jitter spreads provider calls so we do not hammer a free tier at :00.
    jitter_seconds: int = 0
    enabled: bool = True
    requires: tuple[str, ...] = ()


def record_run(job_id: str, started: dt.datetime, result: JobResult | None, error: str | None) -> None:
    """Persist a job run for observability. Never raises into the job itself."""
    try:
        with session_scope() as session:
            session.add(
                IngestRun(
                    job=job_id,
                    started_at=started,
                    finished_at=dt.datetime.now(dt.UTC),
                    ok=error is None,
                    items_seen=result.items_seen if result else 0,
                    items_written=result.items_written if result else 0,
                    error=error,
                    detail=result.detail if result else None,
                )
            )
    except Exception:  # pragma: no cover - observability must not break the job
        logger.exception("failed to record ingest run for %s", job_id)


def execute_job(spec: JobSpec) -> JobResult | None:
    """Run a job with timing, error capture and run logging.

    Errors are swallowed *after* being recorded: one failing provider must not
    take down the scheduler or stop the other jobs.
    """
    started = dt.datetime.now(dt.UTC)
    logger.info("job %s: start", spec.id)
    result: JobResult | None = None
    error: str | None = None
    try:
        raw = spec.func()
        if isinstance(raw, JobResult):
            result = raw
        elif isinstance(raw, dict):
            result = JobResult(detail=raw)
        else:
            result = JobResult()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("job %s failed", spec.id)

    elapsed = (dt.datetime.now(dt.UTC) - started).total_seconds()
    if result is not None:
        result.detail.setdefault("elapsed_seconds", round(elapsed, 3))
        if result.note:
            result.detail.setdefault("note", result.note)
    record_run(spec.id, started, result, error)
    logger.info(
        "job %s: done in %.2fs seen=%s written=%s%s%s",
        spec.id,
        elapsed,
        result.items_seen if result else "-",
        result.items_written if result else "-",
        f" note={result.note}" if result and result.note else "",
        f" error={error}" if error else "",
    )
    return result

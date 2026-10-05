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
    # Wait this long after startup before the first run. Only meaningful with
    # ``run_on_start``. Needed where one startup job depends on another's output:
    # jobs scheduled for "now" all fire together, so a job that reads what a
    # sibling writes can otherwise run first and act on an empty table.
    start_delay_seconds: int = 0
    # A long ingest must not overlap itself.
    max_instances: int = 1
    # Jobs that must have run for this one to do anything useful, in the order they
    # should be run. This is a fact about the pipeline, so it is declared here
    # rather than inferred from the run history -- a history shows what happened,
    # not what is required. Surfaced on the Operations page and checked for cycles
    # by tests/test_job_dependencies.py.
    depends_on: tuple[str, ...] = ()
    # Jitter spreads provider calls so we do not hammer a free tier at :00.
    jitter_seconds: int = 0
    enabled: bool = True
    requires: tuple[str, ...] = ()


def start_run(job_id: str, started: dt.datetime) -> int | None:
    """Record that a run has begun, and return its row id.

    A row used to be written only when the job *finished*, so a job that takes
    forty minutes was invisible for forty minutes -- and the newest thing on the
    Operations page was the previous run's error. That is precisely how a stale
    failure gets read as a current one, which is what happened here: a news run
    that was working normally was reported as failing, because the last completed
    run of that job had failed an hour earlier.

    ``ok`` is left NULL, which the template already renders as "running". Nothing
    wrote a NULL before, so that branch was dead.
    """
    try:
        with session_scope() as session:
            row = IngestRun(job=job_id, started_at=started, finished_at=None, ok=None)
            session.add(row)
            session.flush()
            return row.id
    except Exception:  # pragma: no cover - observability must not break the job
        logger.exception("failed to record the start of %s", job_id)
        return None


def finish_run(
    run_id: int | None,
    job_id: str,
    started: dt.datetime,
    result: JobResult | None,
    error: str | None,
) -> None:
    """Close out a run. Falls back to inserting one if the start was not recorded.

    Never raises into the job: an unrecordable run is a missing report, not a
    failed one.
    """
    if run_id is None:
        record_run(job_id, started, result, error)
        return

    try:
        with session_scope() as session:
            row = session.get(IngestRun, run_id)
            if row is None:
                # The row was pruned or the database was rebuilt under us.
                record_run(job_id, started, result, error)
                return
            row.finished_at = dt.datetime.now(dt.UTC)
            row.ok = error is None
            row.items_seen = result.items_seen if result else 0
            row.items_written = result.items_written if result else 0
            row.error = error
            row.detail = result.detail if result else None
    except Exception:  # pragma: no cover - observability must not break the job
        logger.exception("failed to record ingest run for %s", job_id)


def record_run(job_id: str, started: dt.datetime, result: JobResult | None, error: str | None) -> None:
    """Persist a completed job run in one insert. Never raises into the job itself."""
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
    run_id = start_run(spec.id, started)
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
    finish_run(run_id, spec.id, started, result, error)
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

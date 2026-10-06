"""A background job spec: what to run, how often, and how to record it."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from awltux.db.models import IngestRun, utcnow
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
    #: True when the job only has work while its coverage probe reports a gap.
    #:
    #: A *backfill* job -- resolving symbols, appraising stored stories -- has nothing
    #: to do once its count reaches zero, and running it anyway spends provider calls
    #: confirming that. A *refresh* job is the opposite: its coverage reads zero
    #: precisely when it is working, and time alone creates its next run's work. So
    #: the default is to run, and a job opts in to being skipped when idle.
    backfill: bool = False
    enabled: bool = True
    requires: tuple[str, ...] = ()


def running_jobs(session) -> set[str]:
    """Jobs with a run open right now.

    A run row is opened when a job starts and closed when it finishes, so an open
    row means a job is *currently* executing -- which is what the Operations page
    needs to disable the right buttons rather than the ones that happen to have been
    clicked in this browser tab.
    """
    from sqlalchemy import select

    return {
        job
        for (job,) in session.execute(
            select(IngestRun.job).where(IngestRun.finished_at.is_(None)).distinct()
        ).all()
        if job
    }


def close_orphaned_runs() -> int:
    """Mark runs left open by a previous process as interrupted, and return how many.

    If the process dies mid-run -- a restart, a redeploy, a crash -- the row it
    opened is never closed. The Operations page then shows that job as running
    forever, with its button disabled, and the only person who could tell the
    difference is the one who remembers deploying.

    That is worse than showing nothing: it hides the fact that the work did not
    finish. Called once at startup, when the only process that could own an open row
    is the one that has just gone away.
    """
    from sqlalchemy import select

    closed = 0
    try:
        with session_scope() as session:
            rows = (
                session.execute(select(IngestRun).where(IngestRun.finished_at.is_(None)))
                .scalars()
                .all()
            )
            for row in rows:
                row.finished_at = utcnow()
                row.ok = False
                note = "interrupted: the process restarted while this run was in progress"
                row.error = f"{row.error}\n{note}" if row.error else note
                closed += 1
    except Exception:  # pragma: no cover - observability must not stop startup
        logger.exception("could not close orphaned runs")
        return 0
    if closed:
        logger.info("closed %d run(s) left open by a previous process", closed)
    return closed


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


def skip_reason(spec: JobSpec, status: Any) -> str | None:
    """Whether this run should be skipped, from the job's place in the pipeline.

    A pure function of the spec and the status, so the rule can be tested as a rule
    rather than through whatever state a database happens to be in. Two questions:

    * **Are its dependencies met?** A declared dependency that has neither succeeded
      nor produced anything to read blocks the job. Running news appraisal against an
      empty news table, or a decision sweep against no valuations, spends provider and
      model calls to produce nothing.
    * **Has it anything to do?** Asked only of jobs that declare themselves
      ``backfill``. A refresh job's coverage reaches zero precisely when it is
      working -- prices are current, valuations exist -- and skipping it then would
      freeze them, because the next hour's work is something no coverage count can
      see yet.

    A job with no coverage notion at all (a poller, a housekeeping sweep) has
    ``outstanding is None`` and always runs. That is deliberate: its whole purpose is
    to fetch what has not been published yet, which by definition is not in the
    database to be counted.
    """
    if status is None:
        return None
    if status.blocked:
        return f"waiting for {', '.join(status.never_ran)}"
    if spec.backfill and status.outstanding == 0:
        return f"nothing outstanding: {status.reason}"
    return None


def guard_reason(spec: JobSpec) -> str | None:
    """Why a scheduled run should be skipped, or ``None`` to go ahead.

    Reads the statuses from the database and applies :func:`skip_reason`. Reuses the
    machinery the Operations page already uses for its queue rather than inventing a
    second notion of readiness that could disagree with it.

    Any failure here runs the job. A guard that cannot evaluate itself is not evidence
    that there is nothing to do, and refusing to work because a query failed would
    turn a transient database problem into a silent outage.
    """
    from awltux.db import session_scope
    from awltux.scheduler.dependencies import job_statuses
    from awltux.scheduler.registry import build_job_specs

    try:
        with session_scope() as session:
            statuses = {
                status.id: status for status in job_statuses(session, build_job_specs())
            }
    except Exception:  # pragma: no cover - a guard must never stop a job
        logger.exception("could not evaluate the guard for %s; running it", spec.id)
        return None

    return skip_reason(spec, statuses.get(spec.id))


def execute_job(spec: JobSpec) -> JobResult | None:
    """Run a job with timing, error capture and run logging.

    Errors are swallowed *after* being recorded: one failing provider must not
    take down the scheduler or stop the other jobs.
    """
    started = dt.datetime.now(dt.UTC)
    run_id = start_run(spec.id, started)

    watched = guard_reason(spec)
    if watched is not None:
        # Recorded, not silent. A job that fires, finds nothing to do and says so is
        # a good outcome; the alternative is what prompted this -- a run history with
        # holes in it cannot be told apart from a scheduler that is not firing at all.
        skipped = JobResult(note=f"skipped: {watched}")
        skipped.detail["elapsed_seconds"] = round(
            (dt.datetime.now(dt.UTC) - started).total_seconds(), 3
        )
        # Copied into the detail for the same reason the normal path does it: the
        # note is what the Operations page reads back, and a skip whose reason is
        # not stored is indistinguishable from a job that did nothing.
        skipped.detail["note"] = skipped.note
        finish_run(run_id, spec.id, started, skipped, None)
        logger.info("job %s: skipped (%s)", spec.id, watched)
        return skipped

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

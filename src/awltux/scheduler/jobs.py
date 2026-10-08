"""A background job spec: what to run, how often, and how to record it."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from awltux.db.models import IngestRun, utcnow
from awltux.db.session import session_scope
from awltux.scheduler import progress
from awltux.timezones import as_utc

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
    #: What this run is about, when it is about one thing -- an instrument ticker today.
    #:
    #: Recorded on the run row when the run *starts*, because a run's detail otherwise only
    #: arrives when it closes: the page that follows a job in flight is exactly the page
    #: that wants to say which company it is watching, and a log belonging to one instrument
    #: out of many is unreadable without it. A scoped refresh writes every instrument's log
    #: to the same file, so the job id alone cannot answer it.
    target: str | None = None


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


def last_successful_runs(session) -> dict[str, dt.datetime]:
    """When each job last did something that counted, from the run history.

    **Successful, not merely attempted.** A run that raised, or that a restart killed
    mid-write, produced nothing; its job is still behind, and the next start should
    pick it up. Anchoring on the last attempt instead would make an interrupted run
    look like work done -- and this process is restarted by every deploy, on a machine
    that is switched off every night, so that is the common case rather than the rare
    one. ``close_orphaned_runs`` has already marked such a run failed by the time this
    is read (``main.py`` calls it before the scheduler starts).

    A run the guard *skipped* counts: it fired, and it correctly found nothing to do.
    Re-running it every start would be a job polling a coverage probe that just told
    it there was nothing left.

    The value is the run's **start**, so a job that is running right now is not treated
    as behind -- queueing a second copy behind the first is the one thing
    ``max_instances`` would then have to catch.

    SQLite hands back naive datetimes however the column was declared, and these are
    compared against an aware "now", so they are normalised here rather than at every
    use. See :mod:`awltux.scheduler.catchup` for what the answer is used for.
    """
    from sqlalchemy import func, select

    rows = session.execute(
        select(IngestRun.job, func.max(IngestRun.started_at))
        .where(IngestRun.ok.is_(True))
        .group_by(IngestRun.job)
    ).all()

    latest_by_job: dict[str, dt.datetime] = {}
    for job, latest in rows:
        aware = as_utc(latest)
        if job and aware is not None:
            latest_by_job[job] = aware
    return latest_by_job


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


def start_run(job_id: str, started: dt.datetime, target: str | None = None) -> int | None:
    """Record that a run has begun, and return its row id.

    A row used to be written only when the job *finished*, so a job that takes
    forty minutes was invisible for forty minutes -- and the newest thing on the
    Operations page was the previous run's error. That is precisely how a stale
    failure gets read as a current one, which is what happened here: a news run
    that was working normally was reported as failing, because the last completed
    run of that job had failed an hour earlier.

    ``ok`` is left NULL, which the template already renders as "running". Nothing
    wrote a NULL before, so that branch was dead.

    ``target`` is stored as the run's detail immediately, so a run in flight can say what it
    is about. `finish_run` merges the job's own detail over it rather than replacing it.
    """
    try:
        with session_scope() as session:
            row = IngestRun(
                job=job_id,
                started_at=started,
                finished_at=None,
                ok=None,
                detail={"target": target} if target else None,
            )
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
            # Merged, not replaced: what the run was about was written when it started and
            # is still true when it ends. A run that failed, or was stopped, returns no
            # result at all -- and that is the run whose page most needs to name its target.
            detail = dict(row.detail or {})
            detail.update(result.detail if result else {})
            row.detail = detail or None
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


def execute_job(spec: JobSpec, cause: str | None = None) -> JobResult | None:
    """Run a job with timing, error capture and run logging.

    Errors are swallowed *after* being recorded: one failing provider must not
    take down the scheduler or stop the other jobs.

    ``cause`` is why this run happened when it did, and is written into the progress
    log as its first line. It exists for the catch-up path (see
    :mod:`awltux.scheduler.catchup`): a run that answers a missed trigger looks
    exactly like a scheduled one afterwards, and the one moment you want to know the
    difference is the morning the machine was off.

    The whole run is wrapped in a progress capture, so everything the job logs --
    and everything it says through ``progress.note`` -- lands in one file that
    replaces the previous run's. See :mod:`awltux.scheduler.progress`.
    """
    started = dt.datetime.now(dt.UTC)
    run_id = start_run(spec.id, started, spec.target)

    with progress.capture(spec.id, run_id, started, spec.target) as run_log:
        return _execute_captured(spec, started, run_id, run_log, cause)


@dataclass(slots=True)
class _Outcome:
    """How a job's body ended, before anything is recorded about it."""

    result: JobResult | None
    #: ``None`` means the job succeeded. Anything else is what the run row's ``error``
    #: column carries and what makes the run unsuccessful.
    error: str | None
    #: ``ok``, ``failed`` or ``stopped`` -- the word the progress log closes with.
    word: str

    @property
    def stopped(self) -> bool:
        return self.word == "stopped"


def _invoke(spec: JobSpec) -> _Outcome:
    """Call the job's body and describe how it ended. Records and logs nothing.

    Three endings, and the difference between the last two is the whole reason this is
    a named step rather than two branches inline:

    * **ok** -- it returned.
    * **failed** -- it raised.
    * **stopped** -- it left because a stop was requested, at a boundary of its own
      choosing, with everything it had finished committed. Recorded as *unsuccessful*
      anyway, and deliberately: "successful" is what catch-up reads to decide a job is
      up to date, and this run did not finish its work -- counting it as done would
      silently skip the rest until the next interval. The wording is what separates it
      from a failure, exactly as the restart sweep's "interrupted: ..." does for a
      killed run.
    """
    try:
        raw = spec.func()
    except progress.Stopped as exc:
        where = str(exc)
        # The reason is the exception's, because a stop is not always a deploy: a run
        # that ran out of a daily provider quota leaves at the same boundary and must
        # not be reported as something somebody asked for.
        error = f"stopped: {exc.reason} at {where}" if where else f"stopped: {exc.reason}"
        result = JobResult(note=error)
        result.detail["stopped"] = True
        result.detail["stopped_reason"] = exc.reason
        if where:
            result.detail["stopped_at"] = where
        logger.info("job %s: %s", spec.id, error)
        return _Outcome(result=result, error=error, word="stopped")
    except Exception as exc:
        logger.exception("job %s failed", spec.id)
        return _Outcome(result=None, error=f"{type(exc).__name__}: {exc}", word="failed")

    if isinstance(raw, JobResult):
        result = raw
    elif isinstance(raw, dict):
        result = JobResult(detail=raw)
    else:
        result = JobResult()
    return _Outcome(result=result, error=None, word="ok")


def _execute_captured(
    spec: JobSpec,
    started: dt.datetime,
    run_id: int | None,
    run_log: progress.RunLog,
    cause: str | None = None,
) -> JobResult | None:
    """The body of a run, with its progress log already open."""
    if cause:
        # Before the guard, so a catch-up that declines to work still says why it
        # fired. Written to the file directly rather than through the logger: the
        # level can hide INFO, and this is the line that explains the run.
        logger.info("job %s: %s", spec.id, cause)
        progress.note(cause)

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
        progress.note(f"skipped: {watched}")
        finish_run(run_id, spec.id, started, skipped, None)
        logger.info("job %s: skipped (%s)", spec.id, watched)
        _close(run_log, started, "skipped", skipped.note)
        return skipped

    logger.info("job %s: start", spec.id)
    outcome = _invoke(spec)
    result, error = outcome.result, outcome.error

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
    _close(run_log, started, outcome.word, error or (result.note if result else None))
    return result


def _close(run_log: progress.RunLog, started: dt.datetime, outcome: str, detail: str | None) -> None:
    """Write the closing line, after the capture handler is removed.

    Written directly rather than through the logger, because the point of the footer
    is to be the last line of the file and a handler that has just been detached
    cannot guarantee that.
    """
    elapsed = (dt.datetime.now(dt.UTC) - started).total_seconds()
    tail = f" -- {detail}" if detail else ""
    run_log.add(f"=== {outcome} in {elapsed:.1f}s{tail} ===")

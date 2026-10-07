"""Running a one-instrument refresh on its own thread, under the instrument's lease.

Two guards, and they protect different things.

* **The lease** (:mod:`awltux.ingest.lease`) is per instrument: it stops a second refresh
  of the same company, and it is what the universe-wide jobs consult so a sweep and a
  refresh do not write the same rows at once.
* **The process-wide permit** is a single slot for scoped refreshes. It exists because
  the run is recorded as a job, and a job's progress log is *one file, truncated at the
  start of every run* -- two refreshes at once would each truncate the other's log, so
  the panel would show one company's steps under the other's name. The scheduler's own
  worker holds one job at a time for a related reason.

**It runs on a thread rather than in the request.** The steps make network calls and
model calls: minutes, not milliseconds, and a request that blocks that long is one the
browser and any proxy in front of it will abandon -- leaving a refresh running that the
reader believes failed. The thread goes through :func:`~awltux.scheduler.jobs.execute_job`
so the run appears in the run history with a progress log and a close-out line, exactly
like a scheduled one, which is what makes the live panel work without new machinery.
"""

from __future__ import annotations

import logging
import threading

from awltux.db.session import session_scope
from awltux.ingest import refresh
from awltux.scheduler import progress
from awltux.scheduler.jobs import JobResult, JobSpec, execute_job

logger = logging.getLogger(__name__)

#: The run id this appears under in the history and in `data/joblogs/`. Named rather
#: than inlined because the page links to `/jobs/instrument_refresh/log` by string.
REFRESH_JOB = "instrument_refresh"

#: One scoped refresh at a time. See the module docstring: the reason is the job log.
_permit = threading.Semaphore(1)


class Started:
    """What happened when the button was pressed."""

    __slots__ = ("message", "ok", "ticker")

    def __init__(self, ok: bool, message: str, ticker: str) -> None:
        self.ok = ok
        self.message = message
        self.ticker = ticker


def start(ticker: str) -> Started:
    """Take the lease for ``ticker`` and refresh it on a background thread.

    Returns immediately with whether the refresh started and, when it did not, which of
    the three reasons applied -- already running, not in the universe, or another
    instrument's refresh holding the single slot. Each is a different thing for the
    reader to do, so they are told apart rather than collapsed into "failed".
    """
    acquired = _permit.acquire(blocking=False)
    if not acquired:
        return Started(
            False, "another instrument's refresh is already running", ticker
        )

    try:
        token = _claim(ticker)
    except Exception:
        _permit.release()
        raise

    if token is None:
        _permit.release()
        return Started(False, "a refresh of this instrument is already running", ticker)

    thread = threading.Thread(
        target=_run, args=(ticker, token), name=f"refresh-{ticker}", daemon=True
    )
    thread.start()
    return Started(True, "refresh started", ticker)


def _claim(ticker: str) -> str | None:
    """Take the lease, or ``None`` if the instrument cannot be refreshed.

    Raises nothing for the ordinary refusals: a ticker that is not in the universe is a
    stale link, not an error, and the caller renders the same way either way.
    """
    from awltux.ingest.lease import acquire, expire_stale

    with session_scope() as session:
        expire_stale(session)
        if refresh.instrument_or_none(session, ticker) is None:
            return None
        row = acquire(session, ticker, note="refresh requested")
        return row.token if row is not None else None


def _run(ticker: str, token: str) -> None:
    """The thread body: execute the refresh as a job, then release the lease."""
    spec = JobSpec(
        id=REFRESH_JOB,
        func=lambda: _body(ticker, token),
        interval_seconds=3600,
        max_instances=1,
        description=f"Refresh {ticker}",
    )
    try:
        execute_job(spec)
    finally:
        _permit.release()


def _body(ticker: str, token: str) -> JobResult:
    """Run the sequence and close the lease out, whatever happened."""
    from awltux.ingest.lease import release

    outcome: dict[str, object] = {}
    failed: str | None = None
    try:
        with session_scope() as session:
            outcome = refresh.run(session, ticker, token=token)
    except Exception as exc:  # noqa: BLE001 - the lease must be released either way
        failed = f"{type(exc).__name__}: {exc}"
        logger.exception("instrument refresh failed for %s", ticker)

    with session_scope() as session:
        release(
            session,
            ticker,
            token=token,
            state="failed" if failed else "done",
            note=failed or _summary(outcome),
        )

    if failed:
        raise RuntimeError(failed)

    results = outcome.get("results") or []
    written = sum(1 for row in results if row.get("ok"))
    note = outcome.get("stopped")
    if isinstance(note, str):
        # A budget stop or a lost lease is not a failure, and the run says so rather
        # than reporting success over work that did not happen.
        progress.note(note)
        return JobResult(items_seen=len(results), items_written=written, note=note)
    return JobResult(items_seen=len(results), items_written=written, detail=outcome)


def _summary(outcome: dict[str, object]) -> str:
    """One line naming what the refresh did, for the lease row the page reads."""
    results = outcome.get("results") or []
    ok = sum(1 for row in results if row.get("ok"))
    return f"{ok} of {len(results)} steps completed"


__all__ = ["REFRESH_JOB", "Started", "start"]

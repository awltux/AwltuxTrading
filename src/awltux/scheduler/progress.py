"""A progress log per job, kept for the most recent run only.

A job that takes forty minutes is a black box from the outside: the Operations page
says it is running and the run history says nothing until it finishes. This gives it
a voice -- what it is doing now, and how far through it is -- and keeps exactly one
log per job so the answer is never stale.

**One file per job, truncated at the start of every run.** `<data_dir>/joblogs/
<job>.log`. "Overwritten each run" is the requirement and also the retention policy:
there is no rotation, no accumulation and nothing to prune, because the interesting
question is always *what is it doing now*.

**Captured from logging, with an explicit door for progress.** Most jobs already
emit ``logger.info`` at their boundaries, and those lines belong in the log without
anyone changing a job. But boundaries are not progress -- measured before this was
written, `ingest/xbrl.py` logged once per run, at the end -- so :func:`note` exists
for the loops that need to say "filer 12 of 40". Both arrive in the same file,
formatted the same way, because a reader should not have to know which is which.

**Why a file rather than a table.** Three reasons, in order:

1. A job that logs must not contend for SQLite's write lock. That lock is the
   scarcest resource in this system and the whole of ``db/session.py``'s discipline
   is about not holding it; appending a log line inside a job's transaction would
   put it back on the critical path.
2. The database is the only copy of the universe and is backed up before every
   migration. Progress chatter does not belong in that backup.
3. Tailing by byte offset is how the live panel reads it without re-sending a whole
   file every second.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Imported at module level, not inside the function that uses it. `conftest` points
# every *module-level* `get_settings` reference at the test settings, so a lazy
# import inside `log_dir` silently resolved the real configuration and wrote job
# logs into the developer's own `data/` directory during tests.
from awltux.config import get_settings

logger = logging.getLogger(__name__)

#: One run's log is capped here. A job that loops over thousands of rows and notes
#: each one must not be able to fill the volume; the cap writes a marker and stops
#: rather than silently dropping lines, so a truncated log never reads as a
#: complete one.
MAX_BYTES = 2 * 1024 * 1024

#: The logger jobs call for explicit progress. Named so it can be recognised in a
#: log line, and separate from `awltux.scheduler.jobs` so a job that notes progress
#: does not look like it is re-entering the scheduler.
PROGRESS_LOGGER = "awltux.progress"

#: Thread-local: which run, if any, this thread is currently executing. A job is
#: run by one thread, and the handler filters on this so a manual run triggered from
#: a web request cannot have its lines land in a scheduled run's file.
_local = threading.local()

_FORMAT = logging.Formatter(
    fmt="%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"
)


@dataclass(slots=True)
class RunLog:
    """The log of one run, as the process holding it sees it."""

    job_id: str
    run_id: int | None
    started_at: dt.datetime
    path: Path
    written: int = 0
    truncated: bool = False

    def add(self, text: str) -> None:
        """Append one already-formatted line, respecting the cap.

        The file handle is opened and closed per write rather than held. A job's log
        is written a few dozen times per run, and holding a descriptor for forty
        minutes across a container restart is a worse trade than reopening a small
        file.
        """
        if self.truncated:
            return
        payload = text if text.endswith("\n") else text + "\n"
        size = len(payload.encode("utf-8"))
        if self.written + size > MAX_BYTES:
            self.truncated = True
            marker = (
                f"[log truncated at {MAX_BYTES // 1024} KiB -- the job is still "
                "running; its result will be in the run history]\n"
            )
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(marker)
            self.written += len(marker.encode("utf-8"))
            return
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload)
            self.written += size
        except OSError:  # pragma: no cover - a log must never fail a job
            logger.debug("could not write the job log at %s", self.path, exc_info=True)


def log_dir() -> Path:
    return get_settings().joblog_dir


def log_path(job_id: str) -> Path:
    """Where a job's most recent log lives. Safe for any job id string."""
    # Job ids are registry constants, but a path is a path: the same rule as
    # everywhere else in this codebase is that anything reaching the filesystem is
    # reduced to characters that cannot escape the directory.
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_id) or "job"
    return log_dir() / f"{safe}.log"


class _CaptureHandler(logging.Handler):
    """Copies this thread's records into the active run's file.

    Skips :data:`PROGRESS_LOGGER` because :func:`note` has already written those
    lines itself -- it has to, so that progress does not depend on the log level. It
    still *emits* them, so they reach the container log too; without this the file
    would carry each progress line twice whenever INFO was enabled.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == PROGRESS_LOGGER:
            return
        active: RunLog | None = getattr(_local, "active", None)
        if active is None or getattr(record, "thread", None) != threading.get_ident():
            return
        try:
            active.add(self.format(record))
        except Exception:  # pragma: no cover - logging must not raise
            self.handleError(record)


def note(message: str) -> None:
    """Record a progress line against the run active on this thread.

    **Written straight to the file, not through the logging level.** The first
    version called ``logger.info`` and relied on the capture handler, which made the
    panel depend on ``--log-level``: at ``WARNING`` the notes were dropped by the
    logger's effective level before any handler saw them, and the panel went blank
    while the job ran perfectly. Progress is part of what a run reports, not console
    chatter that a log level may silence -- so it is written directly *and* emitted,
    which puts it in the panel always and in the container log at whatever level is
    configured.

    A no-op when nothing is running beyond the log line, so a job function can be
    called from a test, a script or the CLI without knowing whether it was invoked by
    the scheduler. That matters: a job that had to check whether it was being watched
    would end up with two code paths, and only one of them would be exercised.
    """
    active: RunLog | None = getattr(_local, "active", None)
    if active is not None:
        stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        active.add(f"{stamp} PROGRESS {message}")
    logging.getLogger(PROGRESS_LOGGER).info("%s", message)


@contextmanager
def capture(job_id: str, run_id: int | None, started_at: dt.datetime) -> Iterator[RunLog]:
    """Truncate this job's log and capture the run into it.

    A failure to create the file must not stop the job: the log is a convenience and
    the run history is the record. ``capture`` therefore yields a usable object even
    when the directory is unwritable, and the job proceeds unwatched.
    """
    path = log_path(job_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # "w", not "a": the requirement is that only the most recent run is kept, and
        # truncating here is also what makes a stale offset from the panel's last
        # poll meaningless -- the API hands out a run id for exactly that reason.
        path.write_text("", encoding="utf-8")
    except OSError:  # pragma: no cover - see the docstring
        logger.debug("could not open the job log at %s", path, exc_info=True)

    active = RunLog(job_id=job_id, run_id=run_id, started_at=started_at, path=path)
    handle = _CaptureHandler()
    handle.setFormatter(_FORMAT)

    root = logging.getLogger("awltux")
    previous = getattr(_local, "active", None)
    _local.active = active
    root.addHandler(handle)
    active.add(
        f"=== {job_id} run {run_id if run_id is not None else '-'} "
        f"started {started_at.strftime('%Y-%m-%dT%H:%M:%SZ')} ==="
    )
    try:
        yield active
    finally:
        root.removeHandler(handle)
        _local.active = previous


def current() -> RunLog | None:
    """The run this thread is executing, if any."""
    return getattr(_local, "active", None)


def read(job_id: str, offset: int = 0) -> tuple[str, int, int]:
    """Bytes from ``offset`` onward, the new offset, and the file's size.

    Returns text rather than lines so a poll that lands mid-line still delivers it;
    the caller appends what it gets and the next poll completes the line. Returning
    only whole lines would silently drop the tail of a job's last words until it
    wrote another one.
    """
    path = log_path(job_id)
    try:
        size = path.stat().st_size
    except OSError:
        return "", 0, 0
    if offset < 0 or offset > size:
        # A shrunk file means a new run started; start from the beginning of it.
        offset = 0
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return "", offset, size
    return chunk.decode("utf-8", "replace"), offset + len(chunk), size

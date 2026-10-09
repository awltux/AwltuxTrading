"""Database engine and session management.

SQLite is the right choice here: single-user, single-container, no operations
overhead, and the free-tier ingest volume (a few hundred instruments, daily bars)
fits comfortably. It is configured properly rather than casually:

* **WAL** so the scheduler's writes do not block dashboard reads.
* **foreign_keys=ON** -- off by default in SQLite, and our cascades depend on it.
* **busy_timeout** so a concurrent write waits instead of raising.
* **check_same_thread=False** because the scheduler runs in worker threads.
* **A re-entrant ``session_scope``** so a nested call joins the open transaction
  rather than opening a competing connection. See :func:`session_scope`.
* **One Python function registered on every connection** --
  :func:`_register_recency_weight` -- so an ordering that depends on the news recency
  decay is computed by the same code in SQL as it is in Python.
* **No ``BEGIN IMMEDIATE``.** It was tried and removed: taking the write lock at
  the start of *every* transaction means a job that holds one across a rate-limit
  wait blocks reads as well as writes, and the dashboard 500s with "database is
  locked". WAL already lets readers proceed during a write; the remaining rule is
  that jobs must not hold a transaction across a slow provider call.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from awltux.config import Settings, get_settings
from awltux.db.models import Base

logger = logging.getLogger(__name__)

#: Per-thread stack of open scopes, so ``session_scope`` can be re-entrant.
_state = threading.local()

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None

#: The name the recency decay is registered under. A constant so the registration below
#: and the ordering in ``web/queries.py`` cannot disagree about the spelling.
RECENCY_FUNCTION = "awltux_recency"


def _register_recency_weight(dbapi_connection) -> None:
    """Expose ``analysis.relevance.recency_weight`` to SQL as a function.

    The news page orders the whole corpus by priority -- ``materiality x credibility x
    recency`` -- and the recency term is an exponential decay. SQLite only grew ``exp``
    and ``pow`` when compiled with its optional math extension, and that is not something
    to rely on: measured 2026-10-09, this project's container answers ``select exp(1)``
    with 2.718..., and the interpreter the test suite runs on raises ``no such function:
    exp``. Deriving the decay in SQL would therefore work in production and fail in the
    tests, which is the wrong way round for a rule this load-bearing.

    Registering the Python function instead has a second benefit that matters more: there
    is then **one** definition of the decay. The number the news table prints beside a
    story and the expression it sorts by are literally the same call.

    The argument arrives as SQLite stores it -- an ISO string, because SQLAlchemy's
    ``DateTime`` is TEXT there -- so it is parsed back to a datetime. A value that will
    not parse is treated as a missing timestamp, which is exactly what the Python caller
    does with ``None``: both fall back to the mid weight rather than raising inside a
    query.
    """
    import datetime as dt

    from awltux.analysis.relevance import recency_weight

    def recency(value: object) -> float:
        moment = value
        if isinstance(moment, str):
            try:
                moment = dt.datetime.fromisoformat(moment)
            except ValueError:
                moment = None
        return recency_weight(moment if isinstance(moment, dt.datetime) else None)

    dbapi_connection.create_function(RECENCY_FUNCTION, 1, recency, deterministic=True)


def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    """Apply the pragmas SQLite needs to behave like a server database."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        # Keep temp tables/spills off disk; our working sets are small.
        cursor.execute("PRAGMA temp_store=MEMORY")
    finally:
        cursor.close()
    _register_recency_weight(dbapi_connection)


def create_db_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    settings = settings or get_settings()
    settings.ensure_dirs()
    engine = create_engine(
        settings.database_url,
        echo=echo,
        future=True,
        # The scheduler writes from worker threads, so connections are shared.
        connect_args={"check_same_thread": False, "timeout": 15},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", _configure_sqlite)
    return engine


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        _engine = create_db_engine(settings)
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(settings),
            expire_on_commit=False,
            autoflush=False,
            future=True,
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception.

    **Re-entrant per thread.** A nested call joins the transaction already open on
    this thread rather than opening a second connection, and only the outermost
    scope commits.

    That matters because the ingest functions interleave provider calls with
    writes, and a provider call opens a session of its own to record rate-limit
    usage. With one connection per scope, the sequence *write -> provider call*
    deadlocked: the outer transaction held SQLite's single write lock while the
    inner one waited for it, until ``busy_timeout`` expired and the job died with
    "database is locked" after exactly 15 seconds.

    Joining the caller's transaction removes the second connection entirely, so
    there is nothing to deadlock against. The writes also become atomic with the
    job that triggered them, which is what you want anyway: a partially-recorded
    fetch should not survive a failure.
    """
    stack: list[Session] | None = getattr(_state, "stack", None)
    if stack is None:
        stack = []
        _state.stack = stack

    if stack:
        # Nested: hand back the session already in progress. The caller owns the
        # commit, because it is the one that knows what the whole unit of work is.
        yield stack[-1]
        return

    session = get_session_factory()()
    stack.append(session)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        stack.pop()
        session.close()


def in_transaction() -> bool:
    """Whether this thread already has a scope open. Used by tests and callers
    that want to avoid holding a write lock across a slow provider call."""
    return bool(getattr(_state, "stack", None))


def release_write_lock(session: Session) -> None:
    """Commit the current transaction, keeping the scope open.

    For loops that do many provider calls: each one ends the transaction (so
    SQLite's write lock is released) while the surrounding ``session_scope`` stays
    in charge of the eventual rollback on failure.

    Long ingest loops need this. ``ingest_rss_news`` polls roughly a thousand feeds
    for a 500-instrument universe, and doing that inside a single transaction held
    the write lock for minutes -- every other writer, including a job run from the
    CLI, failed with "database is locked" after ``busy_timeout``.

    Using this gives up atomicity for the enclosing batch, which is the right
    trade for idempotent ingest: a partially ingested feed poll is fine to repeat,
    whereas a lock held for minutes is not.

    **Prefer :func:`release_before_network` for anything that is about to make a
    network call.** Placing this by hand at the end of a loop body is what failed
    twice -- see that function.
    """
    if session.in_transaction():
        session.commit()


def release_before_network() -> None:
    """Commit this thread's open transaction, if it has one, before network I/O.

    Called at the network boundary -- by the HTTP client and the model client --
    rather than remembered at each call site, because remembering it did not work.
    The rule "a job must not hold a transaction across a slow provider call" is in
    this module's docstring, and it was violated twice by *new* code added to
    existing loops:

    * ``ingest_rss_news`` was fixed with an explicit release between feed polls;
      a per-headline classifier call was later added inside the same transaction,
      holding the lock for ~20 seconds per instrument instead of per poll;
    * ``news_analysis`` releases between items, but the appraisal -- which is where
      the model call happens -- runs before that release, so the lock is held
      across it.

    Both looked correct, because in both the release is present and near the loop.
    Placing the commit *at the boundary* makes the property hold for code that has
    not been written yet, which is the only kind of guarantee worth having here.

    The atomicity given up is the same as :func:`release_write_lock`'s, and for the
    same reason: ingest and appraisal are idempotent and repeatable, whereas a lock
    held across a provider call fails every other writer.
    """
    stack: list[Session] | None = getattr(_state, "stack", None)
    if not stack:
        return
    session = stack[-1]
    if session.in_transaction():
        session.commit()


def init_db(settings: Settings | None = None) -> Engine:
    """Create any missing tables.

    Schema *evolution* is Alembic's job; this is the bootstrap path used on
    first run and by the test suite.
    """
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    return engine


def healthcheck() -> dict[str, object]:
    """Cheap readiness probe used by the container healthcheck."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            tables = connection.execute(
                text("SELECT count(*) FROM sqlite_master WHERE type='table'")
            ).scalar_one()
        return {"ok": True, "tables": int(tables)}
    except Exception as exc:  # pragma: no cover - only on a broken volume
        logger.exception("database healthcheck failed")
        return {"ok": False, "error": str(exc)}


def reset_engine() -> None:
    """Dispose and forget the cached engine (used by tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None

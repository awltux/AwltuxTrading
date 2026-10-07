"""The per-instrument lease: taking it, renewing it, and asking who holds one.

The record is :class:`~awltux.db.models.InstrumentRefresh`; this module owns the
operations on it, so that "is this instrument locked" has one answer rather than one per
caller.

**The lock is cooperative and must be cheap to consult.** A universe job asks about it
once per instrument, inside a loop that runs a thousand times, so the read is a single
`SELECT` of unexpired tickers and callers are expected to take that set once per run
rather than per item -- see :func:`locked_tickers`.

**Nothing here commits**, for the same reason as :mod:`awltux.ingest.blockers`: the lease
is taken in the same transaction as the work it protects, so a rolled-back start does not
leave a lock nobody will release. The one exception is :func:`heartbeat`, which must
commit to be a heartbeat at all -- an uncommitted renewal is invisible to every other
process, which is the entire population that needs to see it.

**Expiry is the safety valve, and it is deliberately generous.** A refresh spends minutes
in model calls and document downloads; the TTL only has to outlast one *step*, because
the holder renews between steps. So an expired lease means the process is gone, not that
the work is slow, and a caller that finds one takes the lease rather than waiting for a
reaper that does not exist.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.db import InstrumentRefresh, utcnow
from awltux.timezones import as_utc

#: How long a lease lasts without a renewal. Long enough that the slowest single step --
#: a document download, or an appraisal of a long filing -- cannot expire underneath it,
#: short enough that a killed container releases the instrument within the hour.
LEASE_SECONDS = 1800

#: A lease that has run its course says so rather than staying "running" forever, because
#: `held` is what a reader is shown and a stale "running" reads as a hung job.
EXPIRED = "expired"


def new_token() -> str:
    """A fresh holder token."""
    return str(uuid.uuid4())


def locked_tickers(session: Session, *, now: dt.datetime | None = None) -> set[str]:
    """Instruments whose lease is currently held.

    Taken **once per run**, not once per item: the universe jobs call this at the top and
    carry the set, because the alternative is a query inside a loop over a thousand
    instruments on the one database everybody shares.
    """
    stamp = now or utcnow()
    rows = session.execute(
        select(InstrumentRefresh.instrument_t212_ticker)
        .where(InstrumentRefresh.state == "running")
        .where(InstrumentRefresh.expires_at > stamp)
    ).all()
    return {ticker for (ticker,) in rows if ticker}


def exclude_locked(statement, session: Session, column=None, *, now: dt.datetime | None = None):
    """Narrow a selection to instruments no scoped refresh currently holds.

    The one line a universe-wide job needs so it does not write the same company the
    refresh is working on. Applied to the *selection* rather than checked inside the
    loop, because a job that has already loaded its instrument list would otherwise have
    to re-ask per item -- and, worse, an instrument fetched into memory before the lease
    was taken would sail past a check placed after the load.

    ``column`` defaults to ``Instrument.t212_ticker`` and is passed explicitly by a caller
    selecting rows keyed by something else (`PriceBar`, `Filing`), because the filter has
    to name the column the rows actually carry.

    A no-op when nothing is locked, which is almost always -- so the cost is one indexed
    `SELECT` per run, not per instrument.
    """
    from awltux.db import Instrument

    locked = locked_tickers(session, now=now)
    if not locked:
        return statement
    return statement.where((column if column is not None else Instrument.t212_ticker).not_in(locked))


def acquire(
    session: Session,
    ticker: str,
    *,
    note: str | None = None,
    now: dt.datetime | None = None,
) -> InstrumentRefresh | None:
    """Take the lease for ``ticker``, or return ``None`` if somebody holds it.

    ``None`` rather than an exception: the caller is a web request that has to render
    "a refresh is already running" either way, and a refusal is a normal outcome of
    pressing a button twice rather than an error.

    An **expired** lease is taken over rather than respected -- see the module docstring.
    """
    stamp = now or utcnow()
    row = session.get(InstrumentRefresh, ticker)

    # `as_utc`, because SQLite hands back a naive datetime whatever the column declares
    # -- so `row.expires_at > stamp` is a naive-versus-aware comparison and raises
    # TypeError. This is the same trap `dashboard.py::job_log_page` and the scheduler's
    # own run rows have hit; `awltux.timezones` is the one normaliser for it.
    if row is not None and row.state == "running" and as_utc(row.expires_at) > stamp:
        return None

    expires = stamp + dt.timedelta(seconds=LEASE_SECONDS)
    if row is None:
        row = InstrumentRefresh(
            instrument_t212_ticker=ticker,
            token=new_token(),
            state="running",
            note=note,
            started_at=stamp,
            expires_at=expires,
            finished_at=None,
            steps=[],
        )
        session.add(row)
    else:
        row.token = new_token()
        row.state = "running"
        row.note = note
        row.started_at = stamp
        row.expires_at = expires
        row.finished_at = None
        row.steps = []
    session.flush()
    return row


def heartbeat(session: Session, ticker: str, *, token: str) -> bool:
    """Renew the lease between steps, if ``token`` still holds it.

    Commits, and that is the point: a renewal that is only in this transaction's memory
    is invisible to the other process that is deciding whether to skip this instrument,
    which is the only reader that matters.

    Returns whether the lease was still ours. A refresh that has been taken over -- its
    own TTL expired, somebody else started one -- should stop rather than carry on
    writing under a lease it no longer holds.
    """
    row = session.get(InstrumentRefresh, ticker)
    if row is None or row.token != token or row.state != "running":
        return False
    row.expires_at = utcnow() + dt.timedelta(seconds=LEASE_SECONDS)
    session.commit()
    return True


def record_step(
    session: Session,
    ticker: str,
    *,
    token: str,
    step: str,
    note: str | None,
    ok: bool,
) -> None:
    """Append one step's outcome to the lease row, for the page to read back.

    Uncommitted, unlike the heartbeat: the steps are a record of what the run did and are
    written by the same process that owns the lease, so they travel with it.
    """
    row = session.get(InstrumentRefresh, ticker)
    if row is None or row.token != token:
        return
    entries = list(row.steps or [])
    entries.append(
        {
            "step": step,
            "ok": ok,
            "note": note,
            "at": utcnow().isoformat(),
        }
    )
    row.steps = entries
    row.note = note


def release(
    session: Session,
    ticker: str,
    *,
    token: str,
    state: str = "done",
    note: str | None = None,
) -> None:
    """Give the lease up, if it is still ours, and say how the run ended.

    Only the holder releases, so a refresh whose TTL expired and was taken over cannot
    unlock the run that replaced it.
    """
    row = session.get(InstrumentRefresh, ticker)
    if row is None or row.token != token:
        return
    row.state = state
    row.note = note
    row.finished_at = utcnow()
    # Expired immediately: the row is history now, and leaving `expires_at` in the future
    # would keep the instrument out of every sweep until the TTL ran down.
    row.expires_at = utcnow()
    session.flush()


def expire_stale(session: Session, *, now: dt.datetime | None = None) -> int:
    """Mark leases that ran out as expired rather than leaving them "running".

    Not a reaper: it takes nothing over and releases nothing. It exists so the page stops
    saying "running" for a refresh whose process died, and so `state` and `expires_at`
    cannot disagree in the direction a reader would notice.
    """
    stamp = now or utcnow()
    rows = (
        session.execute(
            select(InstrumentRefresh)
            .where(InstrumentRefresh.state == "running")
            .where(InstrumentRefresh.expires_at <= stamp)
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.state = EXPIRED
        row.finished_at = stamp
    return len(rows)


def current(session: Session, ticker: str) -> InstrumentRefresh | None:
    """The instrument's lease row, held or not."""
    return session.get(InstrumentRefresh, ticker)


__all__ = [
    "EXPIRED",
    "LEASE_SECONDS",
    "acquire",
    "current",
    "expire_stale",
    "heartbeat",
    "locked_tickers",
    "new_token",
    "record_step",
    "release",
]

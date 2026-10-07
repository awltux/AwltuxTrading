"""Recording, and clearing, a job's inability to do its work for one instrument.

The record itself is :class:`~awltux.db.models.InstrumentBlocker`; this module owns the
two operations on it, so that "what counts as the same blocker" is decided once rather
than at each call site.

**A job records a blocker where it gives up, and clears it where it succeeds.** Both
halves matter and the second is the one that gets forgotten: a blocker that is never
cleared turns every past failure into a permanent accusation, and the "Needs attention"
filter becomes a list of things that used to be broken. That is why
:func:`clear_blocker` is called on the success path of the same step, not in a periodic
sweep -- a sweep would clear a blocker that a job is still failing on, on any run that
happened to fail before the sweep reached it.

Neither function commits: the caller owns the transaction, exactly as it does for the
work the blocker is about. A blocker is written in the same transaction as the row that
records the attempt, so a rolled-back attempt does not leave a complaint behind.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.db import InstrumentBlocker, utcnow

#: The reasons are the provider's words and can be long. Truncated at the column width
#: rather than rejected: a blocker with a clipped explanation is still a blocker, and
#: losing it because a traceback was 600 characters would be the worst of both.
REASON_LIMIT = 512


def record_blocker(
    session: Session,
    ticker: str,
    *,
    job: str,
    stage: str,
    reason: str,
) -> InstrumentBlocker:
    """Note that ``job`` could not do ``stage`` for ``ticker``, and why.

    Upserted on ``(ticker, job, stage)``: a failure that has now happened five runs
    running is one blocker with ``occurrences == 5``, because the question the filter
    asks is "is this still broken", not "how many times was it logged". A row that had
    been resolved starts counting again from zero, with ``resolved_at`` cleared -- a
    problem that came back is current, and the history is in ``first_seen_at``.
    """
    now = utcnow()
    existing = session.execute(
        select(InstrumentBlocker)
        .where(InstrumentBlocker.instrument_t212_ticker == ticker)
        .where(InstrumentBlocker.job == job)
        .where(InstrumentBlocker.stage == stage)
        .limit(1)
    ).scalar_one_or_none()

    text = " ".join((reason or "").split())[:REASON_LIMIT]

    if existing is None:
        row = InstrumentBlocker(
            instrument_t212_ticker=ticker,
            job=job,
            stage=stage,
            reason=text,
            first_seen_at=now,
            last_seen_at=now,
            occurrences=1,
            resolved_at=None,
        )
        session.add(row)
        # Flushed, not left pending, and it is load-bearing. The lookup above is a
        # SELECT, so it cannot see a row this transaction has added but not sent -- and a
        # job that records the same blocker twice in one run (two attempts at the same
        # instrument, or a retry) would insert a second row and fail the unique
        # constraint. Flushing here makes the upsert idempotent within a transaction,
        # which is the only place it was ever called.
        session.flush()
        return row

    if existing.resolved_at is not None:
        # Reopened: it was fixed and has broken again, so the count restarts and the
        # reason is the *current* one rather than the one it was fixed for.
        existing.resolved_at = None
        existing.first_seen_at = now
        existing.occurrences = 1
    else:
        existing.occurrences += 1
    existing.last_seen_at = now
    existing.reason = text
    return existing


def clear_blocker(session: Session, ticker: str, *, job: str, stage: str) -> None:
    """Note that ``job`` did ``stage`` for ``ticker``, so any blocker stops counting.

    Called on the success path, and it is deliberately quiet when there is nothing to
    clear: the overwhelming majority of successes are for instruments that were never
    blocked, and a function that had to be guarded at every call site would be one
    that gets forgotten at one of them.

    The row is kept and stamped rather than deleted. Deleting it would make a provider
    that fails every other run leave no trace at all, which is exactly the pattern
    worth noticing.
    """
    now = utcnow()
    rows = (
        session.execute(
            select(InstrumentBlocker)
            .where(InstrumentBlocker.instrument_t212_ticker == ticker)
            .where(InstrumentBlocker.job == job)
            .where(InstrumentBlocker.stage == stage)
            .where(InstrumentBlocker.resolved_at.is_(None))
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.resolved_at = now


__all__ = ["REASON_LIMIT", "clear_blocker", "record_blocker"]

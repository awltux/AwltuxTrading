"""Refreshing one instrument: the sequence, and running it under a lease.

An instrument can be suggested as a strong buy while most of what the suggestion rests on
has never been fetched. The dashboard then shows a confident call built on an em-dash,
and the reader has no way to ask "what would you say if you actually had the data?" --
the scheduled jobs rotate at their own pace, rationed to free-tier budgets, and waiting
for an instrument's turn is hours to days.

This module is that ask. It runs the pipeline stages **for one company, in dependency
order**, and reports each step's outcome.

**The order is derived, not restated.** ``JobSpec.depends_on`` is the declared pipeline
and :func:`~awltux.scheduler.dependencies.dependency_order` already sorts by it, so the
sequence here is built from the registry rather than written out a second time -- two
orders that agree today and disagree after the next new job is a bug that shows up as a
wrong answer rather than as an error. :data:`OVERRIDES` is the one exception and is
declared as such, with its reason.

**It runs the job functions, not copies of them.** Each step calls the same entry point
the scheduler calls, with a ticker scope. That matters more than it looks: a step
therefore records the same blockers, writes the same progress lines and reports in the
same shape as a scheduled run, so the Operations page and the attention filter cannot
disagree about what happened.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from awltux.db import Instrument, utcnow
from awltux.scheduler import progress

if TYPE_CHECKING:  # pragma: no cover - typing only
    from awltux.scheduler.jobs import JobResult

logger = logging.getLogger(__name__)

#: How long the whole refresh may take before it gives up and releases the lease. Not a
#: per-step timeout -- a step is a network call whose latency is not ours to bound -- but
#: a backstop so a wedged provider cannot hold an instrument out of every sweep.
TOTAL_BUDGET_SECONDS = 900


@dataclass(frozen=True, slots=True)
class Step:
    """One stage of the refresh, and how to run it for a single instrument."""

    job: str
    label: str
    #: Called with the scope. Every registered job entry point takes an optional
    #: ``tickers`` list; see the note in ``ingest/jobs.py``.
    run: Callable[..., JobResult]


def _parse_documents(tickers: list[str] | None = None):
    """Read the filings this refresh downloaded, so their events reach the decision.

    Not a registered job: it is only ever invoked here, because it is the one step whose
    cost is proportional to what the *previous* step just downloaded. Registered, it
    would need a coverage probe and an interval, and it would then be free to run over
    the whole backlog on the scheduler's timetable for no stated reason.
    """
    from awltux.db.session import session_scope
    from awltux.ingest.parsing import extract_held_filings
    from awltux.scheduler.jobs import JobResult

    with session_scope() as session:
        report = extract_held_filings(session, tickers=tickers)

    return JobResult(
        items_seen=report["attempted"],
        items_written=report["parsed"],
        note=(
            f"{report['parsed']} document(s) read, {report['events']} filing event(s)"
            if report["parsed"]
            else None
        ),
        detail=report,
    )


def _steps_from_registry() -> tuple[Step, ...]:
    """The scoped step list, in the order the registry declares."""
    from awltux.scheduler.dependencies import dependency_order
    from awltux.scheduler.registry import build_job_specs

    specs = {spec.id: spec for spec in build_job_specs()}
    ordered = dependency_order(list(specs.values()))

    steps: list[Step] = []
    for spec in ordered:
        if spec.id not in SCOPED_JOBS:
            continue
        steps.append(Step(job=spec.id, label=spec.description.split(",")[0], run=spec.func))

    # The document read is placed where its *input* is: immediately after the download
    # that produces it and before the decision that reads its events. It is not in the
    # registry, so `dependency_order` has nothing to say about it.
    after = steps.index(next(step for step in steps if step.job == "shareholder_reports"))
    steps.insert(
        after + 1, Step(job="document_parsing", label="Read the filings", run=_parse_documents)
    )
    return _apply_overrides(tuple(steps))


#: The registry jobs this refresh runs, and it is deliberately not all of them.
#:
#: Left out and why: ``t212_instruments``, ``universe_refresh`` and ``macro_rates`` are
#: facts about the world rather than about a company (a scoped run cannot fetch one
#: instrument's universe membership); ``price_intraday`` is a display feed; ``edgar_events``
#: polls a global feed; ``calibration`` and ``retention`` are housekeeping.
SCOPED_JOBS = frozenset(
    {
        "symbol_resolution",
        "price_eod",
        "filings_edgar",
        "shareholder_reports",
        "xbrl_statements",
        "fundamentals",
        "uk_companies",
        "news_rss",
        "news_relevance",
        "news_analysis",
        "sentiment",
        "valuation",
        "decision",
    }
)

#: Steps that must run in an order ``dependency_order`` does not produce, with the reason.
#:
#: ``symbol_resolution`` is declared *after* ``price_eod`` because its coverage probe asks
#: "which instruments have an ISIN but no price history" -- for a sweep, that question can
#: only be asked once a price run has been attempted. For one company the data dependency
#: runs the other way: a wrong derived symbol is *why* the price request fails, so a
#: refresh that prices first reports a failure and then fixes the cause without retrying.
#: Reordering costs nothing on a sweep, which does not use this list.
OVERRIDES: tuple[str, ...] = ("symbol_resolution", "price_eod")


def _apply_overrides(steps: tuple[Step, ...]) -> tuple[Step, ...]:
    """Move the overridden steps to the front, in the declared order."""
    by_job = {step.job: step for step in steps}
    front = [by_job[job] for job in OVERRIDES if job in by_job]
    rest = [step for step in steps if step.job not in OVERRIDES]
    return tuple(front + rest)


def steps() -> tuple[Step, ...]:
    """The refresh sequence. Built per call because the registry depends on settings."""
    return _steps_from_registry()


def step_ids() -> tuple[str, ...]:
    return tuple(step.job for step in steps())


def run(
    session: Session,
    ticker: str,
    *,
    token: str,
    settings=None,
    steps_to_run: Sequence[Step] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, object]:
    """Run every step for one instrument, renewing the lease as it goes.

    Each step is called with the scope, and its outcome is recorded on the lease row as
    it finishes so the instrument page can show progress while the run is still going.

    **A step that raises does not stop the refresh.** The pipeline is a chain of
    independent fetches; a Yahoo failure says nothing about whether EDGAR will answer,
    and stopping at the first error would make the button useless exactly when the data
    is in the worst state. The failure is recorded against its step and the run carries
    on to the ones that can still work -- which is what the reader asked for.

    **The budget and the lease are both checked between steps.** A refresh that lost its
    lease has been taken over (its TTL expired), so it stops rather than writing under a
    lock somebody else now holds.
    """
    from awltux.ingest.lease import heartbeat, record_step

    scope = [ticker]
    sequence = list(steps_to_run if steps_to_run is not None else steps())
    started = now or utcnow()
    deadline = started + dt.timedelta(seconds=TOTAL_BUDGET_SECONDS)

    results: list[dict[str, object]] = []
    for position, step in enumerate(sequence, start=1):
        progress.note(f"step {position} of {len(sequence)}: {step.job}")

        if not heartbeat(session, ticker, token=token):
            # Somebody else holds the instrument now. Stop rather than race them.
            progress.note(f"lease lost before {step.job}; stopping")
            record_step(
                session, ticker, token=token, step=step.job, note="lease lost", ok=False
            )
            return {"stopped": "lease lost", "steps_done": position - 1, "results": results}
        if utcnow() > deadline:
            record_step(
                session, ticker, token=token, step=step.job, note="budget exhausted", ok=False
            )
            return {
                "stopped": f"budget of {TOTAL_BUDGET_SECONDS}s exhausted",
                "steps_done": position - 1,
                "results": results,
            }

        note: str | None = None
        ok = True
        try:
            result = step.run(scope)
            note = getattr(result, "note", None) or _summarise(result)
        except Exception as exc:  # noqa: BLE001 - one step must not end the refresh
            ok = False
            note = f"{type(exc).__name__}: {exc}"
            logger.warning("refresh step %s failed for %s: %s", step.job, ticker, exc)

        record_step(session, ticker, token=token, step=step.job, note=note, ok=ok)
        session.commit()
        results.append({"step": step.job, "ok": ok, "note": note})

    return {"steps_done": len(sequence), "results": results}


def run_under_lease(ticker: str, token: str) -> dict[str, object]:
    """Run the sequence under a lease this caller already holds, then give the lease up.

    The one place that does, because the release has to happen on the failure path as well:
    a refresh that dies still holding its lease keeps the instrument out of every sweep until
    the TTL expires, which is the one thing the lease cannot recover from on its own.

    Two callers, and they differ only in how the lease was taken: the web button claims it
    before starting a thread (so pressing the button twice refuses the second), and the
    scheduled held-name sweep claims one per instrument as it reaches it.

    Returns what :func:`run` produced, or ``{"failed": ...}`` when a step raised out of the
    sequence itself. It does not raise: whether that failure ends the caller's run is the
    caller's decision, and they make it differently.
    """
    from awltux.db.session import session_scope
    from awltux.ingest.lease import release

    outcome: dict[str, object] = {}
    failed: str | None = None
    try:
        with session_scope() as session:
            outcome = run(session, ticker, token=token)
    except Exception as exc:  # noqa: BLE001 - the lease must be released either way
        failed = f"{type(exc).__name__}: {exc}"
        logger.exception("instrument refresh failed for %s", ticker)

    with session_scope() as session:
        release(
            session,
            ticker,
            token=token,
            state="failed" if failed else "done",
            note=failed or summary(outcome),
        )

    if failed:
        return {"failed": failed, **outcome}
    return outcome


def summary(outcome: dict[str, object]) -> str:
    """One line naming what the refresh did, for the lease row the page reads."""
    results = outcome.get("results") or []
    ok = sum(1 for row in results if row.get("ok"))
    return f"{ok} of {len(results)} steps completed"


def _summarise(result: object) -> str | None:
    """A one-line outcome from a ``JobResult`` that carries no note of its own."""
    written = getattr(result, "items_written", None)
    seen = getattr(result, "items_seen", None)
    if written is None and seen is None:
        return None
    return f"{written if written is not None else 0} written of {seen if seen is not None else 0} seen"


def instrument_or_none(session: Session, ticker: str) -> Instrument | None:
    """The instrument a refresh was asked for, if it is one we analyse."""
    instrument = session.get(Instrument, ticker)
    if instrument is None or not instrument.in_universe or instrument.excluded:
        return None
    return instrument


__all__ = [
    "OVERRIDES",
    "SCOPED_JOBS",
    "TOTAL_BUDGET_SECONDS",
    "Step",
    "instrument_or_none",
    "run",
    "run_under_lease",
    "step_ids",
    "steps",
    "summary",
]

"""Triggers that came due while nothing was running.

The scheduler's triggers are ``IntervalTrigger``s anchored to process start and its
job store is in memory, so no part of a schedule survives a restart. That turns a
missed trigger from *late* into *never*: on the next start the interval is recomputed
from *now*, so a job with a daily interval is next due a day after the process came
back -- and this process is restarted every morning, because the machine is switched
off overnight. A daily job on that machine never runs at all.

Measured on the live database before this existed: ``news_rss`` -- hourly at the time, and
daily since 2026-10-16 -- had not run for **23.7 hours** while the process was up, and
**eight of the twenty-one** registered jobs were past their interval at the moment of
measuring. The job that prompted this is now on the *other* side of it: a daily poll is
exactly the case a restart can skip entirely, which is what this catches.

**The run table is the source, not a second one.** ``ingest_run`` already holds a
durable row per execution and already survives the process -- the drain reads it for
exactly that reason. A persisted APScheduler job store would be a parallel record of a
schedule that is also printed from the registry, and the two could disagree.

**Collated, not replayed.** However many triggers went past, the job runs once. That is
APScheduler's ``coalesce``, and it is the only sane reading of a ten-hour outage:
replaying an hourly job ten times spends ten times the provider budget to arrive at the
state one run already reaches.

**What this deliberately does not do is bootstrap.** A job that has never run has no
missed trigger -- there was no schedule yet -- so it keeps the randomised first run the
scheduler gives everything, and ``run_on_start`` stays the way a fresh container
declares which jobs must populate their dependencies immediately.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from awltux.scheduler.jobs import JobSpec

#: How many missed triggers may be enumerated one by one when working out a job's next
#: firing time. Past this the *last* missed trigger is used instead of the first.
#:
#: Both give the same run -- APScheduler coalesces the enumeration down to its last
#: entry and re-anchors the phase there -- so this only bounds how much work the
#: scheduler thread does at startup while holding the job-store lock. At the registry's
#: one-hour floor it is ten days, which is already far past the point where the
#: difference between "ten days behind" and "a year behind" changes anything.
MAX_ENUMERATED_MISSES = 240


@dataclass(frozen=True, slots=True)
class CatchUp:
    """One trigger that came due while nothing was running, and one run to answer it."""

    job_id: str
    #: When the job last did something that counted, from the run history. A run that
    #: failed or was interrupted does not count -- see ``jobs.last_successful_runs``.
    last_success: dt.datetime
    interval_seconds: int
    #: How many triggers went past. Recorded because it is the difference between "the
    #: process was down for an hour" and "for a week", which a timestamp alone hides.
    missed: int
    #: The instant the decision was made, so ``overdue_by`` is a fact about the startup
    #: rather than about whenever a reader happens to look.
    as_of: dt.datetime

    @property
    def due_at(self) -> dt.datetime:
        """The most recent trigger the job missed -- the one this run answers.

        This is where the trigger's phase resumes: APScheduler advances the next fire
        time from the coalesced run time, so an hourly job that missed a day goes back
        to firing hourly rather than staying a day out of step.
        """
        return self.last_success + dt.timedelta(seconds=self.missed * self.interval_seconds)

    @property
    def scheduled_at(self) -> dt.datetime:
        """Where the catch-up is *scheduled*, which is the **first** missed trigger.

        Not the last one, although that is the run that happens. Scheduling at the
        first is what makes the schedule of catch-ups mean something: it is monotone
        with how long the job has gone unrun, and APScheduler runs due jobs in
        ascending due-time order, so the ordering this module returns is the ordering
        the single worker actually works through. See :func:`catch_ups`.
        """
        return self.last_success + dt.timedelta(seconds=self.interval_seconds)

    @property
    def overdue_by(self) -> dt.timedelta:
        """How long past its first unanswered trigger the job is."""
        return self.as_of - self.scheduled_at

    @property
    def cause(self) -> str:
        """The line the run's progress log opens with, so a catch-up says so."""
        return (
            f"catching up: last successful run {self.last_success:%Y-%m-%d %H:%M}Z, "
            f"{self.missed} trigger(s) due since; running once"
        )


def catch_up_for(
    job_id: str,
    last_success: dt.datetime | None,
    interval_seconds: int,
    now: dt.datetime,
) -> CatchUp | None:
    """The catch-up this job is owed, or ``None`` if it is not behind.

    A pure function of the last successful run and the interval, so the rule can be
    tested as a rule rather than through whatever a database happens to hold.

    ``missed`` counts the interval boundaries in ``(last_success, now]``. Anything
    before the last of them has already been collated away, so a job three weeks behind
    and a job one interval behind both return a single catch-up -- which is the point,
    and why the count is carried rather than acted on.
    """
    # A job that has never succeeded is not behind: it has not missed anything, because
    # it had no schedule to miss. Bootstrapping is `run_on_start`'s job, and a job that
    # has only ever failed gets its ordinary first run within the spread -- retrying it
    # at every start would be the stampede that rule exists to prevent.
    if last_success is None:
        return None
    # Defensive: a zero or negative interval would divide by zero or make every instant
    # "due since forever". `test_scheduler` enforces the real floor.
    if interval_seconds <= 0:
        return None

    elapsed = (now - last_success).total_seconds()
    missed = int(elapsed // interval_seconds)
    if missed < 1:
        return None
    return CatchUp(
        job_id=job_id,
        last_success=last_success,
        interval_seconds=interval_seconds,
        missed=missed,
        as_of=now,
    )


def catch_ups(
    specs: Iterable[JobSpec],
    last_successes: Mapping[str, dt.datetime],
    now: dt.datetime,
) -> list[CatchUp]:
    """What every job is owed after a restart, most overdue first.

    Most overdue first is the ordering because it is the only priority that needs
    nobody to maintain it: the job whose data is oldest is the one worth refreshing
    first, and after an outage that is exactly the question. ``MAX_CONCURRENT_JOBS`` is
    one, so this order decides what the single worker does next -- and it is the same
    order APScheduler will use, because it works through due jobs by due time and
    :attr:`CatchUp.scheduled_at` is what the job is given as its next run.

    ``run_on_start`` jobs are excluded because they run on every start regardless --
    scheduling them twice would be a second run of the same job at the same second.
    Disabled jobs are excluded because a paused job is not a missed one. Manual-only
    jobs are excluded because there is no interval to be behind: nothing was owed to a
    job nobody asked to run, and the ones that spend model calls -- the repairs -- must
    not be triggered by a restart on the strength of having been run once by hand.
    """
    owed: list[CatchUp] = []
    for spec in specs:
        interval = spec.interval_seconds
        if not spec.enabled or spec.run_on_start or interval is None:
            continue
        found = catch_up_for(spec.id, last_successes.get(spec.id), interval, now)
        if found is not None:
            owed.append(found)
    # `sorted` is stable, so jobs due at the same instant stay in registry order --
    # which is the pipeline order the registry is written in.
    return sorted(owed, key=lambda one: one.scheduled_at)


def next_run_time_for(owed: CatchUp) -> dt.datetime:
    """Where to schedule a catch-up: the first missed trigger, within the bound.

    Enumerating every missed trigger is free for a night off (ten entries) and
    unbounded in principle, so a job that has not run for years falls back to the last
    one. Both produce the same single run, for the reason in ``MAX_ENUMERATED_MISSES``.
    """
    if owed.missed <= MAX_ENUMERATED_MISSES:
        return owed.scheduled_at
    return owed.due_at

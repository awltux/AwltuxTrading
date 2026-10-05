"""Job dependencies, and which job to run next.

The Operations page listed fifteen jobs and a history, and left you to work out
the order from the descriptions. Two different questions were missing, and they
have different answers:

* **What has to run before this job?** That is a fact about the pipeline, so it is
  *declared* -- ``JobSpec.depends_on`` -- rather than inferred from the run
  history, which only ever says what happened, not what is required.
* **Which job should I run now?** That is a fact about the data, so it is
  *measured*: each probe below counts the universe's coverage of what that job
  produces. A job that has never run and a job whose dependency has never run look
  identical in a run history, and they need different actions.

Both are reported together, because either alone is misleading. Coverage alone
would suggest running ``valuation`` on a universe with no accounts; the dependency
alone would say everything is ready when four hundred instruments have no prices.

The probes are deliberately counts rather than "is the table non-empty". The
useful question on a half-built database -- which is the normal state of this one
-- is how much is missing, not whether anything exists at all.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from awltux.db import (
    DecisionOutcome,
    DecisionRun,
    Filing,
    FundamentalPeriod,
    IngestRun,
    Instrument,
    NewsAnalysis,
    NewsItem,
    PriceBar,
    SentimentSeries,
    ValuationRun,
    utcnow,
)
from awltux.ingest.symbols import is_uk_listing

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from awltux.scheduler.jobs import JobSpec

#: How recent a story must be for "awaiting appraisal" to be a fair statement.
#: Older material stories are not this job's outstanding work; they are history.
APPRAISAL_WINDOW_DAYS = 14


@dataclass(slots=True)
class JobStatus:
    """One job's place in the pipeline, and what is left for it to do."""

    id: str
    description: str
    #: Jobs that must have run for this one to do anything useful.
    depends_on: tuple[str, ...] = ()
    #: Dependencies that have never completed successfully.
    never_ran: list[str] = field(default_factory=list)
    #: Universe instruments (or stories, or decisions) still lacking this job's
    #: output. ``None`` where the job has no backfill notion at all.
    outstanding: int | None = None
    #: One plain sentence: what is missing, or why nothing is.
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.never_ran)

    @property
    def has_work(self) -> bool:
        return self.outstanding is not None and self.outstanding > 0

    @property
    def runnable(self) -> bool:
        """Worth running now: something to do, and nothing owed first."""
        return self.has_work and not self.blocked

    def as_dict(self) -> dict[str, object]:
        return {
            "job": self.id,
            "needs": list(self.depends_on),
            "never_ran": list(self.never_ran),
            "outstanding": self.outstanding,
            "reason": self.reason,
            "runnable": self.runnable,
        }


# --------------------------------------------------------------------------- #
# coverage helpers
# --------------------------------------------------------------------------- #


def _universe_rows(session: Session) -> list[Instrument]:
    return list(
        session.execute(
            select(Instrument)
            .where(Instrument.in_universe.is_(True))
            .where(Instrument.excluded.is_(False))
        )
        .scalars()
        .all()
    )


def _covered(session: Session, column) -> set[str]:
    return {value for (value,) in session.execute(select(column).distinct()).all() if value}


def _missing(session: Session, column) -> set[str]:
    """Universe tickers with no row carrying the given ticker column."""
    rows = _universe_rows(session)
    return {row.t212_ticker for row in rows} - _covered(session, column)


def _note(missing: int, total: int, what: str) -> str:
    if total == 0:
        return "no universe to cover"
    if missing == 0:
        return f"all {total:,} in the universe have {what}"
    return f"{missing:,} of {total:,} in the universe have {what}"


def _count(session: Session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


# --------------------------------------------------------------------------- #
# probes: what does this job still have to do?
# --------------------------------------------------------------------------- #


def _probe_t212_instruments(session: Session) -> tuple[int | None, str]:
    total = _count(session, Instrument)
    if total == 0:
        return 1, "no instruments stored, so nothing downstream can run"
    return 0, f"{total:,} instruments stored"


def _probe_universe_refresh(session: Session) -> tuple[int | None, str]:
    universe = len(_universe_rows(session))
    if universe:
        return 0, f"{universe:,} selected for analysis"
    stored = _count(session, Instrument)
    if stored == 0:
        return 1, "no instruments to select from"
    return 1, f"{stored:,} instruments stored but none is selected"


def _probe_price_eod(session: Session) -> tuple[int | None, str]:
    rows = _universe_rows(session)
    missing = len({row.t212_ticker for row in rows} - _covered(session, PriceBar.instrument_t212_ticker))
    return missing, _note(missing, len(rows), "end-of-day price history")


def _probe_price_intraday(session: Session) -> tuple[int | None, str]:
    # Quotes are point-in-time: there is no backfill, so this is never "outstanding".
    return None, "polls live quotes during market hours; there is nothing to backfill"


def _probe_fundamentals(session: Session) -> tuple[int | None, str]:
    rows = _universe_rows(session)
    missing = len(
        {row.t212_ticker for row in rows} - _covered(session, FundamentalPeriod.instrument_t212_ticker)
    )
    return missing, _note(missing, len(rows), "accounts stored")


def _probe_filings_edgar(session: Session) -> tuple[int | None, str]:
    rows = _universe_rows(session)
    us = [row for row in rows if not is_uk_listing(row.exchange_name, row.yahoo_symbol)]
    missing = len({row.t212_ticker for row in us} - _covered(session, Filing.instrument_t212_ticker))
    note = _note(missing, len(us), "a filing record")
    return missing, f"{note} (US listings only; UK accounts come from Companies House)"


def _probe_edgar_events(session: Session) -> tuple[int | None, str]:
    return None, "polls the EDGAR current-events feed; there is nothing to backfill"


def _probe_uk_companies(session: Session) -> tuple[int | None, str]:
    rows = _universe_rows(session)
    uk = [row for row in rows if is_uk_listing(row.exchange_name, row.yahoo_symbol)]
    missing = [row for row in uk if not row.ch_company_number]
    if not uk:
        return 0, "no UK listings in the universe"
    if not missing:
        return 0, f"all {len(uk):,} UK listings resolved"
    return len(missing), f"{len(missing):,} of {len(uk):,} UK listings have no company number"


def _probe_news_rss(session: Session) -> tuple[int | None, str]:
    total = _count(session, NewsItem)
    if total == 0:
        return 1, "no news stored"
    return 0, f"{total:,} stories stored"


def _probe_news_analysis(session: Session) -> tuple[int | None, str]:
    analysed = select(NewsAnalysis.news_item_id)
    pending = session.execute(
        select(func.count())
        .select_from(NewsItem)
        .where(NewsItem.published_at >= utcnow() - dt.timedelta(days=APPRAISAL_WINDOW_DAYS))
        .where(NewsItem.materiality.in_(("material", "critical")))
        .where(NewsItem.id.not_in(analysed))
    ).scalar_one()
    if pending == 0:
        return 0, f"no material story from the last {APPRAISAL_WINDOW_DAYS} days is unappraised"
    return pending, f"{pending:,} material stories from the last {APPRAISAL_WINDOW_DAYS} days unappraised"


def _probe_sentiment(session: Session) -> tuple[int | None, str]:
    rows = _universe_rows(session)
    covered = {
        value
        for (value,) in session.execute(
            select(SentimentSeries.scope_id).where(SentimentSeries.scope_type == "instrument").distinct()
        ).all()
        if value
    }
    missing = len({row.t212_ticker for row in rows} - covered)
    return missing, _note(missing, len(rows), "a sentiment score")


def _probe_valuation(session: Session) -> tuple[int | None, str]:
    rows = _universe_rows(session)
    missing = len(
        {row.t212_ticker for row in rows} - _covered(session, ValuationRun.instrument_t212_ticker)
    )
    return missing, _note(missing, len(rows), "a valuation on record")


def _probe_decision(session: Session) -> tuple[int | None, str]:
    rows = _universe_rows(session)
    missing = len(
        {row.t212_ticker for row in rows} - _covered(session, DecisionRun.instrument_t212_ticker)
    )
    return missing, _note(missing, len(rows), "a decision on record")


def _probe_calibration(session: Session) -> tuple[int | None, str]:
    waiting = session.execute(
        select(func.count())
        .select_from(DecisionRun)
        .where(DecisionRun.id.not_in(select(DecisionOutcome.decision_run_id)))
    ).scalar_one()
    if waiting == 0:
        return 0, "every decision has been scored"
    # Not outstanding work: the horizons have to elapse before there is anything
    # to score. Reporting a waiting count as a queue would invite pointless runs.
    return None, f"{waiting:,} decisions waiting for their horizon to elapse"


def _probe_retention(session: Session) -> tuple[int | None, str]:
    return None, "housekeeping; it depends on nothing and nothing depends on it"


#: One probe per job id. Kept separate from the registry so the scheduler package
#: still imports without touching the database, and asserted complete by a test so
#: adding a job without saying what it produces fails loudly.
PROBES = {
    "t212_instruments": _probe_t212_instruments,
    "universe_refresh": _probe_universe_refresh,
    "price_eod": _probe_price_eod,
    "price_intraday": _probe_price_intraday,
    "fundamentals": _probe_fundamentals,
    "filings_edgar": _probe_filings_edgar,
    "edgar_events": _probe_edgar_events,
    "uk_companies": _probe_uk_companies,
    "news_rss": _probe_news_rss,
    "news_analysis": _probe_news_analysis,
    "sentiment": _probe_sentiment,
    "valuation": _probe_valuation,
    "decision": _probe_decision,
    "calibration": _probe_calibration,
    "retention": _probe_retention,
}


# --------------------------------------------------------------------------- #
# ordering and reporting
# --------------------------------------------------------------------------- #


def dependency_order(specs: list[JobSpec]) -> list[JobSpec]:
    """Specs in an order where every dependency precedes what depends on it.

    Declaration order breaks ties, so the pipeline reads top-to-bottom the way the
    registry is written. A cycle raises rather than silently dropping jobs: a job
    that can never run in order is a bug in the declaration, not a runtime state.
    """
    by_id = {spec.id: spec for spec in specs}
    ordered: list[JobSpec] = []
    placed: set[str] = set()
    remaining = list(specs)

    while remaining:
        progressed = False
        for spec in list(remaining):
            if all(dep in placed or dep not in by_id for dep in spec.depends_on):
                ordered.append(spec)
                placed.add(spec.id)
                remaining.remove(spec)
                progressed = True
        if not progressed:
            stuck = ", ".join(sorted(spec.id for spec in remaining))
            raise ValueError(f"job dependencies contain a cycle: {stuck}")
    return ordered


def jobs_that_have_ever_succeeded(session: Session) -> set[str]:
    return {
        job
        for (job,) in session.execute(
            select(IngestRun.job).where(IngestRun.ok.is_(True)).distinct()
        ).all()
        if job
    }


def job_statuses(session: Session, specs: list[JobSpec]) -> list[JobStatus]:
    """Every job in dependency order, with what it needs and what it owes."""
    succeeded = jobs_that_have_ever_succeeded(session)
    built: dict[str, JobStatus] = {}
    statuses: list[JobStatus] = []

    for spec in dependency_order(specs):
        probe = PROBES.get(spec.id)
        outstanding, reason = probe(session) if probe else (None, "no coverage check defined")

        # Only a *declared* dependency can block -- a job that merely reads a table
        # another job writes, without saying so, is a missing declaration rather
        # than a silent pass. And a dependency blocks only if it has *both* no
        # successful run and nothing to show for itself.
        #
        # The first draft blocked on the run history alone, and the live page
        # showed why that is wrong: `news_rss` had stored 5,739 stories but had
        # never once completed a run -- it takes forty minutes, and every deploy
        # restarted it -- so `news_analysis` was reported blocked with 62 stories
        # sitting there waiting to be appraised. The history was true and the
        # conclusion was useless.
        #
        # The question that decides whether a job can do anything is whether its
        # dependency has *produced* something, and the probe already answers that.
        # History only distinguishes "owed but already delivered" from "owed and
        # nothing there".
        never_ran = [
            dependency
            for dependency in spec.depends_on
            if dependency not in succeeded
            and (built.get(dependency) is None or built[dependency].has_work)
        ]

        status = JobStatus(
            id=spec.id,
            description=spec.description,
            depends_on=tuple(spec.depends_on),
            never_ran=never_ran,
            outstanding=outstanding,
            reason=reason,
        )
        built[spec.id] = status
        statuses.append(status)
    return statuses


def next_steps(statuses: list[JobStatus]) -> list[JobStatus]:
    """The jobs worth running now, in order.

    A job is a next step when it has work the data shows is missing and nothing it
    declares is waiting on an empty dependency. Blocked jobs are excluded, not
    ranked lower: running them first is the mistake this list exists to prevent.
    """
    return [status for status in statuses if status.runnable]

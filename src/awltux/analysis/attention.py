"""Which instruments a reader should not trust yet, and exactly why.

The dashboard can show a fair value, a score and a gate verdict for a company whose
accounts were never fetched, whose filings are sitting unparsed, or whose balance sheet
does not add up. Every one of those renders as a number rather than as a gap, because
all of them produce the same em-dash in the same column. This module answers the
question the reader actually has -- *can I believe this row?* -- as a short list of
named reasons.

**The reasons are graded, and one setting picks the rung.** The system is still settling,
so what counts as a problem changes as coverage improves; rather than rewriting the rule
set each time, each reason carries the level at which it starts to count and
``config.yaml``'s ``app.attention_level`` (1..3) selects how strict the filter is, so
raising it is the only change needed. The ladder is cumulative. Measured against the live
universe, 2026-10-07:

===========  ==========================================================  ===========
level        reasons                                                      instruments
===========  ==========================================================  ===========
1            the figures we hold are wrong or incomplete                 ~25 of 500
2            and we cannot obtain the accounts at all                    ~190
3            and we have not finished covering it                        ~90%
===========  ==========================================================  ===========

Level 3 is the honest long-run test and it is not the default, because a filter that
selects almost the whole table tells the reader nothing. That is also why the levels are
not "severity": a level-3 reason is not more alarming than a level-1 one, it is one that
stops being *exceptional* once the system has settled.

**Only conditions that can actually fire are here.** Two candidates were measured and
left out rather than written: every annual series in the database is gap-free, and no
instrument's two sources disagree by more than 5% about the same year. Both are real
risks and neither has an instance today, so a check for them would be a branch nothing
can exercise.

**The raw accounting checks are deliberately not a reason.** `ledger.checks` fails for
**37 of the 43** instruments that hold accounts, but the linkbase work showed most of
those are *our* missing lines rather than the filer's arithmetic -- `assets_composition`
alone fails for 36. Flagging on it would mark 86% of the covered universe as suspect
while saying nothing about the company. The equation is different: it compares two
figures we hold, so an imbalance is a real contradiction.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from awltux.analysis import ledger
from awltux.config import Settings, get_settings
from awltux.db import (
    DecisionRun,
    Filing,
    FundamentalPeriod,
    Instrument,
    InstrumentBlocker,
    ResearchReport,
)
from awltux.ingest.symbols import is_uk_listing
from awltux.metrics import value_of

#: The highest rung the setting may name. The level itself lives in ``config.yaml``
#: (``app.attention_level``); this is only the bound the reasons are graded within.
MAX_LEVEL = 3

#: How old the latest annual accounts may be before they are treated as stale. 550 days
#: is eighteen months: a December year end is filed by the following spring, so a
#: further nine months of silence means the company has missed a reporting cycle rather
#: than that we have missed a fetch.
STALE_AFTER_DAYS = 550

#: The figures without which an annual period cannot support a valuation. Both are also
#: what the multi-year markers divide by, so a period missing either is one the analysis
#: silently skips.
HEADLINE_METRICS = ("revenue", "total_assets")

#: The status a `Filing` carries until an extractor has read the document. "Held but
#: nothing has parsed it" is exactly "still pending", because no other step sets it.
UNPARSED_STATUS = "pending"


@dataclass(frozen=True, slots=True)
class Reason:
    """One named problem with one instrument."""

    code: str
    #: What the reader sees. Short, because it goes in a badge and a tooltip.
    label: str
    #: The rung at which this starts to count. See the module docstring.
    level: int
    #: The specifics -- the figures, the count, the provider's words. A reason that does
    #: not say what it measured is a verdict, and a verdict is not a finding.
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Attention:
    """Every reason an instrument needs looking at, at the configured level or below."""

    ticker: str
    level: int
    reasons: tuple[Reason, ...] = ()

    @property
    def needed(self) -> bool:
        return bool(self.reasons)

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(reason.code for reason in self.reasons)

    def summary(self) -> str:
        """One line naming every reason, for a tooltip."""
        return "; ".join(
            f"{reason.label} — {reason.detail}" if reason.detail else reason.label
            for reason in self.reasons
        )


class _Facts:
    """Everything the rules need about one instrument, gathered in bulk.

    One object per instrument rather than a query per rule: the rules are pure functions
    of these facts, and the queries are the expensive part. A page render must not run
    five queries per row for 500 rows.
    """

    __slots__ = (
        "blockers",
        "decision_action",
        "filings",
        "instrument",
        "parsed",
        "period",
        "periods",
        "research_verdict",
    )

    def __init__(self, instrument: Instrument) -> None:
        self.instrument = instrument
        #: The latest annual period we hold, if any. Annual rather than "latest of any
        #: type" -- an interim does not answer "has this company reported this year".
        self.period: FundamentalPeriod | None = None
        self.periods = 0
        self.blockers: list[InstrumentBlocker] = []
        self.filings = 0
        self.parsed = 0
        #: The newest finished deep-dive's verdict, and the newest decision's long-term
        #: action. Kept as the two strings the conflict rule compares rather than as rows:
        #: nothing else on the page reads them, and a row would hold the whole report.
        self.research_verdict: str | None = None
        self.decision_action: str | None = None


def _gather(session: Session, instruments: Sequence[Instrument]) -> dict[str, _Facts]:
    """Gather every rule's inputs for ``instruments`` in four queries."""
    facts = {row.t212_ticker: _Facts(row) for row in instruments}
    if not facts:
        return facts
    tickers = list(facts)

    periods = (
        session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker.in_(tickers))
            .where(FundamentalPeriod.period_type == "annual")
            .order_by(FundamentalPeriod.period_end)
        )
        .scalars()
        .all()
    )
    for period in periods:
        entry = facts[period.instrument_t212_ticker]
        entry.periods += 1
        if entry.period is None or period.period_end > entry.period.period_end:
            entry.period = period

    for blocker in (
        session.execute(
            select(InstrumentBlocker)
            .where(InstrumentBlocker.instrument_t212_ticker.in_(tickers))
            .where(InstrumentBlocker.resolved_at.is_(None))
        )
        .scalars()
        .all()
    ):
        facts[blocker.instrument_t212_ticker].blockers.append(blocker)

    # Counted per (instrument, status) in one grouped query rather than two aggregates.
    for ticker, status, count in session.execute(
        select(
            Filing.instrument_t212_ticker,
            Filing.status,
            func.count(Filing.id),
        )
        .where(Filing.instrument_t212_ticker.in_(tickers))
        .group_by(Filing.instrument_t212_ticker, Filing.status)
    ).all():
        entry = facts[ticker]
        entry.filings += count
        if status != UNPARSED_STATUS:
            entry.parsed += count

    # The two newest rows per instrument, for the conflict rule. Ordered and reduced in
    # Python rather than with a window function: the same shape `periods` above uses, and
    # SQLite has only supported `ROW_NUMBER` since 3.25 while this schema's floor is older.
    for ticker, action in session.execute(
        select(DecisionRun.instrument_t212_ticker, DecisionRun.long_term_action)
        .where(DecisionRun.instrument_t212_ticker.in_(tickers))
        .order_by(DecisionRun.created_at)
    ).all():
        facts[ticker].decision_action = action

    for ticker, verdict in session.execute(
        select(ResearchReport.subject_id, ResearchReport.verdict)
        .where(ResearchReport.subject_type == "instrument")
        .where(ResearchReport.subject_id.in_(tickers))
        .where(ResearchReport.status == "done")
        .order_by(ResearchReport.created_at)
    ).all():
        facts[ticker].research_verdict = verdict

    return facts


def _structural(facts: _Facts) -> Reason | None:
    """The one reason this instrument's accounts cannot be obtained at all.

    Only raised when we *hold* no annual period: an instrument we already have figures
    for is not one we cannot get figures for, whatever its identifiers look like. Called
    before the level-3 "no accounts" rule so the two do not both fire -- they are the
    same fact with and without a cause, and saying both reads as two problems.
    """
    instrument = facts.instrument
    if facts.period is not None:
        return None

    if is_uk_listing(instrument.exchange_name, instrument.yahoo_symbol):
        if instrument.ch_company_number:
            return None
        return Reason(
            code="no_company_number",
            label="No Companies House number",
            level=2,
            detail=(
                "a UK listing with no company number, so its accounts cannot be "
                "requested from Companies House"
            ),
        )

    if instrument.sec_cik:
        return None
    return Reason(
        code="no_sec_cik",
        label="No SEC CIK",
        level=2,
        detail=(
            "a US listing with no SEC CIK, so no filing can be requested from EDGAR "
            "-- EDGAR is the only free authoritative source for these"
        ),
    )


def _equation(facts: _Facts) -> Reason | None:
    """Whether the balance sheet we hold balances.

    The one accounting check that is a genuine contradiction rather than a coverage
    gap: both sides are figures we hold, so a disagreement is not explained by a line
    we failed to read.
    """
    if facts.period is None:
        return None
    check = ledger.equation_check(facts.period)
    if not check.failed:
        return None
    inputs = check.inputs
    detail = (
        f"for the year to {facts.period.period_end}, debits total "
        f"{inputs['debits']:,.0f} against credits of {inputs['credits']:,.0f} "
        f"-- out by {check.residual:,.0f}"
    )
    return Reason(code="equation", label="Balance sheet does not balance", level=1, detail=detail)


def _headlines(facts: _Facts) -> Reason | None:
    """An annual period without the figures the analysis divides by."""
    if facts.period is None:
        return None
    missing = [
        key for key in HEADLINE_METRICS if value_of(facts.period.metrics, key) is None
    ]
    if not missing:
        return None
    return Reason(
        code="missing_headlines",
        label="Accounts incomplete",
        level=1,
        detail=(
            f"the year to {facts.period.period_end} has no "
            + " or ".join(key.replace("_", " ") for key in missing)
        ),
    )


def _stale(facts: _Facts, today: dt.date) -> Reason | None:
    """Accounts older than a full reporting cycle."""
    if facts.period is None:
        return None
    age = (today - facts.period.period_end).days
    if age <= STALE_AFTER_DAYS:
        return None
    return Reason(
        code="stale_accounts",
        label="Accounts out of date",
        level=1,
        detail=f"the latest year ends {facts.period.period_end}, {age} days ago",
    )


def _unattributed(facts: _Facts) -> Reason | None:
    """A period whose figures cannot be traced to the tags they came from.

    Not cosmetic: `metric_sources` is what ties a stored figure to the filer's own tag,
    and without it neither the accounts page nor the linkbase reconciliation can say
    where a number came from.
    """
    if facts.period is None or facts.period.metric_sources:
        return None
    return Reason(
        code="unattributed",
        label="No provenance",
        level=1,
        detail=(
            f"the year to {facts.period.period_end} records no source tag for any "
            "figure, so it cannot be traced to the filing"
        ),
    )


#: What each stage was trying to do, in words.
#:
#: The stored value is a slug because it is part of a unique key, and a sentence built
#: straight from it reads as "fundamentals could not statements" -- which is what the
#: live tooltip said the first time a blocker was written. The fallback is the raw slug,
#: so a stage added by a job that has not been described here is still reported rather
#: than dropped.
STAGE_LABELS = {
    "statements": "fetch the statements",
    "xbrl": "read the filing's XBRL",
    "extract": "read a period out of the payload",
    "cik": "resolve an SEC CIK",
    "document": "download the document",
    "discovery": "find the annual reports",
    "filings": "fetch the filing history",
    "company_number": "resolve a Companies House number",
    "prices": "fetch prices",
    "symbol": "resolve a provider symbol",
}


def _blocked(facts: _Facts) -> Reason | None:
    """A job that has recorded it cannot do its work for this instrument."""
    if not facts.blockers:
        return None
    worst = max(facts.blockers, key=lambda row: row.last_seen_at)
    repeats = f", {worst.occurrences} times running" if worst.occurrences > 1 else ""
    extra = f" (+{len(facts.blockers) - 1} more)" if len(facts.blockers) > 1 else ""
    doing = STAGE_LABELS.get(worst.stage, worst.stage)
    return Reason(
        code="blocked",
        label="A job cannot proceed",
        level=1,
        detail=f"{worst.job} could not {doing}: {worst.reason}{repeats}{extra}",
    )


def _coverage(facts: _Facts) -> Reason | None:
    """Nothing has been fetched for this instrument yet."""
    if facts.period is not None:
        return None
    return Reason(
        code="no_accounts",
        label="No accounts yet",
        level=3,
        detail="no annual period has been fetched for this instrument",
    )


def _unparsed(facts: _Facts) -> Reason | None:
    """Documents held that nothing has read."""
    if not facts.filings or facts.parsed:
        return None
    return Reason(
        code="unparsed_documents",
        label="Documents unread",
        level=3,
        detail=(
            f"{facts.filings} filing(s) held and none parsed, so nothing has been "
            "taken from them"
        ),
    )


#: What each deep-dive verdict says about the business, and which long-term actions that
#: contradicts. Read as: a verdict of ``attractive`` is at odds with the engine wanting out.
#:
#: ``watch`` and ``insufficient_evidence`` contradict nothing. A deep-dive that says "this
#: needs watching" agrees with a hold and with a reduce -- the disagreement worth a reader's
#: attention is a *directional* one, and treating "no conclusion" as a conflict with every
#: action would put most of the table into the filter at level 3.
RESEARCH_CONFLICTS = {
    "attractive": ("sell", "reduce", "avoid"),
    "unattractive": ("buy", "strong_buy"),
}


def _research_conflict(facts: _Facts) -> Reason | None:
    """A paid deep-dive and the engine pointing in opposite directions.

    Level 3, which is the rung a reason belongs on when it is rare and worth a look rather
    than common and worth a filter -- the module docstring's distinction between a level and
    a severity. It is the one place in this application where two *judgements* about the same
    company disagree in public: the deep-dive read the annual reports and the appraised news,
    the engine read the deterministic valuation and the figures, and neither is a measurement.

    Fires only when both exist. Nothing here says which is right, and the detail says so.
    """
    verdict = facts.research_verdict
    action = facts.decision_action
    if not verdict or not action:
        return None
    if action not in RESEARCH_CONFLICTS.get(verdict, ()):
        return None
    return Reason(
        code="research_conflict",
        label="The deep-dive and the decision disagree",
        level=3,
        detail=(
            f"the deep-dive says {verdict.replace('_', ' ')} while the newest decision's "
            f"long-term action is {action.replace('_', ' ')}; both are judgements, and "
            "neither is a measurement"
        ),
    )


def reasons_for(facts: _Facts, *, today: dt.date) -> tuple[Reason, ...]:
    """Every reason this instrument qualifies for, in declaration order.

    Unfiltered by level: the caller decides the rung, and a test asserting that a
    level-3 reason exists must not have to raise the configured level to see it.
    """
    structural = _structural(facts)
    found = [
        _equation(facts),
        _headlines(facts),
        _stale(facts, today),
        _unattributed(facts),
        _blocked(facts),
        structural,
        # Suppressed when there is a cause, so one missing period does not read as two
        # problems -- see `_structural`.
        None if structural is not None else _coverage(facts),
        _unparsed(facts),
        _research_conflict(facts),
    ]
    return tuple(reason for reason in found if reason is not None)


def assess(
    session: Session,
    *,
    tickers: Iterable[str] | None = None,
    level: int | None = None,
    settings: Settings | None = None,
    today: dt.date | None = None,
) -> dict[str, Attention]:
    """The reasons each instrument needs attention for, at ``level`` or below.

    ``level`` defaults to ``app.attention_level`` from the configuration, which is the
    setting the reader raises as coverage improves. Passing it explicitly is for tests
    and for a caller that wants a stricter view than the installation's default.

    Instruments with no reasons at this level are still returned, with an empty tuple,
    so a caller can distinguish "not assessed" from "assessed and clean".
    """
    settings = settings or get_settings()
    resolved = settings.app.attention_level if level is None else level
    if not 1 <= resolved <= MAX_LEVEL:
        raise ValueError(f"attention level must be 1..{MAX_LEVEL}, got {resolved!r}")

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    )
    if tickers is not None:
        wanted = list(tickers)
        if not wanted:
            return {}
        statement = statement.where(Instrument.t212_ticker.in_(wanted))

    instruments = session.execute(statement).scalars().all()
    facts = _gather(session, instruments)
    stamp = today or dt.date.today()

    out: dict[str, Attention] = {}
    for ticker, entry in facts.items():
        found = tuple(
            reason for reason in reasons_for(entry, today=stamp) if reason.level <= resolved
        )
        out[ticker] = Attention(ticker=ticker, level=resolved, reasons=found)
    return out


__all__ = [
    "HEADLINE_METRICS",
    "MAX_LEVEL",
    "STAGE_LABELS",
    "STALE_AFTER_DAYS",
    "UNPARSED_STATUS",
    "Attention",
    "Reason",
    "assess",
    "reasons_for",
]

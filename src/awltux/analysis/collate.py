"""One set of accounts per accounting year, chosen rather than merged.

**The problem this module exists for.** Every writer stores its own row per source, so one
real year can appear as three `fundamental_period` rows: the SEC's own tags
(`xbrl_companyfacts`), a Yahoo statement, and our model's reading of the filed document
(`llm_extraction`). Measured 2026-10-09 on the live database: 394 rows formed 333 accounting
years, and **12 of those years held more than one source** -- 10 with all three of the above
and 2 with two of them. They are not three sets of accounts. They are three views of one set,
and the page printed them as three separate years' worth of figures.

**Chosen, not merged, and that is the whole design.** The first draft of this module filled a
figure the government source did not state from whatever other source did, on the reasoning
that the year's slot should be as complete as possible. That produces a set of accounts no
filer ever published, assembled from figures with different definitions: measured in the same
12 years, Yahoo's `total_debt` runs about 10% above the filer's on four of them because it
includes lease liabilities, `net_ppe` differs by 2.5x on two, and `receivables` by 3.6x. A
figure taken from one source and a figure taken from another are not two halves of one
statement. So one row stands for the year, whole, and the rows it displaced are kept and
reported -- their figures are evidence about what a source said, not inputs.

**Which row stands.** Two rules, from the reader: the accounts for an accounting year are the
full year's once they exist, and a government source takes precedence over anything else
("accounts are aligned to the accounting year, and that is populated with quarterly accounts
until the full years accounts appear, then it is fully replaced"). Ordered by:

1. **basis** -- an annual account covers the year; an interim covers part of it. `ttm` is not
   an account of a year at all: it is a rolling twelve months dated at the moment it was read,
   so it never occupies a slot (29 live instruments carry one; none has *only* a ttm row).
2. **source** -- the filer's own tagged submission first, then our reading of the document,
   then a synthesis of several, then the scraped providers. See `SOURCE_RANK`.
3. **the later period end** -- a Q3 snapshot is a more complete account of the year to date
   than the Q1 one it follows.
4. the row id, so the choice is total and reproducible rather than depending on query order.

The two rules genuinely conflict in one case: a government *interim* against a provider's
*annual* for the same year. Basis wins there, on the grounds that the slot is "the accounts
for year Y" and a full year answer is what it is asking for -- the government interim is
reported as superseded rather than silently dropped. Ranking source first instead is a
one-line change to `_order`.

**The accounting year is anchored on the filings, not on a calendar.** A fiscal year cannot
be derived from a fixed month and day: Apple's ends drift (2024-09-28, then 2025-09-27), and a
`(9, 27)` rule files the first of those under the following year -- which grouped six real
years together in a probe and produced collisions that do not exist. So the boundaries are the
annual period ends we actually hold for that instrument (any source), and a period ending
before one of them belongs to it. A period after every annual end we hold belongs to the year
the next annual will cover, which is genuinely unknown until it is filed, so it is lumped into
one stated bucket rather than guessed at.

**Nothing here is stored.** The collated set is derived on read from the rows the writers
stored, which stay exactly as they are: they are the record of what each source said, and a
table of "the accounts" beside them would be a second source of truth that can disagree with
the evidence behind it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from awltux.db import FundamentalPeriod
from awltux.metrics import DERIVED_METRICS, value_of

#: Sources whose figures come from the filer's own submission or from the register, rather
#: than from a third party's copy or from a model's reading of the document.
#:
#: ``xbrl_companyfacts`` is the SEC's aggregate of what the filer tagged -- the filer's own
#: data reached through a different artefact (`TODO.md` records what that route does and does
#: not use). ``companies_house_ixbrl`` is the UK counterpart and **nothing writes it yet**;
#: it is named here so the rule is already right when the UK reader lands.
GOVERNMENT_SOURCES = ("xbrl_companyfacts", "companies_house_ixbrl")

#: Rank within a basis. Higher wins.
#:
#: ``llm_extraction`` outranks ``deep_research`` for the reason `analysis/fundamental.py`
#: records: both read a document and quote what they read, but the extractor's whole job is
#: one document and its figures while a deep-dive is a synthesis. Both sit above the scraped
#: providers, and the government's own tagged data sits above both -- it is the filer's
#: submission rather than anyone's reading of it.
SOURCE_RANK: dict[str, int] = {
    "xbrl_companyfacts": 50,
    "companies_house_ixbrl": 50,
    "llm_extraction": 40,
    "deep_research": 30,
    "yahoo_statements": 20,
    "yahoo_info": 10,
}

#: Rank within a year's slot. ``ttm`` is present rather than absent so that a source which one
#: day writes one cannot silently key a slot; `collate` drops it before ranking.
BASIS_RANK: dict[str, int] = {"annual": 3, "interim": 2, "quarterly": 1, "ttm": 0}

#: How much two sources may differ before it is a discrepancy rather than rounding.
#:
#: Relative, and measured: of 99 figure collisions across the 12 multi-source years, **8 agree
#: within 1%** -- the same figure rounded at a different precision or converted at a slightly
#: different rate -- and the rest differ by far more (10%, 2.5x, 3.6x, a factor of 10^6, or a
#: sign). Calling the 8 a disagreement would train the reader to ignore the panel.
TOLERANCE = 0.01


@dataclass(slots=True)
class Discrepancy:
    """One figure two sources state differently, with both values kept."""

    metric: str
    chosen_value: float
    other_value: float
    other_source: str

    @property
    def relative(self) -> float:
        """The size of the difference, as a fraction of the larger magnitude."""
        return abs(self.chosen_value - self.other_value) / max(
            abs(self.chosen_value), abs(self.other_value)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "chosen_value": self.chosen_value,
            "other_value": self.other_value,
            "other_source": self.other_source,
            "relative": self.relative,
        }


@dataclass(slots=True)
class Superseded:
    """A row that described the same year and did not win."""

    period: FundamentalPeriod
    reason: str
    discrepancies: list[Discrepancy] = field(default_factory=list)
    #: Figures this row states that the chosen one does not. **Not merged in** -- see the
    #: module docstring -- but listed, because a figure nobody used is a fact about how
    #: complete the year's accounts are.
    only_here: list[str] = field(default_factory=list)

    @property
    def source(self) -> str:
        return self.period.source


@dataclass(slots=True)
class AccountingYear:
    """The one set of accounts chosen for one accounting year."""

    #: The annual period end that bounds this year, or the bucket end for a year whose annual
    #: has not been filed. Used as the identity of the slot.
    label: dt.date
    chosen: FundamentalPeriod
    superseded: list[Superseded] = field(default_factory=list)
    #: True when no annual account of this year is held, so the slot is standing on an interim
    #: and cannot be read as the year's final figures.
    provisional: bool = False

    @property
    def fiscal_year(self) -> int:
        return self.label.year

    @property
    def basis(self) -> str:
        return self.chosen.period_type

    @property
    def source(self) -> str:
        return self.chosen.source

    @property
    def period_end(self) -> dt.date | None:
        return self.chosen.period_end

    @property
    def discrepancies(self) -> list[Discrepancy]:
        return [entry for row in self.superseded for entry in row.discrepancies]

    @property
    def excluded_figures(self) -> int:
        """How many figures a source stated and this year's accounts do not use."""
        return sum(len(row.only_here) for row in self.superseded)

    @property
    def government(self) -> bool:
        return self.chosen.source in GOVERNMENT_SOURCES


def annual_ends(periods: list[FundamentalPeriod]) -> list[dt.date]:
    """Every annual period end held for one instrument, oldest first.

    Any source: a provider's annual is as much evidence that a fiscal year ended on a date as
    the filer's is, and the boundary is what matters here, not the figures behind it.
    """
    ends = {
        period.period_end
        for period in periods
        if period.period_type == "annual" and period.period_end is not None
    }
    return sorted(ends)


def year_for(period: FundamentalPeriod, ends: list[dt.date]) -> dt.date | None:
    """The accounting year a period's accounts belong to, as a slot label.

    The first annual end at or after the period's own end; the period's own end when that is
    an annual end. ``None`` when the period has no date at all.

    **A period after every annual end held is not filed into the last year.** It is the start
    of the *next* fiscal year -- the one the next annual will cover -- so its label is that
    year's boundary extrapolated from the last real one, and `collate` marks the slot
    provisional. Filing it under the last annual end instead would put a period that begins
    after the year closed into that year's accounts, and let it compete with the year's own
    annual for the slot. The extrapolated date is a guess at a date that has not been filed,
    which is why the year says so rather than presenting itself as final.
    """
    if period.period_end is None:
        return None
    for end in ends:
        if end >= period.period_end:
            return end
    if not ends:
        return None
    boundary = ends[-1]
    while boundary < period.period_end:
        boundary = _plus_year(boundary)
    return boundary


def _plus_year(when: dt.date) -> dt.date:
    """A date one year later, with 29 February landing on the 28th rather than raising."""
    try:
        return when.replace(year=when.year + 1)
    except ValueError:
        return when.replace(year=when.year + 1, day=28)


def collate(periods: list[FundamentalPeriod]) -> list[AccountingYear]:
    """One set of accounts per accounting year, oldest first.

    ``periods`` is every stored row for one instrument. Nothing is written and nothing is
    filtered out silently: a row that does not win is reported on the year it lost to, with
    the figures it stated differently.
    """
    ends = annual_ends(periods)
    slots: dict[dt.date, list[FundamentalPeriod]] = {}
    unlabelled: list[FundamentalPeriod] = []

    for period in periods:
        if period.period_type == "ttm":
            # A rolling twelve months is not an account of a year. Dropped here rather than in
            # the query so the caller cannot forget: 29 live instruments carry one.
            continue
        label = year_for(period, ends)
        if label is None:
            unlabelled.append(period)
            continue
        slots.setdefault(label, []).append(period)

    years: list[AccountingYear] = []
    for label in sorted(slots):
        rows = slots[label]
        chosen = max(rows, key=_order)
        others = [row for row in rows if row is not chosen]
        chosen_metrics = chosen.metrics or {}
        superseded = [
            Superseded(
                period=row,
                reason=_why(row, chosen),
                discrepancies=_discrepancies(chosen_metrics, chosen.source, row),
                only_here=sorted(
                    name
                    for name in (row.metrics or {})
                    if name not in chosen_metrics and name not in DERIVED_METRICS
                ),
            )
            for row in sorted(others, key=lambda row: (-_order(row)[0], -_order(row)[1]))
        ]
        years.append(
            AccountingYear(
                label=label,
                chosen=chosen,
                superseded=superseded,
                provisional=chosen.period_type != "annual",
            )
        )

    if unlabelled:
        # No annual period is held at all, so there is no fiscal boundary to anchor on. The
        # slot label is the newest date we do hold; the year is still one set of accounts.
        newest = max(unlabelled, key=_order)
        years.append(
            AccountingYear(
                label=newest.period_end or dt.date.min,
                chosen=newest,
                superseded=[
                    Superseded(period=row, reason="a later account of the same partial year")
                    for row in unlabelled
                    if row is not newest
                ],
                provisional=True,
            )
        )
    return years


def annual_set(periods: list[FundamentalPeriod]) -> list[FundamentalPeriod]:
    """The chosen accounts of every year, annual only, oldest first.

    What the analysis reads when it needs a *year*: one row per year, government-preferred.
    Interim slots are left out deliberately -- a half-year in a series the growth rates are
    computed across would report a collapse in revenue that is really a shorter period.
    """
    return [
        year.chosen
        for year in collate(periods)
        if year.chosen.period_type == "annual"
    ]


def chosen_set(periods: list[FundamentalPeriod]) -> list[FundamentalPeriod]:
    """The chosen accounts of every year, whatever basis they are, oldest first.

    One row per year with the interim slots included, for a reader that does its own
    period-type selection -- `build_snapshot` picks a basis before it computes anything, and
    handing it an annual-only series would take away the fallback it uses when a company has
    filed only one year.
    """
    return [year.chosen for year in collate(periods)]


def _order(period: FundamentalPeriod) -> tuple[int, int, dt.date, int]:
    """The sort key that decides which row stands for a year. Bigger wins, totally ordered."""
    return (
        BASIS_RANK.get(period.period_type, 0),
        SOURCE_RANK.get(period.source, 0),
        period.period_end or dt.date.min,
        period.id or 0,
    )


def _why(loser: FundamentalPeriod, winner: FundamentalPeriod) -> str:
    """One line saying what displaced this row, in the reader's terms."""
    if winner.source in GOVERNMENT_SOURCES and loser.source not in GOVERNMENT_SOURCES:
        return f"the filer's own accounts for this year ({winner.source}) replace them"
    if BASIS_RANK.get(winner.period_type, 0) > BASIS_RANK.get(loser.period_type, 0):
        return (
            f"a later account of the same year ({winner.period_type}, {winner.period_end}) "
            f"replaces this {loser.period_type}"
        )
    if SOURCE_RANK.get(winner.source, 0) > SOURCE_RANK.get(loser.source, 0):
        return f"{winner.source} takes precedence over {loser.source}"
    return "a more recent account of the same year"


def _discrepancies(
    chosen_metrics: dict[str, Any], chosen_source: str, other: FundamentalPeriod
) -> list[Discrepancy]:
    """Every figure the two rows both state, where they do not agree.

    Derived ratios are skipped: they are computed by `ingest/fundamentals.derive_metrics` from
    whatever figures the row holds, so a ratio that differs because an input differed would
    report the same disagreement twice and make the panel twice as long as the problem.
    """
    found: list[Discrepancy] = []
    for name in (other.metrics or {}):
        if name in DERIVED_METRICS:
            continue
        mine = value_of(chosen_metrics, name)
        theirs = value_of(other.metrics, name)
        if mine is None or theirs is None:
            continue
        if _agrees(mine, theirs):
            continue
        found.append(
            Discrepancy(
                metric=name,
                chosen_value=mine,
                other_value=theirs,
                other_source=other.source,
            )
        )
    return sorted(found, key=lambda entry: -entry.relative)


def _agrees(left: float, right: float) -> bool:
    """Whether two figures are the same number to within rounding.

    Absolute first, so that a figure stored as exactly zero agrees with another zero rather
    than dividing by it, and relative after that, so a million-dollar difference on a billion
    is not called a discrepancy.
    """
    if left == right:
        return True
    return abs(left - right) <= TOLERANCE * max(abs(left), abs(right))


__all__ = [
    "BASIS_RANK",
    "GOVERNMENT_SOURCES",
    "SOURCE_RANK",
    "TOLERANCE",
    "AccountingYear",
    "Discrepancy",
    "Superseded",
    "annual_ends",
    "annual_set",
    "chosen_set",
    "collate",
    "year_for",
]

"""Where each line of the accounts is printed, and what its figure is counted in.

**Why this is a module rather than a table inside the ledger.** The chart of accounts was the
only description of a set of accounts this project had, so it was made to carry four different
facts at once: a line's name, the statement it belongs to, the heading it prints under, and the
subtotal it feeds. Those are not the same kind of fact, and the live data proves it.

Measured 2026-10-25 on `JELl_EQ` (Jersey Electricity) FY2025, whose figures the accounts page
shows as *out by 26,867,000* against operating income:

* Yahoo's page states ``Operating Expense`` and ``Other Operating Expenses`` as the **same
  38,688,000**, with ``Selling General And Administration`` absent for 2023-2025 -- and in 2022
  it states 29,293,000 under *both* captions. A global "Other Operating Expenses" mapping would
  therefore count 2022 twice.
* ``Depreciation And Amortization`` (11,821,000) is a **cash flow** row on the same page, not a
  component of its operating expense. `ingest/fundamentals.py` merged the three statements into
  one label space, so it filled the profit and loss's depreciation line -- and the section then
  claimed an expense the source had not put there.
* 53,465,000 - 38,688,000 = 14,777,000, the stated operating income, to the pound: the section
  balances the moment the reader can *remove a line from a heading* and *add the caption the
  source uses*, which is what this module exists to make possible.

Of 377 stored periods holding both gross profit and operating income, 45 agree within 1% and
332 do not. So the fixed chart is not an edge case that needs a second special case; it is the
normal case that needs a presentation layer.

**Three things, kept apart.**

* **A figure** is what the source stated. It lives in ``FundamentalPeriod.metrics`` and this
  module never touches it -- moving a line does not change a single number.
* **A placement** is one line as this set of accounts presents it: a key, a caption, a heading,
  a side, and the subtotal its figure feeds. :data:`CHART` is the **default** placement, not the
  only one; `analysis/corrections.py` records what a reader changed, and :class:`Layout` applies
  it.
* **The arithmetic** (:mod:`analysis.ledger`) sums whatever the layout says feeds a subtotal, so
  a line moved out of a heading stops being deducted there and a line added to it starts, with
  no second table to keep true -- which is what `EXTRA_GROUP`, `COMPONENT_KEYS` and the
  builders' own section lists were.

**The heading a line prints under is the heading the statement prints.** The chart used to name
its sections its own way -- ``gross_profit`` sat under "Cost of sales", which no statement
printed, because the profit and loss prints it in "Revenue" -- so "which heading is this line
under" had two answers and the picker offered the wrong one. :attr:`Account.section` is now the
printed heading, and the statement structure is derived from it: the chart's order *is* the
printed order, section by section.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

#: The two sides a line can be posted on. Repeated from `analysis.corrections` rather than
#: imported, because this module must not depend on the store: a placement is a pure value, and
#: the ledger and the layout have to be usable with no database at all.
DEBIT = "debit"
CREDIT = "credit"


@dataclass(frozen=True, slots=True)
class Account:
    """One line of the ledger, as the chart of accounts carries it.

    ``role`` is what keeps the arithmetic honest, and it is the difference between a
    double-entry ledger and a list of numbers:

    * ``line`` -- a **component**. This is what gets posted and what the totals are
      checked against.
    * ``subtotal`` -- a **stated** total. Shown beside the components that should sum
      to it, and never posted, or the total would be counted twice.
    * ``memo`` -- informational. Per-share figures, and totals that are the sum of
      other lines already posted (``total_debt``, ``retained_earnings``).
    """

    key: str
    label: str
    statement: str
    section: str
    side: str
    role: str = "line"
    #: True when a negative value is an ordinary reading rather than a data error.
    signed: bool = False


#: The chart of accounts. Order is presentation order, section by section.
CHART: tuple[Account, ...] = (
    # ---------------------------------------------------------------- P&L
    Account("revenue", "Revenue", "profit_and_loss", "Revenue", CREDIT),
    Account("cost_of_goods_sold", "Cost of sales", "profit_and_loss", "Revenue", DEBIT),
    # The gross profit is printed in the Revenue section, which is where a reader expects it, and
    # it was the first thing this module had to move: the chart had it under "Cost of sales" --
    # a heading no statement prints -- while `_profit_cascade` printed it after the cost of sales
    # it is derived from. One of the two had to give, and the printed page is the one a reader
    # reads.
    Account(
        "gross_profit", "Gross profit", "profit_and_loss", "Revenue", CREDIT,
        role="subtotal",
    ),
    Account(
        "research_and_development", "Research and development", "profit_and_loss",
        "Operating expenses", DEBIT,
    ),
    Account(
        "sga_expense", "Selling, general and administrative", "profit_and_loss",
        "Operating expenses", DEBIT,
    ),
    Account(
        "depreciation_amortisation", "Depreciation and amortisation", "profit_and_loss",
        "Operating expenses", DEBIT,
    ),
    Account(
        "operating_income", "Operating income", "profit_and_loss", "Operating expenses",
        CREDIT, role="subtotal",
    ),
    Account(
        "interest_expense", "Interest expense", "profit_and_loss", "Finance and tax", DEBIT,
    ),
    Account(
        "interest_income", "Interest income", "profit_and_loss", "Finance and tax", CREDIT,
    ),
    Account(
        "other_nonoperating_income", "Other non-operating income",
        "profit_and_loss", "Finance and tax", CREDIT, signed=True,
    ),
    Account(
        "pretax_income", "Profit before tax", "profit_and_loss", "Finance and tax", CREDIT,
        role="subtotal", signed=True,
    ),
    Account("tax_expense", "Tax", "profit_and_loss", "Finance and tax", DEBIT),
    Account(
        "net_income", "Profit for the period", "profit_and_loss", "Finance and tax", CREDIT,
        role="subtotal", signed=True,
    ),
    Account("ebit", "EBIT", "profit_and_loss", "Memorandum", CREDIT, role="memo"),
    Account("ebitda", "EBITDA", "profit_and_loss", "Memorandum", CREDIT, role="memo"),
    Account(
        "eps_diluted", "Diluted earnings per share", "profit_and_loss", "Memorandum", CREDIT,
        role="memo",
    ),
    Account(
        "dividend_per_share", "Dividend per share", "profit_and_loss", "Memorandum", DEBIT,
        role="memo",
    ),
    # -------------------------------------------------------- Balance sheet
    Account("cash_and_equivalents", "Cash and equivalents", "balance_sheet", "Current assets", DEBIT),
    Account("receivables", "Trade receivables", "balance_sheet", "Current assets", DEBIT),
    Account("inventory", "Inventory", "balance_sheet", "Current assets", DEBIT),
    Account(
        "other_current_assets", "Other current assets", "balance_sheet",
        "Current assets", DEBIT,
    ),
    Account("current_assets", "Total current assets", "balance_sheet", "Current assets", DEBIT, role="subtotal"),
    Account("net_ppe", "Property, plant and equipment", "balance_sheet", "Non-current assets", DEBIT),
    Account(
        "operating_lease_assets", "Operating lease assets", "balance_sheet",
        "Non-current assets", DEBIT,
    ),
    Account("goodwill", "Goodwill", "balance_sheet", "Non-current assets", DEBIT, signed=True),
    Account("intangible_assets", "Other intangibles", "balance_sheet", "Non-current assets", DEBIT),
    Account(
        "other_noncurrent_assets", "Other non-current assets", "balance_sheet",
        "Non-current assets", DEBIT,
    ),
    Account(
        "total_assets", "Total assets", "balance_sheet", "Non-current assets", DEBIT,
        role="subtotal",
    ),
    Account("payables", "Trade payables", "balance_sheet", "Current liabilities", CREDIT),
    Account(
        "compensation_and_benefits", "Compensation and related benefits",
        "balance_sheet", "Current liabilities", CREDIT,
    ),
    Account(
        "other_current_liabilities", "Other current liabilities", "balance_sheet",
        "Current liabilities", CREDIT,
    ),
    Account("short_term_debt", "Short-term borrowings", "balance_sheet", "Current liabilities", CREDIT),
    Account(
        "current_liabilities", "Total current liabilities", "balance_sheet",
        "Current liabilities", CREDIT, role="subtotal",
    ),
    Account("long_term_debt", "Long-term borrowings", "balance_sheet", "Non-current liabilities", CREDIT),
    # A memorandum, not a component, and the reason is the caption it would sit beside.
    # `OtherLiabilitiesNoncurrent` is a *residual* caption -- by construction it holds
    # whatever the filer did not present as its own line -- and on `AIT_US_EQ` that
    # includes the operating lease liability: `OperatingLeaseLiabilityNoncurrent` is
    # 168,231,000 of the 273,513,000 reported as other non-current liabilities, so
    # posting both would count that 168,231,000 twice. Whether the lease is a separate
    # line is the filer's own presentation, which `companyfacts` does not carry (see
    # `TODO.md`: the calculation and presentation linkbases are the fix), so the safe
    # reading is to show the lease without adding it again.
    Account("lease_liabilities", "Lease liabilities", "balance_sheet", "Memorandum", CREDIT, role="memo"),
    Account(
        "other_noncurrent_liabilities", "Other non-current liabilities", "balance_sheet",
        "Non-current liabilities", CREDIT,
    ),
    Account(
        "total_liabilities", "Total liabilities", "balance_sheet",
        "Non-current liabilities", CREDIT, role="subtotal",
    ),
    Account(
        "total_equity", "Total equity", "balance_sheet", "Equity", CREDIT,
        role="subtotal", signed=True,
    ),
    Account("retained_earnings", "Retained earnings", "balance_sheet", "Memorandum", CREDIT, role="memo", signed=True),
    Account("total_debt", "Total debt", "balance_sheet", "Memorandum", CREDIT, role="memo"),
    Account("shares_outstanding", "Shares outstanding", "balance_sheet", "Memorandum", CREDIT, role="memo"),
    Account(
        "stock_based_compensation", "Share-based payment", "balance_sheet", "Memorandum",
        DEBIT, role="memo",
    ),
    # ------------------------------------------------------------- Cash flow
    # Every side here is the counter-entry against cash: an inflow debits cash, an
    # outflow credits it. Reading them as "good" and "bad" would be wrong -- a capex
    # outflow is not a loss -- which is why the statement is a movement, not a result.
    Account("operating_cash_flow", "Cash from operating activities", "cash_flow", "Operating", DEBIT, signed=True),
    Account("capex", "Capital expenditure", "cash_flow", "Investing", CREDIT),
    Account(
        "free_cash_flow", "Free cash flow", "cash_flow", "Investing", DEBIT,
        role="subtotal", signed=True,
    ),
    Account("dividends_paid", "Dividends paid", "cash_flow", "Financing", CREDIT),
)

BY_KEY: dict[str, Account] = {account.key: account for account in CHART}

#: The statement names, in the order a set of accounts is read: the result first,
#: then what is owned and owed, then how the cash moved.
STATEMENTS: tuple[tuple[str, str], ...] = (
    ("profit_and_loss", "Profit & loss"),
    ("balance_sheet", "Balance sheet"),
    ("cash_flow", "Cash flow"),
)


#: Which subtotal a line feeds **by the heading it sits under**.
#:
#: The default, used for every line that does not say otherwise -- the chart's own lines included,
#: which is how one table replaced the `EXTRA_GROUP` mapping the learned lines needed plus the
#: key lists the balance sheet was summed from. A heading that is not here feeds nothing: the
#: balance sheet's "Equity" and every statement's "Memorandum" hold figures this page computes no
#: sum of, and a line put there is printed and counted nowhere, which the statement says.
SECTION_FEEDS: dict[tuple[str, str], str] = {
    ("profit_and_loss", "Revenue"): "gross_profit",
    ("profit_and_loss", "Operating expenses"): "operating_income",
    ("profit_and_loss", "Finance and tax"): "pretax_income",
    ("balance_sheet", "Current assets"): "current_assets",
    ("balance_sheet", "Non-current assets"): "non_current_assets",
    ("balance_sheet", "Current liabilities"): "current_liabilities",
    ("balance_sheet", "Non-current liabilities"): "non_current_liabilities",
}

#: Lines whose own subtotal they feed differs from their heading's, and the top of each cascade.
#:
#: `tax_expense` sits in "Finance and tax" with the interest lines but is deducted after the
#: profit before tax, not before it -- the one place a heading cannot answer the question, which
#: is why it is a line's own fact rather than the section's.
KEY_FEEDS: dict[str, str] = {
    "gross_profit": "operating_income",
    "operating_income": "pretax_income",
    "pretax_income": "net_income",
    "tax_expense": "net_income",
    "net_income": "",
}

#: The subtotals a figure can be counted in. Named so a placement naming a subtotal that is not
#: one of them is refused rather than silently counted nowhere -- the failure the reader would
#: only discover as a residual that did not move.
FEEDS: dict[str, tuple[str, ...]] = {
    "profit_and_loss": ("gross_profit", "operating_income", "pretax_income", "net_income"),
    "balance_sheet": (
        "current_assets",
        "non_current_assets",
        "current_liabilities",
        "non_current_liabilities",
    ),
    "cash_flow": (),
}

#: Which component groups each stated subtotal of the balance sheet is summed from.
#:
#: `total_assets` is the sum of *both* asset groups rather than of the stated current-assets
#: subtotal, which is the choice that keeps a residual against a stated total a measure of the lines
#: this project does not hold rather than of its own arithmetic. One table, read by the statement
#: and by the check that audits it, so the two cannot sum different lines.
SUBTOTAL_GROUPS: dict[str, tuple[str, ...]] = {
    "current_assets": ("current_assets",),
    "total_assets": ("current_assets", "non_current_assets"),
    "current_liabilities": ("current_liabilities",),
    "total_liabilities": ("current_liabilities", "non_current_liabilities"),
}


@dataclass(frozen=True, slots=True)
class Placement:
    """One line as a set of accounts presents it: a key, a caption, a heading, a subtotal.

    ``key`` is the line's identity, and it is one of three things: a canonical metric name, a
    ``taxonomy:Tag`` for a line a filing names, or ``src:<caption>`` for one a provider states
    without a tag. Nothing downstream needs to know which -- a placement is asked for its caption
    and its figure, and the figure is looked up by the key.

    ``feeds`` empty means the figure is printed and **counted in no subtotal**. The statement says
    so, because a figure on a page that moves no total is one a reader will assume is counted.
    """

    key: str
    label: str
    statement: str
    section: str
    side: str
    role: str = "line"
    signed: bool = False
    feeds: str = ""

    @classmethod
    def of(cls, account: Account) -> Placement:
        """The placement the chart gives an account."""
        return cls(
            key=account.key,
            label=account.label,
            statement=account.statement,
            section=account.section,
            side=account.side,
            role=account.role,
            signed=account.signed,
            feeds=default_feeds(
                account.statement, account.section, key=account.key, role=account.role
            ),
        )


@dataclass(frozen=True, slots=True)
class Override:
    """A reader's change to where one line is presented, or to a statement's headings.

    Empty fields mean "leave it as the chart has it", so the record says exactly what was
    decided and a later reader can see that a line was moved and nothing else. ``feeds`` is the
    exception that needs three states -- unset (keep the heading's subtotal), ``""`` (count it in
    nothing, which is what moving a line out of a cascade means), and a subtotal's name.
    """

    section: str = ""
    label: str = ""
    role: str = ""
    feeds: str | None = None


def default_feeds(statement: str, section: str, *, key: str = "", role: str = "line") -> str:
    """The subtotal a line feeds when nobody has said otherwise.

    A **memorandum** feeds nothing by definition, and a line with a :data:`KEY_FEEDS` entry feeds
    that even when its heading says otherwise -- `tax_expense` is printed with the interest lines
    and deducted after the profit before tax. Everyone else feeds whatever their heading feeds,
    which is the one relation `SECTION_FEEDS` states.
    """
    if role == "memo":
        return ""
    if key in KEY_FEEDS:
        return KEY_FEEDS[key]
    return section_feeds(statement, section)


def section_feeds(statement: str, section: str) -> str:
    """The subtotal a heading's lines are summed into, or ``""`` when it sums to nothing.

    Asked when a reader moves a line to another heading and lets the heading decide: a line put
    under "Operating expenses" is deducted at operating income, and one put under a heading this
    page computes no sum of is printed and counted nowhere -- which is the right answer for
    `JELl_EQ`'s depreciation, and the case the fixed vocabulary could not express.
    """
    return SECTION_FEEDS.get((statement, section), "")


def base_sections(statement: str) -> tuple[str, ...]:
    """A statement's headings, in the order the chart introduces them."""
    return tuple(
        dict.fromkeys(
            account.section for account in CHART if account.statement == statement
        )
    )


class Layout:
    """One set of accounts' presentation: its headings, and the lines under each of them.

    Immutable and built once per page: the statement builders and the arithmetic are then two
    readers of the same structure, which is what stops a subtotal and its working from summing
    different lines.
    """

    __slots__ = ("_by_key", "_moved", "_sections")

    def __init__(
        self,
        sections: Mapping[str, Sequence[str]],
        by_key: Mapping[str, Placement],
        moved: Iterable[str] = (),
    ) -> None:
        self._sections = {
            statement: tuple(titles) for statement, titles in sections.items()
        }
        self._by_key = dict(by_key)
        # Which lines a reader moved, so `lines` can seat them beside the heading's components
        # rather than at the chart's index -- a line printed after the total it feeds reads as a
        # memorandum, and a reader who moved a line into a heading meant it to be part of it.
        self._moved = frozenset(moved)

    # -- construction ------------------------------------------------------ #

    @classmethod
    def default(cls) -> Layout:
        """The chart's own presentation, with nothing changed."""
        return cls.build()

    @classmethod
    def build(
        cls,
        *,
        learned: Iterable[Placement] = (),
        moves: Mapping[str, Override] = {},
    ) -> Layout:
        """The chart, with the lines a reader added and the places they moved one to.

        ``learned`` are whole placements: a line this set of accounts has that the chart does
        not, with the heading it was given. ``moves`` are changes to a line the chart *does*
        carry -- a different heading, a different caption, or a different subtotal -- and they
        win over the chart and over a learned line alike, because a move is the later decision.
        """
        placed: dict[str, Placement] = {}
        for account in CHART:
            placed[account.key] = Placement.of(account)
        for line in learned:
            placed[line.key] = line
        for key, change in moves.items():
            base = placed.get(key)
            if base is None:
                continue
            placed[key] = _moved(base, change)

        titles: dict[str, list[str]] = {}
        for statement, _ in STATEMENTS:
            titles[statement] = list(base_sections(statement))
        # A heading a line was moved under has to print: the move *is* the registration, and a line
        # pointing at a heading nobody prints is a line nothing shows. A heading nothing is left
        # under is not a heading -- which is why there is no separate list of them to keep true.
        for placement in placed.values():
            if placement.statement not in titles:
                continue
            if placement.section not in titles[placement.statement]:
                titles[placement.statement].append(placement.section)

        return cls(titles, placed, moves)

    # -- reads ------------------------------------------------------------- #

    def sections(self, statement: str) -> tuple[str, ...]:
        """A statement's headings, in print order."""
        return self._sections.get(statement, ())

    def statements(self) -> tuple[str, ...]:
        return tuple(self._sections)

    def placement(self, key: str) -> Placement | None:
        """Where one line is presented, or ``None`` for a key this layout does not carry."""
        return self._by_key.get(key)

    def lines(self, statement: str, section: str) -> tuple[Placement, ...]:
        """The lines printed under one heading, in print order, subtotals where they belong.

        The chart's own lines come first, in the chart's order -- which is the printed order,
        because that is what :data:`CHART` is -- and a line the reader put here (learned, or moved
        from another heading) is inserted **before the first subtotal**, for the reason the old
        `_section_lines` gave: a line printed under the total it feeds reads as a memorandum, and
        the point of adding it is to move that total.
        """
        members = [
            placement
            for placement in self._by_key.values()
            if placement.statement == statement and placement.section == section
        ]
        ours = sorted(
            (
                line
                for line in members
                if line.key in _CHART_INDEX and line.key not in self._moved
            ),
            key=lambda line: _CHART_INDEX[line.key],
        )
        # Everything the chart did not seat here itself: a caption it never had, and a chart line a
        # reader moved in. Both go in front of the heading's first subtotal, and among themselves
        # in the chart's order so the page does not reshuffle when two lines are moved.
        added = sorted(
            (line for line in members if line not in ours),
            key=lambda line: (_chart_order(line), line.key),
        )
        at = next(
            (index for index, line in enumerate(ours) if line.role == "subtotal"), len(ours)
        )
        return tuple([*ours[:at], *added, *ours[at:]])

    def components(self, statement: str, group: str) -> tuple[Placement, ...]:
        """The lines whose figures are summed into one subtotal group, in print order."""
        found = [
            placement
            for placement in self._by_key.values()
            if placement.statement == statement
            and placement.feeds == group
            and placement.role != "subtotal"
        ]
        found.sort(key=_chart_order)
        return tuple(found)

    def uncounted(self, statement: str) -> tuple[Placement, ...]:
        """Lines printed in a statement whose figures feed no subtotal.

        Reported rather than left to be noticed -- see `ledger.uncounted_note`. Only a line the
        *chart does not carry* is here, because that is the case this exists for: a caption a
        reader put under a heading whose lines are summed by nothing, so the figure they added to
        fix a residual did not move it.

        A **memorandum** is not reported -- printed and deliberately not counted, which is what
        the role means -- and neither is a chart line moved out of a cascade by the reader, nor the
        cash flow's own lines, whose sums are formulas rather than a component list. Saying any of
        those twice would bury the case a reader cannot otherwise discover.
        """
        return tuple(
            sorted(
                (
                    placement
                    for placement in self._by_key.values()
                    if placement.statement == statement
                    and placement.role == "line"
                    and not placement.feeds
                    and placement.key not in BY_KEY
                ),
                key=lambda placement: placement.key,
            )
        )


def _moved(base: Placement, change: Override) -> Placement:
    """One placement with a reader's override applied, field by field."""
    return replace(
        base,
        section=change.section or base.section,
        label=change.label or base.label,
        role=change.role or base.role,
        feeds=base.feeds if change.feeds is None else change.feeds,
    )


def _chart_order(placement: Placement) -> int:
    """The chart's index for a line, so the printed order is the chart's.

    A line the chart does not carry sorts after the ones it does: the chart has no opinion about a
    caption it never had, and `Layout.lines` seats those before the first subtotal instead.
    """
    return _CHART_INDEX.get(placement.key, len(CHART))


_CHART_INDEX: dict[str, int] = {account.key: index for index, account in enumerate(CHART)}


def placement_for(line: Any, *, statement: str, section: str) -> Placement:
    """A placement for a line that arrived from somewhere other than the chart.

    Duck-typed rather than importing `analysis.corrections`, which owns the stored records: a
    learned line and a source caption both arrive here with a key, a caption and a side, and this is
    the one place that decides how they become a line of the accounts.
    """
    key = str(getattr(line, "key", "") or getattr(line, "metric", ""))
    role = str(getattr(line, "role", "") or "line")
    return Placement(
        key=key,
        label=str(getattr(line, "label", "") or key),
        statement=statement,
        section=section,
        side=str(getattr(line, "side", "") or CREDIT),
        role=role,
        signed=bool(getattr(line, "signed", False)),
        feeds=default_feeds(statement, section, key=key, role=role),
    )


__all__ = [
    "BY_KEY",
    "CHART",
    "CREDIT",
    "DEBIT",
    "FEEDS",
    "KEY_FEEDS",
    "SECTION_FEEDS",
    "STATEMENTS",
    "SUBTOTAL_GROUPS",
    "Account",
    "Layout",
    "Override",
    "Placement",
    "base_sections",
    "default_feeds",
    "placement_for",
    "section_feeds",
]

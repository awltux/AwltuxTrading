"""A chart of accounts over the stored figures, and the checks that go with it.

The three statements a reader expects -- profit and loss, balance sheet, cash flow --
built as **a double-entry ledger** rather than as three independent lists of numbers.

**What that means here, and what it does not.** Filings give us aggregated line items,
not transactions, so there is no journal to replay and this module does not pretend
otherwise. What double-entry buys is *articulation*: every figure is posted to a named
account with a normal side, and the statements are read off a trial balance whose
debits and credits have to agree. A total that does not equal the sum of its parts, or
assets that do not equal liabilities plus equity, is then a visible property of the
data rather than something a reader has to verify by hand.

**An imbalance is reported, never plugged.** Three separate things are checked, and
they fail for different reasons:

* **The accounting equation** -- ``total assets = total liabilities + total equity``.
  The filing itself satisfies this, so a residual here means *our extraction* is
  wrong, and it is the one check whose failure is a defect rather than a gap.
* **Composition** -- whether the component lines we hold sum to the stated totals.
  They usually will not, because the taxonomy has more accounts than we extract. That
  residual is named ``unitemised`` and its size is reported rather than hidden, so a
  reader can tell "we are missing one small line" from "we are missing a third of the
  balance sheet".
* **Articulation across years** -- closing retained earnings against opening plus
  profit less dividends, and the movement in cash against the cash flow statement.
  These need two periods and say something no single year can.

**Nothing is stored twice.** The figures live in ``FundamentalPeriod.metrics`` and this
is a view over them. A ledger table would be a second source of truth for numbers that
already have one, and it would go stale the first time a period was re-extracted.

Evidence tier: the statements themselves are mechanical (tier A). The *checks* are
tier A as arithmetic but only as good as the extraction beneath them, which is why
each one carries the residual it measured.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from awltux.db import FundamentalPeriod
from awltux.metrics import value_of

#: Relative tolerance for calling two figures equal, with an absolute floor.
#:
#: Providers round to millions and taxonomies disagree about a line's sign, so an
#: exact comparison would report an imbalance on every filer. Half a percent of the
#: scale being compared, and never less than one unit, is loose enough to accept
#: rounding and tight enough to catch a missing account -- the smallest component in
#: the live data is well above it.
TOLERANCE_FRACTION = 0.005
TOLERANCE_FLOOR = 1.0

#: Figures quoted per share rather than as a magnitude of the statement's currency, and so
#: printed with their pence. See `Line.decimals`, and `metrics.NON_MONETARY_METRICS` for the
#: wider rule these belong to -- a share *count* is not here, because a count has no pence.
PER_SHARE_METRICS: tuple[str, ...] = ("eps_diluted", "eps_basic", "dividend_per_share")
DEBIT = "debit"
CREDIT = "credit"


@dataclass(frozen=True, slots=True)
class Account:
    """One line of the ledger.

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
    Account("cost_of_goods_sold", "Cost of sales", "profit_and_loss", "Cost of sales", DEBIT),
    Account(
        "gross_profit", "Gross profit", "profit_and_loss", "Cost of sales", CREDIT,
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
        "interest_expense", "Interest expense", "profit_and_loss", "Finance", DEBIT,
    ),
    Account(
        "interest_income", "Interest income", "profit_and_loss", "Finance", CREDIT,
    ),
    Account(
        "other_nonoperating_income", "Other non-operating income",
        "profit_and_loss", "Finance", CREDIT, signed=True,
    ),
    Account(
        "pretax_income", "Profit before tax", "profit_and_loss", "Finance", CREDIT,
        role="subtotal", signed=True,
    ),
    Account("tax_expense", "Tax", "profit_and_loss", "Tax", DEBIT),
    Account(
        "net_income", "Profit for the period", "profit_and_loss", "Tax", CREDIT,
        role="subtotal", signed=True,
    ),
    Account("ebit", "EBIT", "profit_and_loss", "Memorandum", CREDIT, role="memo"),
    Account("ebitda", "EBITDA", "profit_and_loss", "Memorandum", CREDIT, role="memo"),
    Account("eps_diluted", "Diluted earnings per share", "profit_and_loss", "Per share", CREDIT, role="memo"),
    Account("dividend_per_share", "Dividend per share", "profit_and_loss", "Per share", DEBIT, role="memo"),
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
#: then what is owned and owed, then how the cash moved. Labels are plain text --
#: the template escapes them, so an ampersand here is an ampersand.
STATEMENTS: tuple[tuple[str, str], ...] = (
    ("profit_and_loss", "Profit & loss"),
    ("balance_sheet", "Balance sheet"),
    ("cash_flow", "Cash flow"),
)

#: The tab strip: the three statements, then the accounting health checks. The checks
#: are a tab rather than a footnote under one of the statements because they are the
#: reason to look at a set of accounts this closely -- they are what says whether the
#: figures above them can be trusted.
TABS: tuple[tuple[str, str], ...] = STATEMENTS + (("health", "Accounting health"),)

#: The statement a bare `/accounts/{id}` opens on.
DEFAULT_STATEMENT = STATEMENTS[0][0]

#: The names :func:`statement` will build -- the tabs minus the checks.
STATEMENT_KINDS: tuple[str, ...] = tuple(name for name, _ in STATEMENTS)

#: Every tab name, for validating the path segment.
TAB_NAMES: frozenset[str] = frozenset(name for name, _ in TABS)

#: The accounts whose *stated* values form the accounting equation. Assets are debits;
#: liabilities and equity are credits. Components are checked against these, never
#: posted in their place -- see :func:`trial_balance`.
EQUATION_DEBIT = ("total_assets",)
EQUATION_CREDIT = ("total_liabilities", "total_equity")


def tolerance(scale: float) -> float:
    """How far two figures may differ and still be called equal."""
    return max(TOLERANCE_FLOOR, abs(scale) * TOLERANCE_FRACTION)


@dataclass(frozen=True, slots=True)
class Posting:
    """A figure entered on one side of one account."""

    account: Account
    amount: float
    #: True when the figure came from the filing rather than from arithmetic below.
    stated: bool = True

    @property
    def debit(self) -> float:
        return self.amount if self.account.side == DEBIT else 0.0

    @property
    def credit(self) -> float:
        return self.amount if self.account.side == CREDIT else 0.0


@dataclass(frozen=True, slots=True)
class TrialBalance:
    """What the ledger holds, and whether the two sides agree.

    ``difference`` is deliberately not zeroed. A trial balance that has been forced to
    balance is a trial balance that cannot tell you anything.
    """

    postings: tuple[Posting, ...]
    scale: float

    @property
    def debits(self) -> float:
        return sum(posting.debit for posting in self.postings)

    @property
    def credits(self) -> float:
        return sum(posting.credit for posting in self.postings)

    @property
    def difference(self) -> float:
        return self.debits - self.credits

    @property
    def balanced(self) -> bool:
        return abs(self.difference) <= tolerance(self.scale)

    @property
    def complete(self) -> bool:
        """Every posting the equation needs was stated.

        Distinct from ``balanced``: an empty ledger balances trivially, and reporting
        that as a clean bill of health would be the worst possible failure here.
        """
        return all(
            BY_KEY[key].key in {posting.account.key for posting in self.postings}
            for key in EQUATION_DEBIT + EQUATION_CREDIT
        )


def trial_balance(period: FundamentalPeriod) -> TrialBalance:
    """The accounting equation, posted from the stated totals.

    **The stated totals are posted, not the components.** That is the whole point: the
    equation ``assets = liabilities + equity`` is a fact about the filing, and it holds
    whatever subset of the components this project happens to extract. Posting the
    components instead would make every filer look insolvent by exactly the amount of
    the accounts we do not collect, and the check would measure our coverage rather
    than the extraction's accuracy. Composition is a separate question with its own
    check -- see :func:`composition`.
    """
    metrics = period.metrics or {}
    postings = [
        Posting(account=BY_KEY[key], amount=amount)
        for key in EQUATION_DEBIT + EQUATION_CREDIT
        if (amount := value_of(metrics, key)) is not None
    ]
    scale = max((abs(posting.amount) for posting in postings), default=0.0)
    return TrialBalance(postings=tuple(postings), scale=scale)


# --------------------------------------------------------------------------- #
# Statements
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Part:
    """One component of a computed subtotal: what it is and what it contributed.

    Signed, because the arithmetic is: revenue less cost of sales, gross profit less the
    operating expenses. ``contribution`` is negative for a deduction and for a line the
    filer's own declaration weights negatively, so summing the parts reproduces
    :attr:`Line.computed` exactly -- which is the point of showing them.
    """

    label: str
    contribution: float
    #: Where the component's figure came from: a canonical metric name in this project's
    #: vocabulary, or ``taxonomy:Tag`` for a line only the filer names.
    source: str = ""

    @property
    def sign(self) -> str:
        return "+" if self.contribution >= 0 else "\u2212"


@dataclass(frozen=True, slots=True)
class Line:
    """One printed line: what was stated, what was computed, and which is which."""

    key: str
    label: str
    stated: float | None
    computed: float | None
    side: str
    role: str = "line"
    #: What the computed figure was made of, in the order it was added. Empty for a line
    #: with no arithmetic behind it -- a stated figure with nothing to check it against.
    parts: tuple[Part, ...] = ()
    #: Whose components those are: empty for this project's own key list, else a phrase
    #: naming the filer's declaration.
    parts_source: str = ""
    #: Declared lines the sum left out, and what the filer tagged them at. Named rather
    #: than folded into the total, so a reader can tell a line we failed to read from a
    #: filer whose subtotal does not add up.
    missing: tuple[str, ...] = ()
    missing_total: float | None = None

    @property
    def amount(self) -> float | None:
        """The figure to print -- what the filing said, if it said anything."""
        return self.stated if self.stated is not None else self.computed

    @property
    def agrees(self) -> bool | None:
        """Whether a stated total matches the components. ``None`` when only one exists."""
        if self.stated is None or self.computed is None:
            return None
        return abs(self.stated - self.computed) <= tolerance(self.stated)

    @property
    def residual(self) -> float | None:
        """Stated less computed. Positive means there are lines we do not hold."""
        if self.stated is None or self.computed is None:
            return None
        return self.stated - self.computed

    @property
    def decimals(self) -> int:
        """How many decimal places this line prints with.

        A per-share figure is a price, and rounding one to the nearest pound is wrong about a
        number a reader may act on: the page printed Microsoft's diluted EPS -- 17.95, from the
        filer's own accounts -- as **18**. The monetary lines keep whole units, which is what a
        balance sheet of hundreds of millions reads as.
        """
        return 2 if self.key in PER_SHARE_METRICS else 0

    def show_work(self) -> str:
        """The arithmetic behind this line, as lines of text for a hover tooltip.

        Asked for directly: *"When I hover over the Accounts 'out by' entries display the
        calculations that have been carried out so I can investigate what's gone wrong."* A
        residual is only investigable if the reader can see what produced the figure it is
        measured against, so this prints the stated total, every component with its sign, the
        sum, and the difference -- and names the lines the sum left out, which is what turns
        an unexplained remainder into "this is the line nobody read".

        Empty when there is no arithmetic to show: a line that only reports a figure has
        nothing to investigate, and a tooltip saying so would be noise.
        """
        return _work_text(
            stated=self.stated,
            computed=self.computed,
            parts=self.parts,
            source=self.parts_source,
            missing=self.missing,
            missing_total=self.missing_total,
            decimals=self.decimals,
        )


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    lines: tuple[Line, ...]

    @property
    def total(self) -> float | None:
        """The section's own subtotal: the last ``subtotal`` line in it, if any."""
        for line in reversed(self.lines):
            if line.role == "subtotal":
                return line.amount
        return None


@dataclass(frozen=True, slots=True)
class Statement:
    which: str
    title: str
    sections: tuple[Section, ...]
    #: Anything the statement could not be built from, named rather than left blank.
    gaps: tuple[str, ...] = ()
    trial_balance: TrialBalance | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lines(self) -> tuple[Line, ...]:
        return tuple(line for section in self.sections for line in section.lines)


def _stated(metrics: dict[str, Any], key: str) -> float | None:
    return value_of(metrics, key)


def _sum(*amounts: float | None) -> float | None:
    """Add up whatever is present, or ``None`` if nothing is.

    A missing component is skipped rather than treated as zero, so a partial total is
    visibly partial: the caller compares it against the stated total and reports the
    difference instead of presenting it as complete.
    """
    present = [amount for amount in amounts if amount is not None]
    return sum(present) if present else None


def _subtract(total: float | None, *deductions: float | None) -> float | None:
    """``total`` less whatever is present, or ``None`` when there is no total.

    The base must exist or the result is not a subtotal at all -- subtracting expenses
    from a missing revenue gives a negative number that reads like a loss. A missing
    *deduction* is skipped instead, because the arithmetic from the lines we hold is
    still worth showing; the residual against the stated subtotal is what tells the
    reader how much of it is missing.
    """
    if total is None:
        return None
    return total - sum(amount for amount in deductions if amount is not None)


def _section(title: str, lines: Sequence[Line]) -> Section:
    return Section(title=title, lines=tuple(lines))


#: The figures each statement shows beside its arithmetic and never sums. Kept as
#: named tuples so the two statements build their memorandum the same way, and so the
#: list is somewhere a reader can find it rather than inline in a builder.
INCOME_MEMORANDA: tuple[str, ...] = ("ebit", "ebitda", "eps_diluted", "dividend_per_share")
BALANCE_MEMORANDA: tuple[str, ...] = (
    "lease_liabilities",
    "retained_earnings",
    "total_debt",
    "shares_outstanding",
    "stock_based_compensation",
)


def _memoranda(metrics: dict[str, Any], keys: Sequence[str]) -> Section:
    """The closing section: what belongs on the page and not in the total."""
    return _section("Memorandum", [_line(metrics, key) for key in keys])


def _line(
    metrics: dict[str, Any],
    key: str,
    computed: float | None = None,
    work: _Work | None = None,
) -> Line:
    """One printed line, pulling its label, side and role from the chart.

    Shared by all three statements, so a line cannot be labelled one way in the profit
    and loss and another in the checks that audit it. ``work`` is the arithmetic behind
    ``computed`` -- see :class:`_Work` -- and is what the page shows on hover.
    """
    account = BY_KEY[key]
    return Line(
        key=key,
        label=account.label,
        stated=_stated(metrics, key),
        computed=computed,
        side=account.side,
        role=account.role,
        parts=work.parts if work else (),
        parts_source=work.source if work else "",
        missing=work.missing if work else (),
        missing_total=work.missing_total if work else None,
    )


def _worked_line(metrics: dict[str, Any], key: str, work: _Work) -> Line:
    """A line whose computed figure and whose arithmetic arrive together.

    The balance sheet's subtotals are built by `_work_from`, which decides whether the sum is
    the filer's declaration or our own key list; this attaches both halves to the line so the
    page can print the figure and explain it.
    """
    return _line(metrics, key, work.total, work)


def _label(key: str | None, fallback: str = "") -> str:
    """A metric's printed label, or the key itself for something not in the chart.

    The tooltip names components in the same words the lines above them are printed in, so a
    reader matching "Selling, general and administrative" in the sum against the line of that
    name does not have to translate a metric key.
    """
    if not key:
        return fallback
    account = BY_KEY.get(key)
    return account.label if account else fallback or key


def _sum_text(value: float | None, decimals: int = 0) -> str:
    """A figure for the hover tooltip: thousands separated, and an em dash for nothing."""
    if value is None:
        return "\u2014"
    return f"{value:,.{decimals}f}"


def _work_text(
    *,
    stated: float | None,
    computed: float | None,
    parts: tuple[Part, ...] = (),
    source: str = "",
    missing: tuple[str, ...] = (),
    missing_total: float | None = None,
    decimals: int = 0,
) -> str:
    """The arithmetic behind one figure, as the text the page shows on hover.

    One function for the statement's lines and for the checks that audit them: the two
    describe the same subtraction, and two renderings of it would eventually disagree about
    what was added up -- which is the failure the whole ledger is arranged to avoid.

    Empty when there is nothing to show. A line that only reports a figure has no arithmetic
    to investigate, and a tooltip saying so would be noise.
    """
    if computed is None and stated is None:
        return ""
    # Nothing to explain: a figure the filing reports and nobody derived has no arithmetic
    # behind it, and a tooltip restating the number would be noise on every row.
    if not parts and not missing and (stated is None or computed is None):
        return ""
    lines: list[str] = []
    if stated is not None:
        lines.append(f"from the filing: {_sum_text(stated, decimals)}")
    if parts:
        lines.append(
            "added up" + (f" ({source.strip('; ')})" if source else "") + ":"
        )
        lines.extend(
            f"  {part.sign} {_sum_text(abs(part.contribution), decimals)}  {part.label}"
            for part in parts
        )
        lines.append(f"= {_sum_text(computed, decimals)} computed")
    elif computed is not None:
        lines.append(f"computed: {_sum_text(computed, decimals)}")
    if missing:
        lines.append("not held, so left out of the sum:")
        lines.extend(f"  - {name}" for name in missing)
        if missing_total is not None:
            lines.append(f"  those lines are {_sum_text(abs(missing_total), decimals)} in total")
    if stated is not None and computed is not None:
        lines.append(
            f"out by {_sum_text(stated - computed, decimals)} (stated \u2212 computed)"
        )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _Work:
    """The arithmetic behind one computed subtotal, on its way to a :class:`Line`.

    A named object rather than four more arguments to `_line`, because the four travel
    together and only one of the three call sites has them: the profit cascade derives its
    own, the balance sheet takes them from the filer's declaration where it has one.
    """

    #: What the components add up to, so the caller attaches the value and its working in
    #: one move rather than recomputing one of them.
    total: float | None = None
    parts: tuple[Part, ...] = ()
    source: str = ""
    missing: tuple[str, ...] = ()
    missing_total: float | None = None


def _extras_total(
    metrics: dict[str, Any], accounts: Sequence[Account]
) -> float | None:
    """What the learned lines of one stage add up to, or ``None`` when none of them has a figure."""
    total: float | None = None
    for account in accounts:
        value = _stated(metrics, account.key)
        if value is None:
            continue
        total = (total or 0.0) + value
    return total


def _extra_parts(
    metrics: dict[str, Any], accounts: Sequence[Account]
) -> tuple[Part, ...]:
    """The learned lines as components of a subtotal, in the *filer's* words for them.

    Deliberately not through :func:`_label`, which knows only the chart: a learned line's key is
    its taxonomy tag, so the working a reader hovers would list
    ``us-gaap:ContractWithCustomerLiabilityCurrent`` where the statement prints
    "Short-term unearned revenue". An absent figure is left out, exactly as :func:`_component`
    leaves one out, because a zero claims the filing stated nothing there.

    The contribution is the figure itself, sign and all, so the working adds up to the total *and*
    agrees line by line with the figure the statement prints beside it. Reported 2026-10-10: the
    two disagreed, and the reader read the working as the thing that was wrong.
    """
    out: list[Part] = []
    for account in accounts:
        value = _stated(metrics, account.key)
        if value is None:
            continue
        out.append(Part(label=account.label, contribution=value, source=account.key))
    return tuple(out)


def _plus_extras(base: float | None, added: float | None) -> float | None:
    """A stage's figure with what the reader added to it.

    A ``None`` base stays ``None``: a line put under "Finance and tax" cannot make profit before
    tax computable when operating income is not, and inventing a total out of the part of the
    cascade that happens to be present would be the residual lying about what it measures.
    """
    if base is None or added is None:
        return base
    return base + added


def _profit_cascade(
    metrics: dict[str, Any], extra: Sequence[Account] | None = None
) -> dict[str, _Work]:
    """The four subtotals this project can derive from the lines it holds.

    One cascade rather than one per caller: the profit and loss statement prints these
    and :func:`profit_articulation` audits them against the reported figure, and two
    copies of the same arithmetic would eventually disagree about which lines are
    included -- which is exactly the disagreement the audit exists to detect.

    **Each subtotal comes back with the arithmetic that produced it**, in the same object,
    because a page that can show a residual but not how the figure beside it was reached is
    one a reader cannot investigate. Deriving the components again where they are printed
    would be the duplication this function exists to prevent.

    **A line the filer names joins here, and this is the only place it can.** The heading the
    reader filed it under says which stage it first feeds and the side it was posted on says
    which way -- see :func:`signed_extras` -- and both go into the total *and* into ``parts``,
    so the working printed beside the figure lists the line it was computed from.

    **Profit before tax is not "operating income less interest".** Interest *income* and
    other non-operating items sit between the two as well, and leaving them out put a
    visible residual on the page for any filer that has them. Measured on `AIT_US_EQ`
    FY2026-06-30: operating income 549,469,000 less interest expense 17,386,000 is
    532,083,000 against a reported profit before tax of 544,274,000 -- a gap of
    12,191,000, which is exactly the interest income (9,448,000) plus other
    non-operating income (2,743,000) the taxonomy did not carry. With them, the three
    lines reconcile to the reported figure to the dollar.
    """
    revenue = _stated(metrics, "revenue")
    cost = _stated(metrics, "cost_of_goods_sold")
    # Which learned lines first join each stage. Every decision about them -- which subtotal,
    # which direction -- was made when they were recorded; nothing here chooses either.
    in_revenue = extras_for_group(extra, "profit_and_loss", "gross_profit")
    in_operating = extras_for_group(extra, "profit_and_loss", "operating_income")
    in_finance = extras_for_group(extra, "profit_and_loss", "pretax_income")

    gross = _plus_extras(
        _subtract(revenue, cost), _extras_total(metrics, in_revenue)
    )
    operating = _plus_extras(
        _subtract(
            gross,
            _stated(metrics, "research_and_development"),
            _stated(metrics, "sga_expense"),
            _stated(metrics, "depreciation_amortisation"),
        ),
        _extras_total(metrics, in_operating),
    )
    # Added when present, deducted when present, and `None` only when neither side is
    # stated -- which is what falls back to operating income. Using `_subtract` here
    # instead reads well and is wrong: it returns `None` when its *base* is missing, so
    # a filer with interest expense and no interest income would have had the expense
    # silently dropped rather than deducted.
    additions = _sum(
        _stated(metrics, "interest_income"),
        _stated(metrics, "other_nonoperating_income"),
    )
    interest = _stated(metrics, "interest_expense")
    finance_extras = _extras_total(metrics, in_finance)
    if additions is None and interest is None:
        # Nothing of our own between the two lines -- so a learned one filed under "Finance and
        # tax" is the whole of the difference, and profit before tax is not left uncomputable.
        non_operating = 0.0 if finance_extras is not None else None
    else:
        non_operating = (additions or 0.0) - (interest or 0.0)
    if operating is None:
        pretax = None
    elif non_operating is None:
        pretax = operating
    else:
        pretax = operating + non_operating + (finance_extras or 0.0)
    tax = _stated(metrics, "tax_expense")
    return _cascade_works(
        metrics,
        gross=gross,
        operating=operating,
        pretax=pretax,
        tax=tax,
        in_revenue=in_revenue,
        in_operating=in_operating,
        in_finance=in_finance,
    )


def _cascade_works(
    metrics: dict[str, Any],
    *,
    gross: float | None,
    operating: float | None,
    pretax: float | None,
    tax: float | None,
    in_revenue: Sequence[Account],
    in_operating: Sequence[Account],
    in_finance: Sequence[Account],
) -> dict[str, _Work]:
    """The four subtotals, each carrying the arithmetic that produced it.

    Split from the derivation above because the working is the other half of the job: a page
    that can print a residual but not how the figure beside it was reached is one a reader
    cannot investigate. A learned line joins here as well as in the totals, or the hover would
    not add up to the figure it sits beside -- which is the one thing it is for.
    """
    return {
        "gross_profit": _Work(
            total=gross,
            parts=(
                _components(metrics, ("revenue", 1.0), ("cost_of_goods_sold", -1.0))
                + _extra_parts(metrics, in_revenue)
            ),
        ),
        "operating_income": _Work(
            total=operating,
            parts=(
                _component("gross_profit", gross, 1.0)
                + _components(
                    metrics,
                    ("research_and_development", -1.0),
                    ("sga_expense", -1.0),
                    ("depreciation_amortisation", -1.0),
                )
                + _extra_parts(metrics, in_operating)
            ),
        ),
        "pretax_income": _Work(
            total=pretax,
            parts=(
                _component("operating_income", operating, 1.0)
                + _components(
                    metrics,
                    ("interest_income", 1.0),
                    ("other_nonoperating_income", 1.0),
                    ("interest_expense", -1.0),
                )
                + _extra_parts(metrics, in_finance)
            ),
        ),
        "net_income": _Work(
            total=_subtract(pretax, tax),
            parts=(
                _component("pretax_income", pretax, 1.0)
                + _components(metrics, ("tax_expense", -1.0))
            ),
        ),
    }


def _component(key: str, value: float | None, weight: float) -> tuple[Part, ...]:
    """One component, or nothing at all when the figure is absent.

    An absent component is left out rather than listed as zero: a sum showing a line at 0
    claims the filing stated nothing there, which is a different fact from our not holding
    it -- and the residual is what tells the reader which of the two it is.
    """
    if value is None:
        return ()
    return (Part(label=_label(key), contribution=weight * value, source=key),)


def _components(
    metrics: dict[str, Any], *weighted: tuple[str, float]
) -> tuple[Part, ...]:
    """The present components of a subtotal, each carrying its key and its weight."""
    out: list[Part] = []
    for key, weight in weighted:
        out.extend(_component(key, _stated(metrics, key), weight))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class _Composition:
    """What the component lines we hold add up to, side by side.

    Named because the balance sheet prints these sums and :func:`composition` audits
    them, and "the sum of the asset lines" is a concept rather than a line of code.
    """

    current_assets: float | None
    non_current_assets: float | None
    current_liabilities: float | None
    non_current_liabilities: float | None

    @property
    def assets(self) -> float | None:
        return _sum(self.current_assets, self.non_current_assets)

    @property
    def liabilities(self) -> float | None:
        return _sum(self.current_liabilities, self.non_current_liabilities)


#: Which component accounts sit on each side of the balance sheet. Declared once so the
#: statement and the check that audits it cannot disagree about what was included.
#:
#: `other_current_assets`, `operating_lease_assets` and `other_noncurrent_assets` are
#: here because leaving them out is what made the totals look wrong: measured on
#: `AIT_US_EQ` FY2026-06-30, the two residuals this check reported were exactly those
#: lines -- 238,506,000 of current assets (cash plus other current) and 282,079,000 of
#: non-current (operating leases plus other). With them the balance sheet reconciles to
#: the dollar, which is what a component list that is actually complete looks like.
CURRENT_ASSET_KEYS = (
    "cash_and_equivalents", "receivables", "inventory", "other_current_assets",
)
NON_CURRENT_ASSET_KEYS = (
    "net_ppe", "operating_lease_assets", "goodwill", "intangible_assets",
    "other_noncurrent_assets",
)
CURRENT_LIABILITY_KEYS = (
    "payables", "compensation_and_benefits", "other_current_liabilities", "short_term_debt",
)
#: `lease_liabilities` is deliberately absent: it is a memorandum, because the caption
#: it would be added to (`other_noncurrent_liabilities`) may already contain it. See the
#: account's definition in :data:`CHART`.
NON_CURRENT_LIABILITY_KEYS = ("long_term_debt", "other_noncurrent_liabilities")

#: The two totals, as their components. Composed from the four above rather than written out:
#: a line added to one side must appear in the total's arithmetic too, or the working shown
#: for the residual would not add up to the figure beside it.
TOTAL_ASSET_KEYS = CURRENT_ASSET_KEYS + NON_CURRENT_ASSET_KEYS
TOTAL_LIABILITY_KEYS = CURRENT_LIABILITY_KEYS + NON_CURRENT_LIABILITY_KEYS

#: The key list behind each subtotal, by the metric name the checks and the page use. The
#: composition writes its sums from these tuples, and the page writes the arithmetic behind
#: them from the same tuples, so the working a reader hovers cannot list a different set of
#: lines from the one the figure was computed from.
COMPONENT_KEYS: dict[str, tuple[str, ...]] = {
    "current_assets": CURRENT_ASSET_KEYS,
    "total_assets": TOTAL_ASSET_KEYS,
    "current_liabilities": CURRENT_LIABILITY_KEYS,
    "total_liabilities": TOTAL_LIABILITY_KEYS,
}


#: Which group of components a line the *filer* names joins, by the heading it sits under.
#:
#: A line learned from a filing has to be counted somewhere or adding it changes nothing, and
#: the heading the reader chose is the one piece of that the chart can act on. The keys are the
#: headings the statement **prints**, and every heading whose lines are summed is here.
#:
#: The balance sheet used to print one heading, "Non-current liabilities and equity", holding two
#: subtotals -- and that is why it no longer does. A heading that covers two totals cannot say
#: which of them a first-time line feeds, so the honest choices were to split it or to refuse to
#: count anything under it; the chart already separated the two, the statement now prints them
#: separately, and :data:`ledger.uncounted_extras` reports the headings that remain -- "Equity"
#: and "Memorandum", where this page computes no sum of the lines at all.
#:
#: On the profit and loss the group is the **stage of the cascade the line first feeds** rather
#: than a bucket of components, because that statement's subtotals are a formula and not a sum of
#: a key list: a line filed under "Operating expenses" belongs in operating income and in
#: everything below it, and in nothing above. Added 2026-10-10 with the same report the ordering
#: fix above answers -- the two lines the reader added under "Operating expenses" were printed
#: and counted nowhere, so the "out by" they were added to fix did not move.
EXTRA_GROUP: dict[tuple[str, str], str] = {
    ("balance_sheet", "Current assets"): "current_assets",
    ("balance_sheet", "Non-current assets"): "non_current_assets",
    ("balance_sheet", "Current liabilities"): "current_liabilities",
    ("balance_sheet", "Non-current liabilities"): "non_current_liabilities",
    ("profit_and_loss", "Revenue"): "gross_profit",
    ("profit_and_loss", "Operating expenses"): "operating_income",
    ("profit_and_loss", "Finance and tax"): "pretax_income",
}

#: Which stated subtotals a component group feeds, so a line added to one is counted in the
#: totals that group is part of rather than only in its own row.
GROUP_SUBTOTALS: dict[str, tuple[str, ...]] = {
    "current_assets": ("current_assets", "total_assets"),
    "non_current_assets": ("total_assets",),
    "current_liabilities": ("current_liabilities", "total_liabilities"),
    "non_current_liabilities": ("total_liabilities",),
}


def extras_in(
    extra: Sequence[Account] | None, statement: str, section: str
) -> list[Account]:
    """The learned lines that belong under one printed heading, in the order they were learned."""
    return [
        account
        for account in (extra or ())
        if account.statement == statement and account.section == section
    ]


def extras_for_group(
    extra: Sequence[Account] | None, statement: str, group: str
) -> list[Account]:
    """The learned lines that join one group -- a component bucket, or a stage of the cascade."""
    return [
        account
        for account in (extra or ())
        if account.statement == statement
        and EXTRA_GROUP.get((account.statement, account.section)) == group
    ]


def extra_keys(
    extra: Sequence[Account] | None, statement: str, group: str
) -> tuple[str, ...]:
    """The learned lines in one component group -- the components a subtotal is summed from."""
    return tuple(
        account.key for account in extras_for_group(extra, statement, group)
    )


def subtotal_extra_keys(
    extra: Sequence[Account] | None, statement: str, subtotal: str
) -> tuple[str, ...]:
    """The learned lines that feed one stated subtotal, by the group their heading joins."""
    return tuple(
        account.key
        for account in (extra or ())
        if account.statement == statement
        and subtotal in GROUP_SUBTOTALS.get(EXTRA_GROUP.get((account.statement, account.section), ""), ())
    )


def uncounted_extras(extra: Sequence[Account] | None, statement: str) -> list[Account]:
    """Learned lines printed in a statement whose heading feeds no stated subtotal.

    Reported rather than left to be noticed: a figure that appears in the accounts and moves no
    total is a figure a reader will assume is counted.
    """
    return [
        account
        for account in (extra or ())
        if account.statement == statement
        and (account.statement, account.section) not in EXTRA_GROUP
    ]


def uncounted_note(extra: Sequence[Account] | None, statement: str) -> str | None:
    """The sentence a statement adds when a line the filer names is counted nowhere, or ``None``.

    One function for all three statements, because the failure it reports is the same on each: a
    figure that appears in the accounts and moves no total is a figure a reader will assume is
    counted.
    """
    uncounted = uncounted_extras(extra, statement)
    if not uncounted:
        return None
    headings = "”, “".join(sorted({account.section for account in uncounted}))
    return (
        f"Lines read from the filing under “{headings}” are printed there and added to no "
        "total: this page computes no sum of that heading's lines, and which total a figure "
        "belongs to is not something it will guess. A line put under a heading whose lines are "
        "summed is added to it."
    )


def _composition(
    metrics: dict[str, Any], extra: Sequence[Account] | None = None
) -> _Composition:
    """What the component lines we hold add up to, including any the filer named by hand.

    The five key lists are the chart's; a learned line joins the group its heading feeds, and
    `EXTRA_GROUP` is the one place that decides which -- so the printed subtotal's arithmetic and
    the check that audits it cannot disagree about what was included.
    """
    current_assets = CURRENT_ASSET_KEYS + extra_keys(extra, "balance_sheet", "current_assets")
    non_current_assets = NON_CURRENT_ASSET_KEYS + extra_keys(
        extra, "balance_sheet", "non_current_assets"
    )
    current_liabilities = CURRENT_LIABILITY_KEYS + extra_keys(
        extra, "balance_sheet", "current_liabilities"
    )
    non_current_liabilities = NON_CURRENT_LIABILITY_KEYS + extra_keys(
        extra, "balance_sheet", "non_current_liabilities"
    )
    return _Composition(
        current_assets=_sum(*(_stated(metrics, key) for key in current_assets)),
        non_current_assets=_sum(*(_stated(metrics, key) for key in non_current_assets)),
        current_liabilities=_sum(*(_stated(metrics, key) for key in current_liabilities)),
        non_current_liabilities=_sum(
            *(_stated(metrics, key) for key in non_current_liabilities)
        ),
    )


def profit_and_loss(
    period: FundamentalPeriod, *, extra: Sequence[Account] | None = None
) -> Statement:
    """The result for the period, with each stated subtotal checked against its parts.

    ``gross_profit``, ``operating_income``, ``pretax_income`` and ``net_income`` are
    each shown with the arithmetic this project can do from the lines it holds. Where
    the filing states the subtotal too, the two are both printed and the residual is
    the number that matters -- it is the size of the lines we do not extract (other
    operating income, associates, minority interests), and a reader who cannot see it
    cannot tell an extraction gap from a business with unusual economics.

    A line the filer names joins the cascade: the heading the reader filed it under says which
    subtotal it first feeds and the side they posted it on says which way, so a figure added to
    fix a residual moves it. Where the calculation linkbase has been read the *filer's* own
    arithmetic picks such a line up by its tag too, which is the check that matters.
    """
    metrics = period.metrics or {}
    gaps: list[str] = []

    if _stated(metrics, "revenue") is None:
        gaps.append("revenue")
    cascade = _profit_cascade(metrics, extra)

    def held(title: str, lines: list[Line]) -> Section:
        return _section(
            title,
            _section_lines(
                lines, metrics=metrics, statement="profit_and_loss", section=title, extra=extra
            ),
        )

    sections = (
        held(
            "Revenue",
            [
                _line(metrics, "revenue"),
                _line(metrics, "cost_of_goods_sold"),
                _line(metrics, "gross_profit", cascade["gross_profit"].total, cascade["gross_profit"]),
            ],
        ),
        held(
            "Operating expenses",
            [
                _line(metrics, "research_and_development"),
                _line(metrics, "sga_expense"),
                _line(metrics, "depreciation_amortisation"),
                _line(metrics, "operating_income", cascade["operating_income"].total, cascade["operating_income"]),
            ],
        ),
        held(
            "Finance and tax",
            [
                _line(metrics, "interest_expense"),
                _line(metrics, "interest_income"),
                _line(metrics, "other_nonoperating_income"),
                _line(metrics, "pretax_income", cascade["pretax_income"].total, cascade["pretax_income"]),
                _line(metrics, "tax_expense"),
                _line(metrics, "net_income", cascade["net_income"].total, cascade["net_income"]),
            ],
        ),
        _memoranda(metrics, INCOME_MEMORANDA),
    )
    notes = [
        "A stated subtotal and the arithmetic beside it differ by the lines this "
        "project does not extract; the residual is shown rather than absorbed.",
    ]
    uncounted = uncounted_note(extra, "profit_and_loss")
    if uncounted:
        notes.append(uncounted)
    return Statement(
        which="profit_and_loss",
        title="Profit & loss",
        sections=sections,
        gaps=tuple(gaps),
        notes=tuple(notes),
    )


def balance_sheet(
    period: FundamentalPeriod,
    *,
    declared: Mapping[str, Declared] | None = None,
    extra: Sequence[Account] | None = None,
) -> Statement:
    """What is owned and owed, with the components checked against the stated totals.

    ``declared`` puts the filer's own children behind the four subtotals where its
    calculation linkbase has been read, so the residual printed beside a total is the
    lines *the filing* breaks it into that this project does not hold -- which for a
    bucket line like `other_current_assets` is a very different figure from the residual
    against our own key list.

    ``extra`` are lines the *filer* names and the chart does not (see `analysis/corrections`).
    They are printed under the heading they were learned with and counted in the subtotals that
    heading feeds, so adding a line the filing states moves the residual it was added to fix.
    """
    metrics = period.metrics or {}
    gaps: list[str] = []
    held = _composition(metrics, extra)

    def sum_of(metric: str, ours: float | None, keys: Sequence[str]) -> _Work:
        """The filer's sum for this subtotal where it declares one, else our own list.

        The keys travel with the call rather than being looked up from a second table: the
        same tuple that produced the composition figure produces the arithmetic shown for it,
        so a line added to one cannot be missing from the other.
        """
        return _work_from(
            declared,
            metric,
            ours,
            tuple(keys) + subtotal_extra_keys(extra, "balance_sheet", metric),
            metrics,
        )

    def section(title: str, lines: list[Line]) -> Section:
        return _section(
            title,
            _section_lines(
                lines,
                metrics=metrics,
                statement="balance_sheet",
                section=title,
                extra=extra,
            ),
        )

    if _stated(metrics, "total_equity") is None:
        gaps.append("total equity")

    sections = (
        section(
            "Current assets",
            [
                _line(metrics, "cash_and_equivalents"),
                _line(metrics, "receivables"),
                _line(metrics, "inventory"),
                _line(metrics, "other_current_assets"),
                _worked_line(metrics, "current_assets", sum_of("current_assets", held.current_assets, CURRENT_ASSET_KEYS)),
            ],
        ),
        section(
            "Non-current assets",
            [
                _line(metrics, "net_ppe"),
                _line(metrics, "operating_lease_assets"),
                _line(metrics, "goodwill"),
                _line(metrics, "intangible_assets"),
                _line(metrics, "other_noncurrent_assets"),
                _worked_line(metrics, "total_assets", sum_of("total_assets", held.assets, TOTAL_ASSET_KEYS)),
            ],
        ),
        section(
            "Current liabilities",
            [
                _line(metrics, "payables"),
                _line(metrics, "compensation_and_benefits"),
                _line(metrics, "other_current_liabilities"),
                _line(metrics, "short_term_debt"),
                _worked_line(
                    metrics,
                    "current_liabilities",
                    sum_of("current_liabilities", held.current_liabilities, CURRENT_LIABILITY_KEYS),
                ),
            ],
        ),
        section(
            "Non-current liabilities",
            [
                _line(metrics, "long_term_debt"),
                _line(metrics, "other_noncurrent_liabilities"),
                _worked_line(metrics, "total_liabilities", sum_of("total_liabilities", held.liabilities, TOTAL_LIABILITY_KEYS)),
            ],
        ),
        section("Equity", [_line(metrics, "total_equity")]),
        _memoranda(metrics, BALANCE_MEMORANDA),
    )
    notes = [
        "Total assets, total liabilities and total equity are as stated by the "
        "filing. The component lines above each total are what this project "
        "extracts; the residual against the stated total is not an error.",
    ]
    uncounted = uncounted_note(extra, "balance_sheet")
    if uncounted:
        notes.append(uncounted)
    return Statement(
        which="balance_sheet",
        title="Balance sheet",
        sections=sections,
        gaps=tuple(gaps),
        trial_balance=trial_balance(period),
        notes=tuple(notes),
    )


def cash_flow(
    period: FundamentalPeriod, *, extra: Sequence[Account] | None = None
) -> Statement:
    """How cash moved, and what is missing from the movement.

    The statement is a *movement*, so it only reconciles against the previous period's
    cash balance. The reconciliation itself lives in :func:`cash_movement` because it
    needs two periods, and this builds the single-period view.
    """
    metrics = period.metrics or {}
    operating = _stated(metrics, "operating_cash_flow")
    capex = _stated(metrics, "capex")

    def held(title: str, lines: list[Line]) -> Section:
        return _section(
            title,
            _section_lines(
                lines, metrics=metrics, statement="cash_flow", section=title, extra=extra
            ),
        )

    notes = [
        "The taxonomy holds operating cash flow, capital expenditure and dividends. "
        "Acquisitions, disposals, share issues and borrowings are not extracted, so "
        "this is not a complete statement of the movement in cash and says so "
        "rather than balancing to a figure it cannot support.",
    ]
    uncounted = uncounted_note(extra, "cash_flow")
    if uncounted:
        notes.append(uncounted)

    return Statement(
        which="cash_flow",
        title="Cash flow",
        sections=(
            held("Operating", [_line(metrics, "operating_cash_flow")]),
            held(
                "Investing",
                [
                    _line(metrics, "capex"),
                    # Free cash flow is a calculation like any subtotal, so it carries its
                    # working: operating cash flow less capital expenditure, which is the
                    # second thing a reader checks after the residual.
                    _line(
                        metrics,
                        "free_cash_flow",
                        _subtract(operating, capex),
                        _Work(
                            total=_subtract(operating, capex),
                            parts=_components(
                                metrics, ("operating_cash_flow", 1.0), ("capex", -1.0)
                            ),
                            source="this project's own list of component lines",
                        ),
                    ),
                ],
            ),
            _section("Financing", [_line(metrics, "dividends_paid")]),
        ),
        notes=tuple(notes),
    )


def _extra_line(metrics: dict[str, Any], account: Account) -> Line:
    """A line the filer names that the chart does not carry.

    Stated and nothing else: there is no arithmetic behind a figure a person put there, and
    inventing a component list for it would be inventing a claim. Its contribution to the
    subtotal above it comes from the heading it was put under -- see :data:`EXTRA_GROUP`.
    """
    return Line(
        key=account.key,
        label=account.label,
        stated=_stated(metrics, account.key),
        computed=None,
        side=account.side,
        role="line",
    )


def _section_lines(
    base: list[Line],
    *,
    metrics: dict[str, Any],
    statement: str,
    section: str,
    extra: Sequence[Account] | None,
) -> list[Line]:
    """One section's own lines with the learned ones **before** its subtotal.

    Position is not decoration here. A learned line printed under the total it feeds reads as
    a memorandum -- and it was, in the first version, because the extras were appended and the
    statement builders put each section's subtotal last in ``base``. Reported 2026-10-10: *"they
    appear below the section total and aren't included in the section total calculation ... the
    point of adding these values is to fix the 'out by X'"*. So the extras go in front of the
    first subtotal line, which is the one they are counted in -- see :data:`EXTRA_GROUP` for
    which subtotal that is, by heading and by statement.

    A section with no subtotal (the cash flow's "Financing", the balance sheet's "Equity") keeps
    them at the end, where the note beside the statement says they are counted nowhere.
    """
    learned = [_extra_line(metrics, account) for account in extras_in(extra, statement, section)]
    if not learned:
        return list(base)
    at = next(
        (index for index, line in enumerate(base) if line.role == "subtotal"), len(base)
    )
    return base[:at] + learned + base[at:]


def statement(
    period: FundamentalPeriod,
    which: str,
    *,
    declared: Mapping[str, Declared] | None = None,
    extra: Sequence[Account] | None = None,
) -> Statement:
    """One statement by name. Raises for a name that is not a statement."""
    if which == "balance_sheet":
        return balance_sheet(period, declared=declared, extra=extra)
    builders = {
        "profit_and_loss": profit_and_loss,
        "cash_flow": cash_flow,
    }
    try:
        build = builders[which]
    except KeyError:
        raise KeyError(f"no statement {which!r}; expected one of {sorted(builders)}") from None
    return build(period, extra=extra)


# --------------------------------------------------------------------------- #
# Accounting health
# --------------------------------------------------------------------------- #

#: A check either agrees, disagrees, or could not be attempted.
OK = "ok"
IMBALANCE = "imbalance"
UNKNOWN = "not computable"


@dataclass(frozen=True, slots=True)
class Check:
    """One accounting-health finding, with the figures that produced it."""

    key: str
    label: str
    status: str
    detail: str
    residual: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    #: The arithmetic behind the residual, as text for the page's hover panel, for the checks
    #: that have one. Built by :func:`_work_text` -- the same function `Line.show_work` uses,
    #: so a figure and the check that audits it cannot explain themselves differently.
    work: str = ""
    #: The one line of the accounts this check measures, when it measures one. Set so the page
    #: can open the filing *at that line* for a reader who wants to see what the filer tagged
    #: against what we hold. Empty for a check that spans the accounts rather than auditing one
    #: line -- the accounting equation, the roll-forward and the cash movement have no single
    #: caption to open, and a link to the whole 10-K would be an offer to go and look for it.
    about: str = ""

    @property
    def failed(self) -> bool:
        return self.status == IMBALANCE


@dataclass(frozen=True, slots=True)
class Declared:
    """A subtotal measured from the filer's own declared children.

    Kept as one value with its gaps rather than a bare number, because the two are used
    differently: the statement prints ``total`` -- the best figure available, and the
    whole point of reading the declaration -- while the *check* refuses to call it
    computable when ``missing`` is non-empty, since a subtotal with a line left out has
    not been checked at all.

    ``missing`` names the declared leaves this project holds no figure for, so a reader
    is told which line to look at rather than only that something is absent, and
    ``missing_total`` is what the filer itself tagged those lines at -- when it tagged
    them all -- which is what turns "out by 2,093,000" into "out by exactly the line we do
    not hold" instead of leaving a residual that looks unexplained.
    """

    total: float | None
    missing: tuple[str, ...] = ()
    missing_total: float | None = None
    #: The same lines as :attr:`missing`, as ``taxonomy:Tag`` rather than as display text.
    #: A reader needs "Prepaid expenses"; the *fix* -- adopting that caption into a line
    #: for this filer -- is a mapping, and a mapping is keyed by the tag.
    missing_tags: tuple[str, ...] = ()
    #: The declared children this sum was actually made of, as ``(name, contribution)``, in
    #: the filing's own order. Recorded so the accounts page can show the arithmetic behind
    #: one subtotal rather than only its result: a reader looking at "out by 26,710,000,000"
    #: needs to see which lines the declaration added and which of them was worth that much.
    #: ``contribution`` carries the filer's weight, so a line it declares as a deduction
    #: appears negative.
    parts: tuple[tuple[str, float], ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing


def _check(
    key: str, label: str, status: str, detail: str, **rest: Any
) -> Check:
    """One finding, named. A constructor rather than the field list written out at each exit.

    Every check carries the same ten fields, and the two that arrived last -- ``work`` and
    ``about`` -- are exactly the kind that gets added to three exits and forgotten in the
    fourth. Named once here, they cannot be.
    """
    return Check(key=key, label=label, status=status, detail=detail, **rest)


def _agree(
    key: str,
    label: str,
    stated: float | None,
    computed: float | None,
    detail: str,
    *,
    missing: tuple[str, ...] = (),
    missing_total: float | None = None,
    work: _Work | None = None,
    about: str = "",
) -> Check:
    """A stated total against the parts we hold. Unknown when either side is missing.

    ``missing`` is for a declaration-driven sum: the figure is the best available and is
    still printed by the statement, but a component was left out of it, so the check says
    *not computable* and names what is absent instead of reporting a residual that is
    really our coverage.

    When the filer's own figures for the absent lines account for the whole residual, the
    detail says so. That is the one thing a reader can act on: it means the difference is
    fully explained by named lines rather than being an unexplained disagreement.
    """
    if stated is None or computed is None:
        return _check(key, label, UNKNOWN, f"{detail} -- not enough stated", about=about)
    work_text = _work_text(
        stated=stated,
        computed=computed,
        parts=work.parts if work else (),
        source=work.source if work else "",
        missing=missing,
        missing_total=missing_total,
    )
    residual = stated - computed
    if missing:
        explained = missing_total is not None and abs(residual - missing_total) <= tolerance(
            stated
        )
        sentence = f"{detail}; missing {', '.join(missing)}"
        if explained:
            sentence += " -- which is exactly those lines, so nothing else is unexplained"
        return _check(
            key,
            label,
            UNKNOWN,
            sentence,
            residual=residual,
            inputs={
                "stated": stated,
                "computed": computed,
                "missing": list(missing),
                "explained": explained,
            },
            work=work_text,
            about=about,
        )
    return _check(
        key,
        label,
        OK if abs(residual) <= tolerance(stated) else IMBALANCE,
        detail,
        residual=residual,
        inputs={"stated": stated, "computed": computed},
        work=work_text,
        about=about,
    )


def _work_from(
    declared: Mapping[str, Declared] | None,
    metric: str,
    ours: float | None,
    keys: Sequence[str],
    metrics: dict[str, Any],
) -> _Work:
    """A subtotal's value and the arithmetic behind it: the filer's, or our own.

    Two summations can stand behind one printed subtotal and they are not the same sum. Where
    the linkbase declared this total, the figure is the sum of the filer's own children and
    the working names those -- which is what makes a residual legible, because it is then the
    lines *the filing* breaks the total into that we do not hold. Otherwise the figure is our
    own key list and the working names the lines we added up.
    """
    entry = (declared or {}).get(metric)
    if entry is not None:
        return _Work(
            total=entry.total,
            parts=tuple(
                Part(label=_label(child, child), contribution=contribution, source=child)
                for child, contribution in entry.parts
            ),
            source="the filer's own declared lines",
            missing=entry.missing,
            missing_total=entry.missing_total,
        )
    return _Work(
        total=ours,
        parts=_components(metrics, *((key, 1.0) for key in keys)),
        source="this project's own list of component lines",
    )


def _computed(
    declared: Mapping[str, Declared] | None, metric: str, ours: float | None
) -> tuple[float | None, tuple[str, ...], float | None, str]:
    """What one subtotal's components add up to, and whose components they are.

    Returns the value, the declared lines left out of it, what the filer tagged those at,
    and a phrase naming the source -- empty for our own key list, because then there is
    nothing to attribute. Shared by the check and the statement so the two cannot show
    different computed columns for the same subtotal.
    """
    entry = (declared or {}).get(metric)
    if entry is None:
        return ours, (), None, ""
    return entry.total, entry.missing, entry.missing_total, "; the filer's own declared lines"


def _agree_computed(
    key: str,
    label: str,
    stated: float | None,
    metric: str,
    ours: float | None,
    detail: str,
    declared: Mapping[str, Declared] | None,
    metrics: dict[str, Any],
    *,
    extra: Sequence[Account] | None = None,
) -> Check:
    """One composition check, from the filer's declared children where we have them.

    The working travels with it: a check that reports "out by 26,710,000" without being able
    to say what it added up is a finding a reader cannot investigate, and the composition is
    exactly where the arithmetic is a decision (the filer's children or ours).
    """
    computed, missing, missing_total, source = _computed(declared, metric, ours)
    work = _work_from(
        declared,
        metric,
        ours,
        tuple(COMPONENT_KEYS.get(metric, ()))
        + subtotal_extra_keys(extra, "balance_sheet", metric),
        metrics,
    )
    return _agree(
        key,
        label,
        stated,
        computed,
        detail + source,
        missing=missing,
        missing_total=missing_total,
        work=work,
        about=metric,
    )


def composition(
    period: FundamentalPeriod,
    *,
    declared: Mapping[str, Declared] | None = None,
    extra: Sequence[Account] | None = None,
) -> list[Check]:
    """Whether the components we hold sum to the totals the filing states.

    A failure here is **not** a defect in the filing or in our extraction; it is the
    size of the accounts this project does not collect. It is a check rather than a
    note because the residual is what tells a reader whether a statement is usable:
    a hundred pounds of "other" is not the same as a third of the balance sheet.

    ``declared`` replaces our own component lists with the filer's, for the subtotals it
    covers: the check then measures the *issuer's* arithmetic instead of this codebase's
    assertion about how a balance sheet is built. That is the stronger claim, and it is
    why the sums differ -- our list is a subset of the taxonomy, the filer's is its own
    balance sheet. A subtotal the filer declares and we cannot complete stays *not
    computable* with the absent lines named; the composition from our own list remains
    the only verdict available for a subtotal no linkbase covers.

    ``extra`` are lines the filer names and the chart does not. They join the same sums the
    printed statement adds them to, from the same table, so the row a reader added a figure
    under is the row whose residual moves.
    """
    metrics = period.metrics or {}
    held = _composition(metrics, extra)
    return [
        _agree_computed(
            "assets_composition",
            "Components sum to stated total assets",
            _stated(metrics, "total_assets"),
            "total_assets",
            held.assets,
            "asset lines we hold against total assets",
            declared,
            metrics,
            extra=extra,
        ),
        _agree_computed(
            "liabilities_composition",
            "Components sum to stated total liabilities",
            _stated(metrics, "total_liabilities"),
            "total_liabilities",
            held.liabilities,
            "liability lines we hold against total liabilities",
            declared,
            metrics,
            extra=extra,
        ),
        _agree_computed(
            "current_assets_composition",
            "Components sum to stated current assets",
            _stated(metrics, "current_assets"),
            "current_assets",
            held.current_assets,
            "current asset lines we hold against current assets",
            declared,
            metrics,
            extra=extra,
        ),
        # The mirror of the line above, and it was missing. Measured 2026-10-07 on
        # `MSFT_US_EQ`: its balance sheet states current liabilities of 168,825 against
        # the 93,326 we hold, and the 75,499 difference is *exactly* two captions --
        # short-term income taxes 2,534 and short-term unearned revenue 72,965. Both
        # were offered by the 10-K extraction and neither could be promoted, because
        # nothing was checking this subtotal. A gap that is never measured is a caption
        # that is never discovered.
        _agree_computed(
            "current_liabilities_composition",
            "Components sum to stated current liabilities",
            _stated(metrics, "current_liabilities"),
            "current_liabilities",
            held.current_liabilities,
            "current liability lines we hold against current liabilities",
            declared,
            metrics,
            extra=extra,
        ),
    ]


def profit_articulation(
    period: FundamentalPeriod, extra: Sequence[Account] | None = None
) -> Check:
    """Whether the lines we hold add up to the profit the filing reports.

    The most consequential composition check, because profit is what every ratio
    downstream divides by. A large residual here means the margins and returns this
    system computes rest on a numerator it cannot reproduce.

    It reads :func:`_profit_cascade`, the same arithmetic the statement prints, so the
    two cannot drift into disagreeing about which lines count -- which would make the
    audit pass a statement that is visibly wrong. ``extra`` travels with it for the same
    reason: a line the reader added that the statement counts and this check did not would
    be exactly that disagreement, one row apart on the same page.
    """
    metrics = period.metrics or {}
    # The cascade's own working travels with the figure, so the health row explains itself the
    # same way the statement line it audits does -- a reader hovering one and then the other
    # must not get two different accounts of the same subtraction.
    work = _profit_cascade(metrics, extra)["net_income"]
    return _agree(
        "profit_articulation",
        "Lines we hold reconcile to reported profit",
        _stated(metrics, "net_income"),
        work.total,
        "income and expense lines against reported profit",
        work=work,
        about="net_income",
    )


def equation_check(period: FundamentalPeriod) -> Check:
    """``assets = liabilities + equity`` on the stated totals.

    The one check whose failure means our extraction is wrong rather than incomplete:
    the filing balances by construction, so a residual here is a defect. It is kept
    separate from composition for exactly that reason -- merging them would let a large
    "we do not collect that account" residual hide a real equation failure.
    """
    ledger = trial_balance(period)
    if not ledger.complete:
        missing = [
            key
            for key in EQUATION_DEBIT + EQUATION_CREDIT
            if key not in {posting.account.key for posting in ledger.postings}
        ]
        return Check(
            key="accounting_equation",
            label="Assets = liabilities + equity",
            status=UNKNOWN,
            detail="the filing does not state " + ", ".join(missing),
        )
    return Check(
        key="accounting_equation",
        label="Assets = liabilities + equity",
        status=OK if ledger.balanced else IMBALANCE,
        detail="stated totals, debits against credits",
        residual=ledger.difference,
        inputs={"debits": ledger.debits, "credits": ledger.credits},
    )


def retained_earnings_rollforward(
    period: FundamentalPeriod, previous: FundamentalPeriod | None
) -> Check:
    """Closing equity against opening plus profit less dividends.

    This is the articulation that makes a balance sheet and a profit and loss one set
    of accounts rather than two tables. It needs the previous period, and it compares
    *retained earnings* rather than total equity because a share issue moves equity
    without touching profit.
    """
    if previous is None:
        return Check(
            key="retained_earnings_rollforward",
            label="Retained earnings roll forward",
            status=UNKNOWN,
            detail="needs the previous period",
        )
    opening = _stated(previous.metrics or {}, "retained_earnings")
    closing = _stated(period.metrics or {}, "retained_earnings")
    profit = _stated(period.metrics or {}, "net_income")
    dividends = _stated(period.metrics or {}, "dividends_paid")
    if opening is None or closing is None or profit is None:
        return Check(
            key="retained_earnings_rollforward",
            label="Retained earnings roll forward",
            status=UNKNOWN,
            detail="needs opening and closing retained earnings and profit",
        )
    expected = opening + profit - (dividends or 0.0)
    residual = closing - expected
    return Check(
        key="retained_earnings_rollforward",
        label="Retained earnings roll forward",
        status=OK if abs(residual) <= tolerance(closing) else IMBALANCE,
        detail="closing against opening plus profit less dividends",
        residual=residual,
        inputs={"opening": opening, "profit": profit, "dividends": dividends or 0.0},
    )


def cash_movement(
    period: FundamentalPeriod, previous: FundamentalPeriod | None
) -> Check:
    """The change in cash against the cash flow lines we hold.

    Expected to disagree, and the disagreement is the useful part: the taxonomy does
    not carry acquisitions, disposals, share issues or borrowings, so the residual is
    the size of the financing and investing activity we cannot see. Reported rather
    than suppressed, so "the cash flow statement is incomplete" is a measured claim
    instead of a caveat nobody can size.
    """
    if previous is None:
        return Check(
            key="cash_movement",
            label="Movement in cash reconciles",
            status=UNKNOWN,
            detail="needs the previous period",
        )
    opening = _stated(previous.metrics or {}, "cash_and_equivalents")
    closing = _stated(period.metrics or {}, "cash_and_equivalents")
    if opening is None or closing is None:
        return Check(
            key="cash_movement",
            label="Movement in cash reconciles",
            status=UNKNOWN,
            detail="needs cash at the start and the end of the period",
        )
    operating = _stated(period.metrics or {}, "operating_cash_flow") or 0.0
    capex = _stated(period.metrics or {}, "capex") or 0.0
    dividends = _stated(period.metrics or {}, "dividends_paid") or 0.0
    explained = operating - capex - dividends
    change = closing - opening
    residual = change - explained
    return Check(
        key="cash_movement",
        label="Movement in cash reconciles",
        status=OK if abs(residual) <= tolerance(closing) else IMBALANCE,
        detail="change in cash against operating, investing and financing lines held",
        residual=residual,
        inputs={"opening": opening, "closing": closing, "explained": explained},
    )


def checks(
    period: FundamentalPeriod,
    previous: FundamentalPeriod | None = None,
    *,
    declared: Mapping[str, Declared] | None = None,
    extra: Sequence[Account] | None = None,
) -> list[Check]:
    """Every accounting-health check for one period, equation first.

    Order is the order a reader should work in: the equation is pass/fail on our own
    extraction, then whether the figures add up, then the two articulations across
    years. ``declared`` is the filer's own arithmetic, which replaces ours in the
    composition checks for the subtotals its linkbase covers; ``extra`` are the lines the
    filer names and the chart does not, which join the same sums the statement adds them to.
    """
    return [
        equation_check(period),
        profit_articulation(period, extra),
        *composition(period, declared=declared, extra=extra),
        retained_earnings_rollforward(period, previous),
        cash_movement(period, previous),
    ]

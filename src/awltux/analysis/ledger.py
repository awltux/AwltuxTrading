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

from collections.abc import Sequence
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
class Line:
    """One printed line: what was stated, what was computed, and which is which."""

    key: str
    label: str
    stated: float | None
    computed: float | None
    side: str
    role: str = "line"

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


def _line(metrics: dict[str, Any], key: str, computed: float | None = None) -> Line:
    """One printed line, pulling its label, side and role from the chart.

    Shared by all three statements, so a line cannot be labelled one way in the profit
    and loss and another in the checks that audit it.
    """
    account = BY_KEY[key]
    return Line(
        key=key,
        label=account.label,
        stated=_stated(metrics, key),
        computed=computed,
        side=account.side,
        role=account.role,
    )


def _profit_cascade(metrics: dict[str, Any]) -> dict[str, float | None]:
    """The four subtotals this project can derive from the lines it holds.

    One cascade rather than one per caller: the profit and loss statement prints these
    and :func:`profit_articulation` audits them against the reported figure, and two
    copies of the same arithmetic would eventually disagree about which lines are
    included -- which is exactly the disagreement the audit exists to detect.

    **Profit before tax is not "operating income less interest".** Interest *income* and
    other non-operating items sit between the two as well, and leaving them out put a
    visible residual on the page for any filer that has them. Measured on `AIT_US_EQ`
    FY2026-06-30: operating income 549,469,000 less interest expense 17,386,000 is
    532,083,000 against a reported profit before tax of 544,274,000 -- a gap of
    12,191,000, which is exactly the interest income (9,448,000) plus other
    non-operating income (2,743,000) the taxonomy did not carry. With them, the three
    lines reconcile to the reported figure to the dollar.
    """
    gross = _subtract(_stated(metrics, "revenue"), _stated(metrics, "cost_of_goods_sold"))
    operating = _subtract(
        gross,
        _stated(metrics, "research_and_development"),
        _stated(metrics, "sga_expense"),
        _stated(metrics, "depreciation_amortisation"),
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
    if additions is None and interest is None:
        non_operating = None
    else:
        non_operating = (additions or 0.0) - (interest or 0.0)
    if operating is None:
        pretax = None
    elif non_operating is None:
        pretax = operating
    else:
        pretax = operating + non_operating
    return {
        "gross_profit": gross,
        "operating_income": operating,
        "pretax_income": pretax,
        "net_income": _subtract(pretax, _stated(metrics, "tax_expense")),
    }


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


def _composition(metrics: dict[str, Any]) -> _Composition:
    return _Composition(
        current_assets=_sum(*(_stated(metrics, key) for key in CURRENT_ASSET_KEYS)),
        non_current_assets=_sum(*(_stated(metrics, key) for key in NON_CURRENT_ASSET_KEYS)),
        current_liabilities=_sum(*(_stated(metrics, key) for key in CURRENT_LIABILITY_KEYS)),
        non_current_liabilities=_sum(
            *(_stated(metrics, key) for key in NON_CURRENT_LIABILITY_KEYS)
        ),
    )


def profit_and_loss(period: FundamentalPeriod) -> Statement:
    """The result for the period, with each stated subtotal checked against its parts.

    ``gross_profit``, ``operating_income``, ``pretax_income`` and ``net_income`` are
    each shown with the arithmetic this project can do from the lines it holds. Where
    the filing states the subtotal too, the two are both printed and the residual is
    the number that matters -- it is the size of the lines we do not extract (other
    operating income, associates, minority interests), and a reader who cannot see it
    cannot tell an extraction gap from a business with unusual economics.
    """
    metrics = period.metrics or {}
    gaps: list[str] = []

    if _stated(metrics, "revenue") is None:
        gaps.append("revenue")
    cascade = _profit_cascade(metrics)

    sections = (
        _section(
            "Revenue",
            [
                _line(metrics, "revenue"),
                _line(metrics, "cost_of_goods_sold"),
                _line(metrics, "gross_profit", cascade["gross_profit"]),
            ],
        ),
        _section(
            "Operating expenses",
            [
                _line(metrics, "research_and_development"),
                _line(metrics, "sga_expense"),
                _line(metrics, "depreciation_amortisation"),
                _line(metrics, "operating_income", cascade["operating_income"]),
            ],
        ),
        _section(
            "Finance and tax",
            [
                _line(metrics, "interest_expense"),
                _line(metrics, "interest_income"),
                _line(metrics, "other_nonoperating_income"),
                _line(metrics, "pretax_income", cascade["pretax_income"]),
                _line(metrics, "tax_expense"),
                _line(metrics, "net_income", cascade["net_income"]),
            ],
        ),
        _memoranda(metrics, INCOME_MEMORANDA),
    )
    return Statement(
        which="profit_and_loss",
        title="Profit & loss",
        sections=sections,
        gaps=tuple(gaps),
        notes=(
            "A stated subtotal and the arithmetic beside it differ by the lines this "
            "project does not extract; the residual is shown rather than absorbed.",
        ),
    )


def balance_sheet(period: FundamentalPeriod) -> Statement:
    """What is owned and owed, with the components checked against the stated totals."""
    metrics = period.metrics or {}
    gaps: list[str] = []
    held = _composition(metrics)

    if _stated(metrics, "total_equity") is None:
        gaps.append("total equity")

    sections = (
        _section(
            "Current assets",
            [
                _line(metrics, "cash_and_equivalents"),
                _line(metrics, "receivables"),
                _line(metrics, "inventory"),
                _line(metrics, "other_current_assets"),
                _line(metrics, "current_assets", held.current_assets),
            ],
        ),
        _section(
            "Non-current assets",
            [
                _line(metrics, "net_ppe"),
                _line(metrics, "operating_lease_assets"),
                _line(metrics, "goodwill"),
                _line(metrics, "intangible_assets"),
                _line(metrics, "other_noncurrent_assets"),
                _line(metrics, "total_assets", held.assets),
            ],
        ),
        _section(
            "Current liabilities",
            [
                _line(metrics, "payables"),
                _line(metrics, "compensation_and_benefits"),
                _line(metrics, "other_current_liabilities"),
                _line(metrics, "short_term_debt"),
                _line(metrics, "current_liabilities", held.current_liabilities),
            ],
        ),
        _section(
            "Non-current liabilities and equity",
            [
                _line(metrics, "long_term_debt"),
                _line(metrics, "other_noncurrent_liabilities"),
                _line(metrics, "total_liabilities", held.liabilities),
                _line(metrics, "total_equity"),
            ],
        ),
        _memoranda(metrics, BALANCE_MEMORANDA),
    )
    return Statement(
        which="balance_sheet",
        title="Balance sheet",
        sections=sections,
        gaps=tuple(gaps),
        trial_balance=trial_balance(period),
        notes=(
            "Total assets, total liabilities and total equity are as stated by the "
            "filing. The component lines above each total are what this project "
            "extracts; the residual against the stated total is not an error.",
        ),
    )


def cash_flow(period: FundamentalPeriod) -> Statement:
    """How cash moved, and what is missing from the movement.

    The statement is a *movement*, so it only reconciles against the previous period's
    cash balance. The reconciliation itself lives in :func:`cash_movement` because it
    needs two periods, and this builds the single-period view.
    """
    metrics = period.metrics or {}
    operating = _stated(metrics, "operating_cash_flow")
    capex = _stated(metrics, "capex")

    return Statement(
        which="cash_flow",
        title="Cash flow",
        sections=(
            _section("Operating", [_line(metrics, "operating_cash_flow")]),
            _section(
                "Investing",
                [
                    _line(metrics, "capex"),
                    _line(metrics, "free_cash_flow", _subtract(operating, capex)),
                ],
            ),
            _section("Financing", [_line(metrics, "dividends_paid")]),
        ),
        notes=(
            "The taxonomy holds operating cash flow, capital expenditure and dividends. "
            "Acquisitions, disposals, share issues and borrowings are not extracted, so "
            "this is not a complete statement of the movement in cash and says so "
            "rather than balancing to a figure it cannot support.",
        ),
    )


def statement(period: FundamentalPeriod, which: str) -> Statement:
    """One statement by name. Raises for a name that is not a statement."""
    builders = {
        "profit_and_loss": profit_and_loss,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
    }
    try:
        build = builders[which]
    except KeyError:
        raise KeyError(f"no statement {which!r}; expected one of {sorted(builders)}") from None
    return build(period)


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

    @property
    def failed(self) -> bool:
        return self.status == IMBALANCE


def _agree(key: str, label: str, stated: float | None, computed: float | None, detail: str) -> Check:
    """A stated total against the parts we hold. Unknown when either side is missing."""
    if stated is None or computed is None:
        return Check(key=key, label=label, status=UNKNOWN, detail=f"{detail} -- not enough stated")
    residual = stated - computed
    status = OK if abs(residual) <= tolerance(stated) else IMBALANCE
    return Check(
        key=key,
        label=label,
        status=status,
        detail=detail,
        residual=residual,
        inputs={"stated": stated, "computed": computed},
    )


def composition(period: FundamentalPeriod) -> list[Check]:
    """Whether the components we hold sum to the totals the filing states.

    A failure here is **not** a defect in the filing or in our extraction; it is the
    size of the accounts this project does not collect. It is a check rather than a
    note because the residual is what tells a reader whether a statement is usable:
    a hundred pounds of "other" is not the same as a third of the balance sheet.
    """
    metrics = period.metrics or {}
    checks = [
        _agree(
            "assets_composition",
            "Components sum to stated total assets",
            _stated(metrics, "total_assets"),
            _composition(metrics).assets,
            "asset lines we hold against total assets",
        ),
        _agree(
            "liabilities_composition",
            "Components sum to stated total liabilities",
            _stated(metrics, "total_liabilities"),
            _composition(metrics).liabilities,
            "liability lines we hold against total liabilities",
        ),
        _agree(
            "current_assets_composition",
            "Components sum to stated current assets",
            _stated(metrics, "current_assets"),
            _composition(metrics).current_assets,
            "current asset lines we hold against current assets",
        ),
        # The mirror of the line above, and it was missing. Measured 2026-10-07 on
        # `MSFT_US_EQ`: its balance sheet states current liabilities of 168,825 against
        # the 93,326 we hold, and the 75,499 difference is *exactly* two captions --
        # short-term income taxes 2,534 and short-term unearned revenue 72,965. Both
        # were offered by the 10-K extraction and neither could be promoted, because
        # nothing was checking this subtotal. A gap that is never measured is a caption
        # that is never discovered.
        _agree(
            "current_liabilities_composition",
            "Components sum to stated current liabilities",
            _stated(metrics, "current_liabilities"),
            _composition(metrics).current_liabilities,
            "current liability lines we hold against current liabilities",
        ),
    ]
    return checks


def profit_articulation(period: FundamentalPeriod) -> Check:
    """Whether the lines we hold add up to the profit the filing reports.

    The most consequential composition check, because profit is what every ratio
    downstream divides by. A large residual here means the margins and returns this
    system computes rest on a numerator it cannot reproduce.

    It reads :func:`_profit_cascade`, the same arithmetic the statement prints, so the
    two cannot drift into disagreeing about which lines count -- which would make the
    audit pass a statement that is visibly wrong.
    """
    metrics = period.metrics or {}
    return _agree(
        "profit_articulation",
        "Lines we hold reconcile to reported profit",
        _stated(metrics, "net_income"),
        _profit_cascade(metrics)["net_income"],
        "income and expense lines against reported profit",
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
    period: FundamentalPeriod, previous: FundamentalPeriod | None = None
) -> list[Check]:
    """Every accounting-health check for one period, equation first.

    Order is the order a reader should work in: the equation is pass/fail on our own
    extraction, then whether the figures add up, then the two articulations across
    years.
    """
    return [
        equation_check(period),
        profit_articulation(period),
        *composition(period),
        retained_earnings_rollforward(period, previous),
        cash_movement(period, previous),
    ]

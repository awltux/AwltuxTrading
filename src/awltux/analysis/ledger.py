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

from awltux.analysis.layout import (  # noqa: F401  (re-exported)
    BY_KEY,
    CHART,
    CREDIT,
    DEBIT,
    STATEMENTS,
    SUBTOTAL_GROUPS,
    Account,
    Layout,
    Placement,
)
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


def _magnitude(key: str, value: float) -> float:
    """A stored figure read the way the line's weight expects it.

    **A line the chart marks ``signed`` keeps its sign; every other chart line's figure is a
    magnitude.** The flag says exactly this -- *"True when a negative value is an ordinary reading
    rather than a data error"* -- so `other_nonoperating_income` at -1,197,000 is a loss and stays
    one, while a debit line like `sga_expense` is an amount to be deducted and the weight does the
    deducting. Filings print expenses in brackets, the picker keeps that sign because it is what
    the page says, and subtracting -64,410,000 would add the expense back. Reported 2026-10-10:
    *"the account display reads the correct sign, but the 'out by X' calculation is still using
    the positive sign."*

    A line the *filer* names is not in the chart and has no flag to read: its figure is the
    reader's statement of the amount, sign and all, and it is read as it stands.
    """
    account = BY_KEY.get(key)
    if account is None or account.signed:
        return value
    return abs(value)


def _sized(metrics: dict[str, Any], key: str) -> float | None:
    """A stored chart line's figure as its own weight expects it -- see :func:`_magnitude`.

    One name for the pair, because every sum in the ledger has to read a figure the same way the
    working beside it does: two of these in one expression is how a total and its explanation come
    apart.
    """
    value = _stated(metrics, key)
    return None if value is None else _magnitude(key, value)


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


def _line(
    metrics: dict[str, Any],
    placement: Placement,
    computed: float | None = None,
    work: _Work | None = None,
) -> Line:
    """One printed line, pulling its caption, side and role from its *placement*.

    Shared by all three statements, so a line cannot be labelled one way in the profit and loss
    and another in the checks that audit it. ``work`` is the arithmetic behind ``computed`` -- see
    :class:`_Work` -- and is what the page shows on hover.

    The placement rather than the key, because where a line is printed and what it is counted in
    are no longer properties of the chart: see :mod:`awltux.analysis.layout`.
    """
    return Line(
        key=placement.key,
        label=placement.label,
        stated=_stated(metrics, placement.key),
        computed=computed,
        side=placement.side,
        role=placement.role,
        parts=work.parts if work else (),
        parts_source=work.source if work else "",
        missing=work.missing if work else (),
        missing_total=work.missing_total if work else None,
    )


def _worked_line(metrics: dict[str, Any], placement: Placement, work: _Work) -> Line:
    """A line whose computed figure and whose arithmetic arrive together."""
    return _line(metrics, placement, work.total, work)


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


def _contribution(metrics: dict[str, Any], placement: Placement) -> float | None:
    """What one line contributes to the subtotal it feeds, or ``None`` when it states nothing.

    Three rules, and the difference between them is what a line *is*:

    * **A chart line** contributes a magnitude on its own side -- ``+`` for a credit, ``-`` for a
      debit -- unless the chart marks it ``signed``, in which case its figure is read as it stands
      because a negative is an ordinary reading (`other_nonoperating_income`). That is the
      ``_magnitude`` rule the sums already used, now driven by the *placement's* side so a line the
      reader moved into a heading is counted the way that heading reads.
    * **A line the chart does not carry** -- learned from a filing, or taken from a source's own
      caption -- is the reader's statement of the amount, sign and all, and is never re-signed.
      The form says so where they enter it, and flipping the sign of a figure somebody typed in
      order to fix a residual would be the page arguing with its own instruction.
    * An absent figure contributes nothing, and is left out of the sum rather than treated as
      zero: a line printed at 0 claims the source stated nothing there, which is a different fact
      from our not holding it.
    """
    value = _stated(metrics, placement.key)
    if value is None:
        return None
    if placement.key not in BY_KEY:
        return value
    if placement.signed:
        return value
    magnitude = abs(value)
    return magnitude if placement.side == CREDIT else -magnitude


def _part(placement: Placement, contribution: float) -> Part:
    return Part(
        label=placement.label, contribution=contribution, source=placement.key
    )


def _contributions(
    metrics: dict[str, Any], placements: Sequence[Placement]
) -> tuple[tuple[Placement, float], ...]:
    """The lines of one subtotal that state a figure, with what each contributes."""
    out: list[tuple[Placement, float]] = []
    for placement in placements:
        contribution = _contribution(metrics, placement)
        if contribution is not None:
            out.append((placement, contribution))
    return tuple(out)


#: The profit and loss cascade, as (stage, the stage it is added to). Ordered, because each stage
#: is built on the one before it: gross profit feeds operating income, which feeds profit before
#: tax, which feeds the profit for the period.
CASCADE: tuple[tuple[str, str | None], ...] = (
    ("gross_profit", None),
    ("operating_income", "gross_profit"),
    ("pretax_income", "operating_income"),
    ("net_income", "pretax_income"),
)


def _profit_cascade(
    metrics: dict[str, Any], layout: Layout | None = None
) -> dict[str, _Work]:
    """The four subtotals this project can derive from the lines it holds.

    One cascade rather than one per caller: the profit and loss statement prints these
    and :func:`profit_articulation` audits them against the reported figure, and two
    copies of the same arithmetic would eventually disagree about which lines are
    included -- which is exactly the disagreement the audit exists to detect.

    **Each subtotal comes back with the arithmetic that produced it**, in the same object,
    because a page that can show a residual but not how the figure beside it was reached is
    one a reader cannot investigate.

    **Which lines are in a stage comes from the layout**, not from a key list here: a line's
    ``feeds`` is what decides, so a line the reader moved out of "Operating expenses" stops
    being deducted there and a line moved in starts -- without a second table to keep true. The
    chart's own feed for each line is :data:`layout.SECTION_FEEDS`, reproduce-the-old-numbers
    exact.

    **Profit before tax is not "operating income less interest".** Interest *income* and
    other non-operating items sit between the two as well, and leaving them out put a
    visible residual on the page for any filer that has them. Measured on `AIT_US_EQ`
    FY2026-06-30: operating income 549,469,000 less interest expense 17,386,000 is
    532,083,000 against a reported profit before tax of 544,274,000 -- a gap of
    12,191,000, which is exactly the interest income (9,448,000) plus other
    non-operating income (2,743,000) the taxonomy did not carry. With them, the three
    lines reconcile to the reported figure to the dollar.
    """
    layout = layout or Layout.default()
    totals: dict[str, float | None] = {}
    works: dict[str, _Work] = {}
    for stage, parent in CASCADE:
        components = layout.components("profit_and_loss", stage)
        total, parts = _stage(
            _contributions(metrics, components),
            parent=parent,
            parent_total=totals.get(parent) if parent else None,
            anchor=components[0] if components else None,
        )
        totals[stage] = total
        works[stage] = _Work(total=total, parts=parts)
    return works


def _stage(
    entries: Sequence[tuple[Placement, float]],
    *,
    parent: str | None,
    parent_total: float | None,
    anchor: Placement | None,
) -> tuple[float | None, tuple[Part, ...]]:
    """One stage of the cascade from its own lines, and the arithmetic that produced it.

    Two shapes, and the difference is which end the stage is built from:

    * **A stage with a parent** starts at the parent's figure. If the parent is not computable the
      stage is not either -- a line put under "Finance and tax" cannot make profit before tax
      computable when operating income is not, and inventing a total out of the part of the
      cascade that happens to be present would make the residual lie about what it measures.
      The **components are still listed** in the working, because "these are the lines, and the
      total above them is missing" is what a reader needs to see.
    * **The first stage** is built from its own first line -- ``anchor``, which is revenue by the
      chart's order. A missing anchor leaves the stage uncomputable, which is the behaviour
      `_subtract` had and the reason a cost of sales with no revenue does not print a negative
      gross profit that reads like a loss.
    """
    parts = tuple(_part(placement, contribution) for placement, contribution in entries)
    if parent is None:
        if not entries or anchor is None or entries[0][0].key != anchor.key:
            return None, parts
        total = entries[0][1] + sum(contribution for _, contribution in entries[1:])
        return total, parts
    if parent_total is None:
        return None, parts
    return (
        parent_total + sum(contribution for _, contribution in entries),
        (Part(label=_label(parent), contribution=parent_total, source=parent), *parts),
    )


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


def _composition(
    metrics: dict[str, Any], layout: Layout | None = None
) -> _Composition:
    """What the component lines we hold add up to, including any the filer named by hand.

    The four sums are driven by the layout: a component joins the group its ``feeds`` names, and
    :data:`layout.SECTION_FEEDS` is the one place that decides which for a line nobody moved -- so
    the printed subtotal's arithmetic and the check that audits it cannot disagree about what was
    included, and a line moved from one side of the balance sheet to the other moves with it.

    A signed line keeps its sign and every other figure is a magnitude, exactly as
    :func:`_magnitude` documents: the balance sheet's groups are each on one side already, so the
    sign is the group's and not the line's.
    """
    layout = layout or Layout.default()

    def group(name: str) -> float | None:
        return _sum(
            *(_sized(metrics, placement.key) for placement in layout.components("balance_sheet", name))
        )

    return _Composition(
        current_assets=group("current_assets"),
        non_current_assets=group("non_current_assets"),
        current_liabilities=group("current_liabilities"),
        non_current_liabilities=group("non_current_liabilities"),
    )


def _group_parts(
    metrics: dict[str, Any], layout: Layout, statement: str, groups: Sequence[str]
) -> tuple[Part, ...]:
    """The arithmetic behind a subtotal summed from one or more component groups.

    Built from the same placements that produced the figure, so the working a reader hovers cannot
    list a different set of lines from the one the total was computed from.
    """
    parts: list[Part] = []
    for group in groups:
        for placement in layout.components(statement, group):
            contribution = _sized(metrics, placement.key)
            if contribution is not None:
                parts.append(_part(placement, contribution))
    return tuple(parts)


def _sections(
    metrics: dict[str, Any],
    layout: Layout,
    statement: str,
    works: Mapping[str, _Work],
) -> tuple[Section, ...]:
    """A statement's headings and their lines, with each subtotal's figure and working attached.

    The headings, their order and which lines sit under each are the layout's; the figures are the
    cascade's or the composition's. That split is the point of the module: a reader who adds a
    heading or moves a line changes the layout and the figures follow, and no builder carries a
    second copy of the structure.
    """
    sections: list[Section] = []
    for title in layout.sections(statement):
        lines: list[Line] = []
        for placement in layout.lines(statement, title):
            work = works.get(placement.key) if placement.role == "subtotal" else None
            lines.append(_line(metrics, placement, work.total if work else None, work))
        sections.append(_section(title, lines))
    return tuple(sections)


def uncounted_note(layout: Layout | None, statement: str) -> str | None:
    """The sentence a statement adds when a line the filer names is counted nowhere, or ``None``.

    One function for all three statements, because the failure it reports is the same on each: a
    figure that appears in the accounts and moves no total is a figure a reader will assume is
    counted.
    """
    uncounted = (layout or Layout.default()).uncounted(statement)
    if not uncounted:
        return None
    headings = "”, “".join(sorted({placement.section for placement in uncounted}))
    return (
        f"Lines read from the filing under “{headings}” are printed there and added to no "
        "total: this page computes no sum of that heading's lines, and which total a figure "
        "belongs to is not something it will guess. A line put under a heading whose lines are "
        "summed is added to it."
    )


def profit_and_loss(
    period: FundamentalPeriod,
    *,
    declared: Mapping[str, Declared] | None = None,
    layout: Layout | None = None,
) -> Statement:
    """The result for the period, with each stated subtotal checked against its parts.

    ``gross_profit``, ``operating_income``, ``pretax_income`` and ``net_income`` are
    each shown with the arithmetic this project can do from the lines it holds. Where
    the filing states the subtotal too, the two are both printed and the residual is
    the number that matters -- it is the size of the lines we do not extract, and a
    reader who cannot see it cannot tell an extraction gap from a business with unusual
    economics.

    ``declared`` is unused here and kept for the signature every builder shares: the profit
    cascade's stages are a formula, and the linkbase declares the balance sheet's totals rather
    than these. It is documented rather than removed because a caller that hands the same three
    arguments to :func:`statement` must not have to know which statement uses which.

    Which lines each section holds, and which subtotal a line feeds, is the layout's -- so a line
    a reader moved out of "Operating expenses" is no longer deducted at operating income, and a
    caption they added there is.
    """
    layout = layout or Layout.default()
    metrics = period.metrics or {}
    gaps: list[str] = []

    if _stated(metrics, "revenue") is None:
        gaps.append("revenue")

    notes = [
        "A stated subtotal and the arithmetic beside it differ by the lines this "
        "project does not extract; the residual is shown rather than absorbed.",
    ]
    uncounted = uncounted_note(layout, "profit_and_loss")
    if uncounted:
        notes.append(uncounted)
    return Statement(
        which="profit_and_loss",
        title="Profit & loss",
        sections=_sections(metrics, layout, "profit_and_loss", _profit_cascade(metrics, layout)),
        gaps=tuple(gaps),
        notes=tuple(notes),
    )


def balance_sheet(
    period: FundamentalPeriod,
    *,
    declared: Mapping[str, Declared] | None = None,
    layout: Layout | None = None,
) -> Statement:
    """What is owned and owed, with the components checked against the stated totals.

    ``declared`` puts the filer's own children behind the four subtotals where its
    calculation linkbase has been read, so the residual printed beside a total is the
    lines *the filing* breaks it into that this project does not hold -- which for a
    bucket line like `other_current_assets` is a very different figure from the residual
    against our own key list.

    Components are grouped by the layout, so a line the reader moved to the other side of the
    balance sheet is summed there and the totals it feeds follow.
    """
    layout = layout or Layout.default()
    metrics = period.metrics or {}
    gaps: list[str] = []
    held = _composition(metrics, layout)

    def sum_of(metric: str, ours: float | None) -> _Work:
        """The filer's sum for this subtotal where it declares one, else our own groups.

        The groups travel from :data:`layout.SUBTOTAL_GROUPS` rather than being written out here,
        which is what makes the subtotal the statement prints and the sum the check audits the same
        sum by construction.
        """
        return _work_from(
            declared,
            metric,
            ours,
            layout,
            "balance_sheet",
            SUBTOTAL_GROUPS[metric],
            metrics,
        )

    figures = {
        "current_assets": sum_of("current_assets", held.current_assets),
        "total_assets": sum_of("total_assets", held.assets),
        "current_liabilities": sum_of("current_liabilities", held.current_liabilities),
        "total_liabilities": sum_of("total_liabilities", held.liabilities),
    }

    if _stated(metrics, "total_equity") is None:
        gaps.append("total equity")

    notes = [
        "Total assets, total liabilities and total equity are as stated by the "
        "filing. The component lines above each total are what this project "
        "extracts; the residual against the stated total is not an error.",
    ]
    uncounted = uncounted_note(layout, "balance_sheet")
    if uncounted:
        notes.append(uncounted)
    return Statement(
        which="balance_sheet",
        title="Balance sheet",
        sections=_sections(metrics, layout, "balance_sheet", figures),
        gaps=tuple(gaps),
        trial_balance=trial_balance(period),
        notes=tuple(notes),
    )


def cash_flow(
    period: FundamentalPeriod,
    *,
    declared: Mapping[str, Declared] | None = None,
    layout: Layout | None = None,
) -> Statement:
    """How cash moved, and what is missing from the movement.

    The statement is a *movement*, so it only reconciles against the previous period's
    cash balance. The reconciliation itself lives in :func:`cash_movement` because it
    needs two periods, and this builds the single-period view.

    Free cash flow is the one subtotal here that this project computes, and its arithmetic is a
    formula -- operating cash flow less capital expenditure -- rather than a sum of the lines a
    group feeds. That is why its components are written out where the balance sheet's are asked of
    the layout: a cash flow line's *side* is the counter-entry against cash, so it does not say
    which way the movement runs, and reading the side as the direction would add a capex outflow
    back on.
    """
    layout = layout or Layout.default()
    metrics = period.metrics or {}
    operating = _sized(metrics, "operating_cash_flow")
    capex = _sized(metrics, "capex")
    free = _subtract(operating, capex)
    figures = {
        "free_cash_flow": _Work(
            total=free,
            parts=tuple(
                part
                for part in (
                    _component_part("operating_cash_flow", operating, 1.0),
                    _component_part("capex", capex, -1.0),
                )
                if part is not None
            ),
            source="this project's own list of component lines",
        )
    }

    notes = [
        "The taxonomy holds operating cash flow, capital expenditure and dividends. "
        "Acquisitions, disposals, share issues and borrowings are not extracted, so "
        "this is not a complete statement of the movement in cash and says so "
        "rather than balancing to a figure it cannot support.",
    ]
    uncounted = uncounted_note(layout, "cash_flow")
    if uncounted:
        notes.append(uncounted)

    return Statement(
        which="cash_flow",
        title="Cash flow",
        sections=_sections(metrics, layout, "cash_flow", figures),
        notes=tuple(notes),
    )


def _component_part(key: str, value: float | None, weight: float) -> Part | None:
    """One component of a formula-driven subtotal, or nothing when the figure is absent."""
    if value is None:
        return None
    return Part(label=_label(key), contribution=weight * value, source=key)


def statement(
    period: FundamentalPeriod,
    which: str,
    *,
    declared: Mapping[str, Declared] | None = None,
    layout: Layout | None = None,
) -> Statement:
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
    return build(period, declared=declared, layout=layout)

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
    layout: Layout,
    statement: str,
    groups: Sequence[str],
    metrics: dict[str, Any],
) -> _Work:
    """A subtotal's value and the arithmetic behind it: the filer's, or our own.

    Two summations can stand behind one printed subtotal and they are not the same sum. Where
    the linkbase declared this total, the figure is the sum of the filer's own children and
    the working names those -- which is what makes a residual legible, because it is then the
    lines *the filing* breaks the total into that we do not hold. Otherwise the figure is the
    sum of the component groups the layout assigns this subtotal, and the working names those
    lines.
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
        parts=_group_parts(metrics, layout, statement, groups),
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
    layout: Layout,
    groups: Sequence[str],
) -> Check:
    """One composition check, from the filer's declared children where we have them.

    The working travels with it: a check that reports "out by 26,710,000" without being able
    to say what it added up is a finding a reader cannot investigate, and the composition is
    exactly where the arithmetic is a decision (the filer's children or ours).
    """
    computed, missing, missing_total, source = _computed(declared, metric, ours)
    work = _work_from(
        declared, metric, ours, layout, "balance_sheet", groups, metrics
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
    layout: Layout | None = None,
) -> list[Check]:
    """Whether the components we hold sum to the totals the filing states.

    A failure here is **not** a defect in the filing or in our extraction; it is the
    size of the accounts this project does not collect. It is a check rather than a
    note because the residual is what tells a reader whether a statement is usable:
    a hundred pounds of "other" is not the same as a third of the balance sheet.

    ``declared`` replaces our own component groups with the filer's, for the subtotals it
    covers: the check then measures the *issuer's* arithmetic instead of this codebase's
    assertion about how a balance sheet is built. That is the stronger claim, and it is
    why the sums differ -- our list is a subset of the taxonomy, the filer's is its own
    balance sheet. A subtotal the filer declares and we cannot complete stays *not
    computable* with the absent lines named; the composition from our own groups remains
    the only verdict available for a subtotal no linkbase covers.

    ``layout`` puts the lines where the reader put them, so a component moved from one side of
    the balance sheet to the other is summed there and the row whose residual moves is the row
    they moved it under -- the printed statement and this check read the same groups.
    """
    layout = layout or Layout.default()
    metrics = period.metrics or {}
    held = _composition(metrics, layout)
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
            layout=layout,
            groups=SUBTOTAL_GROUPS["total_assets"],
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
            layout=layout,
            groups=SUBTOTAL_GROUPS["total_liabilities"],
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
            layout=layout,
            groups=SUBTOTAL_GROUPS["current_assets"],
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
            layout=layout,
            groups=SUBTOTAL_GROUPS["current_liabilities"],
        ),
    ]


def profit_articulation(
    period: FundamentalPeriod, layout: Layout | None = None
) -> Check:
    """Whether the lines we hold add up to the profit the filing reports.

    The most consequential composition check, because profit is what every ratio
    downstream divides by. A large residual here means the margins and returns this
    system computes rest on a numerator it cannot reproduce.

    It reads :func:`_profit_cascade`, the same arithmetic the statement prints, so the
    two cannot drift into disagreeing about which lines count -- which would make the
    audit pass a statement that is visibly wrong. ``layout`` travels with it for the same
    reason: a line the reader moved that the statement counts differently and this check
    did not would be exactly that disagreement, one row apart on the same page.
    """
    metrics = period.metrics or {}
    # The cascade's own working travels with the figure, so the health row explains itself the
    # same way the statement line it audits does -- a reader hovering one and then the other
    # must not get two different accounts of the same subtraction.
    work = _profit_cascade(metrics, layout)["net_income"]
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
    layout: Layout | None = None,
) -> list[Check]:
    """Every accounting-health check for one period, equation first.

    Order is the order a reader should work in: the equation is pass/fail on our own
    extraction, then whether the figures add up, then the two articulations across
    years. ``declared`` is the filer's own arithmetic, which replaces ours in the
    composition checks for the subtotals its linkbase covers; ``layout`` is where the reader
    put each line, which joins the same sums the printed statement adds it to.
    """
    return [
        equation_check(period),
        profit_articulation(period, layout),
        *composition(period, declared=declared, layout=layout),
        retained_earnings_rollforward(period, previous),
        cash_movement(period, previous),
    ]

"""Check our subtotals against the filer's declared ones, not against our own.

``analysis/ledger.py`` decides how a balance sheet is built and then checks whether the
figures we hold add up the way *we* say they should. The filer states the same thing
machine-readably in its calculation linkbase, so the same figures can be checked
against the issuer's own arithmetic -- which is a different and stronger claim.

**The distinction this module exists to make.** A component check that fails has three
possible causes, and one wording currently reports all three identically:

1. **The filer declares lines we do not hold.** DFPH's balance sheet declares six
   children of ``us-gaap:Assets``; the stored period holds three of them. Nothing is
   wrong with the filer's figures or with the arithmetic -- our coverage is short, and
   the honest verdict is *not computable* plus the names of the lines we are missing.
2. **The filer declares a line our vocabulary has no name for.** A custom extension tag
   (``toi_DerivativeWarrantLiabilitiesNoncurrent``) or a subtotal we do not model
   (``us-gaap:OperatingCostsAndExpenses``). Also not computable, but the fix is
   different: the vocabulary, not the extraction.
3. **We hold every line the filer declares, and it still does not sum.** A real
   contradiction between the filer's own arithmetic and the figures we read, pointing
   at a tag we are misreading -- a restatement, a different context, a concept whose
   definition moved. This is the only case that should read as a failure.

Measured re-checking the queued failures: DFPH's equation itself passes
(180,376,000 liabilities less 15,720,000 equity reconciles to 164,656,000 assets), and
what fails is composition -- in case 1. So the marker that reads "components do not sum"
is reporting our own coverage as if it were the filer's error.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from awltux.analysis.ledger import (
    IMBALANCE,
    OK,
    UNKNOWN,
    Check,
    Declared,
    tolerance,
)
from awltux.db import FundamentalPeriod
from awltux.ingest.linkbase import Calculation, Linkbase
from awltux.ingest.xbrl import TAG_MAP
from awltux.metrics import value_of

#: Every tag name our vocabulary knows, **without its taxonomy prefix**. `TAG_MAP` is
#: deliberately taxonomy-agnostic -- a 20-F filer's ``ifrs-full:Revenue`` and a 10-K
#: filer's ``us-gaap:Revenue`` are the same money and map to the same metric -- so the
#: prefix is not part of what we can name and cannot be part of the membership test.
#: Derived from `TAG_MAP` rather than kept by hand: a second list is a second thing to
#: fall behind.
VOCABULARY: frozenset[str] = frozenset(tag for spec in TAG_MAP for tag in spec.tags)

#: How many unheld lines to name in a check's detail before eliding. A filer that breaks
#: assets into fourteen lines produces a sentence nobody reads; the count and a few
#: names are what a reader acts on.
NAMED_LIMIT = 4


def knows(tag: str) -> bool:
    """Whether any canonical metric could hold ``tag``, ignoring its taxonomy.

    The distinction this draws is the one that decides the fix: a declared line we have
    no metric for needs the vocabulary extended, and no amount of re-extraction will
    produce it, while a line we do have a metric for and no figure for is a gap in what
    the period carries.
    """
    return tag.split(":", 1)[-1] in VOCABULARY


#: How deep a declaration is walked before the walk is abandoned. The trees are the
#: filing's, so a cycle would be its bug rather than ours -- and a page that cannot finish
#: rendering is a worse outcome than a check that reports what it managed.
MAX_DEPTH = 6


def leaves(
    linkbase: Linkbase, concept: str, *, role: str | None = None, _depth: int = 0
) -> tuple[tuple[str, float], ...]:
    """Every bottom-level declared child of ``concept``, with its weight on the path.

    **To the leaves, not one level down.** ``Assets`` is declared as ``AssetsCurrent`` and
    ``AssetsNoncurrent`` -- subtotals the filer states and this project has no metric for
    -- so a one-level sum reaches two concepts we cannot value and stops. The money is at
    the bottom: cash, receivables, PP&E, deposits. Weights multiply along the path because
    a subtotal can be declared with a negative weight (treasury stock is the case
    `test_linkbase.py` pins), and a leaf found through one has to carry that sign.

    **One role only, and that is not a detail.** Measured on `DAC_US_EQ`: its balance
    sheet declares ``OtherAssetsCurrent`` as a *leaf* of ``AssetsCurrent``, while a
    footnote role declares ``OtherAssetsCurrent`` as a *parent* of four further captions.
    Walking every role together therefore expands a line the statement treats as one, and
    reports the footnote's four children as lines we are missing -- none of which is true
    of the balance sheet the check is about. A footnote decomposing a caption is a
    different tree, so the walk stays inside the role that declares the subtotal.

    A concept that is its own descendant is dropped rather than followed, which together
    with :data:`MAX_DEPTH` is the only protection a filer's malformed tree gets.
    """
    if _depth >= MAX_DEPTH:
        return ()
    out: list[tuple[str, float]] = []
    in_role = {spec.parent for spec in linkbase.calculations if role is None or spec.role == role}
    for spec in linkbase.for_parent(concept):
        if role is not None and spec.role != role:
            continue
        for tag, weight in spec.children:
            if tag in in_role and tag != concept:
                out.extend(
                    (leaf, weight * nested)
                    for leaf, nested in leaves(linkbase, tag, role=role, _depth=_depth + 1)
                )
            else:
                out.append((tag, weight))
    return tuple(out)


def declared_sums(
    period: FundamentalPeriod,
    linkbase: Linkbase,
    *,
    figures: Mapping[str, float] | None = None,
) -> dict[str, Declared]:
    """What each declared subtotal adds up to, from the figures this project holds.

    The arithmetic the filer publishes, applied to our numbers: for every subtotal in
    :data:`_SUBTOTALS` that its balance sheet declares, the sum of the declared leaves we
    hold. The result is handed to :mod:`awltux.analysis.ledger`, which prints it as the
    computed column and checks it against the stated total -- so "out by" means the lines
    the *filing* breaks the total into that we do not hold, rather than the size of our
    own vocabulary.

    A leaf whose metric is a sum of several tags is taken once, exactly as
    :func:`_reading` does: `other_current_assets` is one line to us and two to `DAC_US_EQ`,
    and counting it per tag would double the money.

    ``missing_total`` is left unset unless the filer tagged **every** absent line, because
    a partial price is the most misleading number in this module: it would read as an
    explanation of the residual while leaving part of it unaccounted for.
    """
    index = tag_index(period)
    sums = summed_members(period)
    metrics = period.metrics or {}
    prices = dict(figures or {})

    out: dict[str, Declared] = {}
    for metric, concept in _SUBTOTALS.items():
        specs = linkbase.for_parent(concept)
        if not specs:
            continue
        # The role that declares this subtotal, which is the statement to walk. A subtotal
        # declared in several roles uses the first, in the filing's order.
        declared = leaves(linkbase, concept, role=specs[0].role)
        if not declared:
            continue
        total = 0.0
        missing: list[str] = []
        absent_total: float | None = 0.0
        counted: set[str] = set()
        for tag, weight in declared:
            child_metric = index.get(tag)
            value = value_of(metrics, child_metric) if child_metric else None
            if value is None:
                # Not held. Named whether or not we have a price for it: the name is what
                # says which line to look at, and the price is what says whether it is the
                # whole of the residual.
                missing.append(_priced_name(tag, prices))
                if tag in prices and absent_total is not None:
                    absent_total += prices[tag] * weight
                else:
                    absent_total = None
                continue
            members = sums.get(child_metric or "")
            if members is not None:
                if child_metric in counted:
                    continue
                counted.add(child_metric)
            total += weight * value
        out[metric] = Declared(
            total=total if total or not missing else None,
            missing=tuple(missing),
            # Only when the filer tagged every absent line: a partial price would look
            # like an explanation while leaving part of the residual unexplained.
            missing_total=absent_total if missing else None,
        )
    return out


def _priced_name(tag: str, figures: Mapping[str, float]) -> str:
    """``us-gaap:PrepaidExpenseCurrent (2,093,000)`` when the filer's figure is known."""
    value = figures.get(tag)
    return f"{tag} ({value:,.0f})" if value is not None else tag


#: Which of our subtotals each declared concept is. The filer names `us-gaap:Assets`;
#: this codebase calls the same figure ``total_assets`` -- and only the four *composition*
#: subtotals are here, because those are the ones the ledger checks against components.
_SUBTOTALS: Mapping[str, str] = {
    "total_assets": "us-gaap:Assets",
    "total_liabilities": "us-gaap:Liabilities",
    "current_assets": "us-gaap:AssetsCurrent",
    "current_liabilities": "us-gaap:LiabilitiesCurrent",
}


@dataclass(frozen=True, slots=True)
class Declaration:
    """One declared subtotal, measured against the figures we hold."""

    role: str
    parent: str
    #: The canonical metric the parent's figure is held under.
    metric: str
    #: Our figure for the parent.
    stated: float
    #: The filer's children summed from our figures -- ``None`` unless every declared
    #: child had one, because a partial sum is not a smaller total, it is a different
    #: number.
    declared_sum: float | None
    #: Declared children we do have a figure for.
    held: tuple[str, ...] = ()
    #: Declared children our vocabulary names but this period has no figure for.
    absent: tuple[str, ...] = ()
    #: Declared children our vocabulary does not name at all.
    unmodelled: tuple[str, ...] = ()
    #: Declared children we hold *inside a line that is itself a sum of captions*, so the
    #: figure we hold covers this child and others and cannot be attributed to one.
    #: `other_current_assets` is the case that produced this: it is
    #: ``OtherAssetsCurrent+OtherReceivablesNetCurrent`` for `DAC_US_EQ`, and the filer
    #: declares both as children of `AssetsCurrent`. Counting the line twice would double
    #: count the money, and counting it zero times would understate the coverage -- so it
    #: is counted once, and anything the sum cannot cover is named here.
    pooled: tuple[str, ...] = ()
    #: What the filer tagged each child at, from its own companyfacts payload, for the
    #: children we do not hold -- the figure that turns "we have no metric for
    #: PrepaidExpenseCurrent" into "...and it is 2,093,000, which is the size of the gap".
    figures: Mapping[str, float] = field(default_factory=dict)
    residual: float | None = None

    @property
    def complete(self) -> bool:
        """Whether every declared child had a figure, so the sum means something."""
        return not self.absent and not self.unmodelled and not self.pooled

    @property
    def status(self) -> str:
        if not self.complete:
            return UNKNOWN
        return OK if abs(self.residual or 0.0) <= tolerance(self.stated) else IMBALANCE

    def as_check(self, children: int) -> Check:
        """The verdict, in the shape the accounts page already renders."""
        return Check(
            key=f"filer_arithmetic.{self.metric}",
            label=f"Declared: {self.parent}",
            status=self.status,
            detail=self.detail(children),
            residual=self.residual,
            inputs={
                "stated": self.stated,
                "declared_sum": self.declared_sum,
                "held": list(self.held),
                "absent": list(self.absent),
                "unmodelled": list(self.unmodelled),
                "pooled": list(self.pooled),
                "role": self.role,
            },
        )

    def detail(self, declared: int) -> str:
        if not self.complete:
            parts = [f"the filer declares {declared} lines here and we hold {len(self.held)}"]
            if self.unmodelled:
                parts.append(f"no metric for {_priced(self.unmodelled, self.figures)}")
            if self.absent:
                parts.append(f"no figure for {_priced(self.absent, self.figures)}")
            if self.pooled:
                parts.append(
                    f"{_named(self.pooled)} is held inside a line that sums several "
                    "captions, so it cannot be counted on its own here"
                )
            return "; ".join(parts) + " -- not computable from what we hold"
        return (
            f"the filer's own {declared} lines sum to {self.declared_sum:,.0f} "
            f"against a stated {self.stated:,.0f}"
        )


def _priced(tags: Iterable[str], figures: Mapping[str, float]) -> str:
    """The names, each with the filer's own figure where one was read.

    The figure is what makes a missing line actionable: "no metric for
    PrepaidExpenseCurrent" says what to build, and "2,093,000" says whether it is the
    whole of the residual or a footnote to it.
    """
    listed = list(tags)
    shown = [
        f"{tag} ({figures[tag]:,.0f})" if tag in figures else tag for tag in listed[:NAMED_LIMIT]
    ]
    if len(listed) > NAMED_LIMIT:
        return f"{', '.join(shown)} and {len(listed) - NAMED_LIMIT} more"
    return ", ".join(shown)


def _named(tags: Iterable[str]) -> str:
    listed = list(tags)
    shown = ", ".join(listed[:NAMED_LIMIT])
    if len(listed) > NAMED_LIMIT:
        return f"{shown} and {len(listed) - NAMED_LIMIT} more"
    return shown


def _members(span: str) -> tuple[str, ...]:
    """The tags a provenance span names, qualified the way ``metric_sources`` writes them.

    **The taxonomy is written once.** A metric supplied by one tag records
    ``us-gaap:OtherAssetsCurrent``; a metric that is the *sum* of several records
    ``us-gaap:OtherAssetsCurrent+OtherReceivablesNetCurrent`` -- the prefix on the first
    and bare names after it, which is how ``ExtractedFact.as_source`` builds a joined tag
    and how ``total_debt`` has always been written. A reader that splits on ``+`` and
    compares the pieces to locator tags therefore misses every member but the first, which
    is what made the live page call two captions we hold "no metric for". So a member
    without a prefix takes the first one's.

    A span that is prose rather than a tag -- ``"Other current assets 48,594"``, which is
    what the model-reading path stores -- stays as it is: it matches no locator, and
    inventing a prefix for it would only make it look like one.
    """
    parts = [part.strip() for part in span.split("+") if part.strip()]
    if not parts:
        return ()
    taxonomy = parts[0].split(":", 1)[0] if ":" in parts[0] else ""
    if not taxonomy:
        return tuple(parts)
    return tuple(part if ":" in part else f"{taxonomy}:{part}" for part in parts)


def accession(period: FundamentalPeriod) -> str:
    """The accession this period's figures were filed under, or ``""``.

    Read from the provenance rather than from ``filing_id``: an XBRL period is written
    straight from the companyfacts payload and never linked to a ``Filing`` row, so the
    accession in ``metric_sources`` is the only route from a stored period to the filing
    -- and therefore to the linkbase published beside it.

    A summed metric (``other_current_assets`` is one for a filer whose bucket is several
    captions) records both accessions joined by a comma. The first is the filing that
    reported the period, which is the one whose linkbase declares these subtotals.
    """
    for source in (period.metric_sources or {}).values():
        if not isinstance(source, dict):
            continue
        found = str(source.get("accession") or "").split(",")[0].strip()
        if found:
            return found
    return ""


def tag_index(period: FundamentalPeriod) -> dict[str, str]:
    """``taxonomy:Tag`` -> canonical metric, from the tags this period actually used.

    ``metric_sources`` records the tag each figure came from, so this is the *right*
    mapping for this period rather than the preferred one from ``TAG_MAP`` -- which
    matters precisely for the filers whose ``TAG_MAP`` entry is the unusual case, the
    ones the accounting-equation failures are about.

    A period stored before provenance was recorded has no sources, so nothing can be
    reconciled and the caller gets an empty index rather than a guess.
    """
    index: dict[str, str] = {}
    for metric, source in (period.metric_sources or {}).items():
        if not isinstance(source, dict):
            continue
        span = source.get("span")
        if not isinstance(span, str) or not span:
            continue
        # A metric that is the sum of several tags records them joined by `+` -- see
        # `_members`. Each maps to the metric, because each is where that caption's money
        # is held; `summed_members` is what stops the sum counting the same figure twice.
        for tag in _members(span):
            index.setdefault(tag, metric)
    return index


def summed_members(period: FundamentalPeriod) -> dict[str, tuple[str, ...]]:
    """``metric`` -> the tags it is the sum of, for the metrics that are sums.

    Only the multi-tag spans appear: a metric supplied by one tag is not a sum, and
    treating it as one would change nothing except by obscuring that.
    """
    out: dict[str, tuple[str, ...]] = {}
    for metric, source in (period.metric_sources or {}).items():
        if not isinstance(source, dict):
            continue
        members = _members(str(source.get("span") or ""))
        if len(members) > 1:
            out[metric] = members
    return out


@dataclass(frozen=True, slots=True)
class _Reading:
    """What one declared child contributes to its subtotal."""

    #: ``held``, ``absent``, ``unmodelled`` or ``pooled``.
    kind: str
    #: The weighted figure to add, zero for everything that is not counted.
    contribution: float = 0.0
    #: The metric the figure came from, so the caller can count a summed line once.
    metric: str | None = None


def _reading(
    tag: str,
    weight: float,
    *,
    index: Mapping[str, str],
    sums: Mapping[str, tuple[str, ...]],
    metrics: Mapping[str, Any],
    declared: set[str],
    counted: set[str],
) -> _Reading:
    """What we can say about one declared child.

    Named and separated because the four verdicts are the whole difficulty of this check
    and they are easy to confuse in a single loop: a line we hold, a line our vocabulary
    names with no figure this period, a line we have no name for at all, and a line we
    hold *inside a summed metric* whose share of it cannot be attributed.
    """
    metric = index.get(tag)
    value = value_of(metrics, metric) if metric else None
    if value is None:
        # No figure. Which of the two reasons it is decides the fix, so they are told
        # apart: `absent` needs a re-extraction, `unmodelled` needs the vocabulary.
        return _Reading("absent" if (metric or knows(tag)) else "unmodelled")

    members = sums.get(metric or "")
    if members is None:
        return _Reading("held", weight * value, metric)
    if set(members) > declared:
        # We hold this caption inside a line that also sums captions the filer does not
        # declare *here*, so its figure covers more than this child. Counting it would
        # invent a split the filing does not make.
        return _Reading("pooled", 0.0, metric)
    if metric in counted:
        # The line is one figure standing for several declared children, and it is
        # already in the sum. Adding it again would count the same money twice.
        return _Reading("held", 0.0, metric)
    return _Reading("held", weight * value, metric)


def reconcile(
    period: FundamentalPeriod,
    linkbase: Linkbase,
    *,
    parents: Iterable[str] | None = None,
    figures: Mapping[str, float] | None = None,
) -> list[Declaration]:
    """Measure every declared subtotal we hold a figure for.

    ``parents`` limits the work to particular tags. Declarations come back in the
    filer's order and duplicates are kept: the same subtotal declared in two roles is
    two statements, and two roles disagreeing with each other is worth seeing.

    **A declared child may be held inside a summed line.** `other_current_assets` is one
    line to us and two to `DAC_US_EQ`, which declares `OtherAssetsCurrent` and
    `OtherReceivablesNetCurrent` as separate children of `AssetsCurrent`. Summing our
    figure once per child would count that money twice; skipping the children would claim
    two lines we read are missing. So the line is counted **once**, and a child whose
    summed line also covers captions the filer declares elsewhere is reported as
    ``pooled`` -- held, but with no attributable share. :func:`_reading` decides each case.

    ``figures`` is the filer's own companyfacts value per ``taxonomy:Tag`` for this period
    end, used only to *price* the children we do not hold. It changes no verdict: a
    declared line we have no metric for stays unmodelled whether or not we know its
    figure, and the figure is there so a reader can tell a 2,093,000 rounding line from a
    third of the balance sheet.
    """
    index = tag_index(period)
    sums = summed_members(period)
    wanted = set(parents) if parents is not None else None
    metrics = period.metrics or {}

    out: list[Declaration] = []
    for spec in linkbase.calculations:
        if wanted is not None and spec.parent not in wanted:
            continue
        metric = index.get(spec.parent)
        stated = value_of(metrics, metric) if metric else None
        if metric is None or stated is None:
            # The parent is a subtotal we do not hold. There is nothing to check, and
            # reporting it would bury the declarations we can check.
            continue

        total = 0.0
        counted: set[str] = set()
        declared = {tag for tag, _weight in spec.children}
        buckets: dict[str, list[str]] = {
            "held": [],
            "absent": [],
            "unmodelled": [],
            "pooled": [],
        }

        for tag, weight in spec.children:
            reading = _reading(
                tag,
                weight,
                index=index,
                sums=sums,
                metrics=metrics,
                declared=declared,
                counted=counted,
            )
            total += reading.contribution
            if reading.contribution and reading.metric:
                counted.add(reading.metric)
            buckets[reading.kind].append(tag)

        held, absent = buckets["held"], buckets["absent"]
        unmodelled, pooled = buckets["unmodelled"], buckets["pooled"]
        out.append(
            _declared(
                spec,
                metric=metric,
                stated=stated,
                total=total,
                held=held,
                absent=absent,
                unmodelled=unmodelled,
                pooled=pooled,
                figures=figures,
            )
        )
    return out


def _declared(
    spec: Calculation,
    *,
    metric: str,
    stated: float,
    total: float,
    held: list[str],
    absent: list[str],
    unmodelled: list[str],
    pooled: list[str],
    figures: Mapping[str, float] | None,
) -> Declaration:
    """One declaration's verdict.

    A partial sum is not a smaller total, it is a different number, so ``declared_sum``
    and ``residual`` are present only when nothing was left out or misattributed -- which
    is what makes ``status`` meaningful rather than merely favourable.

    Only the lines that could not be placed are priced: the ones inside the sum already
    carry their figure, and a price on a pooled line would suggest we know its share.
    """
    complete = not absent and not unmodelled and not pooled
    prices = {
        tag: figures[tag] for tag in (*absent, *unmodelled) if figures and tag in figures
    }
    return Declaration(
        role=spec.role,
        parent=spec.parent,
        metric=metric,
        stated=stated,
        declared_sum=total if complete else None,
        held=tuple(held),
        absent=tuple(absent),
        unmodelled=tuple(unmodelled),
        pooled=tuple(pooled),
        figures=prices,
        residual=(stated - total) if complete else None,
    )


def checks(
    period: FundamentalPeriod,
    linkbase: Linkbase,
    *,
    parents: Iterable[str] | None = None,
    figures: Mapping[str, float] | None = None,
) -> list[Check]:
    """The reconciliation of every declaration we can measure, as page-ready checks."""
    declared = {spec.parent: len(spec.children) for spec in linkbase.calculations}
    return [
        item.as_check(declared.get(item.parent, len(item.held)))
        for item in reconcile(period, linkbase, parents=parents, figures=figures)
    ]


def contradictions(declarations: Iterable[Declaration]) -> list[Declaration]:
    """Only the declarations where we hold every line and it still does not sum."""
    return [item for item in declarations if item.status == IMBALANCE]

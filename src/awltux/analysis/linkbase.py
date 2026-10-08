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

from collections.abc import Iterable
from dataclasses import dataclass

from awltux.analysis.ledger import IMBALANCE, OK, UNKNOWN, Check, tolerance
from awltux.db import FundamentalPeriod
from awltux.ingest.linkbase import Linkbase
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
    residual: float | None = None

    @property
    def complete(self) -> bool:
        """Whether every declared child had a figure, so the sum means something."""
        return not self.absent and not self.unmodelled

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
                "role": self.role,
            },
        )

    def detail(self, declared: int) -> str:
        if not self.complete:
            parts = [f"the filer declares {declared} lines here and we hold {len(self.held)}"]
            if self.unmodelled:
                parts.append(f"no metric for {_named(self.unmodelled)}")
            if self.absent:
                parts.append(f"no figure for {_named(self.absent)}")
            return "; ".join(parts) + " -- not computable from what we hold"
        return (
            f"the filer's own {declared} lines sum to {self.declared_sum:,.0f} "
            f"against a stated {self.stated:,.0f}"
        )


def _named(tags: Iterable[str]) -> str:
    listed = list(tags)
    shown = ", ".join(listed[:NAMED_LIMIT])
    if len(listed) > NAMED_LIMIT:
        return f"{shown} and {len(listed) - NAMED_LIMIT} more"
    return shown


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
        if isinstance(span, str) and span:
            index.setdefault(span, metric)
    return index


def reconcile(
    period: FundamentalPeriod, linkbase: Linkbase, *, parents: Iterable[str] | None = None
) -> list[Declaration]:
    """Measure every declared subtotal we hold a figure for.

    ``parents`` limits the work to particular tags. Declarations come back in the
    filer's order and duplicates are kept: the same subtotal declared in two roles is
    two statements, and two roles disagreeing with each other is worth seeing.
    """
    index = tag_index(period)
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
        held: list[str] = []
        absent: list[str] = []
        unmodelled: list[str] = []
        for tag, weight in spec.children:
            child_metric = index.get(tag)
            child = value_of(metrics, child_metric) if child_metric else None
            if child is None:
                if child_metric is not None or knows(tag):
                    absent.append(tag)
                else:
                    unmodelled.append(tag)
                continue
            total += weight * child
            held.append(tag)

        complete = not absent and not unmodelled
        out.append(
            Declaration(
                role=spec.role,
                parent=spec.parent,
                metric=metric,
                stated=stated,
                declared_sum=total if complete else None,
                held=tuple(held),
                absent=tuple(absent),
                unmodelled=tuple(unmodelled),
                residual=(stated - total) if complete else None,
            )
        )
    return out


def checks(
    period: FundamentalPeriod, linkbase: Linkbase, *, parents: Iterable[str] | None = None
) -> list[Check]:
    """The reconciliation of every declaration we can measure, as page-ready checks."""
    declared = {spec.parent: len(spec.children) for spec in linkbase.calculations}
    return [
        item.as_check(declared.get(item.parent, len(item.held)))
        for item in reconcile(period, linkbase, parents=parents)
    ]


def contradictions(declarations: Iterable[Declaration]) -> list[Declaration]:
    """Only the declarations where we hold every line and it still does not sum."""
    return [item for item in declarations if item.status == IMBALANCE]

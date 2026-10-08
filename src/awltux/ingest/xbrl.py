"""Primary financial statements from XBRL, with the citation attached.

The figures in ``FundamentalPeriod`` come from one of three places -- a Yahoo
snapshot, an LLM reading a filed document, or XBRL -- and they are not equally
good. This module is the third, and it is the one the research note argues for:
XBRL is the company's own tagging of its own statements, filed under an accession
number that can be re-fetched and re-checked years later.

**What this replaces.** An LLM asked for ``total_assets`` returns a number and a
quoted span, which is good but not free and not deterministic. XBRL returns the
number the company tagged, in the unit it tagged it in, with the accession it was
filed under. For a US filer there is no reason to have a model read a balance
sheet when the issuer has already published it in machine-readable form.

**The unit is exact and that matters.** The extraction path warns that a UK
annual report states figures in thousands or millions, so cross-period arithmetic
on those is unsafe. XBRL facts carry their unit, so ``391,035,000,000`` is dollars
rather than "somewhere between 391 and 391 billion" -- which is why the markers in
:mod:`awltux.analysis.accounting` can be ratios of these figures at all.

**Nothing here decides anything.** :func:`annual_periods` is a pure function of a
``companyfacts`` payload. It fetches nothing, opens no session, and can be tested
against a captured response. The provider parses; this maps; the caller writes.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import FundamentalPeriod, Instrument
from awltux.db.session import release_write_lock
from awltux.ingest.blockers import clear_blocker, record_blocker
from awltux.providers.edgar import EdgarProvider, ProviderError
from awltux.scheduler import progress

logger = logging.getLogger(__name__)

#: This job's registry id, used to key the blockers it records. Named rather than
#: repeated, because a blocker keyed by a misspelt job id is a blocker the attention
#: check never reports.
JOB = "xbrl_statements"

#: A fiscal year, within a window wide enough for 52/53-week retailers and for
#: companies whose year end moves a few days. Below this a fact is a quarter;
#: above it, a fact spanning two years, which is a cumulative caption rather than
#: a period.
MIN_YEAR_DAYS = 340
MAX_YEAR_DAYS = 380

#: Forms whose figures may define a fiscal year. A 10-Q carries quarterly figures and
#: would put three-month numbers in an annual column, so it is not here.
#:
#: **6-K is, and it is where a foreign private issuer's annual figures actually arrive.**
#: Measured 2026-10-07 on `CNI_US_EQ` (Canadian National Railway, a 40-F filer): its
#: companyfacts payload carries **6,338** facts and every one is tagged `6-K`, with no
#: `40-F` fact at all -- the annual statements are *furnished* as a 6-K exhibit rather
#: than filed with the annual report. Excluded, the filer looked like it had no annual
#: data: 457 us-gaap tags, 24 annual-duration `Revenues` facts, 39 annual-duration
#: `NetIncomeLoss` facts, and `annual_periods` returned nothing. Every one of those
#: durations is self-evidently a year -- see :data:`ANNUAL_REPORT_FORMS` for why the
#: instants need more care than that.
ANNUAL_FORMS = frozenset(
    {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"}
)

#: The forms that may define a fiscal year end when **nothing else has**.
#:
#: A *duration* is self-evidently annual when it spans :data:`MIN_YEAR_DAYS` to
#: :data:`MAX_YEAR_DAYS`, whatever form carried it. An *instant* is not: the same
#: balance sheet appears at every quarter end, so with no annual duration to anchor it a
#: 6-K would turn each interim date into a "year" -- the phantom-year failure the
#: ``established`` guard in :func:`annual_periods` exists to prevent. This is the narrower
#: set that guard falls back to.
ANNUAL_REPORT_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})

#: How a metric's unit is recognised. XBRL unit keys are strings -- ``"USD"``,
#: ``"USD/shares"``, ``"shares"`` -- so a per-share figure taken from the
#: ``shares`` unit would be out by a factor of the share price.
MONETARY = "monetary"
PER_SHARE = "per_share"
SHARE_COUNT = "share_count"


@dataclass(frozen=True, slots=True)
class MetricTag:
    """One canonical metric, and the tags that can supply it, best first.

    The order is the preference, not a set: a company that tags both ``Revenues``
    and ``RevenueFromContractWithCustomerExcludingAssessedTax`` is describing the
    same money twice, and the first is the one the rest of the industry moved to.
    Which tag was actually used is recorded per period, so a reader can see when a
    series switches definition mid-way.
    """

    key: str
    kind: str
    tags: tuple[str, ...]


#: The mapping, in statement order. Every tag here is one this codebase has seen
#: in a real companyfacts payload; adding one is a deliberate act, because a tag
#: that does not exist is indistinguishable from a company that does not report
#: the figure.
TAG_MAP: tuple[MetricTag, ...] = (
    # --- income statement ---------------------------------------------------
    MetricTag("revenue", MONETARY, (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    )),
    MetricTag("cost_of_goods_sold", MONETARY, (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    )),
    MetricTag("gross_profit", MONETARY, ("GrossProfit",)),
    MetricTag("research_and_development", MONETARY, ("ResearchAndDevelopmentExpense",)),
    MetricTag("sga_expense", MONETARY, (
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    )),
    MetricTag("operating_income", MONETARY, ("OperatingIncomeLoss",)),
    MetricTag("depreciation_amortisation", MONETARY, (
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    )),
    MetricTag("interest_expense", MONETARY, (
        "InterestExpenseNonoperating",
        "InterestExpense",
    )),
    # The other half of net interest, and the line that makes a profit and loss
    # articulate. Its absence is not academic: on `AIT_US_EQ` FY2026-06-30, operating
    # income less interest expense is 532,083,000 against a reported profit before tax
    # of 544,274,000, and the 12,191,000 gap is exactly this tag (9,448,000) plus
    # other non-operating income (2,743,000).
    MetricTag("interest_income", MONETARY, (
        "InvestmentIncomeInterest",
        "InterestIncomeOperating",
        "InterestAndDividendIncomeOperating",
    )),
    MetricTag("other_nonoperating_income", MONETARY, (
        "OtherNonoperatingIncomeExpense",
        "NonoperatingIncomeExpense",
        "OtherNonoperatingIncome",
    )),
    MetricTag("pretax_income", MONETARY, (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    )),
    MetricTag("tax_expense", MONETARY, ("IncomeTaxExpenseBenefit",)),
    MetricTag("net_income", MONETARY, ("NetIncomeLoss", "ProfitLoss")),
    MetricTag("eps_diluted", PER_SHARE, ("EarningsPerShareDiluted",)),
    MetricTag("dividend_per_share", PER_SHARE, (
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    )),
    # --- balance sheet ------------------------------------------------------
    MetricTag("cash_and_equivalents", MONETARY, (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    )),
    MetricTag("receivables", MONETARY, (
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    )),
    MetricTag("inventory", MONETARY, ("InventoryNet",)),
    MetricTag("current_assets", MONETARY, ("AssetsCurrent",)),
    MetricTag("net_ppe", MONETARY, ("PropertyPlantAndEquipmentNet",)),
    # The right-of-use asset ASC 842 and IFRS 16 put on the balance sheet. It is the
    # counterpart to `lease_liabilities`, which the liability side has carried all
    # along, so a filer with operating leases had one side of the entry and not the
    # other. `AIT_US_EQ` FY2026-06-30: 213,199,000, and `NoncurrentAssets` is exactly
    # this plus PP&E, which is what identified it.
    MetricTag("operating_lease_assets", MONETARY, (
        "OperatingLeaseRightOfUseAsset",
        "OperatingLeaseRightOfUseAssetNet",
        "OperatingLeaseRightOfUseAssetAfterAccumulatedAmortization",
    )),
    MetricTag("goodwill", MONETARY, ("Goodwill",)),
    MetricTag("intangible_assets", MONETARY, (
        "FiniteLivedIntangibleAssetsNet",
        "IntangibleAssetsNetExcludingGoodwill",
    )),
    MetricTag("other_noncurrent_assets", MONETARY, (
        "OtherAssetsNoncurrent",
        "OtherAssetsNoncurrentNonoperating",
    )),
    MetricTag("other_current_assets", MONETARY, (
        "OtherAssetsCurrent",
        "PrepaidExpenseAndOtherAssetsCurrent",
    )),
    MetricTag("total_assets", MONETARY, ("Assets",)),
    MetricTag("payables", MONETARY, (
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    )),
    MetricTag("short_term_debt", MONETARY, (
        "LongTermDebtCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
    )),
    # The current-liability components. Measured on `AIT_US_EQ` FY2026-06-30, the
    # current-liability residual was exactly these two and nothing else: payables
    # 341,094,000 plus compensation 109,060,000 plus other current 162,257,000 equals
    # the stated `LiabilitiesCurrent` of 612,411,000 to the dollar.
    MetricTag("compensation_and_benefits", MONETARY, (
        "EmployeeRelatedLiabilitiesCurrent",
        # The caption the same money carries on most other balance sheets -- see
        # `METRIC_NOTES`. An alternative and not an addition: a filer that tags both is
        # describing one liability twice, and the coverage rule keeps the first.
        "AccruedLiabilitiesCurrent",
    )),
    MetricTag("other_current_liabilities", MONETARY, (
        "OtherLiabilitiesCurrent",
    )),
    MetricTag("current_liabilities", MONETARY, ("LiabilitiesCurrent",)),
    MetricTag("long_term_debt", MONETARY, ("LongTermDebtNoncurrent", "LongTermDebt")),
    MetricTag("lease_liabilities", MONETARY, ("OperatingLeaseLiabilityNoncurrent",)),
    MetricTag("other_noncurrent_liabilities", MONETARY, (
        "OtherLiabilitiesNoncurrent",
    )),
    MetricTag("total_liabilities", MONETARY, ("Liabilities",)),
    MetricTag("retained_earnings", MONETARY, ("RetainedEarningsAccumulatedDeficit",)),
    MetricTag("total_equity", MONETARY, (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    )),
    MetricTag("stock_based_compensation", MONETARY, ("ShareBasedCompensation",)),
    # --- cash flow ----------------------------------------------------------
    MetricTag("operating_cash_flow", MONETARY, (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    )),
    MetricTag("capex", MONETARY, (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    )),
    MetricTag("dividends_paid", MONETARY, (
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfDividends",
    )),
)

#: Captions summed into a metric **on top of** the tag that supplies it.
#:
#: Keyed by the winning tag, because whether an addition is safe depends on what that
#: tag already contains. A balance sheet presents several captions in one bucket, and
#: `TAG_MAP` picks one per metric -- right for a figure the filer names once, wrong for
#: *other current assets*, where the filer names each piece separately.
#:
#: **Every candidate was measured before it was kept.** Measured 2026-10-08 over the 98
#: companyfacts payloads archived on the volume -- 1,153 periods, re-derived twice, once
#: with each candidate and once without. A candidate is kept only when it closes
#: composition checks and closes none of them wrongly:
#:
#:     accrued-liabilities alternative   20 closed    0 worse    0 newly failing
#:     other-receivables addition         4 closed    0 worse    0 newly failing
#:     prepaid-expense addition           8 closed    0 worse   15 newly failing
#:     contract-liability addition        5 closed   14 worse    4 newly failing
#:
#: The two rejected ones are rejected on that evidence, not on taste, and the reason is
#: visible in the names: `PrepaidExpenseAndOtherAssetsCurrent` and `OtherLiabilitiesCurrent`
#: are *residual* captions that already contain what was being added to them. Measured on
#: `DAC_US_EQ` FY2025-12-31, the kept pair takes current assets from out by 48,843,000 to
#: 2,093,000 -- inside the check's 0.5% tolerance, so it agrees -- and current liabilities
#: from 65,397,000 to 36,625,000. The rest of that residual is the deferred revenue the
#: `ContractWithCustomerLiabilityCurrent` addition would have closed, and it is left
#: unexplained rather than closed wrongly for fifteen other filers.
EXTRA_TAGS: dict[str, tuple[str, ...]] = {
    "OtherAssetsCurrent": ("OtherReceivablesNetCurrent",),
}


#: Share counts. The us-gaap tag is an instant at the balance-sheet date, so it
#: lines up with a period end exactly; the dei tag is the figure printed on the
#: 10-K cover and is dated at filing, weeks later.
SHARE_TAGS: tuple[str, ...] = (
    "CommonStockSharesOutstanding",
    "EntityCommonStockSharesOutstanding",
)

#: How far after a fiscal year end a cover-page figure may sit and still belong to
#: it. A cover-page share count is dated at filing -- three weeks after the balance
#: sheet for a US filer -- so requiring an exact period-end match silently drops
#: every share count in the payload, which is how the dilution and payout markers
#: lose their input without anything reporting an error.
COVER_DATE_WINDOW_DAYS = 120

#: Figures XBRL does not state as such, composed from ones it does. Each is
#: recorded with the inputs it came from rather than with a taxonomy tag, because
#: there is no tag: citing one would be a citation to a fact that does not exist.
#:
#: ``total_debt`` is the only one, and it is needed because every leverage marker
#: reads it. XBRL's ``LongTermDebt`` is ambiguous across filers -- some include the
#: current portion, some do not -- so summing the two components we are sure about
#: is the version that cannot double-count.
COMPOSED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("total_debt", ("short_term_debt", "long_term_debt")),
)

#: Facts that describe an instant rather than a span. Everything not listed is a
#: duration fact, and mixing the two is how a balance-sheet item ends up averaged
#: across a year.
INSTANT_METRICS: frozenset[str] = frozenset({
    "cash_and_equivalents",
    "receivables",
    "inventory",
    "current_assets",
    "net_ppe",
    "operating_lease_assets",
    "goodwill",
    "intangible_assets",
    "other_noncurrent_assets",
    "other_current_assets",
    "total_assets",
    "payables",
    "compensation_and_benefits",
    "other_current_liabilities",
    "short_term_debt",
    "current_liabilities",
    "long_term_debt",
    "lease_liabilities",
    "other_noncurrent_liabilities",
    "total_liabilities",
    "retained_earnings",
    "total_equity",
    "shares_outstanding",
})

#: Preference order when a company tags the same figure in more than one
#: taxonomy. ``us-gaap`` first: an IFRS filer filing on 20-F tags in ``ifrs-full``,
#: but where both exist the US taxonomy is the one the extractor's other sources
#: were reconciled against.
TAXONOMY_ORDER: tuple[str, ...] = ("us-gaap", "ifrs-full", "dei")


@dataclass(frozen=True, slots=True)
class ExtractedFact:
    """One figure, and everything needed to re-derive it from the filing.

    ``citation`` is deliberately a single string rather than a struct: it is what
    a person pastes into EDGAR's full-text search to see the number in the
    document it came from, and it is what a marker shows when it says where a
    figure came from.
    """

    key: str
    value: float
    tag: str
    taxonomy: str
    unit: str
    accession: str
    form: str
    filed: dt.date | None
    period_end: dt.date

    def as_source(self) -> dict[str, Any]:
        """The provenance entry written into ``FundamentalPeriod.metric_sources``.

        The shape is the one the model documents -- ``value``, ``source``,
        ``span`` -- with the filing coordinates added, because for XBRL the
        accession *is* the span. A reader who wants the sentence it came from
        opens the accession; a reader who wants the number already has it.
        """
        payload: dict[str, Any] = {
            "value": self.value,
            "source": "xbrl_companyfacts",
            "span": f"{self.taxonomy}:{self.tag}",
            "unit": self.unit,
            "accession": self.accession,
            "form": self.form,
        }
        if self.filed is not None:
            payload["filed"] = self.filed.isoformat()
        return payload


@dataclass(slots=True)
class ExtractedPeriod:
    """One fiscal year's figures, plus the citation for each."""

    period_end: dt.date
    currency: str | None
    facts: dict[str, ExtractedFact] = field(default_factory=dict)
    #: Tags that were present but unusable, so an absent metric can be told from
    #: an unparsed one.
    rejected: dict[str, str] = field(default_factory=dict)

    def metrics(self) -> dict[str, float]:
        return {key: fact.value for key, fact in self.facts.items()}

    def sources(self) -> dict[str, Any]:
        return {key: fact.as_source() for key, fact in self.facts.items()}


def _parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _duration_days(fact: dict[str, Any]) -> int | None:
    start = _parse_date(fact.get("start"))
    end = _parse_date(fact.get("end"))
    if start is None or end is None:
        return None
    return (end - start).days


def _unit_matches(unit: str, kind: str) -> bool:
    lowered = (unit or "").lower()
    if kind == MONETARY:
        return "/" not in lowered and lowered != "shares"
    if kind == PER_SHARE:
        return lowered.endswith("/shares")
    return lowered == "shares"


def _currency_of(unit: str) -> str | None:
    """The reporting currency from a unit key like ``USD`` or ``USD/shares``."""
    head = (unit or "").split("/")[0].strip().upper()
    if not head or head == "SHARES":
        return None
    return head[:8]


# --------------------------------------------------------------------------- #
# candidate selection
# --------------------------------------------------------------------------- #


def _is_annual_duration(fact: dict[str, Any]) -> bool:
    days = _duration_days(fact)
    return days is not None and MIN_YEAR_DAYS <= days <= MAX_YEAR_DAYS


def _is_annual_instant(fact: dict[str, Any]) -> bool:
    return fact.get("start") in (None, "") and _parse_date(fact.get("end")) is not None


def _eligible(fact: dict[str, Any], *, instant: bool) -> bool:
    if str(fact.get("form") or "").upper() not in ANNUAL_FORMS:
        return False
    if _parse_date(fact.get("end")) is None:
        return False
    return _is_annual_instant(fact) if instant else _is_annual_duration(fact)


def _better(candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
    """Whether a candidate should replace the one held for the same period.

    The **earliest filed** wins. A figure appears in the year it was reported and
    again as a comparative in later filings, and a later filing may have restated
    it. Taking the original is what was actually published for that year, and it
    is the same rule ``FundamentalPeriod.as_of`` exists for: a valuation built on
    a restatement published two years later is a valuation with hindsight in it.
    """
    left = _parse_date(candidate.get("filed")) or dt.date.max
    right = _parse_date(incumbent.get("filed")) or dt.date.max
    return left < right


def _select(
    facts: dict[str, Any], tag: str, taxonomy: str, *, instant: bool, kind: str
) -> list[dict[str, Any]]:
    """The usable annual facts for one tag, in the order the payload lists them."""
    units = (facts.get(taxonomy) or {}).get(tag) or {}
    entries = units.get("units") if isinstance(units, dict) else None
    if not isinstance(entries, dict):
        return []

    out: list[dict[str, Any]] = []
    for unit, series in entries.items():
        if not _unit_matches(unit, kind) or not isinstance(series, list):
            continue
        for fact in series:
            if not isinstance(fact, dict):
                continue
            value = fact.get("val")
            if not isinstance(value, int | float):
                continue
            if not _eligible(fact, instant=instant):
                continue
            out.append({**fact, "_unit": unit, "_taxonomy": taxonomy, "_tag": tag})
    return out


def _pick_per_period(candidates: list[dict[str, Any]]) -> dict[dt.date, dict[str, Any]]:
    """One fact per period end, earliest filed."""
    chosen: dict[dt.date, dict[str, Any]] = {}
    for fact in candidates:
        end = _parse_date(fact.get("end"))
        if end is None:
            continue
        incumbent = chosen.get(end)
        if incumbent is None or _better(fact, incumbent):
            chosen[end] = fact
    return chosen


def _first_tag(
    facts: dict[str, Any], spec: MetricTag, *, instant: bool
) -> tuple[dict[dt.date, dict[str, Any]], str | None]:
    """The tag that describes this metric most recently, ties going to the declared order.

    **Preference is by tag, not by period.** A company that reports revenue under the
    newer tag for two years and the older one before that must not produce a series that
    changes definition halfway, so one tag supplies the whole series and the others are
    not consulted -- ``test_the_preferred_tag_supplies_every_period_it_has`` pins that.

    But *declaration* order alone drops a metric entirely when a filer stops using the
    tag we prefer. Measured on ``AIT_US_EQ``: the first cash tag,
    ``CashAndCashEquivalentsAtCarryingValue``, has no annual fact after 2021-06-30,
    while ``CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`` covers
    2023-2026. So it was chosen, contributed nothing to any period on file, and cash was
    absent from **every balance sheet from 2022 onward** -- the current-asset total out
    by 127,130,000 with nothing on the page to say why.

    So the tag whose coverage reaches the most recent year wins, and the declared order
    breaks ties. One tag still supplies the whole series, which is what keeps the
    anti-mixing property; what changes is only *which* tag that is, and it is now the
    one the company is actually using.
    """
    best: tuple[dt.date, dict[dt.date, dict[str, Any]], str] | None = None
    for taxonomy in TAXONOMY_ORDER:
        for tag in spec.tags:
            chosen = _pick_per_period(
                _select(facts, tag, taxonomy, instant=instant, kind=spec.kind)
            )
            if not chosen:
                continue
            # `>` and not `>=`: the first tag in preference order keeps a tie, so a
            # filer whose tags cover the same years is read exactly as before.
            latest = max(chosen)
            if best is None or latest > best[0]:
                best = (latest, chosen, f"{taxonomy}:{tag}")
    if best is None:
        return {}, None
    return best[1], best[2]


def _metric_facts(
    facts: dict[str, Any],
    spec: MetricTag,
    *,
    instant: bool,
    adopted: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[dict[dt.date, dict[str, Any]], str | None]:
    """The facts for one metric: the winning tag, plus the captions added to it.

    ``_first_tag`` answers "which tag supplies this figure", and for a figure a filer
    names once that is the whole answer. A bucket line is the exception: a filer presents
    *other current assets* as several captions, and picking one of them leaves the
    composition check out by the rest -- which is what :data:`EXTRA_TAGS` records for every
    filer, and what ``adopted`` records **for one**, proven from that filer's own
    calculation linkbase. See :mod:`awltux.analysis.adopted` for why the second is per
    filer: the same caption that closes `DAC_US_EQ` breaks fifteen other filers.

    **An addition never creates a period.** It is only summed onto a period end the
    winning tag already established, so a filer that tags one part-line at a date we hold
    no statements for cannot appear as a fiscal year with one number in it -- the same
    failure ``_is_year_end`` exists to prevent on the instant side.
    """
    chosen, span = _first_tag(facts, spec, instant=instant)
    if span is None:
        return chosen, span

    taxonomy, _, primary = span.partition(":")
    additions = list(EXTRA_TAGS.get(primary, ()))
    additions.extend((adopted or {}).get(spec.key, ()))

    added: list[str] = []
    for entry in additions:
        #  An adopted caption comes from the filing's declaration, so it is qualified --
        #  and it may live in a taxonomy of its own, which is the usual case for a filer's
        #  own extension (`dac:StraightLiningOfCompanySRevenueCurrentAssets`).
        own_taxonomy, _, tag = entry.partition(":")
        if not tag:
            own_taxonomy, tag = taxonomy, own_taxonomy
        #  Never the tag already supplying the figure, and never twice: a caption summed
        #  onto itself is a doubling that looks like a bigger account.
        if tag == primary or tag in added:
            continue
        extra = _pick_per_period(
            _select(facts, tag, own_taxonomy, instant=instant, kind=spec.kind)
        )
        onto = [end for end in extra if end in chosen]
        if not onto:
            continue
        for end in onto:
            chosen[end] = _summed(chosen[end], extra[end])
        added.append(tag)

    if not added:
        return chosen, span
    return chosen, span + "".join(f"+{tag}" for tag in added)


def _summed(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """One fact standing for two tags that each carry part of the same line.

    The value is the sum, and both tags are named in it, because the figure on the page
    is now arithmetic this project did rather than a number the filer printed -- which is
    exactly why ``_compose`` records a joined tag for the totals it derives. The
    accession lists both filings and ``filed`` is the later of the two, since the sum is
    only knowable once the second one was filed.
    """
    return {
        **first,
        "val": float(first["val"]) + float(second["val"]),
        #  Each part keeps its own taxonomy, because an adopted caption is often the
        #  filer's own extension: `us-gaap:OtherAssetsCurrent+dac:StraightLining...`.
        #  `as_source` prefixes the *first* taxonomy and `analysis._members` qualifies only
        #  the parts that carry none, so a mixed pair reads back correctly -- while a bare
        #  `OtherAssetsCurrent+StraightLining...` would claim the extension was us-gaap and
        #  the reconciliation would then report a line we hold as one we do not.
        "_tag": (
            f"{first['_tag']}+{second['_tag']}"
            if first["_taxonomy"] == second["_taxonomy"]
            else f"{first['_tag']}+{second['_taxonomy']}:{second['_tag']}"
        ),
        "accn": ",".join(
            sorted(
                accession
                for accession in (first.get("accn"), second.get("accn"))
                if accession
            )
        ),
        "filed": max(
            (str(filed) for filed in (first.get("filed"), second.get("filed")) if filed),
            default=None,
        ),
    }


# --------------------------------------------------------------------------- #
# the pure entry point
# --------------------------------------------------------------------------- #


def _make_fact(key: str, fact: dict[str, Any], period_end: dt.date) -> ExtractedFact:
    return ExtractedFact(
        key=key,
        value=float(fact["val"]),
        tag=str(fact["_tag"]),
        taxonomy=str(fact["_taxonomy"]),
        unit=str(fact["_unit"]),
        accession=str(fact.get("accn") or ""),
        form=str(fact.get("form") or ""),
        filed=_parse_date(fact.get("filed")),
        period_end=period_end,
    )


def _nearest_period(
    per_period: dict[dt.date, ExtractedPeriod], when: dt.date
) -> dt.date | None:
    """The fiscal year a cover-page figure belongs to, or ``None``.

    Only backwards: a cover date precedes nothing, it follows the year it reports.
    A figure dated before every period end in the payload belongs to a year we do
    not hold, and attaching it to the earliest we do would put next year's share
    count on this year's balance sheet.
    """
    candidates = [
        end
        for end in per_period
        if end <= when and (when - end).days <= COVER_DATE_WINDOW_DAYS
    ]
    return max(candidates) if candidates else None


def _attach_shares(
    per_period: dict[dt.date, ExtractedPeriod], facts: dict[str, Any]
) -> None:
    """Fill ``shares_outstanding``, exact matches first, cover dates second.

    Two passes because the two tags mean the same thing on different dates. The
    balance-sheet tag is tried first and its answer is never overridden: a count
    taken at the year end is the one the per-share figures in that year were
    divided by.
    """
    for taxonomy in TAXONOMY_ORDER:
        for tag in SHARE_TAGS:
            found = _pick_per_period(
                _select(facts, tag, taxonomy, instant=True, kind=SHARE_COUNT)
            )
            for end, fact in found.items():
                target = end if end in per_period else _nearest_period(per_period, end)
                if target is None:
                    continue
                entry = per_period[target]
                entry.facts.setdefault(
                    "shares_outstanding", _make_fact("shares_outstanding", fact, target)
                )


def _compose(entry: ExtractedPeriod) -> None:
    """Add the totals that are arithmetic on figures already extracted.

    The composed fact carries the accessions of its inputs, so a reader checking
    ``total_debt`` is sent to the two filings that state the halves rather than to
    a tag that does not exist.
    """
    for key, inputs in COMPOSED:
        if key in entry.facts:
            continue
        parts = [entry.facts.get(name) for name in inputs]
        if any(part is None for part in parts):
            continue
        present = [part for part in parts if part is not None]
        entry.facts[key] = ExtractedFact(
            key=key,
            value=sum(part.value for part in present),
            tag="+".join(part.tag for part in present),
            taxonomy="derived",
            unit=present[0].unit,
            accession=",".join(sorted({part.accession for part in present if part.accession})),
            form=present[0].form,
            filed=max((part.filed for part in present if part.filed), default=None),
            period_end=entry.period_end,
        )


def _is_year_end(period_end: dt.date, fact: dict[str, Any], established: set[dt.date]) -> bool:
    """Whether an instant's date is a fiscal year end, and so a balance-sheet date.

    **A duration establishes which dates are year ends; an instant only lands on one.**
    That is why the two passes are not symmetric: an annual duration says by its own span
    that it covers a year, while a balance sheet says nothing about whether its date is a
    quarter end or a year end -- the same figures appear at both.

    So when a duration has established the year ends, an instant at one of those dates is
    that year's balance sheet, whichever form carried it. With **nothing** established
    there is no such signal, and the fallback asks for an annual *report* rather than any
    accepted form: a 6-K balance sheet would otherwise become a "year" at every quarter
    end. Measured 2026-10-07 on `AIT_US_EQ`'s 2024-04-15 row, which held nothing but
    `goodwill` before the guard existed.
    """
    if established:
        return period_end in established
    return str(fact.get("form") or "").upper() in ANNUAL_REPORT_FORMS


def annual_periods(
    facts_payload: dict[str, Any],
    *,
    adopted: Mapping[str, tuple[str, ...]] | None = None,
) -> list[ExtractedPeriod]:
    """Annual figures per fiscal year, newest last.

    Returns only periods that yielded at least one metric -- an empty shell would
    create a ``FundamentalPeriod`` row with no figures, which a coverage count
    cannot tell from a period that was successfully extracted.

    ``adopted`` adds captions proven to belong to a line **for this filer** -- see
    :mod:`awltux.analysis.adopted`. It is the same mechanism as :data:`EXTRA_TAGS` with a
    narrower reach, and it is what turns a proven balance sheet into a complete one.
    """
    facts = facts_payload.get("facts")
    if not isinstance(facts, dict):
        return []

    # period_end -> key -> fact, built once per metric and merged afterwards,
    # because two metrics can share a year and disagree about nothing.
    per_period: dict[dt.date, ExtractedPeriod] = {}

    def slot(period_end: dt.date) -> ExtractedPeriod:
        if period_end not in per_period:
            per_period[period_end] = ExtractedPeriod(period_end=period_end, currency=None)
        return per_period[period_end]

    for spec in (s for s in TAG_MAP if s.key not in INSTANT_METRICS):
        chosen, span = _metric_facts(facts, spec, instant=False, adopted=adopted)
        if span is None:
            continue
        for period_end, fact in chosen.items():
            entry = slot(period_end)
            entry.facts[spec.key] = _make_fact(spec.key, fact, period_end)
            if entry.currency is None and spec.kind == MONETARY:
                entry.currency = _currency_of(str(fact["_unit"]))

    # Only a fact with an explicit twelve-month span defines a fiscal year. An
    # instant is a balance-sheet date, and a balance-sheet date is not always a
    # year end: a filer that tags a goodwill figure at the date of an impairment
    # would otherwise get a "year" consisting of that one number, which inflates
    # coverage and cannot support a single marker. Measured on a live filer whose
    # 2024-04-15 row held nothing but `goodwill`.
    established = set(per_period)

    for spec in (s for s in TAG_MAP if s.key in INSTANT_METRICS):
        chosen, span = _metric_facts(facts, spec, instant=True, adopted=adopted)
        if span is None:
            continue
        for period_end, fact in chosen.items():
            if not _is_year_end(period_end, fact, established):
                continue
            entry = slot(period_end)
            entry.facts[spec.key] = _make_fact(spec.key, fact, period_end)
            if entry.currency is None and spec.kind == MONETARY:
                entry.currency = _currency_of(str(fact["_unit"]))

    _attach_shares(per_period, facts)

    for entry in per_period.values():
        _compose(entry)

    return [per_period[end] for end in sorted(per_period) if per_period[end].facts]


# --------------------------------------------------------------------------- #
# writing them down
# --------------------------------------------------------------------------- #

#: The `source` stamped on rows this module writes. It is what lets a reader tell
#: a figure the company tagged from one a model read out of the same document, and
#: it is deliberately different from ``yahoo_statements`` for the same reason.
SOURCE = "xbrl_companyfacts"

#: How many years back to keep.
#:
#: **Two, by request.** This was six, on the reasoning that a five-year comparison
#: is what a trend needs. That reasoning was wrong about the cost and the benefit:
#: the companyfacts payload is fetched in full either way, so six years buys nothing
#: but storage, and every extra year is another ``FundamentalPeriod`` row rewritten
#: on every visit. Measured on the live container, six years is 12 rows per run for
#: 2 filers; with 312 filers still to do that is roughly 1,900 rows of history.
#:
#: **What two years costs.** ``MIN_PERIODS_FOR_TREND`` is 3, so no marker will claim
#: a *trend*: the readings that describe direction -- accrual and cash-conversion
#: trend, DSO "rising", margin direction -- will say "not yet a trend". The
#: year-over-year markers are unaffected: Piotroski's six change tests, the Beneish
#: indices and every "this year against last" comparison still work, because they
#: need exactly two periods and that is what two years is.
KEEP_YEARS = 2

#: Confidence recorded for an extracted period. Not 1.0: the figures are the
#: company's own, but the *mapping* from taxonomy tag to our vocabulary is ours, so
#: a wrong tag choice is possible and is exactly what ``metric_sources`` is for.
CONFIDENCE = 0.95


@dataclass(slots=True)
class XbrlReport:
    """What one run did, in the shape the job summariser expects."""

    tickers_attempted: int = 0
    tickers_failed: int = 0
    #: Filers whose payload arrived and yielded no period. Counted apart from `failed`
    #: because nothing went wrong -- the fetch and the parse both worked -- and apart
    #: from success because nothing came back. See `_sync_one`.
    tickers_empty: int = 0
    periods_written: int = 0
    metrics_written: int = 0
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.tickers_attempted,
            "failed": self.tickers_failed,
            "empty": self.tickers_empty,
            "periods_written": self.periods_written,
            "metrics_written": self.metrics_written,
            "failures": self.failures[:20],
        }


def sync_xbrl_fundamentals(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: EdgarProvider | None = None,
    tickers: list[str] | None = None,
    limit: int | None = None,
) -> XbrlReport:
    """Write each US filer's annual statements into ``FundamentalPeriod``.

    Rotates least-recently-extracted first, so a rationed run spreads across the
    universe instead of retrying the same names.

    **The rotation is ordered on this job's own output, not on the instrument.**
    ``Instrument.updated_at`` is the obvious key and it is the wrong one: nothing
    in this job touches the instrument row, so the order never changes and every
    run re-reads the same first slice. That is not theoretical -- the first two
    runs both reported twelve periods written while the table stayed at twelve
    rows, because the second run overwrote the first one's filers. Ordered on
    ``max(as_of)`` of the rows it writes, the queue actually drains, and a filer
    whose payload failed stays at the front rather than being skipped past.

    **The write lock is released before every network call.** A companyfacts
    payload is megabytes and the request is not fast; holding SQLite's write lock
    across it would block every other job for the duration, which is the mistake
    ``docs/`` records three times over.
    """
    settings = settings or get_settings()
    provider = provider or EdgarProvider(settings)
    report = XbrlReport()

    # Nulls first: a filer with no XBRL period at all is the one with work to do.
    extracted_at = (
        select(func.max(FundamentalPeriod.as_of))
        .where(FundamentalPeriod.instrument_t212_ticker == Instrument.t212_ticker)
        .where(FundamentalPeriod.source == SOURCE)
        .correlate(Instrument)
        .scalar_subquery()
    )

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .where(Instrument.sec_cik.is_not(None))
        .order_by(extracted_at.asc().nullsfirst(), Instrument.t212_ticker.asc())
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    else:
        # A sweep skips instruments a scoped refresh holds. See `ingest/lease.py`.
        from awltux.ingest.lease import exclude_locked

        statement = exclude_locked(statement, session)
    if limit:
        statement = statement.limit(limit)

    filers = list(session.execute(statement).scalars().all())
    for position, instrument in enumerate(filers, start=1):
        progress.note(f"{position} of {len(filers)}: {instrument.t212_ticker}")
        _sync_one(session, instrument, provider, report)

    logger.info("xbrl fundamentals: %s", report.as_dict())
    return report


def _sync_one(
    session: Session, instrument: Instrument, provider: EdgarProvider, report: XbrlReport
) -> None:
    """Fetch and store one filer's statements, recording any failure on the report.

    One named step rather than a loop body, because the two failures it absorbs are
    different in kind and both need saying: the provider refused us, or the payload
    arrived and could not be parsed. Either way the run continues -- 312 filers is
    too many to lose to one bad response -- and the report carries which happened.

    Both also become an :class:`~awltux.db.models.InstrumentBlocker` under this job, and
    success clears it. The report's ``failures`` list is for the run's log; the blocker is
    the record that outlives the run, which is what the dashboard's attention filter
    reads. Without it "we tried and this filer's statements cannot be had" and "we have
    not got to it yet" are the same em-dash.
    """
    report.tickers_attempted += 1
    cik = instrument.sec_cik
    assert cik is not None

    # Before the request, not after it: this is the whole reason the rule exists,
    # and an after-the-fact release is the bug that was fixed twice.
    release_write_lock(session)
    try:
        payload = provider.get_company_facts(cik)
    except ProviderError as exc:
        report.tickers_failed += 1
        report.failures.append(f"{instrument.t212_ticker}: {exc}")
        record_blocker(
            session,
            instrument.t212_ticker,
            job=JOB,
            stage="statements",
            reason=str(exc),
        )
        session.flush()
        return

    try:
        written, metrics_written = _write_periods(session, instrument, payload)
    except Exception as exc:  # noqa: BLE001 - one bad payload must not stop the run
        report.tickers_failed += 1
        report.failures.append(f"{instrument.t212_ticker}: {type(exc).__name__}: {exc}")
        record_blocker(
            session,
            instrument.t212_ticker,
            job=JOB,
            stage="xbrl",
            reason=f"{type(exc).__name__}: {exc}",
        )
        session.flush()
        return

    # The payload arrived and parsed, so whatever was recorded against those two steps
    # is no longer true. Both, because either could have been the one that failed.
    clear_blocker(session, instrument.t212_ticker, job=JOB, stage="statements")
    clear_blocker(session, instrument.t212_ticker, job=JOB, stage="xbrl")

    if written:
        clear_blocker(session, instrument.t212_ticker, job=JOB, stage="extract")
    else:
        # Asked, received, and got no period out of it -- which used to be recorded as
        # *success*: `_write_periods` returning zero took this branch, cleared the
        # blockers and moved on. That made three states indistinguishable, and the
        # distinction is the whole question: "not yet reached" is waiting, "received and
        # empty" is a filer we cannot read, and "read with the wrong tags" is a mapper
        # to fix. Measured 2026-10-07, of 314 in-universe instruments with a resolved SEC
        # CIK, 261 had no period and nothing said which of the three they were.
        #
        # Deliberately not inferred by the coverage probe, which counts missing periods:
        # that would flag all 261, including the ones the rotation has simply not reached.
        # A blocker is written only where the fetch actually happened and came back empty.
        report.tickers_empty += 1
        record_blocker(
            session,
            instrument.t212_ticker,
            job=JOB,
            stage="extract",
            reason=_payload_note(payload),
        )

    report.periods_written += written
    report.metrics_written += metrics_written
    session.flush()


def _payload_note(payload: dict[str, Any]) -> str:
    """What the payload actually carried, because "extracted nothing" is a symptom.

    The three cases need different fixes and the payload says which one it is: no
    ``facts`` at all (the wrong endpoint, or a filer with no XBRL), facts under a
    taxonomy that is not ``us-gaap`` (a foreign filer on ``ifrs-full``, which the mapper
    does not read), or a ``us-gaap`` taxonomy with no annual frame it recognises. Written
    from the payload rather than guessed, so the blocker can be acted on without
    re-fetching anything.
    """
    facts = payload.get("facts")
    if not isinstance(facts, dict) or not facts:
        return "the companyfacts payload carried no facts at all"
    taxonomies = ", ".join(sorted(str(name) for name in facts)[:4])
    us_gaap = facts.get("us-gaap")
    tags = len(us_gaap) if isinstance(us_gaap, dict) else 0
    return (
        f"the payload carried facts for {taxonomies} but no annual period could be read "
        f"from them ({tags} us-gaap tag(s))"
    )


def _write_periods(
    session: Session, instrument: Instrument, payload: dict[str, Any]
) -> tuple[int, int]:
    """Upsert one instrument's annual periods.

    Returns ``(periods_written, metrics_written)``. The second is counted rather
    than left to the caller because a period's metric count is only known here --
    and a field that always reads zero is worse than an absent one, since it looks
    like a measurement.
    """
    from awltux.analysis.adopted import load as adopted_for
    from awltux.ingest.fundamentals import _upsert_period, derive_metrics

    #  The captions this filer's own linkbase proved belong to a line. Read here, per
    #  instrument, because the mapping is per filer -- see `analysis/adopted.py`.
    adopted = adopted_for(session, instrument.sec_cik)

    periods = annual_periods(payload, adopted=adopted)[-KEEP_YEARS:]
    written = 0
    metric_total = 0
    for period in periods:
        metrics = period.metrics()
        # The derived ratios are ours, not the company's, so they are added to the
        # figures without a citation -- claiming the issuer tagged `roe` when they
        # tagged the two numbers we divided would be a fabricated provenance.
        metrics.update(derive_metrics(metrics))
        if _upsert_period(
            session,
            instrument,
            period_end=period.period_end,
            period_type="annual",
            metrics=metrics,
            source=SOURCE,
            confidence=CONFIDENCE,
            metric_sources=period.sources(),
        ):
            written += 1
            metric_total += len(period.sources())
    return written, metric_total

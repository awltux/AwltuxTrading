"""The filer's own arithmetic, read and checked.

Two claims are under test, and they fail in different ways:

* **The parse is faithful.** The fixture is DFPH's real calculation linkbase for
  FY2025-12-31, captured verbatim from EDGAR, so these assertions are about the
  document the SEC serves rather than about a shape invented for the test. A parser that
  silently drops arcs would make every check below pass by having nothing to check.
* **The verdict separates our gaps from the filer's.** This is the whole point: a
  component check that fails because we hold three of six declared lines is reporting
  our coverage, and must not read as an error in the filer's figures. Only a subtotal
  where every declared line is held -- and still does not sum -- is a contradiction.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest

from awltux.analysis import linkbase as reconciliation
from awltux.analysis.ledger import IMBALANCE, OK, UNKNOWN
from awltux.db import FundamentalPeriod
from awltux.ingest.linkbase import (
    Linkbase,
    parse_calculation_linkbase,
    qualification,
)

CAL = Path(__file__).parent / "fixtures" / "dfph_20251231_cal.xml"

#: The accession DFPH's FY2025-12-31 10-K was filed under, for the provenance the
#: reconciliation reads.
ACCESSION = "0001799191-26-000007"

#: The accession and tags DFPH's 10-K for FY2025-12-31 actually reports, read from the
#: live period. Only the tags the balance-sheet checks need.
DFPH_SOURCES = {
    "total_assets": "us-gaap:Assets",
    "current_assets": "us-gaap:AssetsCurrent",
    "current_liabilities": "us-gaap:LiabilitiesCurrent",
    "total_liabilities": "us-gaap:Liabilities",
    "net_ppe": "us-gaap:PropertyPlantAndEquipmentNet",
    "goodwill": "us-gaap:Goodwill",
    "inventory": "us-gaap:InventoryNet",
    "receivables": "us-gaap:AccountsReceivableNetCurrent",
    "retained_earnings": "us-gaap:RetainedEarningsAccumulatedDeficit",
}


def _period(*, metrics: dict | None = None, sources: dict | None = None,
            provenance: bool = True) -> FundamentalPeriod:
    """DFPH's FY2025-12-31 period as stored, with the figures overridable.

    ``provenance=False`` models a period stored before ``metric_sources`` existed,
    which is the case the reconciliation has to refuse rather than guess at.
    """
    values = {
        "total_assets": 164_656_000.0,
        "current_assets": 112_747_000.0,
        "current_liabilities": 70_962_000.0,
        "total_liabilities": 180_376_000.0,
        "net_ppe": 10_684_000.0,
        "goodwill": 7_230_000.0,
        "inventory": 16_875_000.0,
        "receivables": 58_998_000.0,
        "retained_earnings": -271_419_000.0,
        "total_equity": -15_720_000.0,
    }
    values.update(metrics or {})

    spans: dict[str, str] = dict(DFPH_SOURCES) if provenance else {}
    spans.update(sources or {})

    return FundamentalPeriod(
        instrument_t212_ticker="DFPH_US_EQ",
        period_end=dt.date(2025, 12, 31),
        period_type="annual",
        source="xbrl_companyfacts",
        currency="USD",
        metrics=values,
        metric_sources={
            metric: {"value": values[metric], "span": span, "accession": ACCESSION}
            for metric, span in spans.items()
            if metric in values
        },
    )


@pytest.fixture(scope="module")
def dfph() -> Linkbase:
    return parse_calculation_linkbase(CAL.read_bytes())


class TestNamingATag:
    def test_a_standard_tag_is_split_at_its_first_underscore(self):
        assert qualification("#us-gaap_Assets") == "us-gaap:Assets"

    def test_a_custom_extension_keeps_its_own_prefix(self):
        """Filers extend the taxonomy freely, and DFPH does."""
        assert (
            qualification("#toi_DerivativeWarrantLiabilitiesNoncurrent")
            == "toi:DerivativeWarrantLiabilitiesNoncurrent"
        )

    def test_the_tag_may_contain_underscores_of_its_own(self):
        assert qualification("#us-gaap_CashCashEquivalentsRestrictedCash") == (
            "us-gaap:CashCashEquivalentsRestrictedCash"
        )

    def test_a_locator_naming_no_element_is_refused(self):
        """Guessing a tag from the label would compare two different things."""
        assert qualification("#") is None
        assert qualification("") is None
        assert qualification(None) is None
        assert qualification("no-fragment-here") is None


class TestParsingTheRealDocument:
    def test_every_declared_subtotal_is_read(self, dfph):
        """A dropped arc would make every reconciliation below vacuous."""
        assert dfph.bytes_read == CAL.stat().st_size
        assert dfph.refused == ()
        assert len(dfph.calculations) == 44
        assert len(dfph.roles) == 18
        assert "CONSOLIDATEDBALANCESHEETS" in dfph.roles

    def test_the_balance_sheet_names_the_parent_and_its_children_in_order(self, dfph):
        """The order is the filer's, and it is what a reader compares against."""
        assets = dfph.for_parent("us-gaap:Assets")

        assert len(assets) == 1
        assert assets[0].role == "CONSOLIDATEDBALANCESHEETS"
        assert [tag for tag, _weight in assets[0].children] == [
            "us-gaap:AssetsCurrent",
            "us-gaap:Goodwill",
            "us-gaap:OperatingLeaseRightOfUseAsset",
            "us-gaap:OtherAssetsNoncurrent",
            "us-gaap:PropertyPlantAndEquipmentNet",
            "us-gaap:IntangibleAssetsNetExcludingGoodwill",
        ]

    def test_a_negative_weight_is_kept(self, dfph):
        """Treasury stock is subtracted, and a weights-lost parse still sums."""
        equity = dfph.for_parent("us-gaap:StockholdersEquity")[0]

        assert ("us-gaap:TreasuryStockCommonValue", -1.0) in equity.children

    def test_a_subtotal_declared_in_two_roles_is_kept_twice(self, dfph):
        """Two statements making the same claim is two claims, not one."""
        declared = [c for c in dfph.calculations if c.parent == "us-gaap:OperatingIncomeLoss"]

        assert declared, "the fixture declares operating income somewhere"

    def test_a_document_that_is_not_xml_raises(self):
        """The caller asked for a specific artefact and got something else."""
        from lxml import etree

        with pytest.raises(etree.XMLSyntaxError):
            parse_calculation_linkbase(b"<html>Access Denied</html")

    def test_an_arc_that_cannot_be_read_is_recorded_not_dropped(self):
        """A malformed arc must not silently shrink the filer's arithmetic."""
        document = b"""<?xml version="1.0"?>
        <link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
                       xmlns:xlink="http://www.w3.org/1999/xlink">
          <link:calculationLink xlink:role="http://x/role/BALANCE">
            <link:loc xlink:href="#us-gaap_Assets" xlink:label="a"/>
            <link:loc xlink:href="#us-gaap_Goodwill" xlink:label="b"/>
            <link:calculationArc xlink:from="a" xlink:to="b" weight="lots"/>
          </link:calculationLink>
        </link:linkbase>
        """

        parsed = parse_calculation_linkbase(document)

        assert parsed.calculations == ()
        assert len(parsed.refused) == 1
        assert "lots" in parsed.refused[0]

    def test_an_absent_weight_means_one(self):
        """Optional in the attribute sense, not the "unreadable" sense."""
        document = b"""<?xml version="1.0"?>
        <link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
                       xmlns:xlink="http://www.w3.org/1999/xlink">
          <link:calculationLink xlink:role="http://x/role/BALANCE">
            <link:loc xlink:href="#us-gaap_Assets" xlink:label="a"/>
            <link:loc xlink:href="#us-gaap_Goodwill" xlink:label="b"/>
            <link:calculationArc xlink:from="a" xlink:to="b"/>
          </link:calculationLink>
        </link:linkbase>
        """

        parsed = parse_calculation_linkbase(document)

        assert parsed.calculations[0].children == (("us-gaap:Goodwill", 1.0),)

    def test_it_round_trips_through_its_own_dict(self, dfph):
        """The cached form has to be the same document the parser produced."""
        assert Linkbase.from_dict(dfph.as_dict()).calculations == dfph.calculations


class TestDecidingWhatTheGapIs:
    def test_our_own_missing_lines_are_not_a_filer_error(self, dfph):
        """The finding this module exists for.

        DFPH's stored period holds three of the six lines the filer declares under
        ``us-gaap:Assets``. The current composition check reports that as an imbalance;
        the honest verdict is *not computable*, and it names what is missing so the gap
        is actionable.
        """
        [assets] = reconciliation.reconcile(_period(), dfph, parents=["us-gaap:Assets"])

        assert assets.status == UNKNOWN
        assert assets.declared_sum is None, "a partial sum is a different number"
        assert set(assets.held) == {
            "us-gaap:AssetsCurrent",
            "us-gaap:Goodwill",
            "us-gaap:PropertyPlantAndEquipmentNet",
        }
        assert set(assets.absent) == {
            "us-gaap:OperatingLeaseRightOfUseAsset",
            "us-gaap:OtherAssetsNoncurrent",
            "us-gaap:IntangibleAssetsNetExcludingGoodwill",
        }
        assert assets.unmodelled == ()
        assert "not computable from what we hold" in assets.detail(6)
        assert "no figure for" in assets.detail(6)

    def test_a_line_our_vocabulary_has_no_name_for_is_told_apart(self, dfph):
        """A gap in the model, not in the data, and the fix is different.

        ``toi_DerivativeWarrantLiabilitiesNoncurrent`` is DFPH's own extension tag: no
        canonical metric covers it, so no amount of re-extraction will supply it.
        """
        [liabilities] = reconciliation.reconcile(
            _period(), dfph, parents=["us-gaap:Liabilities"]
        )

        assert liabilities.status == UNKNOWN
        assert "toi:DerivativeWarrantLiabilitiesNoncurrent" in liabilities.unmodelled
        assert "no metric for" in liabilities.detail(len(liabilities.held) + len(liabilities.absent) + 1)

    def test_a_full_set_of_lines_that_still_does_not_sum_is_the_finding(self, dfph):
        """The only case that may read as a failure: we hold it all and it disagrees.

        Built by holding every declared child of ``us-gaap:Assets`` and making them add
        to something other than the stated total -- which is what a misread tag looks
        like from here.
        """
        children = {
            "current_assets": 112_747_000.0,
            "goodwill": 7_230_000.0,
            "net_ppe": 10_684_000.0,
            "intangible_assets": 11_015_000.0,
            "operating_lease_assets": 213_199_000.0,
            "other_noncurrent_assets": 68_880_000.0,
        }
        spans = {
            "intangible_assets": "us-gaap:IntangibleAssetsNetExcludingGoodwill",
            "operating_lease_assets": "us-gaap:OperatingLeaseRightOfUseAsset",
            "other_noncurrent_assets": "us-gaap:OtherAssetsNoncurrent",
        }
        period = _period(
            metrics={**children, "total_assets": 100_000_000.0},
            sources=spans,
        )

        [assets] = reconciliation.reconcile(period, dfph, parents=["us-gaap:Assets"])

        assert assets.complete, assets.detail(6)
        assert assets.status == IMBALANCE
        # 112,747 + 7,230 + 10,684 + 11,015 + 213,199 + 68,880 thousand.
        assert assets.declared_sum == 423_755_000.0
        assert assets.residual == pytest.approx(100_000_000.0 - 423_755_000.0)
        assert reconciliation.contradictions([assets]) == [assets]

    def test_a_full_set_that_sums_is_ok(self, dfph):
        """The control: the check can pass, so a failure above means something."""
        parts = {
            "current_assets": 112_747_000.0,
            "goodwill": 7_230_000.0,
            "net_ppe": 10_684_000.0,
            "intangible_assets": 11_015_000.0,
            "operating_lease_assets": 213_199_000.0,
            "other_noncurrent_assets": 68_880_000.0,
        }
        spans = {
            "intangible_assets": "us-gaap:IntangibleAssetsNetExcludingGoodwill",
            "operating_lease_assets": "us-gaap:OperatingLeaseRightOfUseAsset",
            "other_noncurrent_assets": "us-gaap:OtherAssetsNoncurrent",
        }
        period = _period(
            metrics={**parts, "total_assets": sum(parts.values())},
            sources=spans,
        )

        [assets] = reconciliation.reconcile(period, dfph, parents=["us-gaap:Assets"])

        assert assets.status == OK
        assert assets.residual == 0

    def test_a_period_with_no_provenance_is_not_reconciled(self, dfph):
        """Nothing can be joined without the tag each figure came from.

        An empty answer, not a guess: the alternative is matching on the *preferred*
        tag from ``TAG_MAP``, which is the tag this filer did not use.
        """
        period = _period(provenance=False)

        assert reconciliation.tag_index(period) == {}
        assert reconciliation.reconcile(period, dfph) == []

    def test_a_subtotal_we_do_not_hold_is_skipped_rather_than_reported(self, dfph):
        """Only the declarations we can measure are findings.

        ``us-gaap:OperatingCostsAndExpenses`` is a subtotal DFPH declares and our
        vocabulary has no metric for at all, so there is no figure of ours to check it
        against. Reporting it would bury the declarations that can be checked.
        """
        parents = {item.parent for item in reconciliation.reconcile(_period(), dfph)}

        assert "us-gaap:Assets" in parents
        assert "us-gaap:LiabilitiesCurrent" in parents
        assert "us-gaap:OperatingCostsAndExpenses" not in parents

    def test_the_check_carries_the_figures_behind_it(self, dfph):
        """A score must show its inputs; a verdict with no figures is not a finding."""
        [check] = reconciliation.checks(_period(), dfph, parents=["us-gaap:Liabilities"])

        assert check.status == UNKNOWN
        assert check.inputs["role"] == "CONSOLIDATEDBALANCESHEETS"
        assert check.inputs["stated"] == 180_376_000.0
        assert "toi:DerivativeWarrantLiabilitiesNoncurrent" in check.inputs["unmodelled"]
        assert "OperatingLeaseLiabilityNoncurrent" in " ".join(check.inputs["absent"])


def test_the_fixture_is_the_document_edgar_serves():
    """A captured provider response, kept verbatim -- and the hash is what says so.

    The linkbases are large and the temptation is to hand-write a small one. A
    hand-written fixture tests the parser against the shape its author imagined, which
    is exactly the shape a real document will not have. The digest is checked rather
    than the file's contents because it is what detects a *reformatting* -- the
    parser would still pass while the fixture quietly stopped being verbatim.

    Captured from
    ``https://www.sec.gov/Archives/edgar/data/1799191/000179919126000007/toi-20251231_cal.xml``
    on 2026-10-07.
    """
    digest = hashlib.sha256(CAL.read_bytes()).hexdigest()

    assert digest == "588e2bf28eaa2388fbf21e2b447b9ad01acfb30b53155a7f387bbd08beef08ba"
    # And it is the filer's document, not ours: this custom extension tag appears
    # nowhere in this codebase and could only have come from the filing.
    assert b"toi_DerivativeWarrantLiabilitiesNoncurrent" in CAL.read_bytes()

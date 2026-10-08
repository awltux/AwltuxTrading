"""Reading a filing's linkbase from EDGAR, keeping it, and showing it on the page.

The parser and the reconciliation are tested in `test_linkbase.py` against DFPH's real
document. What is under test here is the wiring that was missing: the fetch by CIK and
accession, the stored copy the page reads instead of making a request, and the accounts
page rendering the filer's declared subtotals.

Offline throughout: the provider is a stub, because a test that reaches EDGAR is a bug.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from awltux.db import AppSetting, FundamentalPeriod
from awltux.ingest import linkbase as linkbases
from tests.helpers import make_instrument

CAL = Path(__file__).parent / "fixtures" / "dac-20251231_cal.xml"
PRE = Path(__file__).parent / "fixtures" / "dac_20251231_pre.xml"
LAB = Path(__file__).parent / "fixtures" / "dac_20251231_lab.xml"
ACCESSION = "0001104659-26-021574"


def _calculation(*args, **kwargs):
    """The calculation linkbase and its filename for a stubbed fetch.

    These tests were written when `fetch` returned that pair; it now returns all three
    trees at once, and this keeps them about the reconciliation rather than about the
    return shape. `TestTheOtherLinkbases` exercises the record itself.
    """
    read = linkbases.fetch(*args, **kwargs)
    return read.calculation, read.source


class StubEdgar:
    """The two calls :func:`linkbases.fetch` makes, and nothing else.

    Records what it was asked for, because "did it use the accession it was given" is
    the part of this that a wrong answer would still pass without.
    """

    def __init__(
        self,
        *,
        names: list[str] | None = None,
        document: bytes | None = None,
        facts: dict | None = None,
    ):
        self.names = names if names is not None else [
            "dac-20251231_cal.xml",
            "dac-20251231_pre.xml",
            "dac-20251231_lab.xml",
            "a.htm",
        ]
        self.document = document if document is not None else CAL.read_bytes()
        self.facts = facts if facts is not None else {"us-gaap": {}}
        self.index_calls: list[tuple] = []
        self.document_calls: list[tuple] = []
        self.facts_calls: list[str] = []

    def get_filing_index(self, cik, accession, **_kwargs):
        self.index_calls.append((cik, accession))
        return self.names

    def document_url(self, cik, accession, name=""):
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"

    def fetch_document(self, url, **_kwargs):
        self.document_calls.append(url)
        #  The body follows the filename, so a stub holding all three documents serves
        #  each of them. A stub that returned the calculation linkbase for every request
        #  would make `fetch` parse one document three times and still pass.
        body = self.document
        for suffix, path in (("_pre.xml", PRE), ("_lab.xml", LAB)):
            if url.endswith(suffix):
                body = path.read_bytes()
        return type("Document", (), {"url": url, "body": body})()

    def get_company_facts(self, cik, **_kwargs):
        self.facts_calls.append(cik)
        return {"facts": self.facts}


def instant(tag: str, value: float, end: str, *, taxonomy: str = "us-gaap") -> dict:
    """One instant fact, in the shape ``companyfacts`` serves it."""
    return {
        taxonomy: {
            tag: {
                "units": {
                    "USD": [
                        {"end": end, "val": value, "form": "20-F", "filed": "2026-02-27",
                         "accn": ACCESSION}
                    ]
                }
            }
        }
    }


def merge(*fragments: dict) -> dict:
    """Combine taxonomy fragments, extending a tag's unit series rather than replacing it.

    A plain ``update`` per taxonomy keeps only the *last* fragment's body for a tag, so
    two facts for the same concept collapse to one -- silently, and in the direction that
    looks like a parser bug. `test_xbrl_statements.py::combine` documents the same trap.
    """
    out: dict[str, dict] = {}
    for fragment in fragments:
        for taxonomy, tags in fragment.items():
            bucket = out.setdefault(taxonomy, {})
            for tag, body in tags.items():
                if tag not in bucket:
                    bucket[tag] = body
                    continue
                for unit, series in body["units"].items():
                    bucket[tag]["units"].setdefault(unit, []).extend(series)
    return out


class TestFindingTheDocument:
    def test_it_finds_the_calculation_linkbase_by_its_suffix(self):
        assert linkbases.find_calculation(["a.htm", "dac-20251231_cal.xml"]) == (
            "dac-20251231_cal.xml"
        )

    def test_a_filing_without_one_says_so_rather_than_guessing(self):
        """Filers are not required to publish one, and a guessed name is a 404."""
        assert linkbases.find_calculation(["a.htm", "b.xml"]) is None


class TestFetching:
    def test_it_reads_the_linkbase_for_the_accession_it_was_given(self):
        provider = StubEdgar()

        read = linkbases.fetch(provider, cik="1369241", accession=ACCESSION)

        assert read.source == "dac-20251231_cal.xml"
        assert provider.index_calls == [("1369241", ACCESSION)]
        #  All three documents, each addressed by the name the listing gave: the
        #  calculation linkbase is the arithmetic, and the other two are what turn a tag
        #  into the line the filing prints.
        assert provider.document_calls == [
            f"https://www.sec.gov/Archives/edgar/data/1369241/{ACCESSION}/dac-20251231_cal.xml",
            f"https://www.sec.gov/Archives/edgar/data/1369241/{ACCESSION}/dac-20251231_pre.xml",
            f"https://www.sec.gov/Archives/edgar/data/1369241/{ACCESSION}/dac-20251231_lab.xml",
        ]
        assert read.calculation is not None and read.calculation.calculations
        assert read.files == {
            "cal": "dac-20251231_cal.xml",
            "pre": "dac-20251231_pre.xml",
            "lab": "dac-20251231_lab.xml",
        }

    def test_the_real_document_declares_the_children_that_closed_the_gap(self):
        """Danaos's own balance sheet, and the two captions this app did not read.

        `AssetsCurrent` is out by 48,843,000 in our figures, and the filer declares it as
        six lines: the four we hold plus `OtherReceivablesNetCurrent` and
        `PrepaidExpenseCurrent`. `OtherAssetsCurrent` is a *sibling* of both, which is why
        adding `PrepaidExpenseCurrent` to it is right here and wrong for the filers whose
        linkbase declares `PrepaidExpenseAndOtherAssetsCurrent` as the whole bucket.
        """
        linkbase, _name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        assert linkbase is not None
        [current] = linkbase.for_parent("us-gaap:AssetsCurrent")

        assert [tag for tag, _weight in current.children] == [
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "us-gaap:AccountsReceivableNetCurrent",
            "us-gaap:InventoryNet",
            "us-gaap:PrepaidExpenseCurrent",
            "us-gaap:OtherReceivablesNetCurrent",
            "us-gaap:OtherAssetsCurrent",
        ]

    def test_a_filing_that_publishes_none_is_not_an_error(self):
        provider = StubEdgar(names=["a.htm"])

        linkbase, name = _calculation(provider, cik="1", accession=ACCESSION)

        assert linkbase is None
        assert name == ""
        assert provider.document_calls == [], "it must not fetch a document it cannot name"


class TestListingTheFilingDirectory:
    """The provider half, against a fake client rather than a stub provider.

    `StubEdgar` reimplements `document_url`, so it cannot catch a wrong URL -- and the
    first version of `get_filing_index` built `.../<accession>/<accession>/index.json` by
    rewriting the `-index.htm` URL (the accession appears twice in it) and got a 404 from
    EDGAR on the live container. This pins the address instead.
    """

    def _provider(self):
        from awltux.providers.edgar import EdgarProvider

        asked: list[str] = []

        class Client:
            def get_json(self, url, **_kwargs):
                asked.append(url)
                return {
                    "directory": {
                        "item": [
                            {"name": "dac-20251231_cal.xml"},
                            {"name": "dac-20251231.htm"},
                        ]
                    }
                }

        provider = EdgarProvider.__new__(EdgarProvider)
        provider._client = Client()  # type: ignore[assignment]
        return provider, asked

    def test_it_asks_for_the_directory_index_json(self):
        provider, asked = self._provider()

        names = provider.get_filing_index("1369241", ACCESSION)

        assert asked == [
            "https://www.sec.gov/Archives/edgar/data/1369241/000110465926021574/index.json"
        ]
        assert names == ["dac-20251231.htm", "dac-20251231_cal.xml"]

    def test_an_unexpected_payload_lists_nothing_rather_than_raising(self):
        """A filing we cannot list is one whose linkbase we cannot read, which the page
        says -- not an exception in a route."""
        from awltux.providers.edgar import EdgarProvider

        class Client:
            def get_json(self, url, **_kwargs):
                return {"unexpected": True}

        provider = EdgarProvider.__new__(EdgarProvider)
        provider._client = Client()  # type: ignore[assignment]

        assert provider.get_filing_index("1369241", ACCESSION) == []


class TestTheDeclaredChildrenWeHoldInsideASummedLine:
    """`other_current_assets` is one line to us and two to Danaos.

    The live page reported "the filer declares 6 lines here and we hold 3; no metric for
    PrepaidExpenseCurrent, OtherReceivablesNetCurrent" -- wrong twice: `OtherAssetsCurrent`
    and `OtherReceivablesNetCurrent` are the two tags of one metric we *do* hold, and the
    first version could not see that because it joined on the whole span. This pins the
    arithmetic that fixes it: the summed line counts once, and only the caption that is
    genuinely absent is reported absent.
    """

    def _period(self) -> FundamentalPeriod:
        linkbase, _name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        metrics = {
            "current_assets": 1_319_419_000.0,
            "cash_and_equivalents": 1_037_292_000.0,
            "receivables": 38_730_000.0,
            "inventory": 23_417_000.0,
            # The two tags Danaos declares separately, summed into one line of ours.
            "other_current_assets": 217_887_000.0,
        }
        spans = {
            "current_assets": "us-gaap:AssetsCurrent",
            "cash_and_equivalents": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "receivables": "us-gaap:AccountsReceivableNetCurrent",
            "inventory": "us-gaap:InventoryNet",
            "other_current_assets": "us-gaap:OtherAssetsCurrent+OtherReceivablesNetCurrent",
        }
        return FundamentalPeriod(
            instrument_t212_ticker="DAC_US_EQ",
            period_end=dt.date(2025, 12, 31),
            period_type="annual",
            source="xbrl_companyfacts",
            metrics=metrics,
            metric_sources={
                metric: {"value": metrics[metric], "span": span, "accession": ACCESSION}
                for metric, span in spans.items()
            },
        )

    def _declaration(self):
        linkbase, _name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        from awltux.analysis import linkbase as reconciliation

        [declaration] = reconciliation.reconcile(
            self._period(), linkbase, parents=["us-gaap:AssetsCurrent"]
        )
        return declaration

    def test_the_summed_line_is_counted_once_not_twice(self):
        declaration = self._declaration()

        # 1,037,292 + 38,730 + 23,417 + 217,887 thousand: five of the six declared lines,
        # with the bucket counted once for the two tags it sums.
        assert set(declaration.held) == {
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "us-gaap:AccountsReceivableNetCurrent",
            "us-gaap:InventoryNet",
            "us-gaap:OtherAssetsCurrent",
            "us-gaap:OtherReceivablesNetCurrent",
        }
        # And the one line left is *unmodelled* rather than "a figure we lack": there is no
        # canonical metric for a prepaid-expense line, which is the finding the page has to
        # report -- widening an extraction would never produce it.
        assert declaration.unmodelled == ("us-gaap:PrepaidExpenseCurrent",)
        assert declaration.absent == ()
        assert declaration.pooled == ()
        assert declaration.declared_sum is None, "one declared line has no metric"
        detail = declaration.detail(6)
        assert "we hold 5" in detail and "no metric for us-gaap:PrepaidExpenseCurrent" in detail

    def test_a_child_left_out_of_the_declaration_is_reported_as_pooled(self):
        """We hold it inside a line summing other captions, so its share is unknown.

        Built by holding the bucket while the filer declares *one* of its two tags: the
        line's figure covers the tag and something else, so attributing it to the tag
        would be inventing a split the filing does not make.
        """
        from awltux.analysis import linkbase as reconciliation
        from awltux.ingest.linkbase import Calculation, Linkbase

        only_one = Linkbase(
            calculations=(
                Calculation(
                    role="CONSOLIDATEDBALANCESHEETS",
                    parent="us-gaap:AssetsCurrent",
                    children=(("us-gaap:OtherAssetsCurrent", 1.0),),
                ),
            )
        )

        [declaration] = reconciliation.reconcile(
            self._period(), only_one, parents=["us-gaap:AssetsCurrent"]
        )

        assert declaration.pooled == ("us-gaap:OtherAssetsCurrent",)
        assert declaration.complete is False
        assert "sums several captions" in declaration.detail(1)


class TestPricingTheLinesWeDoNotHold:
    """`declared_values`: the filer's own figure for each concept it declares.

    This is what turns "no metric for PrepaidExpenseCurrent" into that sentence *with*
    2,093,000 beside it -- the size of the gap, from the filing rather than from our
    arithmetic.
    """

    PAYLOAD = {
        "facts": merge(
            instant("PrepaidExpenseCurrent", 2_093_000.0, "2025-12-31"),
            instant("PrepaidExpenseCurrent", 1_800_000.0, "2024-12-31"),
            instant("PrepaidExpenseCurrent", 900_000.0, "2025-09-30"),
            instant("DepositsAssetsNoncurrent", 428_147_000.0, "2025-12-31"),
            # A fact in the wrong unit is not the figure, and must not be priced as one.
            {
                "us-gaap": {
                    "DeferredCosts": {
                        "units": {"shares": [{"end": "2025-12-31", "val": 5.0, "form": "20-F"}]}
                    }
                }
            },
        )
    }

    def test_it_reads_each_declared_concept_at_the_period_end(self):
        values = linkbases.declared_values(
            self.PAYLOAD,
            ["us-gaap:PrepaidExpenseCurrent", "us-gaap:DepositsAssetsNoncurrent"],
            ends=["2025-12-31"],
        )

        assert values == {
            "2025-12-31": {
                "us-gaap:PrepaidExpenseCurrent": 2_093_000.0,
                "us-gaap:DepositsAssetsNoncurrent": 428_147_000.0,
            }
        }

    def test_only_the_period_ends_we_hold_are_kept(self):
        """Otherwise the record grows four figures a year to answer about one date.

        The quarter end (2025-09-30) and the comparative year (2024-12-31) are both in the
        payload; the caller asks for the dates its own `fundamental_period` rows carry.
        """
        values = linkbases.declared_values(
            self.PAYLOAD, ["us-gaap:PrepaidExpenseCurrent"], ends=["2025-12-31"]
        )

        assert set(values) == {"2025-12-31"}

    def test_it_reads_every_end_when_none_is_given(self):
        values = linkbases.declared_values(self.PAYLOAD, ["us-gaap:PrepaidExpenseCurrent"])

        assert set(values) == {"2024-12-31", "2025-09-30", "2025-12-31"}

    def test_a_concept_in_the_wrong_unit_is_not_priced(self):
        """A share count read as dollars is worse than no figure at all."""
        values = linkbases.declared_values(self.PAYLOAD, ["us-gaap:DeferredCosts"])

        assert values == {}

    def test_a_concept_the_filer_never_tagged_is_absent_rather_than_zero(self):
        values = linkbases.declared_values(self.PAYLOAD, ["us-gaap:NothingLikeThis"])

        assert values == {}


class TestTheFilersArithmeticReplacingOurs:
    """`declared_sums`: the filer's own children, summed from the figures we hold.

    This is the arithmetic the ledger prints as the computed column and checks against the
    stated total. Its two failure modes are both measured here: summing one level down
    (which reaches subtotals we have no metric for and stops) and walking every role at
    once (which pulls a footnote's breakdown into the balance sheet's sum).
    """

    PERIOD = None  # built per test from `_period` below

    def _period(self) -> FundamentalPeriod:
        metrics = {
            "total_assets": 5_113_930_000.0,
            "current_assets": 1_319_419_000.0,
            "current_liabilities": 401_676_000.0,
            "total_liabilities": 1_318_353_000.0,
            "cash_and_equivalents": 1_037_292_000.0,
            "receivables": 38_730_000.0,
            "inventory": 23_417_000.0,
            "other_current_assets": 217_887_000.0,
            "net_ppe": 3_269_703_000.0,
            "other_noncurrent_assets": 42_305_000.0,
            "payables": 17_274_000.0,
            "compensation_and_benefits": 28_772_000.0,
            "other_current_liabilities": 35_990_000.0,
            "short_term_debt": 283_015_000.0,
            "long_term_debt": 872_076_000.0,
            "other_noncurrent_liabilities": 41_983_000.0,
        }
        spans = {
            "total_assets": "us-gaap:Assets",
            "current_assets": "us-gaap:AssetsCurrent",
            "current_liabilities": "us-gaap:LiabilitiesCurrent",
            "total_liabilities": "us-gaap:Liabilities",
            "cash_and_equivalents": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "receivables": "us-gaap:AccountsReceivableNetCurrent",
            "inventory": "us-gaap:InventoryNet",
            "other_current_assets": "us-gaap:OtherAssetsCurrent+OtherReceivablesNetCurrent",
            "net_ppe": "us-gaap:PropertyPlantAndEquipmentNet",
            "other_noncurrent_assets": "us-gaap:OtherAssetsNoncurrent",
            "payables": "us-gaap:AccountsPayableCurrent",
            "compensation_and_benefits": "us-gaap:AccruedLiabilitiesCurrent",
            "other_current_liabilities": "us-gaap:OtherLiabilitiesCurrent",
            "short_term_debt": "us-gaap:LongTermDebtCurrent",
            "long_term_debt": "us-gaap:LongTermDebtNoncurrent",
            "other_noncurrent_liabilities": "us-gaap:OtherLiabilitiesNoncurrent",
        }
        return FundamentalPeriod(
            instrument_t212_ticker="DAC_US_EQ",
            period_end=dt.date(2025, 12, 31),
            period_type="annual",
            source="xbrl_companyfacts",
            currency="USD",
            metrics=metrics,
            metric_sources={
                metric: {"value": metrics[metric], "span": span, "accession": ACCESSION}
                for metric, span in spans.items()
            },
        )

    def _linkbase(self):
        linkbases_read, _name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        return linkbases_read

    def _sums(self, figures=None):
        from awltux.analysis import linkbase as reconciliation

        return reconciliation.declared_sums(self._period(), self._linkbase(), figures=figures)

    def test_it_walks_to_the_leaves_rather_than_one_level_down(self):
        """`Assets` is declared as two subtotals we have no metric for.

        `AssetsCurrent` and `AssetsNoncurrent` are the filer's own subtotals; stopping at
        them would leave total assets computed from nothing. The money is at the bottom.
        """
        sums = self._sums()

        assert sums["current_assets"].total == 1_317_326_000.0
        # 1,037,292 + 38,730 + 23,417 + 217,887 thousand.
        assert sums["total_assets"].missing == (
            "us-gaap:PrepaidExpenseCurrent",
            "us-gaap:DepositsAssetsNoncurrent",
            "us-gaap:DeferredCosts",
        )
        # Every missing line accounts for the whole residual -- but only once the filer's
        # own figures for them are to hand, which is what the next test supplies.
        assert sums["current_assets"].missing == ("us-gaap:PrepaidExpenseCurrent",)
        assert sums["current_assets"].missing_total is None
        assert sums["current_assets"].complete is False

    def test_a_footnote_breakdown_does_not_join_the_statement_sum(self):
        """`OtherAssetsCurrent` is a leaf on the balance sheet and a parent in a footnote.

        Measured on this filing: the balance sheet declares it as one line of
        `AssetsCurrent`, while `DisclosureOtherCurrentAndNonCurrentAssetsDetails` breaks
        it into four. Walking every role together expanded it, so `MarketableSecurities`
        and a custom extension tag appeared as "lines we do not hold" -- none of which is
        true of the balance sheet the check is about -- and the sum would double count.
        """
        sums = self._sums()

        missing = " ".join(sums["current_assets"].missing)
        assert "MarketableSecuritiesCurrent" not in missing
        assert "StraightLiningOfCompanySRevenueCurrentAssets" not in missing

    def test_the_filers_own_figures_price_every_missing_line(self):
        figures = {
            "us-gaap:PrepaidExpenseCurrent": 2_093_000.0,
            "us-gaap:DepositsAssetsNoncurrent": 428_147_000.0,
            "us-gaap:DeferredCosts": 54_356_000.0,
        }

        sums = self._sums(figures=figures)

        assert sums["total_assets"].missing_total == 484_596_000.0
        assert "us-gaap:DeferredCosts (54,356,000)" in sums["total_assets"].missing
        # The current-assets gap is one line, and it is the whole of that residual:
        # 1,319,419 - 1,317,326 = 2,093,000.
        assert sums["current_assets"].missing_total == 2_093_000.0

    def test_a_partly_priced_gap_is_not_called_an_explanation(self):
        """A partial price would read as explaining the residual while leaving some of it.

        Only `PrepaidExpenseCurrent` is priced here, and the assets residual is 484,596,000,
        so `missing_total` must stay unset rather than showing 2,093,000 as the answer.
        """
        sums = self._sums(figures={"us-gaap:PrepaidExpenseCurrent": 2_093_000.0})

        assert sums["total_assets"].missing_total is None

    def test_the_ledger_uses_it_and_says_the_residual_is_those_lines(self):
        """The verdict a reader acts on: *not computable*, and nothing else unexplained."""
        from awltux.analysis import ledger

        figures = {
            "us-gaap:PrepaidExpenseCurrent": 2_093_000.0,
            "us-gaap:DepositsAssetsNoncurrent": 428_147_000.0,
            "us-gaap:DeferredCosts": 54_356_000.0,
            "us-gaap:ContractWithCustomerLiabilityCurrent": 36_625_000.0,
            "us-gaap:ContractWithCustomerLiabilityNoncurrent": 2_618_000.0,
        }
        declared = self._sums(figures=figures)

        checks = {c.key: c for c in ledger.composition(self._period(), declared=declared)}

        assets = checks["assets_composition"]
        assert assets.status == ledger.UNKNOWN
        assert assets.residual == 484_596_000.0
        assert assets.inputs["explained"] is True
        assert "exactly those lines" in assets.detail
        assert "the filer's own declared lines" in assets.detail
        # And the current-assets subtotal, whose only missing line is the prepayment.
        current = checks["current_assets_composition"]
        assert current.residual == 2_093_000.0
        assert current.inputs["explained"] is True

    def test_without_a_declaration_the_check_is_unchanged(self):
        """The control: no stored linkbase means our own key list, exactly as before."""
        from awltux.analysis import ledger

        checks = {c.key: c for c in ledger.composition(self._period())}

        assert "the filer's own declared lines" not in checks["assets_composition"].detail
        assert checks["assets_composition"].residual == 484_596_000.0
        assert checks["assets_composition"].status == ledger.IMBALANCE


class TestTheOtherLinkbases:
    """The presentation and label trees: the order, the statement, and the filer's words.

    The calculation linkbase says what sums to what. These two say *where* a line is
    printed and *what the filer calls it* -- and the second is what turns
    `us-gaap:PrepaidExpenseCurrent` into "Prepaid expenses" on the page, which is the
    difference between a report a reader can act on and one they have to translate.
    """

    def _read(self):
        return linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)

    def test_the_presentation_tree_is_kept_for_the_statements_we_check(self):
        read = self._read()

        assert read.presentation is not None
        assert "StatementConsolidatedBalanceSheets" in read.presentation.roles
        #  The notes are dropped: `DAC_US_EQ`'s presentation document is 647 KB and the
        #  statement roles are 89 KB of it, and nothing asks about a note's order.
        assert all(role.startswith("Statement") for role in read.presentation.roles)

    def test_the_presentation_tree_gives_a_position_in_the_statement(self):
        """Where the line we are missing is printed, counting from the top."""
        read = self._read()
        assert read.presentation is not None

        heading = read.presentation.children(
            "StatementConsolidatedBalanceSheets", "us-gaap:AssetsCurrentAbstract"
        )

        assert "us-gaap:CashAndCashEquivalentsAtCarryingValue" in heading
        assert read.presentation.position(
            "StatementConsolidatedBalanceSheets", "us-gaap:PrepaidExpenseCurrent"
        ) == 4

    def test_the_labels_are_the_words_the_filing_prints(self):
        """Not the taxonomy's generic caption, and that is the whole reason to read them.

        `us-gaap:ContractWithCustomerLiabilityCurrent` has a standard label of "Contract
        with Customer, Liability, Current" and a terse label of "Unearned revenue"; the
        terse one is what Danaos prints. `DeferredCosts` is "Deferred charges, net" rather
        than "Deferred Costs, Noncurrent".
        """
        read = self._read()
        assert read.labels is not None

        assert read.labels.name("us-gaap:PrepaidExpenseCurrent") == "Prepaid expenses"
        assert read.labels.name("us-gaap:OtherReceivablesNetCurrent") == "Due from related parties"
        assert read.labels.name("us-gaap:DeferredCosts") == "Deferred charges, net"
        assert read.labels.name("us-gaap:ContractWithCustomerLiabilityCurrent") == "Unearned revenue"
        #  A subtotal's total label, which is what the statement prints above the sum.
        assert read.labels.totals["us-gaap:AssetsCurrent"] == "Total current assets"
        assert read.labels.name("us-gaap:AssetsCurrent") == "Assets, Current", (
            "the standard label is the name where the filer gave no terse one"
        )

    def test_a_concept_with_no_label_keeps_its_tag(self):
        """A missing label is not a missing line: the reader still needs to know which."""
        from awltux.ingest.linkbase import Labels

        assert Labels().name("us-gaap:SomethingNobodyLabelled") == "us-gaap:SomethingNobodyLabelled"

    def test_the_trees_survive_the_round_trip_through_the_store(self, session):
        read = self._read()
        linkbases.save(
            session,
            ACCESSION,
            read.calculation,
            source=read.source,
            cik="1369241",
            presentation=read.presentation,
            labels=read.labels,
            files=read.files,
        )

        loaded = linkbases.stored(session, ACCESSION)

        assert loaded is not None
        assert loaded.presentation.links == read.presentation.links
        assert loaded.labels.names == read.labels.names
        assert loaded.labels.totals == read.labels.totals
        assert loaded.files["lab"] == "dac-20251231_lab.xml"


class TestKeepingIt:
    def test_a_stored_linkbase_round_trips_with_its_filename(self, session):
        """The page reads SQLite; the filename is the citation it prints.

        Compared on ``calculations`` rather than on the whole object, because
        ``bytes_read`` is a fact about the parse and a stored copy has no bytes --
        `test_linkbase.py` draws the same line for the same reason.
        """
        linkbase, name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)

        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")

        stored_record = linkbases.stored(session, ACCESSION)
        assert stored_record.linkbase.calculations == linkbase.calculations
        assert stored_record.source == "dac-20251231_cal.xml"
        row = session.get(AppSetting, linkbases.setting_key(ACCESSION))
        assert row is not None and row.value["cik"] == "1369241"

    def test_storing_it_twice_replaces_rather_than_duplicates(self, session):
        linkbase, name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")

        rows = session.query(AppSetting).filter(
            AppSetting.key == linkbases.setting_key(ACCESSION)
        ).all()

        assert len(rows) == 1

    def test_nothing_stored_is_none_rather_than_an_empty_linkbase(self, session):
        """An empty tree would render as "the filer declares nothing", which is a claim."""
        assert linkbases.stored(session, ACCESSION) is None
        assert linkbases.stored(session, "") is None

    def test_forgetting_it_is_possible(self, session):
        """A wrong read must not be permanent."""
        linkbase, name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")

        assert linkbases.forget(session, ACCESSION) is True
        assert linkbases.stored(session, ACCESSION) is None
        assert linkbases.forget(session, ACCESSION) is False


class TestThePage:
    @pytest.fixture
    def filer(self, session):
        """Danaos, with the period as stored: the figures 22a27aa produced."""
        instrument = make_instrument("DAC_US_EQ", name="Danaos", sector="Industrials")
        instrument.sec_cik = "0001369241"
        session.add(instrument)
        session.flush()
        return instrument

    def _period(self, session) -> FundamentalPeriod:
        metrics = {
            "total_assets": 5_113_930_000.0,
            "current_assets": 1_319_419_000.0,
            "current_liabilities": 401_676_000.0,
            "total_liabilities": 1_318_353_000.0,
            "cash_and_equivalents": 1_037_292_000.0,
            "receivables": 38_730_000.0,
            "inventory": 23_417_000.0,
            "other_current_assets": 217_887_000.0,
            "net_ppe": 3_269_703_000.0,
            "other_noncurrent_assets": 42_305_000.0,
            # A figure we hold that our *own* component list does not name. It is here
            # because it is the whole difference the declaration makes: `ledger`'s
            # NON_CURRENT_ASSET_KEYS has no entry for it, while the filer declares
            # `DepositsAssetsNoncurrent` as a line of its balance sheet -- so the computed
            # total moves by exactly this when the declaration is applied.
            "deposits_noncurrent": 428_147_000.0,
        }
        spans = {
            "total_assets": "us-gaap:Assets",
            "current_assets": "us-gaap:AssetsCurrent",
            "current_liabilities": "us-gaap:LiabilitiesCurrent",
            "total_liabilities": "us-gaap:Liabilities",
            "cash_and_equivalents": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "receivables": "us-gaap:AccountsReceivableNetCurrent",
            "inventory": "us-gaap:InventoryNet",
            "other_current_assets": "us-gaap:OtherAssetsCurrent+OtherReceivablesNetCurrent",
            "net_ppe": "us-gaap:PropertyPlantAndEquipmentNet",
            "other_noncurrent_assets": "us-gaap:OtherAssetsNoncurrent",
            "deposits_noncurrent": "us-gaap:DepositsAssetsNoncurrent",
        }
        period = FundamentalPeriod(
            instrument_t212_ticker="DAC_US_EQ",
            period_end=dt.date(2025, 12, 31),
            period_type="annual",
            source="xbrl_companyfacts",
            currency="USD",
            metrics=metrics,
            metric_sources={
                metric: {"value": metrics[metric], "span": span, "accession": ACCESSION}
                for metric, span in spans.items()
            },
        )
        session.add(period)
        session.commit()
        return period

    def test_it_offers_to_read_the_filings_arithmetic(self, client, session, filer):
        period = self._period(session)

        body = client.get(f"/accounts/{period.id}/health").text

        assert "Not read yet" in body
        assert f'action="/accounts/{period.id}/linkbase"' in body

    def test_a_stored_linkbase_is_shown_as_declared_subtotals(self, client, session, filer):
        period = self._period(session)
        linkbase, name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")
        session.commit()

        body = " ".join(client.get(f"/accounts/{period.id}/health").text.split())

        assert "The filer&#39;s own arithmetic" in body or "filer" in body.lower()
        assert "Declared: us-gaap:AssetsCurrent" in body
        assert "no figure for OtherReceivablesNetCurrent" not in body, (
            "we hold that caption now — it is a sibling inside other_current_assets"
        )
        assert "PrepaidExpenseCurrent" in body, "the line we still do not hold is named"
        assert "dac-20251231_cal.xml" in body

    def test_a_missing_line_carries_the_filers_own_figure(self, client, session, filer):
        """Named *and valued*: the figure is what says whether the gap is worth closing.

        Stored the way the POST stores it -- the figures come from the companyfacts
        payload at the same time as the linkbase, and the page reads them from SQLite.
        """
        period = self._period(session)
        read = linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(
            session,
            ACCESSION,
            read.calculation,
            source=read.source,
            cik="1369241",
            values={"2025-12-31": {"us-gaap:PrepaidExpenseCurrent": 2_093_000.0}},
            presentation=read.presentation,
            labels=read.labels,
        )
        session.commit()

        body = " ".join(client.get(f"/accounts/{period.id}/health").text.split())

        #  The filer's own words for the line, then its own figure for it.
        assert "Prepaid expenses (2,093,000)" in body, body[
            body.find("filer") : body.find("filer") + 600
        ]
        assert "us-gaap:PrepaidExpenseCurrent (2,093,000)" not in body, (
            "the tag is the precise identifier, but it is not what the page should say"
        )

    def test_the_page_reads_sqlite_and_makes_no_request(self, client, session, filer, monkeypatch):
        """A render must not fetch: the POST is where the network call lives.

        Patched at the provider class itself rather than at the route module's namespace,
        which is where the route imports it from -- a patch that lands nowhere would let
        this pass while the page happily phoned EDGAR.
        """
        period = self._period(session)
        linkbase, name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")
        session.commit()

        def explode(*_args, **_kwargs):
            raise AssertionError("the accounts page fetched from EDGAR")

        monkeypatch.setattr("awltux.providers.edgar.EdgarProvider", explode)

        body = client.get(f"/accounts/{period.id}/health").text

        assert "dac-20251231_cal.xml" in body, "and it renders what it has stored"

    def test_the_balance_sheet_computes_from_the_filers_own_lines(self, client, session, filer):
        """The statement's Computed column is the declaration's sum once one is stored.

        Built so the two disagree: our key list holds no `DepositsAssetsNoncurrent`, so the
        old computed total assets was short by it; the filer declares it, so with the
        declaration the figure includes it and the residual shrinks to the one line
        neither of us can supply without a metric.
        """
        period = self._period(session)
        linkbase, name = _calculation(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(
            session,
            ACCESSION,
            linkbase,
            source=name,
            cik="1369241",
            values={
                "2025-12-31": {
                    "us-gaap:PrepaidExpenseCurrent": 2_093_000.0,
                    "us-gaap:DepositsAssetsNoncurrent": 428_147_000.0,
                    "us-gaap:DeferredCosts": 54_356_000.0,
                }
            },
        )
        session.commit()

        with_declaration = " ".join(
            client.get(f"/accounts/{period.id}/balance_sheet").text.split()
        )

        # The filer declares `DepositsAssetsNoncurrent`, which we hold and our own key list
        # ignores: 4,629,334,000 + 428,147,000 = 5,057,481,000.
        assert "5,057,481,000" in with_declaration, with_declaration[
            with_declaration.find("Total assets"): with_declaration.find("Total assets") + 200
        ]
        # And the health tab explains the residual rather than leaving it open.
        health = " ".join(client.get(f"/accounts/{period.id}/health").text.split())
        assert "exactly those lines" in health
        assert "the filer&#39;s own declared lines" in health or "the filer's own declared lines" in health

    def test_the_page_does_not_use_a_declaration_it_does_not_have(self, client, session, filer):
        """No stored linkbase means the old computed column, exactly as before."""
        period = self._period(session)

        body = " ".join(client.get(f"/accounts/{period.id}/balance_sheet").text.split())

        assert "4,629,334,000" in body
        assert "the filer" not in body.split("Total assets")[1][:400]

    def test_reading_it_stores_it_and_says_so(self, client, session, filer, monkeypatch):
        period = self._period(session)
        provider = StubEdgar()
        monkeypatch.setattr(
            "awltux.providers.edgar.EdgarProvider", lambda *a, **k: provider
        )

        response = client.post(f"/accounts/{period.id}/linkbase", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == (
            f"/accounts/{period.id}/health?linkbase=read#filer-arithmetic"
        )
        assert linkbases.stored(session, ACCESSION) is not None

    def test_a_failure_is_reported_rather_than_500ing(self, client, session, filer, monkeypatch):
        from awltux.providers.edgar import ProviderError

        period = self._period(session)

        class Broken:
            def get_filing_index(self, *_args, **_kwargs):
                raise ProviderError("edgar", "the SEC refused us")

        monkeypatch.setattr("awltux.providers.edgar.EdgarProvider", lambda *a, **k: Broken())

        response = client.post(f"/accounts/{period.id}/linkbase", follow_redirects=False)

        assert response.status_code == 303
        assert "linkbase=failed" in response.headers["location"]

    def test_a_period_with_no_accession_says_which_case_it_is(self, client, session, filer):
        """A Yahoo or model-read period has no filing to read, and that is not a failure."""
        period = FundamentalPeriod(
            instrument_t212_ticker="DAC_US_EQ",
            period_end=dt.date(2024, 12, 31),
            period_type="annual",
            source="yahoo_statements",
            currency="USD",
            metrics={"total_assets": 1.0},
            metric_sources=None,
        )
        session.add(period)
        session.commit()

        body = client.get(f"/accounts/{period.id}/health").text

        assert "no accession" in body

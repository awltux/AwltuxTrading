"""Correcting a period's accounts by hand, and the record of what was corrected.

Asked for directly: *"Lines in an account section must be deleteable, as I've found mistakes in
the automated extraction process."* The tests below are about three properties, and none of them
is layout:

* a correction reaches the **stored** figures rather than one page's rendering of them, so the
  ledger, the checks and every consumer of the row see the corrected accounts;
* it can be undone, and undoing it puts back what the extractor had said;
* it says what it displaced, because the record is the evidence for the edit.

`tests/test_ledger.py` owns the arithmetic; this file owns the editing of it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from bs4 import BeautifulSoup

from awltux.analysis import corrections, ledger
from awltux.db import AppSetting, FundamentalPeriod, Instrument
from tests.helpers import make_instrument

CIK = "0000320193"

#: A small, self-consistent set of accounts: enough for the profit and loss, the balance sheet
#: and the composition checks to have something to say, and small enough that a test's failure
#: is readable.
FIGURES = {
    "revenue": 1_000.0,
    "cost_of_goods_sold": 600.0,
    "gross_profit": 400.0,
    "research_and_development": 50.0,
    "sga_expense": 150.0,
    "depreciation_amortisation": 40.0,
    "operating_income": 160.0,
    "pretax_income": 140.0,
    "tax_expense": 30.0,
    "net_income": 110.0,
    "cash_and_equivalents": 200.0,
    "receivables": 100.0,
    "inventory": 120.0,
    "current_assets": 420.0,
    "net_ppe": 300.0,
    "goodwill": 80.0,
    "intangible_assets": 50.0,
    "total_assets": 850.0,
    "payables": 90.0,
    "short_term_debt": 40.0,
    "current_liabilities": 130.0,
    "long_term_debt": 200.0,
    "total_liabilities": 360.0,
    "total_equity": 490.0,
    "retained_earnings": 300.0,
}


def _sources(*metrics: str, span: str = "us-gaap:Revenues") -> dict:
    """Provenance for a few figures, in the shape `ingest/xbrl.py` writes it."""
    return {
        name: {
            "value": FIGURES[name],
            "source": "xbrl_companyfacts",
            "span": span,
            "unit": "USD",
            "accession": "0000320193-24-000123",
            "form": "10-K",
        }
        for name in metrics
    }


def _period(
    ticker: str,
    period_end: dt.date,
    metrics: dict | None = None,
    *,
    sources: dict | None = None,
    source: str = "xbrl_companyfacts",
) -> FundamentalPeriod:
    return FundamentalPeriod(
        instrument_t212_ticker=ticker,
        period_end=period_end,
        period_type="annual",
        currency="USD",
        source=source,
        metrics=dict(metrics if metrics is not None else FIGURES),
        metric_sources=sources,
        confidence=0.9,
    )


def _store(session, ticker: str, *periods, cik: str | None = CIK):
    """The filer, then its periods, committed -- a request runs on another session."""
    session.add(make_instrument(ticker, name="Test Co", sec_cik=cik))
    session.flush()
    for period in periods:
        session.add(period)
    session.flush()
    session.commit()
    return periods[-1] if periods else None


@pytest.fixture
def two_years(session):
    """One filer with two comparable years, and the newer period's id."""
    return _store(
        session,
        "TEST_US_EQ",
        _period(
            "TEST_US_EQ",
            dt.date(2023, 12, 31),
            {**FIGURES, "retained_earnings": 250.0},
        ),
        _period("TEST_US_EQ", dt.date(2024, 12, 31), sources=_sources("revenue", "sga_expense")),
    )


def _row(session, period_id: int) -> FundamentalPeriod:
    """The row as the database now holds it, after a request has written to it."""
    session.expire_all()
    return session.get(FundamentalPeriod, period_id)


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #


class TestApplyingACorrection:
    """`apply` is pure and is the only place the arithmetic of correcting lives."""

    def test_a_removed_line_is_gone_and_says_it_was_removed(self):
        record = corrections.Record(
            removed={"inventory": corrections.Removal(metric="inventory", was=120.0)}
        )

        metrics, sources = corrections.apply(
            {"inventory": 120.0, "revenue": 1_000.0},
            {"inventory": {"value": 120.0, "span": "us-gaap:InventoryNet"}},
            record,
        )

        assert "inventory" not in metrics
        assert sources["inventory"]["removed"]["was"] == 120.0, (
            "the provenance stays and records the removal: it is what ties the edit to the "
            "filing the line came from"
        )
        assert sources["inventory"]["span"] == "us-gaap:InventoryNet", "and keeps the tag"

    def test_an_added_line_is_written_with_manual_provenance(self):
        record = corrections.Record(
            added={
                "operating_lease_assets": corrections.Correction(
                    metric="operating_lease_assets", value=168.0, side="debit", tag="us-gaap:X"
                )
            }
        )

        metrics, sources = corrections.apply({}, None, record)

        assert metrics["operating_lease_assets"] == 168.0
        assert sources["operating_lease_assets"]["source"] == corrections.MANUAL

    def test_an_addition_overrides_a_filer_rule_that_removed_the_same_line(self):
        """The order is part of the contract: a reader who removed a line everywhere and then
        puts a figure on it in one period means it. The other way round there is no way to
        override a rule you made earlier."""
        rules = corrections.Rules(removed={"inventory": corrections.Removal(metric="inventory")})
        record = corrections.Record(
            added={"inventory": corrections.Correction(metric="inventory", value=99.0)}
        )

        metrics, _ = corrections.apply({"inventory": 120.0}, None, record, rules)

        assert metrics["inventory"] == 99.0

    def test_a_derived_ratio_is_recomputed_rather_than_left_stale(self):
        """A margin computed from a component that has just been removed is a figure claiming
        to describe the corrected accounts, so the derived set is dropped and derived again
        from what is left."""
        record = corrections.Record(
            removed={"gross_profit": corrections.Removal(metric="gross_profit")}
        )

        metrics, _ = corrections.apply(
            {
                "revenue": 1_000.0,
                "gross_profit": 400.0,
                "gross_margin": 0.4,
                "operating_income": 200.0,
            },
            None,
            record,
        )

        assert "gross_margin" not in metrics, "the ratio went with the figure it was made from"
        assert metrics["operating_margin"] == pytest.approx(0.2), (
            "and the ones that can still be computed are computed, not carried over"
        )

    def test_a_removal_that_has_been_undone_does_not_keep_its_marker(self):
        """`apply` rebuilds the markers from the record every time, so a line that has been put
        back cannot still be carrying the word "removed" in its provenance."""
        sources = {"inventory": {"value": 120.0, "removed": {"was": 120.0}}}

        _, rebuilt = corrections.apply({"inventory": 120.0}, sources, corrections.Record())

        assert "removed" not in rebuilt["inventory"]


class TestTheRecord:
    def test_a_correction_round_trips_through_json_including_what_it_displaced(self):
        record = corrections.Record(
            added={
                "net_ppe": corrections.Correction(
                    metric="net_ppe",
                    value=5.0,
                    was=300.0,
                    was_source={"value": 300.0, "span": "us-gaap:PropertyPlantAndEquipmentNet"},
                )
            },
            removed={"inventory": corrections.Removal(metric="inventory", was=120.0, tag="t")},
        )

        restored = corrections.Record.from_dict(record.as_dict())

        assert restored.added["net_ppe"].was == 300.0
        assert restored.added["net_ppe"].was_source["span"] == (
            "us-gaap:PropertyPlantAndEquipmentNet"
        )
        assert restored.removed["inventory"].was == 120.0
        assert restored.removed["inventory"].tag == "t"

    def test_the_filer_rules_live_in_app_setting_under_the_cik(self, session):
        rules = corrections.Rules(
            removed={"inventory": corrections.Removal(metric="inventory", was=120.0)}
        )

        corrections.save_filer(session, CIK, rules)

        key = f"{corrections.SETTING_PREFIX}{CIK}"
        assert session.get(AppSetting, key) is not None
        assert corrections.load_filer(session, CIK).removed["inventory"].was == 120.0

    def test_forgetting_the_last_rule_deletes_the_record_rather_than_leaving_it_empty(self, session):
        rules = corrections.Rules(removed={"inventory": corrections.Removal(metric="inventory")})
        corrections.save_filer(session, CIK, rules)

        rules.removed.clear()
        corrections.save_filer(session, CIK, rules)

        assert session.get(AppSetting, f"{corrections.SETTING_PREFIX}{CIK}") is None


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #


class TestTheAffordancesAreOnThePage:
    def test_every_stated_line_offers_a_removal(self, client, session, two_years):
        soup = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/profit_and_loss").text, "lxml"
        )

        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Revenue" in item.get_text(" ")
        )

        assert row.select_one("td.act a")["href"] == (
            f"/accounts/{two_years.id}/corrections/new"
            "?statement=profit_and_loss&remove=revenue"
        )

    def test_a_line_that_was_never_extracted_offers_nothing_to_remove(
        self, client, session
    ):
        """A figure that is absent rather than wrong is put right with "add a line", and a
        remove link on a row with nothing in it would be an offer that does nothing."""
        period = _store(
            session,
            "TEST_US_EQ",
            _period("TEST_US_EQ", dt.date(2024, 12, 31), {"revenue": 1_000.0}),
        )
        session.commit()

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}").text, "lxml")
        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Cost of sales" in item.get_text(" ")
        )

        assert row.select_one("td.act a") is None

    def test_each_section_offers_a_line_to_add_to_it(self, client, session, two_years):
        body = client.get(f"/accounts/{two_years.id}/profit_and_loss").text

        assert (
            f"/accounts/{two_years.id}/corrections/new?statement=profit_and_loss"
            "&amp;section=Revenue"
        ) in body


class TestTheConfirmPage:
    def test_removing_shows_what_the_line_says_before_it_is_taken_out(
        self, client, session, two_years
    ):
        """The reader is here because they think the extracted figure is wrong; they should be
        able to see it, and the tag it came from, before agreeing."""
        body = client.get(
            f"/accounts/{two_years.id}/corrections/new"
            "?statement=profit_and_loss&remove=revenue"
        ).text

        assert "Take out" in body
        assert "1,000" in body
        assert "us-gaap:Revenues" in body
        assert "0000320193-24-000123" in body

    def test_the_filer_wide_scope_is_offered_only_where_there_is_a_filer(
        self, client, session
    ):
        """A removal recorded against a CIK this period does not have would have nothing to
        apply to, so the tick is not shown and the removal is made for this period alone."""
        with_filer = _store(
            session, "WITH_US_EQ", _period("WITH_US_EQ", dt.date(2024, 12, 31))
        )
        without = _store(
            session,
            "WITHOUT_US_EQ",
            _period("WITHOUT_US_EQ", dt.date(2024, 12, 31)),
            cik=None,
        )
        session.commit()

        assert "every period this filer has" in client.get(
            f"/accounts/{with_filer.id}/corrections/new?remove=revenue"
        ).text
        assert "every period this filer has" not in client.get(
            f"/accounts/{without.id}/corrections/new?remove=revenue"
        ).text

    def test_a_line_that_is_already_removed_says_so_instead_of_offering_it_again(        self, client, session, two_years
    ):
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "revenue", "statement": "profit_and_loss"},
        )

        body = client.get(
            f"/accounts/{two_years.id}/corrections/new?remove=revenue"
        ).text

        assert "already been taken out" in body
        assert "<form method=\"post\" action=\"/accounts/" not in body.split("already been")[1]

    def test_an_unknown_line_is_a_404_rather_than_a_form(self, client, session, two_years):
        assert client.get(
            f"/accounts/{two_years.id}/corrections/new?remove=not_a_line"
        ).status_code == 404

    def test_adding_offers_the_statement_s_own_headings(self, client, session, two_years):
        """The form's question is "which heading does this figure belong under", so the choices
        are the sections the statement prints and the lines the chart puts in them."""
        body = client.get(
            f"/accounts/{two_years.id}/corrections/new?statement=balance_sheet"
        ).text

        assert "<optgroup label=\"Current assets\">" in body
        assert "Property, plant and equipment" in body
        assert "Research and development" not in body, (
            "another statement's lines are not on offer here"
        )

    def test_the_form_asks_for_a_side_because_a_credit_posted_as_a_debit_changes_the_equation(
        self, client, session, two_years
    ):
        body = client.get(f"/accounts/{two_years.id}/corrections/new").text

        assert 'value="debit"' in body and 'value="credit"' in body

    def test_a_figure_read_out_of_a_filing_arrives_prefilled(self, client, session, two_years):
        """The picker on the filing page cannot make the correction itself -- it runs on an
        opaque origin with nothing but its own document -- so it hands the reader here with
        what they clicked, and the decision is still made on our own page."""
        soup = BeautifulSoup(
            client.get(
                f"/accounts/{two_years.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "metric": "operating_lease_assets",
                    "value": "168000000",
                    "tag": "us-gaap:OperatingLeaseRightOfUseAssetNoncurrent",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/x.htm",
                },
            ).text,
            "lxml",
        )

        assert soup.select_one("select[name=metric] option[selected]")["value"] == (
            "operating_lease_assets"
        )
        assert soup.select_one("input[name=value]")["value"] == "168000000"
        assert soup.select_one("input[name=tag]")["value"] == (
            "us-gaap:OperatingLeaseRightOfUseAssetNoncurrent"
        )
        assert soup.select_one("input[name=url]")["value"].endswith("x.htm")


class TestTheSideOfTheLine:
    """*"Selecting the debit/credit selectors when configuring the add line doesn't seem to do
    anything, they are always positive."* -- reported 2026-10-10.

    Two different things, and the answer to both is that the *line* decides the direction, not
    the figure: a figure is a magnitude, and a line the chart already carries is posted on the
    side the chart gives it, so there was nothing for that choice to change and it was recorded
    anyway. A line created from the filing's caption is the one nothing else knows, and that is
    where the reader is asked.
    """

    def test_the_chart_fixes_the_side_of_its_own_lines_whatever_the_form_says(
        self, client, session, two_years
    ):
        """The live row read "revenue ... debit" while the chart posts revenue as a credit, and
        every sum in the ledger used the credit. The record now says what the ledger does."""
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": "revenue",
                "value": "1000",
                "side": "debit",
                "statement": "profit_and_loss",
            },
        )

        row = _row(session, two_years.id)
        assert ledger.BY_KEY["revenue"].side == "credit"
        assert row.metric_sources["revenue"]["side"] == "credit"

    def test_the_reader_decides_the_side_of_a_line_they_create(self, client, session, two_years):
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": "new:us-gaap:ContractWithCustomerLiabilityCurrent",
                "value": "250",
                "side": "credit",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": "Short-term unearned revenue",
                "tag": "us-gaap:ContractWithCustomerLiabilityCurrent",
            },
        )

        row = _row(session, two_years.id)
        key = "us-gaap:ContractWithCustomerLiabilityCurrent"
        assert row.metric_sources[key]["side"] == "credit"

    def test_the_form_asks_for_a_line_to_create_and_states_a_line_the_chart_has(
        self, client, session, two_years
    ):
        """The affordance and the arithmetic have to agree: a control that is recorded and then
        ignored by everything that reads the accounts is worse than no control."""
        on_a_chart_line = BeautifulSoup(
            client.get(
                f"/accounts/{two_years.id}/corrections/new",
                params={"statement": "profit_and_loss", "metric": "revenue"},
            ).text,
            "lxml",
        )

        assert on_a_chart_line.select("input[type=radio][name=side]") == []
        assert on_a_chart_line.select_one("input[type=hidden][name=side]")["value"] == "credit"
        assert "posted where the chart posts it" in on_a_chart_line.get_text(" ")

    def test_pressing_add_a_line_on_a_heading_does_not_ask_for_a_side_either(
        self, client, session, two_years
    ):
        """The other way into this form, and the one with nothing preselected: it opens on the
        heading's own first line, so the side is the chart's there too. This is the path the
        reader took -- *"selecting the debit/credit selectors when configuring the add line"*."""
        form = BeautifulSoup(
            client.get(
                f"/accounts/{two_years.id}/corrections/new",
                params={"statement": "profit_and_loss", "section": "Revenue"},
            ).text,
            "lxml",
        )

        assert form.select_one("select[name=metric] option[selected]")["value"] == "revenue"
        assert form.select("input[type=radio][name=side]") == []
        assert form.select_one("input[type=hidden][name=side]")["value"] == "credit"

    def test_the_form_asks_when_the_line_is_the_filing_s_own(self, client, session, two_years):
        form = BeautifulSoup(
            client.get(
                f"/accounts/{two_years.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "metric": "new:us-gaap:ContractWithCustomerLiabilityCurrent",
                    "tag": "us-gaap:ContractWithCustomerLiabilityCurrent",
                    "caption": "Short-term unearned revenue",
                    "section": "Current liabilities",
                },
            ).text,
            "lxml",
        )

        radios = form.select("input[type=radio][name=side]")
        assert [radio["value"] for radio in radios] == list(corrections.SIDES)
        assert form.select_one("input[type=hidden][name=side]") is None


class TestRemovingALine:
    def test_a_removal_reaches_the_stored_figures_and_so_every_reader_of_them(
        self, client, session, two_years
    ):
        """The property that makes this a correction rather than a display filter: the row no
        longer holds the line, so the ledger, the checks, the snapshot and the decisions all
        see the corrected accounts."""
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet", "reason": "not ours"},
        )

        row = _row(session, two_years.id)
        assert "inventory" not in row.metrics
        assert row.corrections["removed"]["inventory"]["was"] == 120.0
        assert row.corrections["removed"]["inventory"]["reason"] == "not ours"
        assert row.metric_sources["inventory"]["removed"]["was"] == 120.0, (
            "the row's own provenance says the line was taken out, so undoing it has a "
            "figure to put back"
        )

    def test_the_page_prints_the_line_it_was_told_to_take_out(
        self, client, session, two_years
    ):
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet"},
        )

        soup = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/balance_sheet").text, "lxml"
        )

        assert "Corrections to these accounts" in soup.get_text(" ")
        assert "inventory" in soup.select_one("#corrections").get_text(" ")
        # The chart is fixed, so the line is still printed -- as a row with nothing in it and
        # nothing to remove. What must be gone is the figure.
        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Inventory" in item.get_text(" ")
        )
        assert "120" not in row.get_text(" "), "the removed figure is out of the statement"
        assert row.select_one("td.act a") is None

    def test_the_outcome_travels_in_the_url_and_is_rendered_as_a_sentence(
        self, client, session, two_years
    ):
        """The shape every other action on this page uses. The code is chosen from a fixed
        mapping rather than echoed, so nothing a reader typed becomes page text."""
        response = client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].endswith(
            "?corrections=removed#corrections"
        )
        assert "was taken out of these accounts" in client.get(
            response.headers["location"]
        ).text

    def test_removing_something_twice_changes_nothing_the_second_time(
        self, client, session, two_years
    ):
        data = {"metric": "inventory", "statement": "balance_sheet"}
        client.post(f"/accounts/{two_years.id}/corrections/remove", data=data)
        before = _row(session, two_years.id).corrections

        response = client.post(
            f"/accounts/{two_years.id}/corrections/remove", data=data, follow_redirects=False
        )

        assert "already-removed" in response.headers["location"]
        assert _row(session, two_years.id).corrections == before

    def test_an_unknown_line_cannot_be_removed(self, client, session, two_years):
        response = client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "not_a_line", "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "no-line" in response.headers["location"]
        assert _row(session, two_years.id).corrections is None


class TestUndoingACorrection:
    def test_undo_puts_back_the_figure_the_extraction_had(self, client, session, two_years):
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet"},
        )

        client.post(
            f"/accounts/{two_years.id}/corrections/inventory/forget",
            data={"statement": "balance_sheet"},
        )

        row = _row(session, two_years.id)
        assert row.metrics["inventory"] == 120.0
        assert row.corrections is None, "with nothing left to undo, the record goes"

    def test_undo_restores_the_provenance_an_addition_replaced(self, client, session, two_years):
        """An addition overwrites the entry beside the figure, so undoing it has to put back
        *where the line came from* as well as its number."""
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": "sga_expense",
                "value": "999",
                "side": "debit",
                "statement": "profit_and_loss",
            },
        )
        assert _row(session, two_years.id).metric_sources["sga_expense"]["source"] == (
            corrections.MANUAL
        )

        client.post(
            f"/accounts/{two_years.id}/corrections/sga_expense/forget",
            data={"statement": "profit_and_loss"},
        )

        row = _row(session, two_years.id)
        assert row.metrics["sga_expense"] == 150.0
        assert row.metric_sources["sga_expense"]["source"] == "xbrl_companyfacts"
        assert row.metric_sources["sga_expense"]["span"] == "us-gaap:Revenues"

    def test_undoing_something_that_was_never_corrected_says_so(self, client, session, two_years):
        response = client.post(
            f"/accounts/{two_years.id}/corrections/inventory/forget",
            data={"statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "nothing-to-undo" in response.headers["location"]

    def test_a_filer_wide_removal_is_not_undone_by_one_period_s_page(
        self, client, session, two_years
    ):
        """The rule was made once for every period, and undoing it from one page would silently
        change the others. It has its own undo, and this route is not it."""
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet", "scope": "filer"},
        )

        client.post(
            f"/accounts/{two_years.id}/corrections/inventory/forget",
            data={"statement": "balance_sheet"},
        )

        assert "inventory" not in _row(session, two_years.id).metrics, "the rule still stands"


class TestAddingALine:
    def test_a_figure_is_written_into_the_stored_accounts_and_marked_as_manual(
        self, client, session, two_years
    ):
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": "operating_lease_assets",
                "value": "168.5",
                "side": "debit",
                "statement": "balance_sheet",
                "tag": "us-gaap:OperatingLeaseRightOfUseAsset",
                "note": "from the consolidated balance sheet",
            },
        )

        row = _row(session, two_years.id)
        assert row.metrics["operating_lease_assets"] == 168.5
        assert row.metric_sources["operating_lease_assets"]["source"] == corrections.MANUAL
        assert row.metric_sources["operating_lease_assets"]["side"] == "debit"
        assert row.corrections["added"]["operating_lease_assets"]["note"] == (
            "from the consolidated balance sheet"
        )

    def test_a_figure_in_parentheses_is_read_as_negative(self, client, session, two_years):
        """That is how a filing prints a credit, and reading (1,234) as a positive figure would
        put a wrong number on the balance sheet with nothing to complain about."""
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": "other_nonoperating_income",
                "value": "(1,234.5)",
                "statement": "profit_and_loss",
            },
        )

        assert _row(session, two_years.id).metrics["other_nonoperating_income"] == -1234.5

    @pytest.mark.parametrize("typed", ["", "not a number", "5%", "--3"])
    def test_something_that_is_not_a_figure_is_refused_and_changes_nothing(
        self, client, session, two_years, typed
    ):
        response = client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={"metric": "inventory", "value": typed, "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "bad-value" in response.headers["location"]
        assert _row(session, two_years.id).corrections is None

    def test_a_line_that_is_not_in_the_chart_is_refused(self, client, session, two_years):
        response = client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={"metric": "made_up_metric", "value": "10", "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "no-line" in response.headers["location"]
        assert _row(session, two_years.id).corrections is None

    def test_an_added_line_moves_the_check_that_audits_it(self, client, session):
        """The point of writing it through: a figure put in by hand has to change the verdicts
        taken from the accounts, or the page would be showing corrected figures beside checks
        computed from the uncorrected ones."""
        period = _store(
            session,
            "TEST_US_EQ",
            _period("TEST_US_EQ", dt.date(2024, 12, 31), {**FIGURES, "total_assets": 1_000.0}),
        )
        session.commit()
        before = next(
            item for item in ledger.checks(period) if item.key == "assets_composition"
        )
        assert before.failed

        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": "other_noncurrent_assets",
                "value": "150",
                "side": "debit",
                "statement": "balance_sheet",
            },
        )

        after = next(
            item
            for item in ledger.checks(_row(session, period.id))
            if item.key == "assets_composition"
        )
        assert not after.failed, "the missing line was added, so the components now sum"


class TestFilerWideRemovals:
    def test_a_rule_reaches_every_period_the_filer_has_without_waiting_for_a_sync(
        self, client, session, two_years
    ):
        """The page reads a *row*, so recording a rule and waiting for each period's next sync
        would leave two periods of the same company disagreeing on screen about the same line.
        """
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet", "scope": "filer"},
        )

        session.expire_all()
        rows = corrections.filer_periods(session, CIK)

        assert len(rows) == 2, "both years of the filer"
        assert all("inventory" not in row.metrics for row in rows), (
            "the older year lost the line too, without being re-synced"
        )
        assert all(row.corrections is None for row in rows), (
            "the rule is the record, once, against the filer -- not a copy on whichever row "
            "the reader happened to be looking at"
        )

    def test_the_rule_is_recorded_against_the_filer_and_can_be_undone_from_any_period(
        self, client, session, two_years
    ):
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet", "scope": "filer"},
        )
        assert corrections.load_filer(session, CIK).removed["inventory"].was == 120.0

        response = client.post(
            f"/accounts/{two_years.id}/filer-rules/forget",
            data={"metric": "inventory", "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "rule-forgotten" in response.headers["location"]
        assert corrections.load_filer(session, CIK).removed == {}
        # Each period gets *its own* figure back, from its own evidence: the rule took a
        # different number out of the older year, so only that row can say what it was.
        session.expire_all()
        rows = corrections.filer_periods(session, CIK)
        assert {row.period_end: row.metrics["inventory"] for row in rows} == {
            dt.date(2023, 12, 31): 120.0,
            dt.date(2024, 12, 31): 120.0,
        }

    def test_undoing_a_rule_that_was_never_made_says_so(self, client, session, two_years):
        response = client.post(
            f"/accounts/{two_years.id}/filer-rules/forget",
            data={"metric": "inventory", "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "no-rule" in response.headers["location"]

    def test_a_filer_without_a_cik_falls_back_to_a_removal_for_this_period(
        self, client, session
    ):
        """Rather than dropping the correction on the floor because the wider scope it asked
        for is not available."""
        period = _store(
            session,
            "TEST_US_EQ",
            _period("TEST_US_EQ", dt.date(2024, 12, 31)),
            cik=None,
        )
        session.commit()

        response = client.post(
            f"/accounts/{period.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet", "scope": "filer"},
            follow_redirects=False,
        )

        assert "corrections=removed#" in response.headers["location"]
        assert "inventory" not in _row(session, period.id).metrics


class TestOneLineOneDecision:
    """A line corrected twice is not two corrections. The later act supersedes the earlier one,
    or the panel would show two rows for one line with nothing to say which the arithmetic
    obeyed -- and the arithmetic would obey the addition, whatever the order they were made in.
    """

    def test_adding_a_figure_puts_the_line_back_by_hand(self, client, session, two_years):
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet"},
        )

        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": "inventory",
                "value": "130",
                "side": "debit",
                "statement": "balance_sheet",
            },
        )

        row = _row(session, two_years.id)
        assert row.metrics["inventory"] == 130.0
        assert "inventory" not in row.corrections["removed"], (
            "the removal is superseded, not stacked underneath the addition"
        )
        panel = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/balance_sheet").text, "lxml"
        ).select_one("#corrections").get_text(" ")
        assert "removed" not in panel

    def test_removing_a_figure_that_was_put_in_by_hand_takes_it_out_again(
        self, client, session, two_years
    ):
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": "operating_lease_assets",
                "value": "168",
                "side": "debit",
                "statement": "balance_sheet",
            },
        )

        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "operating_lease_assets", "statement": "balance_sheet"},
        )

        row = _row(session, two_years.id)
        assert "operating_lease_assets" not in row.metrics
        assert "operating_lease_assets" not in row.corrections["added"]

    def test_a_hand_figure_overrides_a_filer_wide_removal_and_the_panel_says_so(
        self, client, session, two_years
    ):
        """The order in `apply` is part of the contract: removals first, then additions, so a
        rule made earlier can still be overridden in one period. Two rows that appear to
        contradict each other would read as a bug, so the panel says which one won."""
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet", "scope": "filer"},
        )

        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={"metric": "inventory", "value": "130", "statement": "balance_sheet"},
        )

        assert _row(session, two_years.id).metrics["inventory"] == 130.0
        panel = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/balance_sheet").text, "lxml"
        ).select_one("#corrections").get_text(" ")
        assert "overriding the removal recorded for every period" in panel
        assert "Put it back everywhere" not in panel, (
            "the rule's own row is not printed beside the period's decision -- the rule is "
            "overridden here, so its undo would not change what is on screen"
        )

    def test_a_filer_wide_removal_takes_a_hand_figure_with_it(self, client, session, two_years):
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={"metric": "inventory", "value": "130", "statement": "balance_sheet"},
        )

        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet", "scope": "filer"},
        )

        row = _row(session, two_years.id)
        assert "inventory" not in row.metrics
        assert row.corrections is None, (
            "the line is gone everywhere, so this period holds no hand figure for it"
        )


class TestTheRecordOutlivesTheSyncThatRewritesTheRow:
    """`_upsert_period` replaces every figure with what the payload says -- that is what it is
    for -- so a correction has to be re-applied there, or the next sync quietly undoes the
    reader's work and the page goes back to showing a line they know is wrong."""

    def _sync(self, session, row, metrics: dict | None = None):
        from awltux.ingest.fundamentals import _upsert_period

        return _upsert_period(
            session,
            session.get(Instrument, row.instrument_t212_ticker),
            period_end=row.period_end,
            period_type=row.period_type,
            metrics=dict(metrics if metrics is not None else FIGURES),
            source=row.source,
            confidence=0.9,
        )

    def test_a_removal_outlives_a_re_derive(self, session, two_years):
        row = _row(session, two_years.id)
        corrections.remove(row, "inventory")
        session.flush()

        self._sync(session, row)
        session.flush()

        assert "inventory" not in row.metrics
        assert "inventory" in row.corrections["removed"]

    def test_a_filer_rule_reaches_a_period_that_is_written_afterwards(self, session, two_years):
        """The rule is read whatever happens, not only when the row already carries a
        correction, so a period re-derived months later still has the line removed."""
        rules = corrections.Rules(
            removed={"inventory": corrections.Removal(metric="inventory", was=120.0)}
        )
        corrections.save_filer(session, CIK, rules)
        session.flush()

        self._sync(session, _row(session, two_years.id))
        session.flush()

        assert "inventory" not in session.get(FundamentalPeriod, two_years.id).metrics

    def test_a_row_nobody_has_corrected_keeps_the_provider_s_own_ratios(self, session, two_years):
        """The write-through is only for rows a reader has touched: a provider's own margins
        are not ours to overwrite, so `apply_to_row` is not called at all and the payload's
        figures land verbatim."""
        row = _row(session, two_years.id)

        self._sync(session, row, {**FIGURES, "gross_margin": 0.99})
        session.flush()

        assert row.metrics["gross_margin"] == 0.99, (
            "the provider's own margin, not recomputed from gross profit and revenue"
        )


class TestThePanelOnEveryTab:
    def test_a_corrected_period_says_so_on_the_health_tab_too(self, client, session, two_years):
        """The checks are the rows a correction moves, so the record has to be beside them and
        not only on the statement the removal was made from."""
        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "inventory", "statement": "balance_sheet"},
        )

        body = client.get(f"/accounts/{two_years.id}/health").text

        assert "Corrections to these accounts" in body
        assert "inventory" in body

    def test_an_uncorrected_period_shows_no_empty_panel(self, client, session, two_years):
        """A heading over nothing would make every accounts page look as though somebody had
        been editing it."""
        body = client.get(f"/accounts/{two_years.id}").text

        assert "Corrections to these accounts" not in body

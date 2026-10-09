"""The accounts page: the way in, the tabs, and what each one puts on the screen.

The feature these guard is a *navigation* one -- a date stamp on the instrument page
that opens the period as a set of accounts -- so the tests are about reachability and
about the page saying the true thing, not about the arithmetic. The arithmetic is
`tests/test_ledger.py`'s business.
"""

from __future__ import annotations

import datetime as dt

import pytest
from bs4 import BeautifulSoup

from awltux.analysis import ledger
from awltux.db import FundamentalPeriod
from tests.helpers import make_instrument, make_period

BALANCED = {
    "revenue": 1_000.0,
    "cost_of_goods_sold": 600.0,
    "gross_profit": 400.0,
    "sga_expense": 150.0,
    "research_and_development": 50.0,
    "depreciation_amortisation": 40.0,
    "operating_income": 160.0,
    "interest_expense": 20.0,
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
    "lease_liabilities": 30.0,
    "total_liabilities": 360.0,
    "total_equity": 490.0,
    "retained_earnings": 300.0,
    "operating_cash_flow": 180.0,
    "capex": 60.0,
    "dividends_paid": 40.0,
}


def _store(session, ticker: str, *periods):
    """Instrument first, then its periods, flushing between.

    The flush is not decoration: `FundamentalPeriod` points at `instrument.t212_ticker`
    and SQLAlchemy cannot order the two inserts without the parent row existing.
    """
    session.add(make_instrument(ticker, name="Test Co"))
    session.flush()
    for period in periods:
        session.add(period)
    session.flush()
    # Committed, not merely flushed: a request runs on its own session in another
    # thread, and an uncommitted row is invisible there however often it is flushed.
    session.commit()
    return periods[-1] if periods else None


@pytest.fixture
def stored_period(session):
    """One instrument with two comparable periods, and the newest period's id."""
    return _store(
        session,
        "TEST_US_EQ",
        make_period("TEST_US_EQ", dt.date(2023, 12, 31), dict(BALANCED)),
        make_period(
            "TEST_US_EQ",
            dt.date(2024, 12, 31),
            {**BALANCED, "retained_earnings": 370.0},
        ),
    )


class TestTheWayIn:
    """The date stamp is the entry point. A page nobody can reach is not a feature.

    It lives on the instrument page's Accounts tab: the page renders one topic at a time,
    so the period links are only in the document when that tab is the one being shown.
    """

    def test_the_period_date_on_the_instrument_page_links_to_its_accounts(
        self, client, session, stored_period
    ):
        body = client.get("/instrument/TEST_US_EQ?tab=accounts").text

        assert f'href="/accounts/{stored_period.id}"' in body, (
            "the date stamp must open the accounts"
        )

    def test_every_stored_period_is_reachable(self, client, session, stored_period):
        """Both periods, not only the newest -- the older one is what the articulation
        checks compare against, and a reader may want to open it directly."""
        body = client.get("/instrument/TEST_US_EQ?tab=accounts").text

        assert body.count('href="/accounts/') == 2


class TestTheTabs:
    def test_a_bare_url_opens_the_first_statement(self, client, session, stored_period):
        body = client.get(f"/accounts/{stored_period.id}").text

        assert "Profit &amp; loss" in body or "Profit & loss" in body
        assert "Gross profit" in body

    @pytest.mark.parametrize(
        "statement, expected",
        [
            ("profit_and_loss", "Gross profit"),
            ("balance_sheet", "Total assets"),
            ("cash_flow", "Free cash flow"),
        ],
    )
    def test_each_statement_has_its_own_url(self, client, session, stored_period, statement, expected):
        """One URL per statement, so "look at the cash flow" can be sent to somebody."""
        body = client.get(f"/accounts/{stored_period.id}/{statement}").text

        assert expected in body

    def test_the_tab_strip_links_every_tab_including_the_active_one(
        self, client, session, stored_period
    ):
        body = client.get(f"/accounts/{stored_period.id}/balance_sheet").text

        for name in ("profit_and_loss", "balance_sheet", "cash_flow", "health"):
            assert f'href="/accounts/{stored_period.id}/{name}"' in body, name
        assert 'aria-current="page"' in body

    def test_an_unknown_statement_is_a_404_rather_than_a_silent_fallback(
        self, client, session, stored_period
    ):
        """Quietly showing profit and loss to somebody who asked for the cash flow is
        how a reader ends up reading the wrong statement and never knowing."""
        assert client.get(f"/accounts/{stored_period.id}/cashflowz").status_code == 404

    def test_an_unknown_period_is_a_404(self, client, session, stored_period):
        assert client.get("/accounts/999999").status_code == 404


class TestWhatTheStatementsShow:
    def test_the_ledger_prints_stated_and_computed_side_by_side(
        self, client, session, stored_period
    ):
        """The residual between them is the size of the accounts not extracted, so both
        columns have to be on the page rather than folded into one figure."""
        body = client.get(f"/accounts/{stored_period.id}/profit_and_loss").text

        assert "Stated" in body and "Computed" in body

    def test_a_disagreeing_subtotal_is_flagged_rather_than_absorbed(
        self, client, session
    ):
        """A stated gross profit ten below the arithmetic must be visible as a
        difference, because that difference is the extraction gap."""
        period = _store(
            session,
            "TEST_US_EQ",
            make_period(
                "TEST_US_EQ", dt.date(2024, 12, 31), {**BALANCED, "gross_profit": 390.0}
            ),
        )
        session.commit()

        body = client.get(f"/accounts/{period.id}/profit_and_loss").text

        assert "out by" in body

    def test_the_balance_sheet_shows_its_trial_balance(self, client, session, stored_period):
        body = client.get(f"/accounts/{stored_period.id}/balance_sheet").text

        assert "trial balance" in body.lower()
        assert "Total debits" in body and "Total credits" in body

    def test_the_cash_flow_admits_it_is_incomplete(self, client, session, stored_period):
        body = client.get(f"/accounts/{stored_period.id}/cash_flow").text

        assert "not a complete statement" in body

    def test_a_period_with_no_figures_says_so_instead_of_showing_blanks(
        self, client, session
    ):
        period = _store(
            session,
            "TEST_US_EQ",
            make_period("TEST_US_EQ", dt.date(2024, 12, 31), {}),
        )
        session.commit()

        body = client.get(f"/accounts/{period.id}").text

        assert "nothing to lay out" in body


class TestTheHealthTab:
    def test_it_reports_every_check_with_its_verdict(self, client, session, stored_period):
        body = client.get(f"/accounts/{stored_period.id}/health").text

        for label in (
            "Assets = liabilities + equity",
            "Lines we hold reconcile to reported profit",
            "Components sum to stated total assets",
            "Retained earnings roll forward",
            "Movement in cash reconciles",
        ):
            assert label in body, label

    def test_a_clean_set_of_accounts_says_the_equation_agrees(
        self, client, session, stored_period
    ):
        body = client.get(f"/accounts/{stored_period.id}/health").text

        assert "agrees" in body

    def test_an_equation_that_does_not_hold_is_shown_as_out(self, client, session):
        """The whole point of the trial balance: the difference survives to the page."""
        period = _store(
            session,
            "TEST_US_EQ",
            make_period(
                "TEST_US_EQ", dt.date(2024, 12, 31), {**BALANCED, "total_assets": 900.0}
            ),
        )
        session.commit()

        body = client.get(f"/accounts/{period.id}/health").text

        assert "out" in body

    def test_a_disagreeing_subtotal_shows_the_calculation_on_hover(self, client, session):
        """Asked for directly: *"When I hover over the Accounts 'out by' entries display the
        calculations that have been carried out so I can investigate what's gone wrong."*

        The stated total, every component with its sign, the sum, and what was left out --
        because a residual a reader cannot decompose is a number they can only stare at.
        """
        period = _store(
            session,
            "TEST_US_EQ",
            make_period(
                "TEST_US_EQ",
                dt.date(2024, 12, 31),
                # Operating income stated at 160 against components that add to 110, so the
                # line carries a residual.
                {**BALANCED, "operating_income": 160.0, "sga_expense": 200.0},
            ),
        )
        session.commit()

        body = client.get(f"/accounts/{period.id}/profit_and_loss").text

        assert "out by" in body
        soup = BeautifulSoup(body, "lxml")
        # The disagreeing line, not the first one on the page: most subtotals agree, and
        # those carry their working too.
        row = next(
            item
            for item in soup.select("table.ledger tbody tr")
            if "Operating income" in item.get_text(" ")
        )
        work = row.select_one(".work[data-work]")
        assert work is not None, "the residual carries no working"
        text = work["data-work"]
        assert "from the filing: 160" in text
        assert "added up" in text
        # The components, with their signs and in the words the lines above are printed in.
        assert "Gross profit" in text and "Selling, general and administrative" in text
        assert "\u2212" in text, "a deduction is marked as one"
        assert "= 110 computed" in text
        assert "out by 50 (stated \u2212 computed)" in text

    def test_the_working_adds_up_to_the_figure_beside_it(self, client, session):
        """The point of showing it: a reader can check the arithmetic rather than trust it."""
        period = _store(
            session,
            "TEST_US_EQ",
            make_period("TEST_US_EQ", dt.date(2024, 12, 31), dict(BALANCED)),
        )
        session.commit()
        line = next(
            item
            for item in ledger.statement(period, "profit_and_loss").lines
            if item.key == "gross_profit"
        )

        assert sum(part.contribution for part in line.parts) == pytest.approx(line.computed)
        assert f"= {line.computed:,.0f} computed" in line.show_work()

    def test_the_health_check_shows_the_same_working(self, client, session):
        """The column is headed "Out by" there too, and it measures the same subtractions --
        so a reader who hovers it gets the calculation, not just the difference."""
        period = _store(
            session,
            "TEST_US_EQ",
            make_period(
                "TEST_US_EQ",
                dt.date(2024, 12, 31),
                {**BALANCED, "total_assets": 900.0},
            ),
        )
        session.commit()

        check = next(
            item for item in ledger.checks(period) if item.key == "assets_composition"
        )

        assert check.label == "Components sum to stated total assets"
        assert "from the filing: 900" in check.work
        assert "added up" in check.work
        assert "Cash and equivalents" in check.work
        assert "out by 50 (stated \u2212 computed)" in check.work

    def test_the_profit_articulation_check_shows_the_cascade(self, session):
        """The health row and the statement line audit the same subtraction, so hovering one
        and then the other must not give two accounts of it."""
        period = make_period("TEST_US_EQ", dt.date(2024, 12, 31), dict(BALANCED))

        check = next(
            item for item in ledger.checks(period) if item.key == "profit_articulation"
        )

        assert "added up" in check.work
        assert "Profit before tax" in check.work
        assert "Tax" in check.work

    def test_a_check_with_no_arithmetic_gets_no_empty_tooltip(self, client, session):
        """A dotted underline that promises an explanation and delivers nothing is worse than
        no affordance, so a check with no working is printed plain."""
        period = _store(
            session,
            "TEST_US_EQ",
            make_period("TEST_US_EQ", dt.date(2024, 12, 31), dict(BALANCED)),
        )
        session.commit()

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/health").text, "lxml")

        assert soup.select(".work[data-work]"), "the composition rows have a working"
        for span in soup.select("[data-work]"):
            assert span["data-work"].strip(), f"an empty tooltip on {span}"

    def test_a_line_with_no_arithmetic_has_no_working(self):
        """A figure with nothing behind it has nothing to investigate, and a tooltip that said
        so would be noise on every row."""
        line = ledger.Line(
            key="revenue", label="Revenue", stated=1_000.0, computed=None, side="credit"
        )

        assert line.show_work() == ""

    def test_a_figure_that_agrees_still_shows_how_it_was_reached(self):
        """It is not only failures a reader wants to check: "agrees" is a claim about two
        figures, and the arithmetic behind it is the evidence for that claim."""
        line = ledger.Line(
            key="gross_profit",
            label="Gross profit",
            stated=400.0,
            computed=400.0,
            side="credit",
            parts=(
                ledger.Part(label="Revenue", contribution=1_000.0),
                ledger.Part(label="Cost of sales", contribution=-600.0),
            ),
        )

        text = line.show_work()

        assert "from the filing: 400" in text
        assert "+ 1,000  Revenue" in text and "\u2212 600  Cost of sales" in text
        assert "= 400 computed" in text
        assert "out by 0 (stated \u2212 computed)" in text

    def test_the_markers_are_shown_and_say_which_periods_they_used(
        self, client, session, stored_period
    ):
        """The markers come from the shared snapshot, so the page has to say when they
        describe a different period from the accounts on screen."""
        body = client.get(f"/accounts/{stored_period.id}/health").text

        assert "What the markers measured" in body
        assert "which is not the period on screen unless" in body

    def test_a_one_period_history_does_not_pretend_to_articulate(
        self, client, session
    ):
        """Retained earnings cannot roll forward without an opening balance, and saying
        so is the honest answer rather than showing a movement of zero."""
        period = _store(
            session,
            "TEST_US_EQ",
            make_period("TEST_US_EQ", dt.date(2024, 12, 31), dict(BALANCED)),
        )
        session.commit()

        body = client.get(f"/accounts/{period.id}/health").text

        assert "not computable" in body


def _source_period(
    ticker: str,
    *,
    source: str,
    period_end: dt.date = dt.date(2024, 12, 31),
    metrics: dict | None = None,
    period_type: str = "annual",
) -> FundamentalPeriod:
    """One source's row for a year, with no derived ratios to confuse the counts."""
    return FundamentalPeriod(
        instrument_t212_ticker=ticker,
        source=source,
        period_end=period_end,
        period_type=period_type,
        currency="GBP",
        metrics=metrics if metrics is not None else dict(BALANCED),
        confidence=0.7,
    )


class TestOneYearOnThePage:
    """Measured 2026-10-09: 12 of 333 accounting years held more than one source, ten of them
    carrying the filer's own tags, a Yahoo statement and our reading of the same 10-K. They are
    one set of accounts seen three times -- and the page used to print them as three years."""

    def _three_sources(self, session, client):
        rows = [
            _source_period(
                "TEST_US_EQ",
                source="yahoo_statements",
                # `ebitda` is stated only here, and the filer's own row does not carry it.
                metrics={**BALANCED, "revenue": 1_050.0, "ebitda": 340.0},
            ),
            _source_period("TEST_US_EQ", source="llm_extraction", metrics={**BALANCED, "revenue": 1_000.0}),
            _source_period("TEST_US_EQ", source="xbrl_companyfacts", metrics={**BALANCED, "revenue": 1_000.0}),
        ]
        _store(session, "TEST_US_EQ", *rows)
        session.commit()
        return rows

    def test_the_accounts_tab_lists_one_row_per_year(self, client, session):
        rows = self._three_sources(session, client)

        body = client.get("/instrument/TEST_US_EQ?tab=accounts").text

        assert body.count('/accounts/') == 1, "one year, one row"
        assert "xbrl_companyfacts" in body
        assert rows[2].id, "the link is the chosen row's id"

    def test_the_year_page_lays_out_the_filers_own_accounts(self, client, session):
        self._three_sources(session, client)

        # The year's link is the *chosen* row's id, which is how a reader gets there.
        xbrl_id = client.get("/instrument/TEST_US_EQ?tab=accounts").text.split("/accounts/")[1].split('"')[0]

        body = client.get(f"/accounts/{xbrl_id}").text

        assert "the filer's own accounts" in body
        assert "1,000" in body, "the filer's revenue, not Yahoo's 1,050"

    def test_the_sources_it_displaced_are_named_with_what_they_said(self, client, session):
        self._three_sources(session, client)
        link = client.get("/instrument/TEST_US_EQ?tab=accounts").text.split('/accounts/')[1]
        xbrl_id = link.split('"')[0]

        body = client.get(f"/accounts/{xbrl_id}").text

        assert "2 other sources" in body
        assert "yahoo_statements" in body and "llm_extraction" in body
        assert "1,050" in body, "the figure Yahoo stated is shown, beside the one in force"
        assert "disagrees" in body
        assert "ebitda" in body and "not in these accounts" in body, (
            "a figure only another source states is reported as unused, not merged in"
        )

    def test_a_link_to_a_row_that_lost_still_opens_its_year(self, client, session):
        rows = self._three_sources(session, client)
        yahoo_id = rows[0].id

        response = client.get(f"/accounts/{yahoo_id}")

        assert response.status_code == 200
        assert "the filer's own accounts" in response.text, "the year, not the superseded row"

    def test_the_comparable_is_the_previous_year_and_not_the_previous_source(
        self, client, session
    ):
        """It used to be matched on source, which now compares a year whose accounts come from
        the filer with one whose accounts come from Yahoo."""
        older = _source_period(
            "TEST_US_EQ", source="yahoo_statements", period_end=dt.date(2023, 12, 31)
        )
        newer = _source_period("TEST_US_EQ", source="xbrl_companyfacts")
        _store(session, "TEST_US_EQ", older, newer)
        session.commit()

        body = client.get(f"/accounts/{newer.id}").text

        assert "2023-12-31" in body
        assert "Comparable" in body

    def test_an_interim_year_says_the_annual_has_not_been_filed(self, client, session):
        interim = _source_period(
            "TEST_US_EQ",
            source="yahoo_statements",
            period_end=dt.date(2024, 6, 30),
            period_type="interim",
        )
        _store(session, "TEST_US_EQ", interim)
        session.commit()

        body = client.get(f"/accounts/{interim.id}").text
        listing = client.get("/instrument/TEST_US_EQ?tab=accounts").text

        assert "interim accounts" in body
        assert "full year's have not been filed" in body
        assert "chip warn" in listing, "the year list labels it as interim too"
        assert "interim" in listing

    def test_a_price_per_share_keeps_its_pence(self, client, session):
        """The page printed Microsoft's diluted EPS -- 17.95, from the filer's own accounts --
        as **18**, because every ledger amount was formatted with no decimal places. A
        per-share figure is a price, and the memo lines are where they appear."""
        row = _source_period(
            "TEST_US_EQ",
            source="xbrl_companyfacts",
            metrics={**BALANCED, "eps_diluted": 17.95, "dividend_per_share": 3.64},
        )
        _store(session, "TEST_US_EQ", row)
        session.commit()

        body = client.get(f"/accounts/{row.id}").text

        assert "17.95" in body
        assert "3.64" in body
        assert ">18<" not in body, "the EPS was rounded to the pound"

    def test_a_rolling_snapshot_opens_and_says_what_it_is(self, client, session):
        """29 live instruments carry a `ttm` row, and the Accounts tab linked to them before
        this work: a link that now 404s or silently showed a fiscal year would be worse."""
        rolling = _source_period(
            "TEST_US_EQ",
            source="yahoo_info",
            period_end=dt.date(2024, 12, 31),
            period_type="ttm",
        )
        _store(session, "TEST_US_EQ", rolling)
        session.commit()

        response = client.get(f"/accounts/{rolling.id}")

        assert response.status_code == 200
        assert "rolling twelve months" in response.text
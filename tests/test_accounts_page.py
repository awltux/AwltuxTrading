"""The accounts page: the way in, the tabs, and what each one puts on the screen.

The feature these guard is a *navigation* one -- a date stamp on the instrument page
that opens the period as a set of accounts -- so the tests are about reachability and
about the page saying the true thing, not about the arithmetic. The arithmetic is
`tests/test_ledger.py`'s business.
"""

from __future__ import annotations

import datetime as dt

import pytest

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
    """The date stamp is the entry point. A page nobody can reach is not a feature."""

    def test_the_period_date_on_the_instrument_page_links_to_its_accounts(
        self, client, session, stored_period
    ):
        body = client.get("/instrument/TEST_US_EQ").text

        assert f'href="/accounts/{stored_period.id}"' in body, (
            "the date stamp must open the accounts"
        )

    def test_every_stored_period_is_reachable(self, client, session, stored_period):
        """Both periods, not only the newest -- the older one is what the articulation
        checks compare against, and a reader may want to open it directly."""
        body = client.get("/instrument/TEST_US_EQ").text

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

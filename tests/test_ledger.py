"""The double-entry ledger over the stored accounts, and what it checks.

The property that makes this a ledger rather than three lists of numbers is that the
figures are posted to named accounts with normal sides and the two sides have to agree.
These tests assert that directly, and -- more importantly -- assert the cases where it
**disagrees**, because an imbalance that has been quietly plugged is the failure mode
the whole module exists to avoid.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis import ledger
from awltux.analysis.ledger import CREDIT, DEBIT
from tests.helpers import make_period


def _year(**metrics):
    return make_period("T", dt.date(2024, 12, 31), metrics)


def _balanced(**extra) -> dict:
    """A complete, internally consistent set of accounts.

    Every stated subtotal equals the sum of the components this project extracts, and
    the accounting equation holds, so any residual a test measures came from what the
    test changed rather than from the fixture.
    """
    metrics = {
        "revenue": 1_000.0,
        "cost_of_goods_sold": 600.0,
        "gross_profit": 400.0,
        "research_and_development": 50.0,
        "sga_expense": 150.0,
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
    metrics.update(extra)
    return metrics


class TestTheLedgerIsPostedNotSummed:
    """The decision that makes the equation check mean something."""

    def test_the_equation_posts_the_stated_totals(self):
        """Not the components.

        Posting components would make every filer look insolvent by exactly the amount
        of the accounts this project does not extract, so the check would measure our
        coverage rather than the extraction's accuracy.
        """
        ledger_ = ledger.trial_balance(_year(**_balanced()))

        keys = {posting.account.key for posting in ledger_.postings}
        assert keys == {"total_assets", "total_liabilities", "total_equity"}
        assert ledger_.debits == 850.0
        assert ledger_.credits == 850.0
        assert ledger_.balanced

    def test_assets_and_equity_are_on_opposite_sides(self):
        ledger_ = ledger.trial_balance(_year(**_balanced()))

        sides = {posting.account.key: posting.account.side for posting in ledger_.postings}
        assert sides["total_assets"] == DEBIT
        assert sides["total_liabilities"] == CREDIT
        assert sides["total_equity"] == CREDIT

    def test_an_equation_that_does_not_hold_is_reported_not_plugged(self):
        """The point of the whole module: a difference survives to be seen.

        Total assets inflated by 50 with liabilities and equity untouched is an
        extraction error, and the ledger must say so rather than finding a balancing
        figure.
        """
        ledger_ = ledger.trial_balance(_year(**_balanced(total_assets=900.0)))

        assert not ledger_.balanced
        assert ledger_.difference == pytest.approx(50.0)

    def test_an_incomplete_equation_is_not_reported_as_a_pass(self):
        """An empty ledger balances trivially, which is the worst way to be wrong.

        ``balanced`` and ``complete`` are different questions, and the check has to ask
        the second one. A period with nothing extracted would otherwise report a clean
        accounting equation on the strength of holding no figures at all.
        """
        empty = _year(net_income=1.0)
        ledger_ = ledger.trial_balance(empty)

        assert ledger_.balanced, "0 = 0 is true and means nothing"
        assert not ledger_.complete, "but it must not be reported as a clean bill"
        assert ledger.equation_check(empty).status == ledger.UNKNOWN

    def test_rounding_within_tolerance_is_accepted(self):
        """Providers round to millions; half a percent must not read as an error."""
        ledger_ = ledger.trial_balance(_year(**_balanced(total_assets=850.4)))

        assert ledger_.balanced


class TestTheEquationCheck:
    def test_it_says_what_is_missing_rather_than_failing(self):
        check = ledger.equation_check(_year(total_assets=100.0, total_equity=100.0))

        assert check.status == ledger.UNKNOWN
        assert "total_liabilities" in check.detail

    def test_a_real_imbalance_is_a_failure(self):
        check = ledger.equation_check(_year(**_balanced(total_equity=440.0)))

        assert check.status == ledger.IMBALANCE
        assert check.failed
        assert check.residual == pytest.approx(50.0)

    def test_a_consistent_balance_sheet_passes(self):
        check = ledger.equation_check(_year(**_balanced()))

        assert check.status == ledger.OK
        assert check.residual == pytest.approx(0.0)


class TestComposition:
    """Whether the lines we hold add up to the totals the filing states."""

    def test_it_reports_the_size_of_what_is_not_extracted(self):
        """A check, not a note, because the size decides whether a statement is usable.

        Here 100 of assets are in accounts this taxonomy does not carry. That is not a
        defect, but it is the difference between a complete balance sheet and one
        missing a tenth of itself, and the reader cannot tell without the number.
        """
        check = next(
            c for c in ledger.composition(_year(**_balanced(total_assets=950.0)))
            if c.key == "assets_composition"
        )

        assert check.status == ledger.IMBALANCE
        assert check.residual == pytest.approx(100.0)
        assert check.inputs["stated"] == 950.0
        assert check.inputs["computed"] == 850.0

    def test_matching_components_pass(self):
        checks = {c.key: c for c in ledger.composition(_year(**_balanced()))}

        assert checks["assets_composition"].status == ledger.OK
        assert checks["liabilities_composition"].status == ledger.OK
        assert checks["current_assets_composition"].status == ledger.OK

    def test_a_missing_side_is_unknown_rather_than_a_pass(self):
        checks = {c.key: c for c in ledger.composition(_year(net_ppe=300.0))}

        assert checks["assets_composition"].status == ledger.UNKNOWN


class TestProfitArticulation:
    def test_the_lines_reconcile_to_reported_profit(self):
        check = ledger.profit_articulation(_year(**_balanced()))

        assert check.status == ledger.OK
        assert check.residual == pytest.approx(0.0)

    def test_a_line_we_do_not_hold_shows_up_as_a_residual(self):
        """Profit of 110 cannot be reproduced from revenue 1,000 and the costs held
        when 40 of costs are missing from the taxonomy."""
        check = ledger.profit_articulation(_year(**_balanced(net_income=70.0)))

        assert check.status == ledger.IMBALANCE
        assert check.residual == pytest.approx(-40.0), "stated less computed"

    def test_a_missing_revenue_does_not_become_a_loss(self):
        """Subtracting costs from a missing revenue gives a negative number that reads
        like a loss. The base has to exist or there is no subtotal at all."""
        statement = ledger.profit_and_loss(_year(cost_of_goods_sold=600.0, net_income=-600.0))

        gross = next(line for line in statement.lines if line.key == "gross_profit")
        assert gross.computed is None
        assert "revenue" in statement.gaps


class TestRetainedEarnings:
    def test_closing_equals_opening_plus_profit_less_dividends(self):
        previous = _year(**_balanced(retained_earnings=300.0))
        current = _year(
            **_balanced(retained_earnings=370.0, net_income=110.0, dividends_paid=40.0)
        )

        check = ledger.retained_earnings_rollforward(current, previous)

        assert check.status == ledger.OK
        assert check.residual == pytest.approx(0.0)

    def test_a_movement_that_does_not_articulate_is_a_failure(self):
        previous = _year(**_balanced(retained_earnings=300.0))
        current = _year(**_balanced(retained_earnings=500.0))

        check = ledger.retained_earnings_rollforward(current, previous)

        assert check.status == ledger.IMBALANCE
        assert check.residual == pytest.approx(130.0)

    def test_one_period_cannot_articulate_and_says_so(self):
        check = ledger.retained_earnings_rollforward(_year(**_balanced()), None)

        assert check.status == ledger.UNKNOWN
        assert "previous period" in check.detail


class TestCashMovement:
    def test_it_reports_the_unexplained_movement(self):
        """Expected to disagree, and the size is the useful part: the taxonomy holds no
        acquisitions, disposals, share issues or borrowings."""
        previous = _year(**_balanced(cash_and_equivalents=200.0))
        current = _year(**_balanced(cash_and_equivalents=340.0))

        check = ledger.cash_movement(current, previous)

        assert check.status == ledger.IMBALANCE
        assert check.inputs["explained"] == pytest.approx(80.0)
        assert check.residual == pytest.approx(60.0)

    def test_a_movement_explained_by_the_lines_held_passes(self):
        previous = _year(**_balanced(cash_and_equivalents=200.0))
        current = _year(**_balanced(cash_and_equivalents=280.0))

        check = ledger.cash_movement(current, previous)

        assert check.status == ledger.OK


class TestTheStatements:
    @pytest.mark.parametrize("which", ["profit_and_loss", "balance_sheet", "cash_flow"])
    def test_every_statement_builds_and_names_itself(self, which):
        built = ledger.statement(_year(**_balanced()), which)

        assert built.which == which
        assert built.lines, "a statement with no lines is not a statement"

    def test_an_unknown_statement_is_refused(self):
        with pytest.raises(KeyError, match="no statement"):
            ledger.statement(_year(**_balanced()), "trial_balance")

    def test_the_balance_sheet_carries_its_trial_balance(self):
        statement = ledger.balance_sheet(_year(**_balanced()))

        assert statement.trial_balance is not None
        assert statement.trial_balance.balanced

    def test_each_line_keeps_the_stated_and_the_computed_figure(self):
        """Both are printed, because the residual between them is the finding."""
        statement = ledger.profit_and_loss(_year(**_balanced(gross_profit=390.0)))
        gross = next(line for line in statement.lines if line.key == "gross_profit")

        assert gross.stated == 390.0
        assert gross.computed == 400.0
        assert gross.agrees is False
        assert gross.residual == pytest.approx(-10.0)

    def test_a_line_with_only_a_stated_figure_is_not_called_agreeing(self):
        """``None`` is not the same answer as ``True``, and the page has to know."""
        statement = ledger.balance_sheet(_year(total_assets=500.0))
        assets = next(line for line in statement.lines if line.key == "total_assets")

        assert assets.agrees is None
        assert assets.amount == 500.0

    def test_the_cash_flow_admits_it_is_not_complete(self):
        """It holds three lines of a statement that normally has a dozen, and saying
        so is better than implying the movement is fully explained."""
        statement = ledger.cash_flow(_year(**_balanced()))

        assert any("not a complete statement" in note for note in statement.notes)

    def test_free_cash_flow_is_computed_when_the_provider_omits_it(self):
        statement = ledger.cash_flow(_year(operating_cash_flow=180.0, capex=60.0))
        free = next(line for line in statement.lines if line.key == "free_cash_flow")

        assert free.computed == 120.0
        assert free.amount == 120.0


class TestTheChart:
    def test_every_account_key_is_a_canonical_metric(self):
        """The chart is a view of the vocabulary, not a second list that can drift.

        This is the same failure `metrics.py` was written to end: three lists of names
        that disagreed about which ones existed.
        """
        from awltux.metrics import CANONICAL_METRICS

        unknown = [a.key for a in ledger.CHART if a.key not in CANONICAL_METRICS]
        assert not unknown, f"chart names that are not canonical metrics: {unknown}"

    def test_no_metric_is_posted_twice(self):
        """A duplicate posting is how a total gets double-counted without anyone
        noticing, so the chart is checked for it rather than trusted."""
        keys = [account.key for account in ledger.CHART]
        assert len(keys) == len(set(keys))

    def test_components_and_subtotals_are_distinguished(self):
        """``total_assets`` must not be a posted component, or the assets would be
        counted once as components and again as a total."""
        assert ledger.BY_KEY["total_assets"].role == "subtotal"
        assert ledger.BY_KEY["cash_and_equivalents"].role == "line"

    def test_the_equation_uses_only_subtotals(self):
        for key in ledger.EQUATION_DEBIT + ledger.EQUATION_CREDIT:
            assert ledger.BY_KEY[key].role == "subtotal", key

    def test_every_chart_account_belongs_to_a_known_statement(self):
        known = {name for name, _ in ledger.STATEMENTS}
        strangers = [a.key for a in ledger.CHART if a.statement not in known]
        assert not strangers, strangers


class TestEveryCheckIsReported:
    def test_a_period_with_nothing_stated_still_produces_its_checks(self):
        """Silence would read as a clean bill of health. Every check has to appear,
        marked as not computable, or a reader cannot tell "fine" from "we did not
        look"."""
        results = ledger.checks(_year(net_income=1.0))

        assert {c.key for c in results} == {
            "accounting_equation",
            "profit_articulation",
            "assets_composition",
            "liabilities_composition",
            "current_assets_composition",
            "retained_earnings_rollforward",
            "cash_movement",
        }
        assert all(c.status in {ledger.OK, ledger.IMBALANCE, ledger.UNKNOWN} for c in results)

"""Mapping provider statements onto the canonical metric keys.

The judgement in this module is which vendor row label becomes which canonical
name, and the failure mode is quiet: a mis-mapped label produces a plausible
number under the wrong key, and every marker built on it is then wrong in a way
nothing downstream can detect. So the tests here are mostly about which label
wins, and about the labels that must *not* be used.
"""

from __future__ import annotations

from awltux.ingest.fundamentals import (
    STATEMENT_LABELS,
    derive_metrics,
    metrics_from_info,
    metrics_from_statements,
)
from awltux.metrics import STATED_METRICS


def _statements(**sections: dict[str, float]) -> dict:
    """Two periods, so a column index actually selects something."""
    out = {}
    for name, rows in sections.items():
        out[name] = {
            "columns": ["2024-12-31", "2023-12-31"],
            "rows": {label: [value, value / 2] for label, value in rows.items()},
        }
    return out


class TestStatementMapping:
    def test_the_new_marker_inputs_are_mapped(self):
        financials = _statements(
            income={"Total Revenue": 1_000.0, "EBIT": 150.0},
            balance={
                "Receivables": 220.0,
                "Inventory": 140.0,
                "Payables": 90.0,
                "Net PPE": 400.0,
                "Goodwill": 75.0,
                "Other Intangible Assets": 30.0,
                "Current Debt": 60.0,
                "Long Term Debt": 200.0,
                "Retained Earnings": 310.0,
            },
            cashflow={"Stock Based Compensation": 18.0},
        )
        metrics = metrics_from_statements(financials, 0)

        assert metrics["receivables"] == 220.0
        assert metrics["inventory"] == 140.0
        assert metrics["payables"] == 90.0
        assert metrics["net_ppe"] == 400.0
        assert metrics["goodwill"] == 75.0
        assert metrics["intangible_assets"] == 30.0
        assert metrics["short_term_debt"] == 60.0
        assert metrics["long_term_debt"] == 200.0
        assert metrics["retained_earnings"] == 310.0
        assert metrics["stock_based_compensation"] == 18.0

    def test_the_column_index_selects_the_period(self):
        financials = _statements(income={"Total Revenue": 1_000.0})
        assert metrics_from_statements(financials, 0)["revenue"] == 1_000.0
        assert metrics_from_statements(financials, 1)["revenue"] == 500.0

    def test_a_combined_label_never_stands_in_for_a_narrow_one(self):
        """Yahoo publishes "Goodwill And Other Intangible Assets" as well as
        "Goodwill". Using the combined figure for `goodwill` would inflate the
        equity-softness marker on exactly the companies it exists to flag."""
        financials = _statements(
            balance={"Goodwill And Other Intangible Assets": 900.0},
        )
        metrics = metrics_from_statements(financials, 0)
        assert "goodwill" not in metrics
        assert "intangible_assets" not in metrics

    def test_capex_is_normalised_to_a_positive_outflow(self):
        financials = _statements(cashflow={"Capital Expenditure": -40.0})
        assert metrics_from_statements(financials, 0)["capex"] == 40.0

    def test_every_mapped_label_is_a_canonical_name(self):
        """A typo in a key here would write a metric nothing can read."""
        for key in STATEMENT_LABELS:
            assert key in STATED_METRICS, key

    def test_the_earlier_section_wins_for_a_shared_label(self):
        """Depreciation is an income-statement charge and also a cash-flow add-back;
        the income-statement figure is the one the accrual work wants."""
        financials = _statements(
            income={"Reconciled Depreciation": 50.0},
            cashflow={"Reconciled Depreciation": 999.0},
        )
        assert metrics_from_statements(financials, 0)["depreciation_amortisation"] == 50.0


class TestDerivedMetrics:
    def test_free_cash_flow_is_derived_when_the_provider_omits_it(self):
        """It is an identity, not a disclosure, and most non-large-caps need it."""
        derived = derive_metrics({"operating_cash_flow": 160.0, "capex": 40.0})
        assert derived["free_cash_flow"] == 120.0

    def test_a_provider_definition_is_never_overwritten(self):
        derived = derive_metrics(
            {"operating_cash_flow": 160.0, "capex": 40.0, "free_cash_flow": 130.0}
        )
        assert "free_cash_flow" not in derived

    def test_free_cash_flow_is_left_missing_when_it_cannot_be_computed(self):
        assert "free_cash_flow" not in derive_metrics({"operating_cash_flow": 160.0})

    def test_margins_come_from_revenue(self):
        derived = derive_metrics({"revenue": 1_000.0, "gross_profit": 400.0})
        assert derived["gross_margin"] == 0.4

    def test_roce_uses_operating_profit_over_capital_employed(self):
        derived = derive_metrics(
            {"operating_income": 150.0, "total_equity": 700.0, "total_debt": 200.0}
        )
        assert derived["roce"] == 150.0 / 900.0


class TestInfoFallback:
    def test_profile_figures_map_onto_canonical_names(self):
        metrics = metrics_from_info(
            {"totalRevenue": 1_000.0, "freeCashflow": 120.0, "sharesOutstanding": 100.0}
        )
        assert metrics == {
            "revenue": 1_000.0,
            "free_cash_flow": 120.0,
            "shares_outstanding": 100.0,
        }

    def test_unknown_keys_are_ignored_rather_than_stored(self):
        metrics = metrics_from_info({"totalRevenue": 1_000.0, "recommendationKey": "buy"})
        assert set(metrics) == {"revenue"}

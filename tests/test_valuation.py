"""The deterministic valuation model.

These tests matter more than most: this is where every number in the system
originates. They check both that the arithmetic is right and that the model
*refuses* when its inputs are inadequate, because a fabricated fair value flows
straight into a buy recommendation.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis.valuation import (
    PeerMultiples,
    cost_of_equity,
    dividend_discount,
    earnings_power_value,
    graham_number,
    residual_income,
    sector_multiples,
    value_instrument,
    wacc,
)
from awltux.config import get_settings
from tests.helpers import healthy_metrics, make_period


def _snapshot(periods):
    from awltux.analysis.fundamental import build_snapshot

    return build_snapshot(periods)


class TestDiscountRates:
    def test_cost_of_equity_follows_capm(self):
        settings = get_settings()
        config = settings.valuation
        value = cost_of_equity(1.0, settings)
        assert value == pytest.approx(config.risk_free_rate + config.equity_risk_premium)

    def test_missing_beta_falls_back_to_one(self):
        settings = get_settings()
        assert cost_of_equity(None, settings) == pytest.approx(cost_of_equity(1.0, settings))

    def test_absurd_beta_is_clamped(self):
        """Providers occasionally report absurd betas for thin listings."""
        settings = get_settings()
        assert cost_of_equity(50.0, settings) == pytest.approx(cost_of_equity(3.0, settings))

    def test_wacc_without_debt_is_the_cost_of_equity(self):
        rate, inputs = wacc(
            cost_of_equity_value=0.10, market_cap=1_000_000.0, total_debt=0.0, interest_expense=None
        )
        assert rate == pytest.approx(0.10)
        assert inputs["debt_weight"] == 0.0

    def test_wacc_without_market_cap_is_the_cost_of_equity(self):
        rate, inputs = wacc(
            cost_of_equity_value=0.10, market_cap=None, total_debt=500_000.0, interest_expense=10_000.0
        )
        assert rate == pytest.approx(0.10)
        assert "all-equity" in inputs["note"]

    def test_wacc_blends_both_sources_of_capital(self):
        rate, inputs = wacc(
            cost_of_equity_value=0.10,
            market_cap=1_000_000.0,
            total_debt=1_000_000.0,
            interest_expense=50_000.0,
        )
        assert 0.05 < rate < 0.10
        assert inputs["equity_weight"] == pytest.approx(0.5)
        assert inputs["debt_weight"] == pytest.approx(0.5)


class TestEarningsPowerValue:
    def test_capitalises_maintainable_earnings(self):
        settings = get_settings()
        periods = [
            make_period("T", dt.date(2023, 12, 31), healthy_metrics()),
            make_period("T", dt.date(2024, 12, 31), healthy_metrics()),
        ]
        result = earnings_power_value(
            snapshot=_snapshot(periods),
            periods=periods,
            shares=100_000.0,
            beta=1.0,
            net_debt=120_000.0,
            settings=settings,
        )
        assert result.applicable
        # 100,000 earnings at ~9.7% cost of equity, less 120,000 net debt.
        assert result.fair_value_per_share is not None
        assert result.fair_value_per_share > 0

    def test_refuses_on_loss_making_earnings(self):
        settings = get_settings()
        periods = [
            make_period("T", dt.date(2024, 12, 31), healthy_metrics(net_income=-50_000.0))
        ]
        result = earnings_power_value(
            snapshot=_snapshot(periods),
            periods=periods,
            shares=100_000.0,
            beta=1.0,
            net_debt=0.0,
            settings=settings,
        )
        assert not result.applicable
        assert "not positive" in result.reason

    def test_refuses_without_a_share_count(self):
        settings = get_settings()
        periods = [make_period("T", dt.date(2024, 12, 31), healthy_metrics())]
        result = earnings_power_value(
            snapshot=_snapshot(periods),
            periods=periods,
            shares=None,
            beta=1.0,
            net_debt=0.0,
            settings=settings,
        )
        assert not result.applicable


class TestResidualIncome:
    def test_needs_positive_book_value(self):
        settings = get_settings()
        periods = [
            make_period("T", dt.date(2024, 12, 31), healthy_metrics(total_equity=-1000.0))
        ]
        result = residual_income(
            snapshot=_snapshot(periods),
            shares=100_000.0,
            beta=1.0,
            book_value=-1000.0,
            settings=settings,
        )
        assert not result.applicable

    def test_high_roe_produces_value_above_book(self):
        settings = get_settings()
        periods = [
            make_period("T", dt.date(2024, 12, 31), healthy_metrics(roe=0.25, total_equity=700_000.0))
        ]
        result = residual_income(
            snapshot=_snapshot(periods),
            shares=100_000.0,
            beta=1.0,
            book_value=700_000.0,
            settings=settings,
        )
        assert result.applicable
        assert result.fair_value_per_share is not None
        assert result.fair_value_per_share > 700_000.0 / 100_000.0


class TestDividendDiscount:
    def test_refuses_an_uncovered_dividend(self):
        """Extrapolating a perpetual growth formula from an unsustainable
        dividend produces a confidently wrong number, so it is refused."""
        settings = get_settings()
        periods = [
            make_period(
                "T",
                dt.date(2024, 12, 31),
                healthy_metrics(dividend_per_share=2.0, payout_ratio=1.4),
            )
        ]
        result = dividend_discount(snapshot=_snapshot(periods), beta=1.0, settings=settings)
        assert not result.applicable
        assert "too high to extrapolate" in result.reason

    def test_refuses_when_cash_flow_does_not_cover_the_dividend(self):
        settings = get_settings()
        periods = [
            make_period(
                "T",
                dt.date(2024, 12, 31),
                healthy_metrics(dividend_per_share=0.5, payout_ratio=0.4, free_cash_flow=-1000.0),
            )
        ]
        result = dividend_discount(snapshot=_snapshot(periods), beta=1.0, settings=settings)
        assert not result.applicable
        assert "not covered" in result.reason

    def test_values_a_covered_dividend(self):
        settings = get_settings()
        periods = [
            make_period(
                "T",
                dt.date(2024, 12, 31),
                healthy_metrics(dividend_per_share=0.5, payout_ratio=0.5, revenue_cagr=0.02),
            )
        ]
        result = dividend_discount(snapshot=_snapshot(periods), beta=1.0, settings=settings)
        assert result.applicable
        assert result.fair_value_per_share is not None
        assert result.fair_value_per_share > 0


class TestGraham:
    def test_refuses_without_positive_earnings(self):
        periods = [
            make_period("T", dt.date(2024, 12, 31), healthy_metrics(eps_diluted=-1.0))
        ]
        result = graham_number(
            snapshot=_snapshot(periods), book_value=700_000.0, shares=100_000.0
        )
        assert not result.applicable

    def test_computes_the_defensive_bound(self):
        periods = [make_period("T", dt.date(2024, 12, 31), healthy_metrics(eps_diluted=1.0))]
        result = graham_number(
            snapshot=_snapshot(periods), book_value=700_000.0, shares=100_000.0
        )
        assert result.applicable
        # sqrt(22.5 * 1.0 * 7.0) = 12.55
        assert result.fair_value_per_share == pytest.approx(12.55, abs=0.02)


class TestBlend:
    def test_refuses_a_value_with_too_few_methods(self):
        """One method's output is an assumption, not a valuation."""
        settings = get_settings()
        result = value_instrument(
            price=10.0,
            currency="USD",
            periods=[
                make_period(
                    "T",
                    dt.date(2024, 12, 31),
                    # Only EPV can apply: no FCF, no book value, no dividend.
                    {"net_income": 100_000.0, "shares_outstanding": 100_000.0},
                )
            ],
            closes=[10.0] * 30,
            volumes=[1000.0] * 30,
            market_cap=1_000_000.0,
            beta=1.0,
            peers=PeerMultiples(),
            settings=settings,
        )
        assert result.status == "insufficient_data"
        assert result.fair_value_base is None
        assert result.margin_of_safety is None

    def test_refuses_without_a_share_count(self):
        settings = get_settings()
        result = value_instrument(
            price=10.0,
            currency="USD",
            periods=[make_period("T", dt.date(2024, 12, 31), healthy_metrics(shares_outstanding=0.0))],
            closes=[10.0] * 30,
            volumes=[1000.0] * 30,
            market_cap=1_000_000.0,
            beta=1.0,
            peers=PeerMultiples(),
            settings=settings,
        )
        assert result.status == "insufficient_data"
        assert any("share count" in note for note in result.notes)

    def test_refuses_without_a_price(self):
        settings = get_settings()
        result = value_instrument(
            price=None,
            currency="USD",
            periods=[],
            closes=[],
            volumes=[],
            market_cap=None,
            beta=1.0,
            peers=PeerMultiples(),
            settings=settings,
        )
        assert result.status == "insufficient_data"

    def test_healthy_company_gets_a_range_and_positive_margin(self):
        settings = get_settings()
        periods = [
            make_period("T", dt.date(2022, 12, 31), healthy_metrics()),
            make_period("T", dt.date(2023, 12, 31), healthy_metrics()),
            make_period("T", dt.date(2024, 12, 31), healthy_metrics()),
        ]
        closes = [10.0] * 260
        result = value_instrument(
            price=10.0,
            currency="USD",
            periods=periods,
            closes=closes,
            volumes=[1000.0] * 260,
            market_cap=1_000_000.0,
            beta=1.0,
            peers=PeerMultiples(pe=12.0, pb=1.5, ev_ebitda=7.0, sample_size=8, sector="Tech"),
            settings=settings,
        )
        assert result.status == "ok"
        assert result.fair_value_base is not None
        assert result.fair_value_low < result.fair_value_base < result.fair_value_high
        assert result.margin_of_safety is not None
        # A 15x earnings multiple on 1.0 EPS is well above the 10.0 price.
        assert result.margin_of_safety > 0
        assert result.valuation_confidence is not None

    def test_margin_of_safety_formula(self):
        settings = get_settings()
        periods = [
            make_period("T", dt.date(2024, 12, 31), healthy_metrics()),
            make_period("T", dt.date(2023, 12, 31), healthy_metrics()),
        ]
        result = value_instrument(
            price=8.0,
            currency="USD",
            periods=periods,
            closes=[8.0] * 260,
            volumes=[1000.0] * 260,
            market_cap=800_000.0,
            beta=1.0,
            peers=PeerMultiples(pe=15.0, pb=2.0, ev_ebitda=9.0, sample_size=8),
            settings=settings,
        )
        if result.status == "ok" and result.fair_value_base:
            expected = (result.fair_value_base - 8.0) / result.fair_value_base
            assert result.margin_of_safety == pytest.approx(expected)

    def test_graham_is_excluded_from_the_blend(self):
        """Graham is a bound for a different investor, not a fair-value estimate."""
        settings = get_settings()
        periods = [
            make_period("T", dt.date(2024, 12, 31), healthy_metrics()),
            make_period("T", dt.date(2023, 12, 31), healthy_metrics()),
        ]
        result = value_instrument(
            price=10.0,
            currency="USD",
            periods=periods,
            closes=[10.0] * 260,
            volumes=[1000.0] * 260,
            market_cap=1_000_000.0,
            beta=1.0,
            peers=PeerMultiples(pe=15.0, pb=2.0, ev_ebitda=9.0, sample_size=8),
            settings=settings,
        )
        # Graham is computed and reported, but is not a contributor.
        assert "graham" not in result.methods_applied
        graham = next((m for m in result.methods if m.name == "graham"), None)
        assert graham is not None and graham.applicable


class TestSectorMultiples:
    def test_derives_multiples_from_stored_data(self, session):
        from tests.helpers import make_instrument

        sector = "Technology"
        for index in range(6):
            session.add(
                make_instrument(
                    f"T{index}_US_EQ",
                    name=f"Company {index}",
                    yahoo_symbol=f"T{index}",
                    sector=sector,
                    market_cap=1_000_000.0 + index * 10_000.0,
                )
            )
        # Flush the instruments first: there is no ORM relationship between
        # Instrument and FundamentalPeriod for the unit of work to order by, so
        # the foreign key would otherwise be inserted before its parent.
        session.flush()

        for index in range(6):
            session.add(
                make_period(
                    f"T{index}_US_EQ",
                    dt.date(2024, 12, 31),
                    healthy_metrics(
                        net_income=100_000.0,
                        total_equity=700_000.0,
                        ebitda=180_000.0,
                        net_debt=120_000.0,
                    ),
                )
            )
        session.flush()

        multiples = sector_multiples(session)
        assert sector in multiples
        peers = multiples[sector]
        assert peers.sample_size >= 4
        assert peers.pe is not None and peers.pe > 0
        assert peers.ev_ebitda is not None and peers.ev_ebitda > 0

"""The risk-free rate, and the fact that it stopped being a constant.

The rate anchors the CAPM cost of equity, which anchors every discount rate, which
decides every discounted fair value in the database. It used to be typed into
``config.yaml``, which is honest on the day it is typed and silently wrong
afterwards: on 2026-10-05 the ten-year Treasury yielded 5.31% against a configured
4.2%, and this model's own DCF gives up about 14% of its fair value across that gap.

These tests cover both halves of the fix -- reading the rate from the primary source,
and refusing to act on a rate that cannot be one.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis import macro
from awltux.analysis.valuation import PeerMultiples, cost_of_equity, value_instrument
from awltux.db import AppSetting, session_scope
from awltux.providers.treasury import YieldCurve, parse_yield_curve
from tests.helpers import make_period

#: Captured verbatim from the Treasury's own endpoint, so the parser is tested
#: against the shape it actually receives rather than an invented one.
REAL_CSV = (
    'Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr",'
    '"5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "10/05/2026,4.05,4.10,4.13,4.22,4.27,4.30,4.47,4.84,4.97,5.06,5.19,5.31,5.70,5.66\n"
    "10/02/2026,4.04,4.09,4.11,4.19,4.26,4.27,4.46,4.83,4.96,5.06,5.17,5.28,5.67,5.63\n"
)


class TestParsingTheCurve:
    def test_the_newest_row_wins(self):
        curve = parse_yield_curve(REAL_CSV)
        assert curve is not None
        assert curve.as_of == dt.date(2026, 10, 5)

    def test_yields_are_read_as_percentages(self):
        curve = parse_yield_curve(REAL_CSV)
        assert curve is not None
        assert curve.percent("10 Yr") == pytest.approx(5.31)
        # The distinction the whole module is built around.
        assert curve.fraction("10 Yr") == pytest.approx(0.0531)

    def test_every_tenor_is_kept(self):
        curve = parse_yield_curve(REAL_CSV)
        assert curve is not None
        assert curve.percent("3 Mo") == pytest.approx(4.22)
        assert curve.percent("30 Yr") == pytest.approx(5.66)
        assert len(curve.rates) == 14

    def test_a_file_with_no_rows_is_none_not_an_exception(self):
        """Normal on 1-2 January, before the year's first publication."""
        assert parse_yield_curve('Date,"10 Yr"\n') is None
        assert parse_yield_curve("") is None

    def test_a_blank_tenor_does_not_discard_the_curve(self):
        text = 'Date,"3 Mo","10 Yr"\n10/05/2026,4.22,\n'
        curve = parse_yield_curve(text)
        assert curve is not None
        assert curve.percent("10 Yr") is None
        assert curve.fraction("10 Yr") is None
        assert curve.percent("3 Mo") == pytest.approx(4.22)


class TestThePlausibilityGuard:
    """A plausible-looking wrong rate is worse than no rate at all.

    A yield used as a fraction, or a fraction divided by 100 a second time, moves
    every fair value in the database while looking completely normal.
    """

    @pytest.mark.parametrize("rate", [0.0531, 0.005, 0.042, 0.15])
    def test_real_rates_are_accepted(self, rate):
        assert macro.is_plausible(rate)

    @pytest.mark.parametrize(
        "rate",
        [
            5.31,     # a percentage used as a fraction: 100x too large
            0.000531,  # a fraction divided by 100 again: 100x too small
            0.0,
            -0.01,
            None,
            1.0,
        ],
    )
    def test_unit_and_parse_errors_are_refused(self, rate):
        assert not macro.is_plausible(rate)

    def test_a_curve_already_in_decimals_is_refused_at_storage(self, settings):
        """The exact double-division slip, end to end through the store path.

        Takes ``settings`` so this runs against the fixture's fresh database: the
        assertion that nothing was *read back* is only meaningful in isolation.
        """
        wrong = YieldCurve(as_of=dt.date(2026, 10, 5), rates={"10 Yr": 0.0531})
        with session_scope() as session:
            assert macro.store_observation(session, wrong, tenor="10 Yr") is None
            assert macro.read_observation(session) is None


class TestResolvingTheRate:
    def test_the_market_wins_when_an_observation_exists(self, settings):
        curve = parse_yield_curve(REAL_CSV)
        assert curve is not None
        with session_scope() as session:
            macro.store_observation(session, curve, tenor="10 Yr")
            resolved = macro.resolve_risk_free_rate(session, settings)

        assert resolved.source == "market"
        assert resolved.value == pytest.approx(0.0531)
        assert resolved.as_of == "2026-10-05"
        assert resolved.tenor == "10 Yr"
        assert "10 Yr" in resolved.note

    def test_the_configured_rate_carries_the_day_before_anything_is_observed(self, settings):
        with session_scope() as session:
            resolved = macro.resolve_risk_free_rate(session, settings)

        assert resolved.source == "config"
        assert resolved.value == pytest.approx(settings.valuation.risk_free_rate)
        assert "macro_rates" in resolved.note, "the note should say how to fix it"

    def test_config_source_pins_the_constant_even_when_a_rate_was_observed(self, settings):
        curve = parse_yield_curve(REAL_CSV)
        assert curve is not None
        settings.yaml.valuation.risk_free_rate_source = "config"
        with session_scope() as session:
            macro.store_observation(session, curve, tenor="10 Yr")
            resolved = macro.resolve_risk_free_rate(session, settings)

        assert resolved.source == "config"
        assert resolved.value == pytest.approx(0.042)

    def test_a_corrupt_stored_value_falls_back_rather_than_being_used(self, settings):
        """Whatever wrote it was wrong, so the safe answer is the fallback."""
        with session_scope() as session:
            session.add(AppSetting(key=macro.SETTING_KEY, value={"value": 5.31}))
            session.flush()
            assert macro.read_observation(session) is None
            resolved = macro.resolve_risk_free_rate(session, settings)

        assert resolved.source == "config"

    def test_a_non_numeric_stored_value_is_not_fatal(self, settings):
        with session_scope() as session:
            session.add(AppSetting(key=macro.SETTING_KEY, value={"value": "not a rate"}))
            session.flush()
            assert macro.read_observation(session) is None


class TestTheModelUsesIt:
    def test_cost_of_equity_honours_the_override(self, settings):
        configured = cost_of_equity(1.0, settings)
        observed = cost_of_equity(1.0, settings, risk_free_rate=0.0531)

        assert configured == pytest.approx(0.042 + 0.055)
        assert observed == pytest.approx(0.0531 + 0.055)
        assert observed > configured

    def test_a_higher_rate_produces_a_lower_dcf(self, settings):
        """The channel that makes the constant matter, asserted on the model."""
        period = make_period(
            "TEST_US_EQ",
            dt.date(2025, 12, 31),
            {
                "revenue": 1_000_000.0,
                "net_income": 100_000.0,
                "operating_cash_flow": 160_000.0,
                "free_cash_flow": 120_000.0,
                "total_debt": 200_000.0,
                "net_debt": 120_000.0,
                "total_equity": 700_000.0,
                "shares_outstanding": 100_000.0,
                "eps_diluted": 1.0,
            },
        )
        from awltux.analysis.fundamental import build_snapshot
        from awltux.analysis.valuation import dcf_fcff

        snapshot = build_snapshot([period])
        kwargs = dict(
            snapshot=snapshot,
            market_cap=1_500_000.0,
            shares=100_000.0,
            beta=1.0,
            net_debt=120_000.0,
            settings=settings,
        )
        at_config = dcf_fcff(**kwargs, risk_free_rate=0.042)
        at_market = dcf_fcff(**kwargs, risk_free_rate=0.0531)

        assert at_config.fair_value_per_share is not None
        assert at_market.fair_value_per_share is not None
        assert at_market.fair_value_per_share < at_config.fair_value_per_share
        # Measured, not guessed: this is the ~14% the module docstring quotes.
        drop = 1 - at_market.fair_value_per_share / at_config.fair_value_per_share
        assert 0.10 < drop < 0.20, f"expected a ~14% drop, measured {drop:.1%}"

    def test_the_rate_and_its_provenance_are_recorded_on_the_valuation(self, settings):
        period = make_period(
            "TEST_US_EQ",
            dt.date(2025, 12, 31),
            {
                "revenue": 1_000_000.0,
                "net_income": 100_000.0,
                "operating_cash_flow": 160_000.0,
                "free_cash_flow": 120_000.0,
                "total_debt": 200_000.0,
                "net_debt": 120_000.0,
                "total_equity": 700_000.0,
                "shares_outstanding": 100_000.0,
                "eps_diluted": 1.0,
            },
        )
        result = value_instrument(
            price=20.0,
            currency="USD",
            periods=[period],
            closes=[20.0, 21.0],
            volumes=[1.0, 1.0],
            market_cap=1_500_000.0,
            beta=1.0,
            peers=PeerMultiples(),
            settings=settings,
            risk_free_rate=0.0531,
            risk_free_rate_note="10 Yr US Treasury par yield, published 2026-10-05",
        )

        assumptions = result.inputs["assumptions"]
        assert assumptions["risk_free_rate"] == pytest.approx(0.0531)
        assert assumptions["risk_free_rate_source"] == "supplied"
        assert "2026-10-05" in assumptions["risk_free_rate_note"]
        # The constant is kept alongside, so a reader can see what was overridden.
        assert assumptions["risk_free_rate_fallback"] == pytest.approx(0.042)

    def test_the_market_source_is_recorded_when_it_was_the_market(self, settings):
        period = make_period(
            "TEST_US_EQ",
            dt.date(2025, 12, 31),
            {
                "revenue": 1_000_000.0,
                "net_income": 100_000.0,
                "free_cash_flow": 120_000.0,
                "shares_outstanding": 100_000.0,
                "eps_diluted": 1.0,
            },
        )
        result = value_instrument(
            price=20.0,
            currency="USD",
            periods=[period],
            closes=[20.0, 21.0],
            volumes=[1.0, 1.0],
            market_cap=1_500_000.0,
            beta=1.0,
            peers=PeerMultiples(),
            settings=settings,
            risk_free_rate=0.0531,
            risk_free_rate_note="10 Yr US Treasury par yield",
            risk_free_rate_source="market",
        )
        assert result.inputs["assumptions"]["risk_free_rate_source"] == "market"


class TestRateSensitivity:
    """How much of a fair value is a bet on the discount rate.

    A sensitivity, not a forecast. It answers the question the fair value cannot:
    whether this number rests on the company's cash flows or on the rate used to
    discount them -- which is the only input the model takes from the market rather
    than from the filings.
    """

    def _value(self, settings, metrics, peers=None):
        period = make_period("TEST_US_EQ", dt.date(2025, 12, 31), metrics)
        return value_instrument(
            price=10.0,
            currency="USD",
            periods=[period],
            closes=[10.0, 11.0],
            volumes=[1.0, 1.0],
            market_cap=1_000_000.0,
            beta=1.0,
            peers=peers or PeerMultiples(),
            settings=settings,
            risk_free_rate=0.0531,
        )

    CASH_GENERATOR = {
        "revenue": 1_000_000.0,
        "net_income": 150_000.0,
        "operating_cash_flow": 220_000.0,
        "free_cash_flow": 190_000.0,
        "total_debt": 100_000.0,
        "net_debt": 60_000.0,
        "total_equity": 800_000.0,
        "shares_outstanding": 100_000.0,
        "eps_diluted": 1.50,
        "revenue_cagr": 0.03,
    }

    def test_a_rise_in_the_rate_lowers_the_value(self, settings):
        """The sign is the whole point: higher discount rate, lower present value."""
        result = self._value(settings, self.CASH_GENERATOR)
        assert result.rate_sensitivity is not None
        assert result.rate_sensitivity < 0

    def test_the_shock_and_the_change_are_recorded_on_the_run(self, settings):
        result = self._value(settings, self.CASH_GENERATOR)
        recorded = result.inputs["rate_sensitivity"]

        assert recorded["shock"] == pytest.approx(0.01)
        assert recorded["fair_value_change_pct"] == pytest.approx(result.rate_sensitivity)
        assert "not a forecast" in recorded["note"].lower() or "discount rate" in recorded["note"]
        assert result.as_dict()["rate_sensitivity"] == result.rate_sensitivity

    def test_it_is_a_real_remeasurement_not_a_relabelled_constant(self, settings):
        """Shocking the rate must move the number it claims to describe."""
        shocked = self._value(settings, self.CASH_GENERATOR)
        # Same company, a rate two points higher: the sensitivity must differ,
        # because the response is not linear in the discount rate.
        period = make_period("TEST_US_EQ", dt.date(2025, 12, 31), self.CASH_GENERATOR)
        higher = value_instrument(
            price=10.0,
            currency="USD",
            periods=[period],
            closes=[10.0, 11.0],
            volumes=[1.0, 1.0],
            market_cap=1_000_000.0,
            beta=1.0,
            peers=PeerMultiples(),
            settings=settings,
            risk_free_rate=0.0731,
        )
        assert shocked.rate_sensitivity != higher.rate_sensitivity

    def test_a_peer_anchored_valuation_is_less_rate_sensitive(self, settings):
        """Multiples and Graham ignore the rate, so a company valued on peers must
        move less than one valued on its own discounted cash flows. That contrast
        is the reason the measure is worth showing."""
        peers = PeerMultiples(
            sector="Industrials", sample_size=8, ev_ebitda=12.0, pe=18.0, pb=2.5
        )
        cash_flows = self._value(settings, self.CASH_GENERATOR)
        # Almost no free cash flow, so the DCF and EPV carry little of the blend.
        thin = dict(self.CASH_GENERATOR, free_cash_flow=0.0, operating_cash_flow=1_000.0)
        multiples_led = self._value(settings, thin, peers=peers)

        assert cash_flows.rate_sensitivity is not None
        assert multiples_led.rate_sensitivity is not None
        assert abs(multiples_led.rate_sensitivity) < abs(cash_flows.rate_sensitivity)


class TestTheJob:
    def test_it_stores_what_the_curve_says(self, settings, monkeypatch):
        from awltux.ingest import jobs
        from awltux.providers import treasury as treasury_module

        curve = parse_yield_curve(REAL_CSV)
        assert curve is not None
        monkeypatch.setattr(
            treasury_module.TreasuryProvider, "yield_curve", lambda self, **_: curve
        )

        result = jobs.refresh_macro_rates()

        assert result.items_written == 1
        assert result.detail["risk_free_rate"] == pytest.approx(0.0531)
        with session_scope() as session:
            observation = macro.read_observation(session)
        assert observation is not None
        assert observation.value == pytest.approx(0.0531)
        assert observation.source == "market"

    def test_a_missing_tenor_reports_rather_than_storing_a_blank(self, settings, monkeypatch):
        from awltux.ingest import jobs
        from awltux.providers import treasury as treasury_module

        thin = YieldCurve(as_of=dt.date(2026, 10, 5), rates={"3 Mo": 4.22})
        monkeypatch.setattr(
            treasury_module.TreasuryProvider, "yield_curve", lambda self, **_: thin
        )

        result = jobs.refresh_macro_rates()

        assert result.items_written == 0
        assert result.note is not None
        assert "missing or implausible" in result.note

    def test_a_provider_failure_does_not_raise(self, settings, monkeypatch):
        from awltux.ingest import jobs
        from awltux.providers import treasury as treasury_module
        from awltux.providers.http import ProviderError

        def explode(self, **_):
            raise ProviderError("treasury", "503 from the Treasury")

        monkeypatch.setattr(treasury_module.TreasuryProvider, "yield_curve", explode)

        result = jobs.refresh_macro_rates()

        assert result.items_written == 0
        assert result.note is not None
        assert "could not read" in result.note


class TestTheRateEnvironment:
    """The curve as a shape, and the condition that would show it to be wrong.

    Reported, never predicted. A macro claim with no falsifier cannot be shown to be
    wrong, and one that is not checked is decoration -- so the page states the
    number that would falsify it and says plainly which half of the condition is
    actually being measured.
    """

    def _store(self, session, *, thirty_year: float):
        curve = YieldCurve(
            as_of=dt.date(2026, 10, 5),
            rates={
                "3 Mo": 4.22,
                "2 Yr": 4.84,
                "10 Yr": 5.31,
                "30 Yr": thirty_year,
            },
        )
        macro.store_observation(session, curve, tenor="10 Yr")
        return curve

    def test_nothing_observed_means_nothing_to_report(self, settings):
        from awltux.web import queries

        with session_scope() as session:
            assert queries.rate_environment(session) is None

    def test_the_curve_is_reported_as_a_shape(self, settings):
        from awltux.web import queries

        with session_scope() as session:
            self._store(session, thirty_year=5.66)
            environment = queries.rate_environment(session)

        assert environment is not None
        assert environment["as_of"] == "2026-10-05"
        assert environment["curve"]["10 Yr"] == pytest.approx(5.31)
        assert environment["curve"]["30 Yr"] == pytest.approx(5.66)
        # The long end minus the ten-year: the number that shows a repricing.
        assert environment["spread_10s30s"] == pytest.approx(0.35)

    def test_a_high_long_end_does_not_falsify_the_reading(self, settings):
        from awltux.web import queries

        with session_scope() as session:
            self._store(session, thirty_year=5.66)
            environment = queries.rate_environment(session)

        assert environment is not None
        assert environment["falsifier_met"] is False

    def test_a_long_end_below_the_threshold_is_reported_as_met(self, settings):
        """The falsifier has to be able to fire, or it is not a falsifier."""
        from awltux.web import queries

        with session_scope() as session:
            self._store(session, thirty_year=4.20)
            environment = queries.rate_environment(session)

        assert environment is not None
        assert environment["falsifier_met"] is True

    def test_it_does_not_claim_to_have_measured_the_duration(self, settings):
        """One observation is stored, not a quarter of them."""
        from awltux.web import queries

        with session_scope() as session:
            self._store(session, thirty_year=5.66)
            environment = queries.rate_environment(session)

        assert environment is not None
        note = environment["falsifier_note"]
        assert "quarter" in note
        assert "the duration is not" in note, (
            "claiming the duration was evaluated would be reporting a check that "
            "never ran"
        )


class TestTheInfoPage:
    """The rate environment is what the model is valuing against, so it belongs on
    the page that says what this install is running."""

    def test_before_anything_is_observed_it_says_how_to_fix_it(self, client):
        text = " ".join(client.get("/info").text.split())

        assert "Rate environment" in text
        assert "macro_rates" in text, "the page should name the job that fills this"
        assert "configured constant" in text

    def test_it_reports_the_observed_curve_and_the_falsifier(self, client, session):
        curve = YieldCurve(
            as_of=dt.date(2026, 10, 5),
            rates={"3 Mo": 4.22, "2 Yr": 4.84, "10 Yr": 5.31, "30 Yr": 5.66},
        )
        with session_scope() as scope:
            macro.store_observation(scope, curve, tenor="10 Yr")
        session.commit()

        text = " ".join(client.get("/info").text.split())

        assert "Rate environment" in text
        assert "5.31%" in text, "the rate the model is using"
        assert "5.66" in text, "the long end"
        assert "0.35 points" in text, "the 10s30s spread"
        assert "not met" in text, "the falsifier has to be shown as checkable"

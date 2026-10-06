"""The risk-free rate: where it comes from, and why it is per currency.

The rate anchors the CAPM cost of equity, which anchors every discount rate, which
decides every discounted fair value in the database. It used to be a single typed-in
constant, which is honest on the day it is typed and silently wrong afterwards: on
2026-10-05 the ten-year Treasury yielded 5.31% against a configured 4.2%, and this
model's own DCF gives up about 14% of its fair value across that gap.

It is now read per currency from each sovereign's own published curve, because a
discount rate has to be denominated in the currency of the cash flows it discounts.
Roughly a quarter of this universe is sterling, and one country's curve cannot serve
both without embedding a cross-currency view the model does not hold.

Both curve fixtures below are captured verbatim from the live endpoints, so the
parsers are tested against the shapes they actually receive.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis import macro
from awltux.analysis.valuation import PeerMultiples, cost_of_equity, value_instrument
from awltux.db import AppSetting, session_scope
from awltux.providers.gilt import parse_gilt_curve
from awltux.providers.treasury import parse_yield_curve
from awltux.providers.yields import YieldCurve
from tests.helpers import make_period

#: Captured from the US Treasury's own CSV endpoint.
US_CSV = (
    'Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr",'
    '"5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "10/05/2026,4.05,4.10,4.13,4.22,4.27,4.30,4.47,4.84,4.97,5.06,5.19,5.31,5.70,5.66\n"
    "10/02/2026,4.04,4.09,4.11,4.19,4.26,4.27,4.46,4.83,4.96,5.06,5.17,5.28,5.67,5.63\n"
)

#: Captured from the Bank of England's IADB endpoint. Note the pillar set: the BoE
#: publishes 5/10/20 years, not the Treasury's fourteen, and has no 30-year at all.
UK_CSV = (
    "DATE,IUDSNPY,IUDMNPY,IUDLNPY\n"
    "01 Oct 2026,4.9132,5.3665,5.752\n"
    "02 Oct 2026,4.8917,5.3341,5.6879\n"
)


def _us_curve() -> YieldCurve:
    curve = parse_yield_curve(US_CSV)
    assert curve is not None
    return curve


def _uk_curve() -> YieldCurve:
    curve = parse_gilt_curve(UK_CSV)
    assert curve is not None
    return curve


class TestParsingTheTreasuryCurve:
    def test_the_newest_row_wins(self):
        assert _us_curve().as_of == dt.date(2026, 10, 5)

    def test_yields_are_read_as_percentages(self):
        curve = _us_curve()
        assert curve.percent("10 Yr") == pytest.approx(5.31)
        # The distinction the whole module is built around.
        assert curve.fraction("10 Yr") == pytest.approx(0.0531)

    def test_every_tenor_is_kept(self):
        assert len(_us_curve().rates) == 14

    def test_a_file_with_no_rows_is_none_not_an_exception(self):
        """Normal on 1-2 January, before the year's first publication."""
        assert parse_yield_curve('Date,"10 Yr"\n') is None
        assert parse_yield_curve("") is None


class TestParsingTheGiltCurve:
    def test_the_newest_row_wins(self):
        """Rows arrive oldest-first, so the last usable one is the newest."""
        assert _uk_curve().as_of == dt.date(2026, 10, 2)

    def test_the_three_pillars_are_named_the_way_the_rest_of_the_code_names_them(self):
        """Normalised to ``N Yr`` so one configured tenor selects the same point on
        either curve, rather than needing a per-provider spelling."""
        curve = _uk_curve()
        assert curve.percent("5 Yr") == pytest.approx(4.8917)
        assert curve.percent("10 Yr") == pytest.approx(5.3341)
        assert curve.percent("20 Yr") == pytest.approx(5.6879)
        assert curve.fraction("10 Yr") == pytest.approx(0.053341)

    def test_it_has_no_thirty_year_pillar(self):
        """The reason the falsifier cannot be generalised to the gilt curve."""
        assert _uk_curve().percent("30 Yr") is None

    def test_an_html_error_page_is_no_curve_rather_than_a_crash(self):
        """A rejected series code is answered with HTML and HTTP 200, not an error."""
        assert parse_gilt_curve("<html><body>Invalid series</body></html>") is None

    def test_columns_are_matched_by_series_code_not_by_position(self):
        """A reordered response must not pair a rate with the wrong tenor.

        The header carries the codes, so the mapping is read from it; positional
        parsing would silently relabel the five-year as the ten-year.
        """
        reordered = (
            "DATE,IUDLNPY,IUDMNPY,IUDSNPY\n"
            "02 Oct 2026,5.6879,5.3341,4.8917\n"
        )
        curve = parse_gilt_curve(reordered)
        assert curve is not None
        assert curve.percent("20 Yr") == pytest.approx(5.6879)
        assert curve.percent("10 Yr") == pytest.approx(5.3341)
        assert curve.percent("5 Yr") == pytest.approx(4.8917)


class TestWhichCurveApplies:
    """The mapping from a valuation currency to a sovereign's curve."""

    def test_dollars_use_the_treasury(self):
        assert macro.curve_for("USD") == "treasury"

    def test_sterling_uses_the_gilt_curve(self):
        assert macro.curve_for("GBP") == "gilt"

    def test_pence_is_not_a_separate_currency(self):
        """LSE shares are *quoted* in pence, but prices are normalised to pounds
        before storage, so the units cancel and the sterling rate applies."""
        assert macro.curve_for("GBX") == "gilt"
        assert macro.normalise_currency("GBX") == "GBP"

    def test_a_currency_with_no_curve_is_reported_as_having_none(self):
        assert macro.curve_for("EUR") is None
        assert macro.curve_for(None) is None, (
            "an unknown currency is not dollars; defaulting to USD here is the same "
            "silent substitution, one level further down"
        )

    def test_an_instrument_with_no_currency_falls_back_rather_than_to_dollars(self, settings):
        with session_scope() as session:
            macro.store_observation(session, _us_curve(), currency="USD", tenor="10 Yr")
            resolved = macro.resolve_risk_free_rate(session, settings, None)

        assert resolved.source == "config"
        assert "no recorded currency" in resolved.note


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
        [5.31, 0.000531, 0.0, -0.01, None, 1.0],  # percentage-as-fraction; /100 twice
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
            assert macro.store_observation(session, wrong, currency="USD", tenor="10 Yr") is None
            assert macro.read_observation(session, "USD") is None


class TestResolvingTheRate:
    def test_the_market_wins_when_an_observation_exists(self, settings):
        with session_scope() as session:
            macro.store_observation(session, _us_curve(), currency="USD", tenor="10 Yr")
            resolved = macro.resolve_risk_free_rate(session, settings, "USD")

        assert resolved.source == "market"
        assert resolved.value == pytest.approx(0.0531)
        assert resolved.currency == "USD"
        assert resolved.as_of == "2026-10-05"
        assert "USD" in resolved.note

    def test_each_currency_gets_its_own_curve(self, settings):
        """The point of the whole change: two currencies, two rates."""
        with session_scope() as session:
            macro.store_observation(session, _us_curve(), currency="USD", tenor="10 Yr")
            macro.store_observation(session, _uk_curve(), currency="GBP", tenor="10 Yr")
            usd = macro.resolve_risk_free_rate(session, settings, "USD")
            gbp = macro.resolve_risk_free_rate(session, settings, "GBP")

        assert usd.value == pytest.approx(0.0531)
        assert gbp.value == pytest.approx(0.053341)
        assert usd.value != gbp.value

    def test_pence_resolves_to_the_sterling_rate(self, settings):
        with session_scope() as session:
            macro.store_observation(session, _uk_curve(), currency="GBP", tenor="10 Yr")
            resolved = macro.resolve_risk_free_rate(session, settings, "GBX")

        assert resolved.source == "market"
        assert resolved.value == pytest.approx(0.053341)

    def test_the_configured_rate_carries_the_day_before_anything_is_observed(self, settings):
        with session_scope() as session:
            resolved = macro.resolve_risk_free_rate(session, settings, "USD")

        assert resolved.source == "config"
        assert resolved.value == pytest.approx(settings.valuation.risk_free_rate)
        assert "macro_rates" in resolved.note

    def test_config_source_pins_the_constant_even_when_a_rate_was_observed(self, settings):
        settings.yaml.valuation.risk_free_rate_source = "config"
        with session_scope() as session:
            macro.store_observation(session, _uk_curve(), currency="GBP", tenor="10 Yr")
            resolved = macro.resolve_risk_free_rate(session, settings, "GBP")

        assert resolved.source == "config"
        assert resolved.value == pytest.approx(0.042)

    def test_a_currency_with_no_curve_falls_back_and_names_itself(self, settings):
        """The failure this design exists to prevent.

        Substituting the dollar rate for a currency nobody has wired up would
        recreate exactly the bug the per-currency split was written to fix, so an
        unmapped currency takes the configured constant and the reason says which
        currency it was.
        """
        with session_scope() as session:
            macro.store_observation(session, _us_curve(), currency="USD", tenor="10 Yr")
            resolved = macro.resolve_risk_free_rate(session, settings, "EUR")

        assert resolved.source == "config"
        assert resolved.currency == "EUR"
        assert "EUR" in resolved.note
        assert "no sovereign yield curve" in resolved.note
        # And emphatically not the dollar rate.
        assert resolved.value == pytest.approx(0.042)

    def test_one_currency_being_stored_does_not_disturb_another(self, settings):
        with session_scope() as session:
            macro.store_observation(session, _uk_curve(), currency="GBP", tenor="10 Yr")
            macro.store_observation(session, _us_curve(), currency="USD", tenor="10 Yr")
            macro.store_observation(session, _uk_curve(), currency="GBP", tenor="5 Yr")

            usd = macro.read_observation(session, "USD")
            gbp = macro.read_observation(session, "GBP")

        assert usd is not None and usd.value == pytest.approx(0.0531)
        assert gbp is not None and gbp.value == pytest.approx(0.048917)  # re-stored at 5 Yr

    def test_a_corrupt_stored_value_falls_back_rather_than_being_used(self, settings):
        with session_scope() as session:
            session.add(AppSetting(key=macro.SETTING_KEY, value={"USD": {"value": 5.31}}))
            session.flush()
            assert macro.read_observation(session, "USD") is None
            resolved = macro.resolve_risk_free_rate(session, settings, "USD")

        assert resolved.source == "config"

    def test_a_row_written_before_this_was_currency_aware_is_ignored(self, settings):
        """The old flat shape must not be read as a currency's observation.

        This is a cache of a published number that the next job run republishes, so
        the safe response to a shape that no longer exists is to ignore it rather
        than to guess which currency it was for.
        """
        with session_scope() as session:
            session.add(
                AppSetting(
                    key=macro.SETTING_KEY,
                    value={"value": 0.0531, "source": "market", "as_of": "2026-10-05"},
                )
            )
            session.flush()
            assert macro.read_observation(session, "USD") is None


class TestTheModelUsesIt:
    def test_cost_of_equity_honours_the_override(self, settings):
        configured = cost_of_equity(1.0, settings)
        observed = cost_of_equity(1.0, settings, risk_free_rate=0.0531)

        assert configured == pytest.approx(0.042 + 0.055)
        assert observed == pytest.approx(0.0531 + 0.055)
        assert observed > configured

    def _value(self, settings, metrics, rate, currency="USD"):
        period = make_period("TEST_US_EQ", dt.date(2025, 12, 31), metrics)
        return value_instrument(
            price=10.0,
            currency=currency,
            periods=[period],
            closes=[10.0, 11.0],
            volumes=[1.0, 1.0],
            market_cap=1_000_000.0,
            beta=1.0,
            peers=PeerMultiples(),
            settings=settings,
            risk_free_rate=rate,
            risk_free_rate_source="market",
            risk_free_rate_note="test",
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

    def test_a_higher_rate_produces_a_lower_value(self, settings):
        at_config = self._value(settings, self.CASH_GENERATOR, 0.042)
        at_market = self._value(settings, self.CASH_GENERATOR, 0.0531)

        assert at_config.fair_value_base is not None
        assert at_market.fair_value_base is not None
        assert at_market.fair_value_base < at_config.fair_value_base
        drop = 1 - at_market.fair_value_base / at_config.fair_value_base
        # Measured, not guessed: the ~14% the module docstring quotes is for the DCF
        # alone, so the blend moves less than that.
        assert 0.05 < drop < 0.20, f"expected a measurable drop, got {drop:.1%}"

    def test_the_rate_its_currency_and_its_provenance_are_recorded(self, settings):
        result = self._value(settings, self.CASH_GENERATOR, 0.053341, currency="GBP")

        assumptions = result.inputs["assumptions"]
        assert assumptions["risk_free_rate"] == pytest.approx(0.053341)
        assert assumptions["risk_free_rate_source"] == "market"
        assert assumptions["risk_free_rate_fallback"] == pytest.approx(0.042)
        assert result.inputs["currency"] == "GBP"


class TestRateSensitivity:
    """How much of a fair value is a bet on the discount rate.

    A sensitivity, not a forecast. It answers the question the fair value cannot:
    whether this number rests on the company's cash flows or on the rate used to
    discount them -- the only input taken from the market rather than the filings.
    """

    CASH_GENERATOR = TestTheModelUsesIt.CASH_GENERATOR

    def _value(self, settings, metrics, rate=0.0531, peers=None):
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
            risk_free_rate=rate,
        )

    def test_a_rise_in_the_rate_lowers_the_value(self, settings):
        result = self._value(settings, self.CASH_GENERATOR)
        assert result.rate_sensitivity is not None
        assert result.rate_sensitivity < 0

    def test_the_shock_and_the_change_are_recorded_on_the_run(self, settings):
        result = self._value(settings, self.CASH_GENERATOR)
        recorded = result.inputs["rate_sensitivity"]

        assert recorded["shock"] == pytest.approx(0.01)
        assert recorded["fair_value_change_pct"] == pytest.approx(result.rate_sensitivity)
        assert "discount rate" in recorded["note"]
        assert result.as_dict()["rate_sensitivity"] == result.rate_sensitivity

    def test_it_is_a_real_remeasurement_not_a_relabelled_constant(self, settings):
        """The response is not linear in the discount rate, so the sensitivity must
        differ when the starting rate does."""
        assert (
            self._value(settings, self.CASH_GENERATOR, 0.0531).rate_sensitivity
            != self._value(settings, self.CASH_GENERATOR, 0.0731).rate_sensitivity
        )

    def test_a_peer_anchored_valuation_is_less_rate_sensitive(self, settings):
        """Multiples and Graham ignore the rate, so a company valued on peers must
        move less than one valued on its own discounted cash flows."""
        peers = PeerMultiples(
            sector="Industrials", sample_size=8, ev_ebitda=12.0, pe=18.0, pb=2.5
        )
        cash_flows = self._value(settings, self.CASH_GENERATOR)
        thin = dict(self.CASH_GENERATOR, free_cash_flow=0.0, operating_cash_flow=1_000.0)
        multiples_led = self._value(settings, thin, peers=peers)

        assert cash_flows.rate_sensitivity is not None
        assert multiples_led.rate_sensitivity is not None
        assert abs(multiples_led.rate_sensitivity) < abs(cash_flows.rate_sensitivity)


class TestTheJob:
    def _patch(self, monkeypatch, *, us=None, uk=None, us_error=None):
        """Replace both curve providers. **Both**, because the job now touches two
        and a test that patched one would reach the live Bank of England."""
        from awltux.providers import gilt as gilt_module
        from awltux.providers import treasury as treasury_module
        from awltux.providers.http import ProviderError

        def treasury_curve(self, **_):
            if us_error:
                raise ProviderError("treasury", us_error)
            return us if us is not None else _us_curve()

        def gilt_curve(self, **_):
            return uk if uk is not None else _uk_curve()

        monkeypatch.setattr(treasury_module.TreasuryProvider, "yield_curve", treasury_curve)
        monkeypatch.setattr(gilt_module.GiltProvider, "yield_curve", gilt_curve)

    def test_it_stores_a_rate_for_every_currency_with_a_curve(self, settings, monkeypatch):
        from awltux.ingest import jobs

        self._patch(monkeypatch)
        result = jobs.refresh_macro_rates()

        assert result.items_written == 2
        assert set(result.detail["currencies"]) == {"USD", "GBP"}

        with session_scope() as session:
            usd = macro.read_observation(session, "USD")
            gbp = macro.read_observation(session, "GBP")
        assert usd is not None and usd.value == pytest.approx(0.0531)
        assert gbp is not None and gbp.value == pytest.approx(0.053341)

    def test_one_provider_failing_does_not_stop_the_other(self, settings, monkeypatch):
        """A gilt fetch failing must not cost the dollar rate, or the sweep would
        fall back to the configured constant for currencies that were fine."""
        from awltux.ingest import jobs

        self._patch(monkeypatch, us_error="503 from the Treasury")
        result = jobs.refresh_macro_rates()

        assert result.items_written == 1
        assert result.detail["errors"]
        with session_scope() as session:
            assert macro.read_observation(session, "USD") is None
            assert macro.read_observation(session, "GBP") is not None

    def test_a_missing_tenor_reports_rather_than_storing_a_blank(self, settings, monkeypatch):
        from awltux.ingest import jobs

        thin = YieldCurve(as_of=dt.date(2026, 10, 5), rates={"3 Mo": 4.22})
        self._patch(monkeypatch, us=thin)
        result = jobs.refresh_macro_rates()

        # The gilt curve stored; the Treasury one had no ten-year pillar.
        assert result.items_written == 1
        assert any("USD" in error for error in result.detail["errors"])
        with session_scope() as session:
            assert macro.read_observation(session, "USD") is None

    def test_a_provider_failure_does_not_raise(self, settings, monkeypatch):
        from awltux.ingest import jobs

        self._patch(monkeypatch, us_error="503", uk=YieldCurve(as_of=dt.date(2026, 10, 2), rates={}))
        result = jobs.refresh_macro_rates()

        assert result.items_written == 0
        assert result.note is not None
        assert "no risk-free rate was stored" in result.note


class TestTheRateEnvironment:
    """The curves as shapes, and the condition that would show the reading wrong.

    Reported, never predicted. A macro claim with no falsifier cannot be shown to be
    wrong, and one that is not checked is decoration -- so the page states the number
    that would falsify it and says plainly which half of the condition is measured.
    """

    def _store(self, session, *, us_thirty: float = 5.66):
        macro.store_observation(
            session,
            YieldCurve(
                as_of=dt.date(2026, 10, 5),
                rates={"3 Mo": 4.22, "2 Yr": 4.84, "10 Yr": 5.31, "30 Yr": us_thirty},
            ),
            currency="USD",
            tenor="10 Yr",
        )
        macro.store_observation(session, _uk_curve(), currency="GBP", tenor="10 Yr")

    def test_nothing_observed_means_nothing_to_report(self, settings):
        from awltux.web import queries

        with session_scope() as session:
            assert queries.rate_environment(session) is None

    def test_both_currencies_are_reported(self, settings):
        from awltux.web import queries

        with session_scope() as session:
            self._store(session)
            environment = queries.rate_environment(session)

        assert environment is not None
        codes = [summary["currency"] for summary in environment["currencies"]]
        assert codes == ["GBP", "USD"]

    def test_each_curve_is_reported_as_a_shape(self, settings):
        from awltux.web import queries

        with session_scope() as session:
            self._store(session)
            environment = queries.rate_environment(session)

        assert environment is not None
        by_currency = {s["currency"]: s for s in environment["currencies"]}

        assert by_currency["USD"]["curve"]["10 Yr"] == pytest.approx(5.31)
        assert by_currency["USD"]["long_tenor"] == "30 Yr"
        assert by_currency["USD"]["spread"] == pytest.approx(0.35)

        # The gilt curve's longest pillar is 20 years, not 30, and the label has to
        # travel with the number rather than be hardcoded to "10s30s".
        assert by_currency["GBP"]["long_tenor"] == "20 Yr"
        assert by_currency["GBP"]["spread"] == pytest.approx(5.6879 - 5.3341)

    def test_a_high_long_end_does_not_falsify_the_reading(self, settings):
        from awltux.web import queries

        with session_scope() as session:
            self._store(session, us_thirty=5.66)
            environment = queries.rate_environment(session)

        assert environment is not None
        assert environment["falsifier_met"] is False

    def test_a_long_end_below_the_threshold_is_reported_as_met(self, settings):
        """The falsifier has to be able to fire, or it is not a falsifier."""
        from awltux.web import queries

        with session_scope() as session:
            self._store(session, us_thirty=4.20)
            environment = queries.rate_environment(session)

        assert environment is not None
        assert environment["falsifier_met"] is True

    def test_it_does_not_claim_to_have_measured_the_duration(self, settings):
        """One observation is stored, not a quarter of them."""
        from awltux.web import queries

        with session_scope() as session:
            self._store(session)
            environment = queries.rate_environment(session)

        assert environment is not None
        assert "quarter" in environment["falsifier_note"]
        assert "the duration is not" in environment["falsifier_note"]


class TestTheInfoPage:
    """The rate environment is what the model is valuing against, so it belongs on
    the page that says what this install is running."""

    def test_before_anything_is_observed_it_says_how_to_fix_it(self, client):
        text = " ".join(client.get("/info").text.split())

        assert "Rate environment" in text
        assert "macro_rates" in text, "the page should name the job that fills this"
        assert "configured constant" in text

    def test_it_reports_every_currency_and_the_falsifier(self, client, session):
        with session_scope() as scope:
            macro.store_observation(
                scope,
                YieldCurve(
                    as_of=dt.date(2026, 10, 5),
                    rates={"3 Mo": 4.22, "2 Yr": 4.84, "10 Yr": 5.31, "30 Yr": 5.66},
                ),
                currency="USD",
                tenor="10 Yr",
            )
            macro.store_observation(scope, _uk_curve(), currency="GBP", tenor="10 Yr")
        session.commit()

        text = " ".join(client.get("/info").text.split())

        assert "Rate environment" in text
        assert "5.31%" in text, "the rate the model uses for dollars"
        assert "5.33%" in text, "and the one it uses for sterling"
        assert "GBP curve" in text and "USD curve" in text
        assert "not met" in text, "the falsifier has to be shown as checkable"

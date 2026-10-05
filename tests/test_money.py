"""Currency normalisation.

This is the highest-value test in the suite. LSE-listed shares are quoted in
pence by most market data providers while Trading 212 reports pounds, so a missed
conversion produces a number that is 100x wrong but still entirely plausible --
it survives review. These tests pin the behaviour down.
"""

from __future__ import annotations

import pytest

from awltux.money import (
    canonical_currency,
    convert,
    expected_quote_currency,
    is_lse_symbol,
    multiplier_for,
    normalise,
    normalise_money,
    to_major_currency,
)


class TestNormalise:
    def test_pence_convert_to_pounds(self):
        # The headline case: Yahoo reports VOD.L at 1,250 pence.
        assert normalise(1250.0, "GBp") == pytest.approx(12.50)
        assert normalise(1250.0, "GBX") == pytest.approx(12.50)
        assert normalise(1250.0, "GBx") == pytest.approx(12.50)

    def test_pounds_pass_through(self):
        assert normalise(12.50, "GBP") == pytest.approx(12.50)

    def test_dollars_pass_through(self):
        assert normalise(187.42, "USD") == pytest.approx(187.42)

    def test_none_stays_none(self):
        assert normalise(None, "GBp") is None
        assert normalise(None, None) is None

    def test_unknown_currency_passes_through_unchanged(self):
        # Inventing a conversion would be worse than admitting ignorance.
        assert normalise(100.0, "XYZ") == pytest.approx(100.0)

    def test_empty_currency_is_a_no_op(self):
        assert normalise(100.0, "") == pytest.approx(100.0)

    @pytest.mark.parametrize(
        ("currency", "expected"),
        [("GBp", 0.01), ("GBX", 0.01), ("GBP", 1.0), ("USD", 1.0), ("ZAc", 0.01)],
    )
    def test_multiplier_table(self, currency: str, expected: float):
        assert multiplier_for(currency) == pytest.approx(expected)


class TestNormaliseMoney:
    def test_records_the_multiplier_for_the_audit_trail(self):
        result = normalise_money(1250.0, "GBp")
        assert result is not None
        assert result.value == pytest.approx(12.50)
        assert result.currency == "GBP"
        assert result.multiplier == pytest.approx(0.01)
        assert result.raw_currency == "GBp"
        assert result.was_minor_unit is True

    def test_major_unit_is_not_flagged_as_minor(self):
        result = normalise_money(12.5, "GBP")
        assert result is not None
        assert result.was_minor_unit is False
        assert result.multiplier == pytest.approx(1.0)

    def test_value_can_be_undone_from_the_recorded_factors(self):
        """The original figure must be reconstructable from the stored row."""
        raw = 348.75
        result = normalise_money(raw, "GBp")
        assert result is not None
        assert result.value / result.multiplier == pytest.approx(raw)


class TestCanonicalCurrency:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("gbp", "GBP"),
            ("GBP", "GBP"),
            # Case carries the unit: GBp is pence, GBP is pounds.
            ("GBp", "GBX"),
            ("gbx", "GBX"),
            ("GBX", "GBX"),
            ("usd", "USD"),
            ("", ""),
        ],
    )
    def test_case_and_alias_handling(self, raw: str, expected: str):
        assert canonical_currency(raw) == expected

    def test_pence_and_pounds_never_collapse_to_the_same_key(self):
        """The whole point of the module: these must stay distinguishable."""
        assert canonical_currency("GBp") != canonical_currency("GBP")
        assert multiplier_for("GBp") != multiplier_for("GBP")

    def test_none_is_empty(self):
        assert canonical_currency(None) == ""


class TestToMajorCurrency:
    def test_t212_metadata_is_already_major(self):
        # Trading 212 states GBP, not GBp, so no scaling should be applied.
        value, currency = to_major_currency(12.50, "GBP")
        assert value == pytest.approx(12.50)
        assert currency == "GBP"

    def test_defaults_to_gbp_when_unstated(self):
        value, currency = to_major_currency(10.0, None)
        assert currency == "GBP"


class TestSymbols:
    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [("VOD.L", True), ("vod.l", True), ("AAPL", False), (None, False)],
    )
    def test_is_lse_symbol(self, symbol: str | None, expected: bool):
        assert is_lse_symbol(symbol) is expected

    def test_expected_currency_for_lse_is_pence(self):
        assert expected_quote_currency("VOD.L") == "GBX"
        assert expected_quote_currency("AAPL") is None


class TestConvert:
    def test_converts_with_an_explicit_rate(self):
        assert convert(100.0, 0.79) == pytest.approx(79.0)

    def test_rejects_a_non_positive_rate(self):
        # A zero or negative rate silently zeroes a whole valuation.
        with pytest.raises(ValueError):
            convert(100.0, 0.0)
        with pytest.raises(ValueError):
            convert(100.0, -1.0)

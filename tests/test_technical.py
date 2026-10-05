"""Technical indicators.

The point of these tests is that an indicator with insufficient history must
return ``None`` rather than a number computed from too little data. A 200-day
average of 30 observations is worse than no average, because it looks like an
answer and will be used as one.
"""

from __future__ import annotations

import pytest

from awltux.analysis.technical import (
    analyse,
    classify_trend,
    ema,
    max_drawdown,
    pct_change,
    position_in_range,
    relative_strength,
    rsi,
    sma,
    volatility,
)


class TestPrimitives:
    def test_sma_of_exact_window(self):
        assert sma([1, 2, 3, 4, 5], 5) == pytest.approx(3.0)
        assert sma([1, 2, 3, 4, 5], 2) == pytest.approx(4.5)

    def test_sma_needs_the_full_window(self):
        assert sma([1, 2, 3], 5) is None

    def test_ema_reacts_faster_than_an_sma(self):
        """The defining property: a recent jump moves the EMA more than the SMA."""
        flat_then_jump = [100.0] * 30 + [200.0] * 5
        assert ema(flat_then_jump, 10) > sma(flat_then_jump, 10)

    def test_ema_lags_a_rising_series_less_than_a_long_sma(self):
        values = [float(n) for n in range(1, 61)]
        short = ema(values, 5)
        long = sma(values, 40)
        assert short is not None and long is not None
        assert short > long

    def test_ema_needs_the_full_window(self):
        assert ema([1.0, 2.0], 5) is None

    def test_rsi_of_a_monotonic_rise_is_100(self):
        values = [float(n) for n in range(1, 40)]
        assert rsi(values, 14) == pytest.approx(100.0)

    def test_rsi_of_a_monotonic_fall_is_zero(self):
        values = [float(n) for n in range(40, 1, -1)]
        assert rsi(values, 14) == pytest.approx(0.0)

    def test_rsi_of_a_flat_series_is_neutral(self):
        assert rsi([100.0] * 40, 14) == pytest.approx(50.0)

    def test_rsi_needs_enough_history(self):
        assert rsi([1.0, 2.0, 3.0], 14) is None

    def test_pct_change(self):
        assert pct_change([100.0, 110.0], 1) == pytest.approx(0.10)
        assert pct_change([100.0], 1) is None

    def test_pct_change_of_zero_base_is_none(self):
        # Dividing by a zero previous price is meaningless, not zero.
        assert pct_change([0.0, 10.0], 1) is None


class TestRisk:
    def test_max_drawdown(self):
        # 100 -> 130 -> 65 is a 50% drawdown from the peak.
        assert max_drawdown([100.0, 130.0, 65.0, 80.0]) == pytest.approx(0.5)

    def test_max_drawdown_of_a_monotonic_rise_is_zero(self):
        assert max_drawdown([1.0, 2.0, 3.0]) == pytest.approx(0.0)

    def test_volatility_of_a_flat_series_is_zero(self):
        assert volatility([100.0] * 40) == pytest.approx(0.0)

    def test_volatility_needs_enough_returns(self):
        assert volatility([1.0, 2.0, 3.0]) is None

    def test_position_in_range(self):
        assert position_in_range([10.0, 20.0, 15.0]) == pytest.approx(0.5)
        assert position_in_range([10.0, 20.0, 20.0]) == pytest.approx(1.0)
        assert position_in_range([10.0, 20.0, 10.0]) == pytest.approx(0.0)

    def test_position_in_range_handles_a_flat_series(self):
        # A zero-width range has no position; 0.5 is the neutral answer.
        assert position_in_range([10.0, 10.0, 10.0]) == pytest.approx(0.5)


class TestSnapshot:
    def test_empty_input_reports_no_history(self):
        snapshot = analyse([])
        assert snapshot.bars == 0
        assert snapshot.last_close is None
        assert "no price history" in snapshot.notes
        assert snapshot.trend == "unknown"

    def test_short_history_flags_the_missing_200_day_average(self):
        snapshot = analyse([100.0 + n for n in range(50)])
        assert snapshot.sma_200 is None
        assert snapshot.sma_50 is not None
        assert any("200-day" in note for note in snapshot.notes)

    def test_full_history_populates_every_indicator(self):
        closes = [100.0 * (1.0008 ** n) for n in range(260)]
        snapshot = analyse(closes, [1_000_000.0] * 260)
        assert snapshot.sma_200 is not None
        assert snapshot.rsi_14 is not None
        assert snapshot.return_1y is not None
        assert snapshot.volatility_annual is not None
        assert snapshot.high_52w is not None
        assert snapshot.avg_volume_30d == pytest.approx(1_000_000.0)

    def test_volume_trend_detects_a_surge(self):
        volumes = [1000.0] * 230 + [5000.0] * 30
        snapshot = analyse([100.0] * 260, volumes)
        assert snapshot.volume_trend is not None
        assert snapshot.volume_trend > 1.0


class TestTrendClassification:
    def test_uptrend_when_above_both_averages(self):
        snapshot = analyse([100.0 * (1.001 ** n) for n in range(260)])
        assert snapshot.trend == "uptrend"

    def test_downtrend_when_below_both_averages(self):
        snapshot = analyse([100.0 * (0.999 ** n) for n in range(260)])
        assert snapshot.trend == "downtrend"

    def test_unknown_without_averages(self):
        assert classify_trend(analyse([100.0])) == "unknown"


class TestRelativeStrength:
    def test_outperformance_is_positive(self):
        instrument = [100.0 * (1.002 ** n) for n in range(130)]
        benchmark = [100.0 * (1.001 ** n) for n in range(130)]
        value = relative_strength(instrument, benchmark, periods=126)
        assert value is not None and value > 0

    def test_underperformance_is_negative(self):
        instrument = [100.0 * (1.0005 ** n) for n in range(130)]
        benchmark = [100.0 * (1.002 ** n) for n in range(130)]
        value = relative_strength(instrument, benchmark, periods=126)
        assert value is not None and value < 0

    def test_uses_the_shorter_series_when_lengths_differ(self):
        """Comparing different time spans would silently misstate performance."""
        value = relative_strength([100.0] * 10, [100.0] * 200, periods=126)
        assert value is None

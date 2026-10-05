"""Technical indicators, computed from stored bars.

Pure functions over plain lists so they can be tested against hand-computed
fixtures without a database, pandas, or the network. Numeric care is deliberate:

* Indicators return ``None`` rather than a partial value when there is not enough
  history. A 200-day moving average computed from 30 days is worse than no answer
  because it looks like an answer.
* Percentages are returned as **fractions** (0.05 = 5%), matching the valuation
  model. Formatting decides how to display them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: A year of trading days, used to annualise volatility.
TRADING_DAYS = 252


@dataclass(slots=True)
class TechnicalSnapshot:
    """Trend and volatility read for one instrument, as of the latest bar."""

    bars: int = 0
    last_close: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    rsi_14: float | None = None
    return_1d: float | None = None
    return_1w: float | None = None
    return_1m: float | None = None
    return_3m: float | None = None
    return_6m: float | None = None
    return_1y: float | None = None
    volatility_annual: float | None = None
    max_drawdown_1y: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    position_in_52w_range: float | None = None
    avg_volume_30d: float | None = None
    volume_trend: float | None = None
    trend: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bars": self.bars,
            "last_close": self.last_close,
            "sma_20": self.sma_20,
            "sma_50": self.sma_50,
            "sma_200": self.sma_200,
            "rsi_14": self.rsi_14,
            "return_1m": self.return_1m,
            "return_3m": self.return_3m,
            "return_6m": self.return_6m,
            "return_1y": self.return_1y,
            "volatility_annual": self.volatility_annual,
            "max_drawdown_1y": self.max_drawdown_1y,
            "position_in_52w_range": self.position_in_52w_range,
            "volume_trend": self.volume_trend,
            "trend": self.trend,
        }


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #


def sma(values: list[float], period: int) -> float | None:
    """Simple moving average of the most recent ``period`` values."""
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ema(values: list[float], period: int) -> float | None:
    """Exponential moving average, seeded with an SMA of the first window."""
    if period <= 0 or len(values) < period:
        return None
    multiplier = 2.0 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (value - current) * multiplier + current
    return current


def rsi(values: list[float], period: int = 14) -> float | None:
    """Wilder's RSI.

    Uses Wilder's smoothing rather than a simple average of gains and losses,
    because the simple version gives materially different readings on the same
    data and is not what any charting package shows.
    """
    if len(values) < period + 1:
        return None

    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for index in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def pct_change(values: list[float], periods_back: int) -> float | None:
    """Fractional change over ``periods_back`` bars."""
    if periods_back <= 0 or len(values) <= periods_back:
        return None
    previous = values[-periods_back - 1]
    if previous == 0:
        return None
    return (values[-1] - previous) / previous


def daily_returns(values: list[float]) -> list[float]:
    returns: list[float] = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        if previous:
            returns.append((values[index] - previous) / previous)
    return returns


def volatility(values: list[float], *, annualise: bool = True) -> float | None:
    """Standard deviation of daily returns, annualised by sqrt(252)."""
    returns = daily_returns(values)
    if len(returns) < 20:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    daily = math.sqrt(variance)
    return daily * math.sqrt(TRADING_DAYS) if annualise else daily


def max_drawdown(values: list[float]) -> float | None:
    """Largest peak-to-trough decline as a positive fraction."""
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (peak - value) / peak
            worst = max(worst, drawdown)
    return worst


def position_in_range(values: list[float]) -> float | None:
    """Where the last value sits between the window's min and max (0..1)."""
    if len(values) < 2:
        return None
    low, high = min(values), max(values)
    if high == low:
        return 0.5
    return (values[-1] - low) / (high - low)


# --------------------------------------------------------------------------- #
# snapshot
# --------------------------------------------------------------------------- #


def analyse(closes: list[float], volumes: list[float] | None = None) -> TechnicalSnapshot:
    """Build a full trend/volatility snapshot from chronological closes."""
    snapshot = TechnicalSnapshot(bars=len(closes))
    if not closes:
        snapshot.notes.append("no price history")
        return snapshot

    snapshot.last_close = closes[-1]
    year_window = closes[-TRADING_DAYS:]

    snapshot.sma_20 = sma(closes, 20)
    snapshot.sma_50 = sma(closes, 50)
    snapshot.sma_200 = sma(closes, 200)
    snapshot.ema_12 = ema(closes, 12)
    snapshot.ema_26 = ema(closes, 26)
    snapshot.rsi_14 = rsi(closes, 14)

    snapshot.return_1d = pct_change(closes, 1)
    snapshot.return_1w = pct_change(closes, 5)
    snapshot.return_1m = pct_change(closes, 21)
    snapshot.return_3m = pct_change(closes, 63)
    snapshot.return_6m = pct_change(closes, 126)
    snapshot.return_1y = pct_change(closes, 252)

    snapshot.volatility_annual = volatility(closes)
    snapshot.max_drawdown_1y = max_drawdown(year_window)

    snapshot.high_52w = max(year_window)
    snapshot.low_52w = min(year_window)
    snapshot.position_in_52w_range = position_in_range(year_window)

    if volumes:
        recent = volumes[-30:]
        if recent:
            snapshot.avg_volume_30d = sum(recent) / len(recent)
        prior = volumes[-60:-30]
        if prior and snapshot.avg_volume_30d:
            baseline = sum(prior) / len(prior)
            if baseline > 0:
                snapshot.volume_trend = snapshot.avg_volume_30d / baseline - 1.0

    snapshot.trend = classify_trend(snapshot)
    if len(closes) < 200:
        snapshot.notes.append(
            f"only {len(closes)} bars: the 200-day average is unavailable"
        )
    return snapshot


def classify_trend(snapshot: TechnicalSnapshot) -> str:
    """Reduce the moving averages into one label.

    Deliberately coarse and explainable. A label like "uptrend" is only useful if
    you can say which comparison produced it, so the rule is stated rather than
    learned:
      * price above both the 50-day and 200-day averages -> uptrend
      * price below both -> downtrend
      * otherwise -> mixed
    """
    price = snapshot.last_close
    if price is None:
        return "unknown"
    if snapshot.sma_50 is None and snapshot.sma_200 is None:
        return "unknown"
    if snapshot.sma_50 is None or snapshot.sma_200 is None:
        average = snapshot.sma_50 or snapshot.sma_200
        if average is None:
            return "unknown"
        return "uptrend" if price > average else "downtrend"

    above_50 = price > snapshot.sma_50
    above_200 = price > snapshot.sma_200
    if above_50 and above_200:
        return "uptrend"
    if not above_50 and not above_200:
        return "downtrend"
    return "mixed"


def relative_strength(
    closes: list[float], benchmark_closes: list[float], periods: int = 126
) -> float | None:
    """Excess return versus a benchmark over the same window.

    Positive means the instrument outperformed. Windows are truncated to the
    shorter series so a mismatch in history length cannot silently compare
    different time spans.
    """
    usable = min(len(closes), len(benchmark_closes), periods + 1)
    if usable < 20:
        return None
    instrument_return = pct_change(closes[-usable:], usable - 1)
    benchmark_return = pct_change(benchmark_closes[-usable:], usable - 1)
    if instrument_return is None or benchmark_return is None:
        return None
    return instrument_return - benchmark_return

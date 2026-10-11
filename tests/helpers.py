"""Shared builders and doubles for tests.

Plain functions rather than fixtures, because most tests want to construct a
specific shape of data (a particular instrument, a particular price path) rather
than receive whatever the fixture happens to provide.

The provider double lives here too rather than in the test module that first
needed it: a fake reused from another test module makes one feature's tests fail
when an unrelated feature's fixture changes, and `tests/test_business_panel.py`
was the only file in the tree importing across test modules.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from awltux.db import FundamentalPeriod, Instrument, PriceBar


def make_instrument(ticker: str = "AAPL_US_EQ", **overrides) -> Instrument:
    """An instrument with plausible defaults, overridable per test."""
    defaults = {
        "t212_ticker": ticker,
        "name": overrides.pop("name", "Apple Inc"),
        "short_name": "Apple",
        "isin": overrides.pop("isin", "US0378331005"),
        "currency_code": "USD",
        "instrument_type": "STOCK",
        "exchange_name": "NASDAQ",
        "yahoo_symbol": overrides.pop("yahoo_symbol", "AAPL"),
        "in_universe": True,
        "mapping_confidence": 0.9,
    }
    defaults.update(overrides)
    return Instrument(**defaults)


def make_bars(
    ticker: str,
    closes: list[float],
    *,
    start: dt.date | None = None,
    currency: str = "USD",
    volume: float = 1_000_000.0,
    source: str = "test",
    source_rank: int = 20,
) -> list[PriceBar]:
    """A chronological bar series built from a list of closes."""
    start = start or (dt.date.today() - dt.timedelta(days=len(closes) + 5))
    bars = []
    for index, close in enumerate(closes):
        bars.append(
            PriceBar(
                instrument_t212_ticker=ticker,
                date=start + dt.timedelta(days=index),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                adj_close=close,
                volume=volume,
                currency=currency,
                raw_currency=currency,
                raw_multiplier=1.0,
                raw_close=close,
                source=source,
                source_rank=source_rank,
            )
        )
    return bars


def make_period(
    ticker: str,
    period_end: dt.date,
    metrics: dict[str, float],
    *,
    period_type: str = "annual",
    source: str = "yahoo_statements",
    confidence: float = 0.7,
    currency: str = "USD",
) -> FundamentalPeriod:
    """One stored reporting period."""
    return FundamentalPeriod(
        instrument_t212_ticker=ticker,
        period_end=period_end,
        period_type=period_type,
        currency=currency,
        source=source,
        metrics=metrics,
        confidence=confidence,
    )


def healthy_metrics(**overrides) -> dict[str, float]:
    """A profitable, cash-generative company with modest debt.

    Used as the baseline for valuation tests so that a test only has to state the
    one attribute it is exercising.
    """
    base = {
        "revenue": 1_000_000.0,
        "gross_profit": 400_000.0,
        "operating_income": 150_000.0,
        "net_income": 100_000.0,
        "ebitda": 180_000.0,
        "eps_diluted": 1.0,
        "total_assets": 1_200_000.0,
        "total_liabilities": 500_000.0,
        "total_equity": 700_000.0,
        "total_debt": 200_000.0,
        "cash_and_equivalents": 80_000.0,
        "net_debt": 120_000.0,
        "operating_cash_flow": 160_000.0,
        "capex": 40_000.0,
        "free_cash_flow": 120_000.0,
        "shares_outstanding": 100_000.0,
        "gross_margin": 0.40,
        "operating_margin": 0.15,
        "net_margin": 0.10,
        "roe": 0.143,
        "roce": 0.167,
        "debt_to_equity": 0.286,
        "interest_cover": 12.0,
    }
    base.update(overrides)
    return base


def trending_closes(
    start: float = 100.0,
    *,
    days: int = 260,
    daily_return: float = 0.0005,
    noise: float = 0.0,
) -> list[float]:
    """A deterministic price path, optionally with sinusoidal noise."""
    closes = []
    price = start
    for day in range(days):
        wave = noise * math.sin(day / 7.0) if noise else 0.0
        price *= 1.0 + daily_return + wave
        closes.append(round(price, 4))
    return closes


def t212_exchanges() -> list[dict[str, Any]]:
    """Two exchanges whose *schedule* ids deliberately do not match their ids.

    This is the whole point: if the ids coincided, a wrong join would look right.
    """
    return [
        {
            "id": 1,
            "name": "London Stock Exchange",
            "workingSchedules": [{"id": 101, "timeEvents": []}, {"id": 154, "timeEvents": []}],
        },
        {
            "id": 2,
            "name": "NASDAQ",
            "workingSchedules": [{"id": 56, "timeEvents": []}],
        },
    ]


def t212_instruments() -> list[dict[str, Any]]:
    """A metadata payload as `/equity/metadata/instruments` sends it.

    Three rows, chosen for the join rather than for their names: two share a schedule
    (so they must land on one exchange) and one carries no ``extendedHours`` at all.
    """
    return [
        {
            "ticker": "VODl_EQ",
            "isin": "GB00BH4HKS39",
            "name": "Vodafone",
            "shortName": "VOD",
            "currencyCode": "GBX",
            "type": "STOCK",
            "extendedHours": False,
            "maxOpenQuantity": 1000.0,
            "addedOn": "2020-01-01T00:00:00.000+02:00",
            "workingScheduleId": 101,
        },
        {
            "ticker": "AAPL_US_EQ",
            "isin": "US0378331005",
            "name": "Apple",
            "shortName": "AAPL",
            "currencyCode": "USD",
            "type": "STOCK",
            "extendedHours": True,
            "maxOpenQuantity": 5000.0,
            "addedOn": "2020-01-01T00:00:00.000+02:00",
            "workingScheduleId": 56,
        },
        {
            "ticker": "XNASl_EQ",
            "isin": "IE00BMFKG444",
            "name": "Xtrackers NASDAQ 100",
            "shortName": "XNAS",
            "currencyCode": "USD",
            "type": "ETF",
            "workingScheduleId": 154,
        },
    ]


class FakeT212:
    """The two metadata calls the instrument sync makes, with no network behind them."""

    def __init__(self) -> None:
        self._exchanges = t212_exchanges()
        self._instruments = t212_instruments()

    def get_exchanges(self):
        return self._exchanges

    def get_instruments(self):
        return self._instruments

"""The Yahoo provider, tested against yfinance's real interface rules.

The provider is the app's only price source, so a mismatch with the library's API
is not a degraded feature -- it is a total outage. One such mismatch shipped:
``Ticker.history`` accepts ``*args, **kwargs`` and forwards them to
``PriceHistory.history``, which has a *different* parameter set from
``yfinance.download``. ``progress`` is valid for the latter and raises ``TypeError``
for the former, so every price fetch failed. No unit test caught it because the
tests never called the real library; a live connectivity check did.

These tests stub the library while reproducing its signature constraints, so the
mismatch cannot come back unnoticed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.providers.yahoo import YahooProvider


class FakeFrame:
    """Minimal stand-in for the DataFrame ``Ticker.history`` returns."""

    def __init__(self, rows: list[tuple[dt.datetime, float]]) -> None:
        self._rows = rows
        self.columns = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        self.attrs: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def empty(self) -> bool:
        return not self._rows

    def iterrows(self):
        for when, close in self._rows:
            yield when, {
                "Open": close - 0.5,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Adj Close": close,
                "Volume": 1_000_000.0,
            }


class FakeTicker:
    """Mirrors yfinance's constraint: ``progress`` is not a valid argument.

    ``Ticker.history`` is declared ``(self, *args, **kwargs)`` and forwards to
    ``PriceHistory.history``, which rejects ``progress``. Reproducing that here is
    the whole point -- a permissive stub would let the bug back in.
    """

    HISTORY_REJECTS = {"progress"}

    def __init__(self, symbol: str, *, currency: str = "USD", rows=None) -> None:
        self.symbol = symbol
        self._currency = currency
        self._rows = rows if rows is not None else [
            (dt.datetime(2024, 1, day, tzinfo=dt.UTC), 100.0 + day) for day in range(1, 11)
        ]
        # ``fast_info`` must tolerate an empty history: the empty-frame case is a
        # real provider response, not an error.
        self.fast_info = {"currency": currency}
        if self._rows:
            self.fast_info["last_price"] = self._rows[-1][1]

    def history(self, *args, **kwargs):
        rejected = self.HISTORY_REJECTS & set(kwargs)
        if rejected:
            raise TypeError(
                f"PriceHistory.history() got an unexpected keyword argument "
                f"{sorted(rejected)[0]!r}"
            )
        return FakeFrame(self._rows)

    def __getattr__(self, name: str):
        raise AttributeError(name)


class CurrencyAwareTicker(FakeTicker):
    """Reports a minor-unit currency, as Yahoo does for LSE symbols."""

    def __init__(self, symbol: str, **kwargs) -> None:
        super().__init__(symbol, currency="GBp", **kwargs)


@pytest.fixture
def provider(monkeypatch, settings):
    """A provider whose yfinance module is replaced by the stubs above."""
    instance = YahooProvider(settings)

    class FakeYf:
        Ticker = staticmethod(lambda symbol: FakeTicker(symbol))
        download = staticmethod(lambda **kwargs: FakeFrame([]))

    monkeypatch.setattr(instance, "_yf", FakeYf)
    return instance


class TestHistorySignature:
    def test_history_does_not_pass_progress(self, provider):
        """The exact bug: ``progress`` is a ``download`` argument, not a
        ``history`` argument, and passing it raised TypeError on every call."""
        series = provider.get_history("AAPL", period="1mo")
        assert len(series.bars) == 10

    def test_history_passes_only_supported_arguments(self, provider):
        captured: dict = {}
        original = provider._yf.Ticker

        class RecordingTicker(FakeTicker):
            def history(self, *args, **kwargs):
                captured.update(kwargs)
                return super().history(*args, **kwargs)

        provider._yf.Ticker = lambda symbol: RecordingTicker(symbol)
        try:
            provider.get_history("AAPL", period="1mo")
        finally:
            provider._yf.Ticker = original

        assert "progress" not in captured
        assert captured["interval"] == "1d"
        assert captured["auto_adjust"] is False
        assert captured["actions"] is False

    def test_start_date_replaces_the_period_argument(self, provider):
        captured: dict = {}
        original = provider._yf.Ticker

        class RecordingTicker(FakeTicker):
            def history(self, *args, **kwargs):
                captured.update(kwargs)
                return super().history(*args, **kwargs)

        provider._yf.Ticker = lambda symbol: RecordingTicker(symbol)
        try:
            provider.get_history("AAPL", start=dt.date(2024, 1, 1))
        finally:
            provider._yf.Ticker = original

        assert captured["period"] is None
        assert captured["start"] == "2024-01-01"


class TestCurrencyNormalisationThroughTheProvider:
    def test_us_symbols_pass_through_as_dollars(self, provider):
        series = provider.get_history("AAPL")
        assert series.currency == "USD"
        assert series.raw_multiplier == 1.0
        assert series.bars[-1].close == pytest.approx(110.0)

    def test_lse_symbols_are_converted_from_pence(self, monkeypatch, settings):
        """The pence trap, at the provider boundary where it matters."""
        instance = YahooProvider(settings)

        class FakeYf:
            Ticker = staticmethod(lambda symbol: CurrencyAwareTicker(symbol))

        monkeypatch.setattr(instance, "_yf", FakeYf)
        series = instance.get_history("VOD.L")

        assert series.raw_currency == "GBp"
        assert series.currency == "GBP"
        assert series.raw_multiplier == pytest.approx(0.01)
        # 110 pence is 1.10 pounds, not 110 pounds.
        assert series.bars[-1].close == pytest.approx(1.10)

    def test_the_raw_figure_can_be_recovered(self, monkeypatch, settings):
        instance = YahooProvider(settings)

        class FakeYf:
            Ticker = staticmethod(lambda symbol: CurrencyAwareTicker(symbol))

        monkeypatch.setattr(instance, "_yf", FakeYf)
        series = instance.get_history("VOD.L")
        restored = series.bars[-1].close / series.raw_multiplier
        assert restored == pytest.approx(110.0)


class TestFailureHandling:
    def test_a_library_error_becomes_a_provider_error(self, monkeypatch, settings):
        instance = YahooProvider(settings)

        class ExplodingTicker(FakeTicker):
            def history(self, *args, **kwargs):
                raise RuntimeError("rate limited")

        class FakeYf:
            Ticker = staticmethod(lambda symbol: ExplodingTicker(symbol))

        monkeypatch.setattr(instance, "_yf", FakeYf)
        from awltux.providers.http import ProviderError

        with pytest.raises(ProviderError) as excinfo:
            instance.get_history("AAPL")
        assert "rate limited" in str(excinfo.value)

    def test_an_empty_frame_is_not_an_error(self, provider):
        provider._yf.Ticker = lambda symbol: FakeTicker(symbol, rows=[])
        series = provider.get_history("AAPL")
        assert series.bars == []

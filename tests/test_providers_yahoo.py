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


class FakeMultiColumns:
    """yfinance's MultiIndex columns, as far as this provider looks at them."""

    NAMES = ("Open", "High", "Low", "Close", "Adj Close", "Volume")

    def __init__(self, symbols: list[str]) -> None:
        self.levels = [list(symbols)]
        self._columns = [(symbol, name) for symbol in symbols for name in self.NAMES]

    def get_level_values(self, level: int) -> list[str]:
        return [column[0] for column in self._columns]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._columns)


class FakeMultiFrame:
    """What ``yf.download`` returns, and it is a MultiIndex **even for one ticker**.

    Measured against the real library on 2026-10-09: ``download(["VWRL.L"],
    group_by="ticker")`` gives 6 columns of ``('VWRL.L', 'Open')`` … with
    ``columns.levels`` present -- not 6 simple columns. A stub with simple columns would have
    hidden the bug this models, so there isn't one.
    """

    def __init__(self, symbols: list[str], rows: list[tuple[dt.datetime, float]]) -> None:
        self.columns = FakeMultiColumns(symbols)
        self.attrs: dict[str, str] = {}
        self._symbols = symbols
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def empty(self) -> bool:
        return not self._rows

    def __getitem__(self, symbol: str) -> FakeFrame:
        return FakeFrame(self._rows)


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


class TestTheBatchUnitComesFromTheCallerNotTheFrame:
    """A batch download is one frame carrying **one** currency for the whole request.

    So the frame's own metadata is not per-symbol evidence, and reading it as such is how an
    LSE ETF quoted in pounds came back as 1.41 against a true 141.30. The caller knows the unit
    -- Trading 212 publishes one per instrument and the row holds it -- and states it.
    """

    def _instance(self, monkeypatch, settings, *, frame_currency: str):
        """A provider whose batch download returns one frame for every symbol asked for, and
        the list of requests it was asked with."""
        instance = YahooProvider(settings)
        requests: list = []

        class BatchFrame(FakeFrame):
            def __init__(self) -> None:
                super().__init__(
                    [(dt.datetime(2026, 6, day, tzinfo=dt.UTC), 141.30) for day in (1, 2)]
                )
                # One currency for the whole download, as yfinance gives it: whatever the
                # request's group was, not what any one symbol in it is quoted in.
                self.attrs = {"currency": frame_currency}

            def __getitem__(self, symbol):
                return self

        class FakeYf:
            Ticker = staticmethod(lambda symbol: FakeTicker(symbol))
            download = staticmethod(
                lambda **kwargs: (requests.append(kwargs["tickers"]), BatchFrame())[1]
            )

        monkeypatch.setattr(instance, "_yf", FakeYf)
        return instance, requests

    def test_a_stated_unit_beats_the_frame(self, monkeypatch, settings):
        """The bug: VWRL.L is quoted in GBP and Yahoo says GBP, but the batch frame carried the
        group's unit -- pence -- because the other LSE names in the request are quoted in it.
        The instrument's own unit has to win, or £141.30 is stored as £1.41."""
        instance, _ = self._instance(monkeypatch, settings, frame_currency="GBp")

        series = instance.get_history_batch(["VWRL.L"], currencies={"VWRL.L": "GBP"})["VWRL.L"]

        assert series.raw_currency == "GBP"
        assert series.raw_multiplier == 1.0
        assert series.bars[-1].close == pytest.approx(141.30)

    def test_a_stated_pence_unit_is_still_divided(self, monkeypatch, settings):
        """The other direction, and the case that was already right: the same frame, the same
        request, an instrument the broker says is quoted in pence."""
        instance, _ = self._instance(monkeypatch, settings, frame_currency="GBP")

        series = instance.get_history_batch(["VOD.L"], currencies={"VOD.L": "GBX"})["VOD.L"]

        assert series.raw_multiplier == pytest.approx(0.01)
        assert series.bars[-1].close == pytest.approx(1.413)

    def test_the_group_is_the_unit_the_caller_stated(self, monkeypatch, settings):
        """The grouping is how the symbols are *asked for*, and grouping by the suffix is what
        put a pound-quoted ETF in the pence request."""
        instance, requests = self._instance(monkeypatch, settings, frame_currency="GBp")

        instance.get_history_batch(["VOD.L", "VWRL.L"], currencies={"VWRL.L": "GBP"})

        assert list(requests) == [["VOD.L"], ["VWRL.L"]], "one request per stated unit"

    def test_with_no_stated_unit_the_frame_speaks_for_the_group(self, monkeypatch, settings):
        """A caller with nothing to say gets the old behaviour: the frame's currency is the
        provider's own word for the request we made, and the suffix convention only stands in
        when the frame says nothing at all."""
        instance, _ = self._instance(monkeypatch, settings, frame_currency="GBP")

        series = instance.get_history_batch(["VOD.L"])["VOD.L"]

        assert series.raw_multiplier == 1.0, "the frame's own unit, not the suffix's"

    def test_with_nothing_stated_anywhere_the_suffix_convention_stands_in(
        self, monkeypatch, settings
    ):
        """Which is right for most LSE lines, and is still a guess -- hence the caller stating
        the unit wherever it can."""
        instance, _ = self._instance(monkeypatch, settings, frame_currency="")

        series = instance.get_history_batch(["VOD.L"])["VOD.L"]

        assert series.raw_currency == "GBX"
        assert series.raw_multiplier == pytest.approx(0.01)

    def test_a_single_symbol_fetch_has_no_group_to_be_wrong_about(
        self, monkeypatch, settings
    ):
        """`get_history` asks for one symbol and takes the unit from the ticker's own
        ``fast_info`` -- a per-symbol statement -- so it never had this bug. The fix is in the
        batch path and changes nothing here."""
        instance, _ = self._instance(monkeypatch, settings, frame_currency="GBP")
        instance._yf.Ticker = staticmethod(lambda symbol: CurrencyAwareTicker(symbol))

        series = instance.get_history("VOD.L")

        assert series.raw_currency == "GBp", "the ticker's own unit"
        assert series.raw_multiplier == pytest.approx(0.01)
        assert series.bars[-1].close == pytest.approx(1.10), "110 pence is 1.10 pounds"


class TestASymbolAloneInItsGroupStillGetsItsBars:
    """`refresh_prices_eod` groups symbols by the unit they are quoted in, and a unit one symbol
    has to itself is ordinary -- an LSE ETF quoted in pounds, in a universe of US and pence
    lines. yfinance answers a one-ticker request with MultiIndex columns exactly as it does a
    forty-ticker one, so which shape comes back is a property of the *frame*:

    measured 2026-10-09, `download(["VWRL.L"], group_by="ticker")` gives 6 columns of
    `('VWRL.L', 'Open')` … and `columns.levels` is present.

    Asking "were more than one symbol requested?" instead got this wrong, and the symptom was
    not a wrong price but no price at all: "the provider returned no bars for VWRL.L" on every
    run after the unit fix landed.
    """

    def _instance(self, monkeypatch, settings, *, symbols: list[str]):
        instance = YahooProvider(settings)
        rows = [(dt.datetime(2026, 6, day, tzinfo=dt.UTC), 141.30) for day in (1, 2)]

        class FakeYf:
            Ticker = staticmethod(lambda symbol: FakeTicker(symbol))
            download = staticmethod(lambda **kwargs: FakeMultiFrame(symbols, rows))

        monkeypatch.setattr(instance, "_yf", FakeYf)
        return instance

    def test_one_symbol_in_its_group_still_reads(self, monkeypatch, settings):
        instance = self._instance(monkeypatch, settings, symbols=["VWRL.L"])

        series = instance.get_history_batch(["VWRL.L"], currencies={"VWRL.L": "GBP"})["VWRL.L"]

        assert len(series.bars) == 2, "the rows were there; the columns were not found"
        assert series.bars[-1].close == pytest.approx(141.30)
        assert series.raw_multiplier == 1.0

    def test_a_symbol_missing_from_the_frame_yields_nothing_rather_than_crashing(
        self, monkeypatch, settings
    ):
        """A download that answered for different symbols than it was asked for is a real
        provider response, and the caller records it as "no bars" rather than failing the run."""
        instance = self._instance(monkeypatch, settings, symbols=["SOMETHINGELSE.L"])

        assert instance.get_history_batch(["VWRL.L"]) == {}


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


class TestTheProfilePayload:
    """`get_profile` trims a heavy payload to the keys this project keeps.

    The company description rides on the same call as the sector and the market cap, so it
    costs nothing at the provider -- which is the only reason the recommendations table can
    show one at all.
    """

    @staticmethod
    def _instance(monkeypatch, settings, info: dict):
        class ProfileTicker(FakeTicker):
            def __init__(self, symbol: str) -> None:
                super().__init__(symbol)
                self.info = {"symbol": symbol, **info}

        class FakeYf:
            Ticker = staticmethod(lambda symbol: ProfileTicker(symbol))

        instance = YahooProvider(settings)
        monkeypatch.setattr(instance, "_yf", FakeYf)
        return instance

    def test_the_company_description_is_carried_through(self, monkeypatch, settings):
        instance = self._instance(
            monkeypatch, settings, {"longBusinessSummary": "Hint Co makes hints."}
        )

        assert instance.get_profile("HINT")["longBusinessSummary"] == "Hint Co makes hints."

    def test_keys_the_project_does_not_keep_are_still_dropped(self, monkeypatch, settings):
        """The trim is the point of the method: `info` is a heavy, slow call and only the
        keys named in it are kept."""
        instance = self._instance(
            monkeypatch,
            settings,
            {"longBusinessSummary": "Hint Co makes hints.", "fullTimeEmployees": 12},
        )

        profile = instance.get_profile("HINT")

        assert "fullTimeEmployees" not in profile


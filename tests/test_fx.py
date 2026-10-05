"""FX rate caching.

Two bugs lived here, and the second explains why the first was easy to miss:

* Three rates cached in one pass each wrote a dictionary containing **only
  themselves**. The read used ``load_rates()``, which returns the last *committed*
  value, so each write overwrote the previous one. The cache ended up holding one
  rate instead of three, and the loss was silent.
* Because the writes shared one transaction, the second and third calls each found
  no row via ``session.get`` -- which does not see a pending, unflushed object --
  and inserted it again, colliding on the primary key with
  ``UNIQUE constraint failed: app_setting.key``.

The observable failure was the constraint error. The data loss would have gone
unnoticed, because a missing rate just makes a conversion return ``None``.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis import fx
from awltux.db import AppSetting, session_scope


def stored_rates() -> dict[str, dict[str, object]]:
    with session_scope() as session:
        row = session.get(AppSetting, fx.SETTING_KEY)
        if row is None or not isinstance(row.value, dict):
            return {}
        return row.value.get("rates", {})


@pytest.fixture
def yahoo_stub(monkeypatch):
    """Replace the network lookup with a deterministic rate."""

    class FakeQuote:
        def __init__(self, price: float) -> None:
            self.price = price

    prices = {"GBPUSD=X": 1.25, "EURGBP=X": 0.85}

    def fake_get_quote(symbol: str):
        return FakeQuote(prices[symbol])

    class FakeYahoo:
        def get_quote(self, symbol: str):
            return fake_get_quote(symbol)

    import awltux.providers.yahoo as yahoo_module

    monkeypatch.setattr(yahoo_module, "YahooProvider", FakeYahoo)
    return prices


class TestAccumulation:
    def test_three_rates_cached_together_are_all_kept(self, yahoo_stub, settings):
        """The data-loss bug: each write overwrote the whole dictionary."""
        rates = fx.refresh_common_rates()

        assert len(rates) == 3
        assert set(stored_rates()) == {"USD:GBP", "EUR:GBP", "GBP:USD"}

    def test_rates_cached_in_separate_calls_accumulate(self, yahoo_stub, settings):
        fx.get_rate("USD", "GBP", refresh=True)
        assert set(stored_rates()) == {"USD:GBP"}

        fx.get_rate("EUR", "GBP", refresh=True)
        assert set(stored_rates()) == {"USD:GBP", "EUR:GBP"}

    def test_repeated_refreshes_do_not_duplicate_the_row(self, yahoo_stub, settings):
        """The constraint error: a pending row is invisible to ``session.get``."""
        for _ in range(3):
            fx.refresh_common_rates()

        with session_scope() as session:
            rows = (
                session.query(AppSetting)
                .filter(AppSetting.key == fx.SETTING_KEY)
                .all()
            )
        assert len(rows) == 1


class TestReading:
    def test_a_stored_rate_is_returned(self, yahoo_stub, settings):
        fx.get_rate("USD", "GBP", refresh=True)
        rate = fx.get_rate("USD", "GBP")
        assert rate is not None
        assert rate.rate == pytest.approx(0.8)  # 1 / 1.25

    def test_an_inverse_rate_is_derived(self, yahoo_stub, settings):
        """Only one direction needs to be fetched."""
        fx.get_rate("USD", "GBP", refresh=True)
        inverse = fx.get_rate("GBP", "USD")
        assert inverse is not None
        assert inverse.rate == pytest.approx(1.25)

    def test_an_unknown_pair_returns_none_rather_than_one(self, settings):
        """A silent 1:1 rate would corrupt every comparison that used it."""
        assert fx.get_rate("XYZ", "ABC") is None

    def test_identity_is_exact(self, settings):
        rate = fx.get_rate("GBP", "GBP")
        assert rate is not None and rate.rate == 1.0

    def test_a_naive_stored_timestamp_does_not_break_staleness(self, settings):
        fx._store_rate(
            fx.FxRate(
                base="USD",
                quote="GBP",
                rate=0.8,
                as_of=dt.datetime.now(dt.UTC).replace(tzinfo=None),
                source="test",
            )
        )
        rate = fx.get_rate("USD", "GBP")
        assert rate is not None
        assert rate.stale is False


class TestConversion:
    def test_pence_needs_no_fx(self, settings):
        """``GBp`` is a unit change, not a currency change."""
        assert fx.quote_to_gbp(1250.0, "GBp") == pytest.approx(12.50)

    def test_pounds_are_unchanged(self, settings):
        assert fx.quote_to_gbp(12.50, "GBP") == pytest.approx(12.50)

    def test_an_unconvertible_currency_returns_none(self, settings):
        assert fx.quote_to_gbp(100.0, "XYZ") is None

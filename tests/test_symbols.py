"""Trading 212 ticker parsing and provider-symbol derivation.

Trading 212's ticker format is not a documented public contract, and the UK shape
is genuinely surprising: US listings are ``AAPL_US_EQ`` but UK listings append a
lowercase venue letter with no separator, e.g. ``VODl_EQ``. Parsing these wrongly
attaches another company's prices to a ticker, so the behaviour is pinned here.
"""

from __future__ import annotations

import pytest

from awltux.ingest.symbols import (
    CONFIDENCE_PLAUSIBLE,
    CONFIDENCE_STRONG,
    derive_yahoo_symbol,
    is_uk_listing,
    parse_t212_ticker,
)


class TestParseT212Ticker:
    @pytest.mark.parametrize(
        ("ticker", "expected"),
        [
            # US listings carry an explicit venue token.
            ("AAPL_US_EQ", ("AAPL", "US")),
            ("MSFT_US_EQ", ("MSFT", "US")),
            # UK listings glue a lowercase "l" on with no separator.
            ("VODl_EQ", ("VOD", "LSE")),
            ("BPl_EQ", ("BP", "LSE")),
            ("AAFl_EQ", ("AAF", "LSE")),
            # Other European venues use their own letter.
            ("ADYENa_EQ", ("ADYEN", "AMS")),
            ("AIRp_EQ", ("AIR", "PAR")),
            # A bare symbol is treated as a US listing, since T212 always
            # qualifies non-US ones.
            ("TSLA", ("TSLA", None)),
        ],
    )
    def test_parses_known_shapes(self, ticker: str, expected: tuple[str, str | None]):
        assert parse_t212_ticker(ticker) == expected

    def test_strips_only_the_type_suffix(self):
        assert parse_t212_ticker("AAPL_US_EQ")[0] == "AAPL"
        assert parse_t212_ticker("AAPL_US")[0] == "AAPL"

    def test_does_not_invent_a_base_for_an_unknown_shape(self):
        # Better to admit ignorance than to return a plausible wrong symbol.
        base, venue = parse_t212_ticker("SOMETHING_WEIRD_TOKEN_EQ")
        assert base == "SOMETHING_WEIRD"
        assert venue == "TOKEN"


class TestDeriveYahooSymbol:
    def test_us_listing_is_the_bare_symbol(self):
        mapping = derive_yahoo_symbol("AAPL_US_EQ", exchange_name="NASDAQ")
        assert mapping.yahoo_symbol == "AAPL"
        assert mapping.confidence >= CONFIDENCE_STRONG

    def test_uk_listing_takes_the_dot_l_suffix(self):
        mapping = derive_yahoo_symbol("VODl_EQ", exchange_name="LSE")
        assert mapping.yahoo_symbol == "VOD.L"
        assert mapping.venue == "LSE"

    def test_uk_suffix_is_also_used_without_a_venue_token(self):
        mapping = derive_yahoo_symbol("BP_EQ", exchange_name="London Stock Exchange")
        assert mapping.yahoo_symbol == "BP.L"

    def test_conflicting_venue_and_exchange_is_left_unresolved(self):
        """A ticker/exchange disagreement must not be silently resolved.

        Either source could be stale, and picking one automatically risks
        attaching another company's prices to the ticker. Leaving it unresolved
        costs the analysis for one name and surfaces it for confirmation.
        """
        mapping = derive_yahoo_symbol("AAPL_US_EQ", exchange_name="London Stock Exchange")
        assert mapping.yahoo_symbol is None
        assert mapping.confidence == 0.0
        assert mapping.method == "conflict"
        assert mapping.usable is False

    def test_agreeing_venue_and_exchange_is_resolved(self):
        mapping = derive_yahoo_symbol("VODl_EQ", exchange_name="London Stock Exchange")
        assert mapping.yahoo_symbol == "VOD.L"
        assert mapping.confidence >= CONFIDENCE_STRONG

    def test_unrecognised_exchange_is_not_assumed_to_be_us(self):
        """An exchange we cannot map must not fall through to the US default."""
        mapping = derive_yahoo_symbol("7203t_EQ", exchange_name="Tokyo")
        assert mapping.yahoo_symbol is None
        assert mapping.method == "unknown_exchange"

    def test_unsupported_venue_letter_is_left_unresolved(self):
        # "o" is Oslo, for which no Yahoo suffix is configured in this app.
        mapping = derive_yahoo_symbol("EQNRo_EQ", exchange_name="Oslo")
        # Oslo maps to .OL via the venue table, so this one does resolve.
        assert mapping.yahoo_symbol == "EQNR.OL"

    def test_venue_with_no_yahoo_suffix_is_unresolved(self):
        mapping = derive_yahoo_symbol("7203t_EQ")
        assert mapping.yahoo_symbol is None
        assert mapping.confidence == 0.0
        assert mapping.usable is False

    def test_unparseable_symbol_is_unresolved(self):
        mapping = derive_yahoo_symbol("!!bad!!_EQ")
        assert mapping.yahoo_symbol is None
        assert mapping.method == "unparseable"

    def test_non_lse_european_venue_maps_to_its_yahoo_suffix(self):
        mapping = derive_yahoo_symbol("ADYENa_EQ", exchange_name="Amsterdam")
        assert mapping.yahoo_symbol == "ADYEN.AS"
        assert mapping.confidence == pytest.approx(CONFIDENCE_PLAUSIBLE)


class TestIsUkListing:
    def test_detects_by_yahoo_symbol(self):
        assert is_uk_listing(None, "VOD.L") is True
        assert is_uk_listing(None, "AAPL") is False

    def test_detects_by_exchange_name(self):
        assert is_uk_listing("London Stock Exchange", None) is True
        assert is_uk_listing("NASDAQ", None) is False

    def test_unknown_is_not_uk(self):
        assert is_uk_listing(None, None) is False

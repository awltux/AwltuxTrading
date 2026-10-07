"""Which instrument a stored story is attributed to, and which feeds get a say.

A story legitimately about two companies should name both, and the merge that records
the second is deliberate. What is not legitimate is a ticker recorded because a feed was
*asked* for it: a Yahoo `?s=` feed returns a pool of articles rather than that symbol's
own news, so one announcement reaches the store from many instruments' feeds and picks up
a ticker from each.

Measured 2026-10-07 before the fix: 21 `yahoo_rss` rows carried more than three tickers,
49 more than one, and the same "Transaction in Own Shares" announcement was attributed to
eight different investment trusts, none of which it concerned.
"""

from __future__ import annotations

from awltux.db import NewsItem
from awltux.ingest.news import SYMBOL_POOLED_SOURCES, _merge_target
from awltux.providers.news_rss import RawNewsItem


def _item(source: str, *tickers: str, sectors: list[str] | None = None) -> RawNewsItem:
    return RawNewsItem(
        title="Fidelity Asian Values Plc - Transaction in Own Shares",
        url="https://uk.finance.yahoo.com/news/x.html",
        source=source,
        tickers=list(tickers),
        sectors=list(sectors or []),
    )


def _row(*tickers: str) -> NewsItem:
    return NewsItem(
        source="yahoo_rss",
        url="https://uk.finance.yahoo.com/news/x.html",
        url_hash="h",
        title="Fidelity Asian Values Plc - Transaction in Own Shares",
        tickers=list(tickers),
        sectors=[],
    )


class TestPooledFeedsDoNotAccumulate:
    def test_a_yahoo_feed_contributes_no_second_ticker(self):
        """The row keeps the ticker of the feed that stored it. A second Yahoo feed
        returning the same article is evidence it was asked, not that the story is
        about its instrument."""
        row = _row("PETl_EQ")

        _merge_target(row, _item("yahoo_rss", "ARRl_EQ"))

        assert row.tickers == ["PETl_EQ"]

    def test_eight_feeds_leave_one_ticker(self):
        """The shape of the measured case, from one to eight."""
        row = _row("PETl_EQ")

        for ticker in ("ARRl_EQ", "PMPl_EQ", "AVGl_EQ", "SCFl_EQ", "PENl_EQ", "BGFDl_EQ", "CYNl_EQ"):
            _merge_target(row, _item("yahoo_rss", ticker))

        assert row.tickers == ["PETl_EQ"]

    def test_the_set_names_the_source_it_is_for(self):
        assert "yahoo_rss" in SYMBOL_POOLED_SOURCES
        assert "google_news" not in SYMBOL_POOLED_SOURCES, (
            "a Google News feed is a query for the company's name, so a result is about "
            "what was asked for and a two-company story must still name both"
        )


class TestContentAddressedFeedsStillUnion:
    def test_a_google_news_feed_adds_its_instrument(self):
        row = _row("PETl_EQ")

        _merge_target(row, _item("google_news", "ARRl_EQ"))

        assert row.tickers == ["PETl_EQ", "ARRl_EQ"]

    def test_a_ticker_is_never_added_twice(self):
        row = _row("PETl_EQ", "ARRl_EQ")

        _merge_target(row, _item("google_news", "ARRl_EQ"))

        assert row.tickers == ["PETl_EQ", "ARRl_EQ"]

    def test_sectors_union_the_same_way(self):
        row = _row("PETl_EQ")
        row.sectors = ["Energy"]

        _merge_target(row, _item("google_news", "ARRl_EQ", sectors=["Industrials"]))

        assert row.sectors == ["Energy", "Industrials"]

    def test_a_pooled_feed_adds_no_sector_either(self):
        """The same feed is pooling, so its sector tag is worth no more than its
        ticker."""
        row = _row("PETl_EQ")
        row.sectors = ["Energy"]

        _merge_target(row, _item("yahoo_rss", "ARRl_EQ", sectors=["Industrials"]))

        assert row.sectors == ["Energy"]

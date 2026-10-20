"""The rendered-page cache, and the rule that a mutation cannot be served from it.

Measured 2026-10-20, after the page itself was trimmed to 69-87 ms: the case this serves is a
reader coming Back, reloading, or duplicating a tab, which asks for the same URL within seconds.
The case it must not serve is a page rendered *before* a refresh started -- hence the
invalidation in the refresh route, and the TTL as the backstop.
"""

from __future__ import annotations

import time

from awltux.web import queries
from awltux.web.cache import PAGE_TTL_SECONDS, TTLCache
from tests.helpers import make_instrument

TICKER = "CACHE_US_EQ"


class TestTheCache:
    def test_a_second_read_is_served_from_memory(self):
        cache = TTLCache(seconds=60)

        cache.set(("a", 1), "body")

        assert cache.get(("a", 1)) == "body"
        assert (cache.hits, cache.misses) == (1, 0)

    def test_an_entry_expires(self):
        cache = TTLCache(seconds=0.01)
        cache.set(("a",), "body")

        time.sleep(0.02)

        assert cache.get(("a",)) is None
        assert (cache.hits, cache.misses) == (0, 1)

    def test_invalidate_takes_one_ticker_and_leaves_the_rest(self):
        """The key is `(ticker, tab, window, page)`, so the prefix is the ticker."""
        cache = TTLCache(seconds=60)
        cache.set((TICKER, "decision", None, 1), "decision")
        cache.set((TICKER, "refresh", None, 1), "refresh")
        cache.set(("OTHER", "decision", None, 1), "other")

        assert cache.invalidate((TICKER,)) == 2
        assert cache.get((TICKER, "decision", None, 1)) is None
        assert cache.get(("OTHER", "decision", None, 1)) == "other"

    def test_it_is_bounded(self):
        """Bounded by insertion, not by a sweeper: this process is a dashboard, not a cache."""
        cache = TTLCache(seconds=60, entries=3)
        for index in range(10):
            cache.set((index,), f"body-{index}")

        assert len(cache) == 3
        assert cache.get((9,)) == "body-9", "the newest survives"

    def test_the_ttl_is_short_enough_to_be_invisible(self):
        """A page is a snapshot; five seconds is the longest a reader could catch it out."""
        assert PAGE_TTL_SECONDS <= 10.0


class TestTheInstrumentPage:
    def test_a_repeat_request_is_served_without_a_query(self, client, session):
        """The second load must not need the database at all.

        Asserted by mutating what the page *would* show between the two requests: if the
        second one re-read the row it would render the new sector, and the cache is the only
        reason it does not.
        """
        session.add(make_instrument(TICKER, sector="Industrials"))
        session.commit()

        first = client.get(f"/instrument/{TICKER}?tab=decision").text
        assert "Industrials" in first

        instrument = session.get(queries.Instrument, TICKER)
        instrument.sector = "Changed Between Requests"
        session.commit()

        second = client.get(f"/instrument/{TICKER}?tab=decision").text
        assert "Changed Between Requests" not in second

        cache = client.app.state.page_cache
        assert cache.hits >= 1, "the repeat was not served from the cache"

    def test_a_message_url_is_never_served_from_the_cache(self, client, session):
        """`?refresh=started` is an outcome to report, so that page is always rendered."""
        session.add(make_instrument(TICKER))
        session.commit()

        first = client.get(f"/instrument/{TICKER}?tab=refresh&refresh=started").text
        assert "started" in first

        instrument = session.get(queries.Instrument, TICKER)
        instrument.sector = "Rendered Again"
        session.commit()

        second = client.get(f"/instrument/{TICKER}?tab=refresh&refresh=started").text
        assert second != first or "Rendered Again" in second

    def test_a_different_tab_is_a_different_entry(self, client, session):
        session.add(make_instrument(TICKER))
        session.commit()

        decision = client.get(f"/instrument/{TICKER}?tab=decision").text
        price = client.get(f"/instrument/{TICKER}?tab=price").text

        assert decision != price
        assert "Price history" in price

    def test_the_refresh_post_clears_that_instrument(self, client, session):
        """The one mutation a reader watches happen, so it cannot be answered from memory."""
        session.add(make_instrument(TICKER))
        session.commit()
        client.get(f"/instrument/{TICKER}?tab=refresh")
        cache = client.app.state.page_cache
        assert len(cache) >= 1

        client.post(f"/instrument/{TICKER}/refresh")

        assert cache.get((TICKER, "refresh", None, 1)) is None

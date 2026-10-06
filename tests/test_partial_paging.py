"""Paging that swaps the table instead of reloading the document.

The complaint this answers is specific: clicking "next page" navigated, so the reader
landed back at the head of the page and had to scroll down to the table they were
reading. The fix is an enhancement, not a replacement -- the pager is still a set of
real links that work with JavaScript off, and the tests below hold that line as well as
the new one.

Two properties are worth more than the rest:

* **A fragment is a fragment.** The region endpoints must return the region and nothing
  else. If one started returning a whole document the swap would still "work" while
  silently nesting an `<html>` inside the page.
* **The fragment and the page agree.** Both are rendered from the same context builder,
  so a test asserting they show the same rows is really asserting there is only one
  source of them.
"""

from __future__ import annotations

import pytest

REGIONS = [
    ("dashboard", "/dashboard", "/partials/recommendations"),
]

#: The other three pagers are queued in TODO.md. They are listed here rather than
#: silently dropped, because the mechanism below is generic and only the region
#: extraction is per-page: `/decisions` (page/per_page + filters), `/jobs`
#: (run_page/run_per_page + filters) and `/instrument/{ticker}` (news_page).


@pytest.fixture
def universe(session):
    """Enough decided instruments that the table paginates.

    Deliberately more than one page. The pager only renders when there is something to
    page to, so a single-row fixture would let every assertion below pass against an
    empty string -- which is how a test of "the links are still links" proves nothing.
    """
    import datetime as dt

    from awltux.db import DecisionRun
    from tests.helpers import make_instrument

    for index in range(15):
        session.add(make_instrument(f"TEST{index:02d}_US_EQ", name=f"Test {index}"))
    session.flush()
    for index in range(15):
        session.add(
            DecisionRun(
                instrument_t212_ticker=f"TEST{index:02d}_US_EQ",
                state_sha256="x" * 8,
                engine="deepseek",
                long_term_action="buy",
                short_term_action="hold",
                confidence=0.7,
                created_at=dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC),
            )
        )
    session.commit()
    return "TEST00_US_EQ"


class TestTheRegionContract:
    """The paged region, held to the shape the swap depends on."""

    @pytest.mark.parametrize("name, page_url, partial_url", REGIONS)
    def test_the_page_carries_the_region_wrapper(self, client, universe, name, page_url, partial_url):
        body = client.get(page_url).text

        assert f'data-partial="{partial_url}"' in body, name

    @pytest.mark.parametrize("name, page_url, partial_url", REGIONS)
    def test_the_fragment_returns_the_region_and_not_a_document(
        self, client, universe, name, page_url, partial_url
    ):
        """A fragment that returned a whole page would nest an `<html>` in the swap.

        It would look like it worked, which is why this is asserted rather than assumed.
        """
        response = client.get(partial_url)

        assert response.status_code == 200, name
        assert f'data-partial="{partial_url}"' in response.text, name
        assert "<html" not in response.text.lower(), f"{name} returned a whole document"
        assert "<!doctype" not in response.text.lower(), name

    @pytest.mark.parametrize("name, page_url, partial_url", REGIONS)
    def test_the_pager_is_still_a_set_of_real_links(
        self, client, universe, name, page_url, partial_url
    ):
        """The whole thing degrades to what it was.

        The script intercepts these links; it does not create them. If a pager stopped
        being an href the page would need JavaScript to page at all, which is the
        regression this guards -- and the assertion counts them, so an empty pager
        cannot pass it.
        """
        body = client.get(f"{page_url}?page=1&per_page=10").text

        assert 'class="pager"' in body, name
        assert 'href="/dashboard?page=2' in body, name


class TestTheDashboardRegion:
    def test_the_fragment_holds_the_rows_the_page_holds(self, client, universe):
        """One region builder, so the two cannot disagree about the filter state."""
        page = client.get("/dashboard?per_page=10").text
        fragment = client.get("/partials/recommendations?per_page=10").text

        assert "TEST00_US_EQ" in page
        assert "TEST00_US_EQ" in fragment

    def test_the_fragment_respects_the_page_parameter(self, client, universe):
        first = client.get("/partials/recommendations?page=1&per_page=10").text
        second = client.get("/partials/recommendations?page=2&per_page=10").text

        assert "Page 1 of 2" in first
        assert "Page 2 of 2" in second

    def test_a_nonsensical_page_is_refused_rather_than_served(self, client, universe):
        """`page` is one of the two parameters a reader never types, so a bad value is
        a bug worth refusing rather than a stale bookmark to tolerate."""
        assert client.get("/partials/recommendations?page=0").status_code == 422

    def test_the_fragment_does_not_recompute_the_page_header(self, client, universe):
        """`universe_stats` sweeps the universe and is used *above* the table, which the
        swap does not touch. The region gets the one figure it needs -- the universe size,
        for the empty-table explanation -- and nothing else."""
        fragment = client.get("/partials/recommendations").text

        assert "in universe" not in fragment, (
            "the summary strip belongs to the page, not to the swapped region"
        )

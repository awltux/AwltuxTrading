"""Reading an instrument's news, and paging it.

Written after a bug that paging alone would not have fixed. Three callers asked
"what news does this instrument have?" by taking the newest N rows *across the whole
universe* and filtering them by ticker in Python — so the limit was applied before
the filter and the window was global.

Measured on the live database, which held 6,555 items at the time:

* the instrument page showed **nothing for 131 of the 153** instruments that had news;
* the decision engine fetched the newest 400 of 1,470 in-window items and saw **no
  news at all for 47 of 135 tickers** — which is not a display bug, it silently moved
  `news_materiality` and the sentiment answer toward "no news here".

Both degrade in the direction opposite to the obvious one: the more news is
ingested, the smaller each instrument's share of a fixed global window, so the
per-instrument view empties rather than grows.

The regression tests below are shaped around that: they put an instrument's news
*outside* the most recent rows and assert it is still found.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.db import NewsItem, utcnow
from awltux.db.news import appraisals_for, news_for_ticker
from tests.helpers import make_instrument


def make(session, title: str, *, tickers, hours_ago: float = 1.0, materiality="material"):
    row = NewsItem(
        source="test",
        url=f"https://example.com/{title.replace(' ', '-')}",
        url_hash=title,
        title=title,
        summary="",
        published_at=utcnow() - dt.timedelta(hours=hours_ago),
        tickers=list(tickers),
        materiality=materiality,
        direction="neutral",
        relevance=0.5,
    )
    session.add(row)
    session.flush()
    return row


class TestTheFilterIsNotAGlobalWindow:
    def test_an_instruments_news_is_found_beyond_the_newest_rows(self, session):
        """The bug, stated as a test.

        An instrument whose news is all older than the newest 40 rows globally used
        to show an empty list, because the query took the global newest 40 and then
        looked for the ticker among them.
        """
        for index in range(60):
            make(session, f"filler {index}", tickers=["BUSY_US_EQ"], hours_ago=index + 1)
        make(session, "Acme wins contract", tickers=["ACME_US_EQ"], hours_ago=100)

        rows, total = news_for_ticker(session, "ACME_US_EQ")

        assert total == 1
        assert [row.title for row in rows] == ["Acme wins contract"]

    def test_an_instrument_with_no_news_returns_nothing(self, session):
        """A genuinely empty instrument must stay distinguishable from a broken one."""
        make(session, "Someone else's story", tickers=["OTHER_US_EQ"])

        rows, total = news_for_ticker(session, "ACME_US_EQ")

        assert rows == []
        assert total == 0

    def test_a_story_naming_several_instruments_is_returned_for_each(self, session):
        make(session, "Sector-wide warning", tickers=["ACME_US_EQ", "OTHER_US_EQ"])

        for ticker in ("ACME_US_EQ", "OTHER_US_EQ"):
            _, total = news_for_ticker(session, ticker)
            assert total == 1, ticker


class TestPaging:
    @pytest.fixture
    def fifty(self, session):
        for index in range(50):
            make(session, f"story {index:02d}", tickers=["ACME_US_EQ"], hours_ago=index + 1)
        return session

    def test_pages_do_not_overlap_and_do_not_skip(self, fifty):
        """Offset is only safe once the row set is defined in SQL.

        Offsetting the old query would have paged through a different slice each
        time, because the filter happened after the limit.
        """
        first, total = news_for_ticker(fifty, "ACME_US_EQ", limit=20, offset=0)
        second, _ = news_for_ticker(fifty, "ACME_US_EQ", limit=20, offset=20)
        third, _ = news_for_ticker(fifty, "ACME_US_EQ", limit=20, offset=40)

        ids = [row.id for row in first + second + third]
        assert len(ids) == 50 == total
        assert len(set(ids)) == 50, "a story appeared on two pages"
        assert [row.title for row in first][0] == "story 00"

    def test_the_total_is_the_whole_set_not_the_page(self, fifty):
        """A pager that counts only what it shows cannot say how many pages exist."""
        rows, total = news_for_ticker(fifty, "ACME_US_EQ", limit=5)

        assert len(rows) == 5
        assert total == 50

    def test_the_total_counts_only_this_instrument(self, session):
        for index in range(10):
            make(session, f"acme {index}", tickers=["ACME_US_EQ"], hours_ago=index + 1)
        for index in range(30):
            make(session, f"other {index}", tickers=["OTHER_US_EQ"], hours_ago=index + 1)

        _, total = news_for_ticker(session, "ACME_US_EQ")

        assert total == 10

    def test_an_offset_past_the_end_is_empty_rather_than_wrong(self, fifty):
        """Which is what a stale `?news_page=9` link produces."""
        rows, total = news_for_ticker(fifty, "ACME_US_EQ", limit=20, offset=400)

        assert rows == []
        assert total == 50


class TestTheOtherFilters:
    def test_the_window_excludes_older_stories(self, session):
        make(session, "recent", tickers=["ACME_US_EQ"], hours_ago=2)
        make(session, "old", tickers=["ACME_US_EQ"], hours_ago=24 * 30)

        rows, total = news_for_ticker(
            session, "ACME_US_EQ", since=utcnow() - dt.timedelta(days=14)
        )

        assert total == 1
        assert rows[0].title == "recent"

    def test_materiality_narrows_the_total_as_well_as_the_page(self, session):
        make(session, "material one", tickers=["ACME_US_EQ"], materiality="material")
        make(session, "noise", tickers=["ACME_US_EQ"], materiality="noise")

        rows, total = news_for_ticker(session, "ACME_US_EQ", materiality="material")

        assert total == 1
        assert rows[0].title == "material one"

    def test_appraisals_are_fetched_for_the_page_only(self, session):
        """Loading appraisals for a thousand stories to show twenty-five is the
        kind of cost that only shows up once the table is large."""
        from tests.test_news_analysis import make_item

        kept = [make_item(session, f"paged {i}", url=f"https://a.com/{i}") for i in range(3)]
        for index in range(30):
            make_item(session, f"unrelated {index}", url=f"https://b.com/{index}",
                      tickers=["OTHER_US_EQ"])

        rows, _ = news_for_ticker(session, "ACME_US_EQ", limit=10)

        assert {row.id for row in rows} == {row.id for row in kept}
        assert appraisals_for(session, rows) == {}


class TestThePageItself:
    def test_the_instrument_page_pages_its_news(self, client, session, universe_instrument):
        """Through the real request, because the bug was in the wiring as much as the
        query: the route has to pass the page through to the query."""
        for index in range(30):
            make(session, f"story {index:02d}", tickers=["TEST_US_EQ"], hours_ago=index + 1)
        session.commit()

        first = client.get("/instrument/TEST_US_EQ")
        second = client.get("/instrument/TEST_US_EQ?news_page=2")

        assert first.status_code == second.status_code == 200
        assert "story 00" in first.text
        assert "story 00" not in second.text, "page two repeated page one"
        assert "page 2 of" in second.text

    def test_a_page_beyond_the_end_says_so_rather_than_500ing(self, client, session):
        session.add(make_instrument("TEST_US_EQ", name="Test Industries", sector="Industrials"))
        session.commit()

        response = client.get("/instrument/TEST_US_EQ?news_page=99")

        assert response.status_code == 200
        assert "No headlines naming this instrument" in response.text

    def test_the_heading_reports_the_total_not_the_page(self, client, session):
        session.add(make_instrument("TEST_US_EQ", name="Test Industries", sector="Industrials"))
        for index in range(30):
            make(session, f"story {index:02d}", tickers=["TEST_US_EQ"], hours_ago=index + 1)
        session.commit()

        body = client.get("/instrument/TEST_US_EQ").text

        assert "30 stories" in body

    def test_a_headline_links_to_the_story_page_not_the_publisher(self, client, session):
        """The headline is the doorway to the appraisal, not to the article.

        This list linked `item.url` with `target="_blank"`, so every headline left the
        app -- past the appraisal, the carrier count, the claims and the omissions, which
        are the reason the list exists. The sector page has always linked `/news/{id}`;
        the instrument page now does too. Asked for directly: "It should link the app's
        summary of the article."
        """
        session.add(make_instrument("TEST_US_EQ", name="Test Industries", sector="Industrials"))
        row = make(session, "a story worth appraising", tickers=["TEST_US_EQ"])
        session.commit()

        body = client.get("/instrument/TEST_US_EQ").text

        assert f'href="/news/{row.id}"' in body, "the headline links to this app's page"
        assert f'href="{row.url}"' not in body, "and no longer to the publisher"
        # The link is followed rather than assumed: a heading pointing at a 404 would
        # satisfy the assertion above and be worse than the external link it replaced.
        assert client.get(f"/news/{row.id}").status_code == 200

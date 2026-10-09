"""The compact pager above a table: two arrows, top right, on every paged table.

Asked for directly: *"put pager buttons at the top right of all paged tables — but no
explanatory text, just previous and next buttons."* The sentence stays on the full pager
under the table, where it belongs; the top one exists so a reader who is halfway down a
558-page list can see whether there is a next page without scrolling to find out.

Two properties are worth more than the rest, and both are asserted for every surface
rather than once:

* **It says nothing.** "Page 2 of 9 (1,204 stories)" repeated above the table is a line
  the reader is about to read anyway, and the request was explicit. The test strips the
  markup out of the nav and fails on any letter or digit in what is left, so a future
  edit that adds a caption is caught rather than tolerated.
* **Every paged table has one, and the unpaged ones do not.** Four of the five pagers
  predate this change and are wired differently -- a FilterSet here, a hand-built
  querystring there, `?news_page=` on an instrument -- which is exactly why each is
  checked rather than one being taken as representative.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from awltux.db import DecisionRun, IngestRun, utcnow

#: Matches the whole `<nav class="pager top">…</nav>`, so what it contains can be
#: inspected on its own. Non-greedy because a page holds a second `.pager` below.
TOP_NAV = re.compile(r'<nav class="pager top".*?</nav>', re.S)


def _top_nav(body: str) -> str:
    found = TOP_NAV.search(body)
    assert found, "no compact pager above the table"
    return found.group(0)


def _words(nav: str) -> str:
    """The nav's text with its markup and arrows removed."""
    text = re.sub(r"<[^>]+>", " ", nav)
    return text.replace("←", " ").replace("→", " ").replace("&larr;", " ").replace(
        "&rarr;", " "
    ).strip()


def _runs(session, count: int) -> None:
    base = utcnow() - dt.timedelta(days=2)
    for index in range(count):
        started = base + dt.timedelta(minutes=index)
        session.add(
            IngestRun(
                job="news_rss",
                started_at=started,
                finished_at=started + dt.timedelta(seconds=30),
                ok=True,
                items_seen=1,
                items_written=1,
                detail={},
            )
        )
    session.flush()


def _decisions(session, count: int) -> None:
    from tests.helpers import make_instrument

    for index in range(count):
        ticker = f"PAGE{index:02d}_US_EQ"
        session.add(make_instrument(ticker, name=f"Page {index}"))
    # Flushed before the decisions, because the ticker column is a foreign key and the
    # two tables declare no ORM relationship for the unit of work to order by.
    session.flush()

    for index in range(count):
        session.add(
            DecisionRun(
                instrument_t212_ticker=f"PAGE{index:02d}_US_EQ",
                state_sha256="x" * 8,
                engine="deepseek",
                long_term_action="buy",
                short_term_action="hold",
                confidence=0.7,
                created_at=utcnow() - dt.timedelta(hours=index + 1),
            )
        )
    session.flush()


def _news(session, count: int) -> None:
    from awltux.db import NewsItem

    base = utcnow()
    for index in range(count):
        session.add(
            NewsItem(
                source="test",
                url=f"https://example.com/{index}",
                url_hash=f"pager-{index}",
                title=f"paged story {index:02d}",
                summary="",
                published_at=base - dt.timedelta(hours=index + 1),
                tickers=[],
                sectors=[],
                materiality="mild",
                direction="positive",
                relevant=True,
            )
        )
    session.flush()


def _instruments(session, count: int) -> None:
    from tests.helpers import make_instrument

    for index in range(count):
        session.add(make_instrument(f"PAGE{index:02d}_US_EQ", name=f"Page {index}"))
    session.flush()


class TestEveryPagedTableHasOne:
    def test_the_dashboard_has_one(self, client, session):
        _instruments(session, 15)
        session.commit()

        nav = _top_nav(client.get("/dashboard?per_page=10").text)

        assert 'rel="next"' in nav
        assert 'href="/dashboard?page=2&amp;per_page=10"' in nav

    def test_a_sector_drilldown_has_one_and_it_points_at_the_sector(self, client, session):
        """The sector page fixes its page size at 50, so this needs more than that."""
        from tests.helpers import make_instrument

        for index in range(55):
            session.add(
                make_instrument(
                    f"SECT{index:02d}_US_EQ",
                    name=f"Sector {index}",
                    sector_group="Industrials",
                )
            )
        session.commit()

        nav = _top_nav(client.get("/sectors/Industrials").text)

        assert 'rel="next"' in nav
        assert "/sectors/Industrials" in nav, "a sort or page click must stay in the sector"

    def test_the_news_table_has_one(self, client, session):
        _news(session, 60)
        session.commit()

        nav = _top_nav(client.get("/news?per_page=20").text)

        assert 'rel="next"' in nav
        assert 'href="/news?page=2&amp;per_page=20"' in nav

    def test_the_prediction_ledger_has_one(self, client, session):
        _decisions(session, 30)
        session.commit()

        nav = _top_nav(client.get("/decisions?per_page=10").text)

        assert 'rel="next"' in nav
        assert "page=2" in nav

    def test_the_run_history_has_one(self, client, session):
        _runs(session, 30)
        session.commit()

        nav = _top_nav(client.get("/jobs?run_per_page=10").text)

        assert 'rel="next"' in nav
        assert "run_page=2" in nav

    def test_an_instruments_news_list_has_one(self, client, session):
        from tests.helpers import make_instrument

        session.add(make_instrument("TEST_US_EQ", name="Test Industries"))
        _news(session, 60)
        session.commit()
        # The fixture's stories name no instrument, so tag them all -- the instrument
        # page pages at 25, and a list that fits on one page has no pager to check.
        from sqlalchemy import select

        from awltux.db import NewsItem

        for row in session.execute(select(NewsItem)).scalars().all():
            row.tickers = ["TEST_US_EQ"]
        session.commit()

        nav = _top_nav(client.get("/instrument/TEST_US_EQ").text)

        assert 'rel="next"' in nav
        assert "news_page=2" in nav


class TestItSaysNothing:
    @pytest.mark.parametrize(
        "url, seed",
        [
            ("/dashboard?per_page=10", "instruments"),
            ("/news?per_page=20", "news"),
            ("/decisions?per_page=10", "decisions"),
            ("/jobs?run_per_page=10", "runs"),
        ],
    )
    def test_the_compact_pager_carries_no_words(self, client, session, url, seed):
        """The whole request: previous and next, and nothing else.

        The arrows are entities (`&larr;`), so the check is on what a reader would read:
        strip the tags and the arrow characters and nothing may be left.
        """
        if seed == "instruments":
            _instruments(session, 15)
        elif seed == "news":
            _news(session, 40)
        elif seed == "decisions":
            _decisions(session, 30)
        else:
            _runs(session, 30)
        session.commit()

        nav = _top_nav(client.get(url).text)

        assert _words(nav) == "", f"the compact pager says {_words(nav)!r}"
        assert "Page " not in nav and "page " not in nav


class TestTheEndsAreInert:
    def test_the_first_page_has_no_previous_link(self, client, session):
        _news(session, 40)
        session.commit()

        nav = _top_nav(client.get("/news?per_page=20").text)

        assert 'rel="prev"' not in nav
        assert '<span class="off"' in nav, "the arrow is drawn but is not a link"

    def test_the_last_page_has_no_next_link(self, client, session):
        _news(session, 40)
        session.commit()

        nav = _top_nav(client.get("/news?per_page=20&page=2").text)

        assert 'rel="next"' not in nav
        assert 'rel="prev"' in nav

    def test_a_single_page_table_has_no_compact_pager_at_all(self, client, session):
        """Two dead arrows over one page of results is noise, not an affordance."""
        _news(session, 5)
        session.commit()

        assert not TOP_NAV.search(client.get("/news").text)
        assert not TOP_NAV.search(client.get("/dashboard").text)

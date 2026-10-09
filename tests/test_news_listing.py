"""The news corpus page: sorting, paging and filtering the whole stored table.

The flash ticker is curated twice over -- floored by ``news.ticker_min_materiality`` and
collapsed to one entry per event -- so most of what has been ingested is unreachable from
it. Measured 2026-10-09 on the live database: **27,884 stored stories**, of which 13,976
are classified ``none`` and can never clear a floor that starts at ``mild``, and 16,142
are assessed as *not* relevant and appear nowhere else in the UI at all.

The tests below are shaped around the two ways this page can be quietly wrong:

* **The total is the whole matching set, not the page.** A pager that counts only what it
  shows cannot say how many pages exist, and a total computed without the filters
  disagrees with the rows beside it.
* **Offset paging is only correct over a total order.** ``published_at`` is not unique --
  Google News alone contributes 26,580 of those rows, delivered in batches that share a
  timestamp -- so an ordering without a unique tie-break can repeat one story on two pages
  while another never appears. That failure is silent, which is why the ordering's shape
  is asserted directly rather than inferred from a page's contents.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from awltux.analysis.relevance import priority
from awltux.db import NewsAnalysis, NewsItem, utcnow
from awltux.db.news import appraisals_for
from awltux.web import filters, queries


def make(
    session,
    title: str,
    *,
    tickers=(),
    sectors=(),
    hours_ago: float = 1.0,
    materiality: str | None = "material",
    direction: str | None = "positive",
    relevant: bool | None = True,
    source: str = "test",
    publisher: str | None = None,
    published_at: dt.datetime | None = None,
):
    row = NewsItem(
        source=source,
        url=f"https://example.com/{title.replace(' ', '-')}",
        url_hash=title,
        title=title,
        publisher=publisher if publisher is not None else f"{source} desk",
        summary="",
        published_at=(
            published_at if published_at is not None
            else utcnow() - dt.timedelta(hours=hours_ago)
        ),
        tickers=list(tickers),
        sectors=list(sectors),
        materiality=materiality,
        direction=direction,
        relevance=0.5,
        relevant=relevant,
    )
    session.add(row)
    session.flush()
    return row


class TestTheQueryCountsTheWholeSet:
    def test_the_total_is_the_matching_set_and_not_the_page(self, session):
        """A pager that counts only what it shows cannot say how many pages exist."""
        for index in range(50):
            make(session, f"story {index:02d}", hours_ago=index + 1)

        rows, total = queries.news_listing(session, limit=20)

        assert len(rows) == 20
        assert total == 50

    def test_pages_do_not_overlap_and_do_not_skip(self, session):
        for index in range(50):
            make(session, f"story {index:02d}", hours_ago=index + 1)

        first, total = queries.news_listing(session, limit=20, offset=0)
        second, _ = queries.news_listing(session, limit=20, offset=20)
        third, _ = queries.news_listing(session, limit=20, offset=40)

        ids = [row.id for row in first + second + third]
        assert len(ids) == 50 == total
        assert len(set(ids)) == 50, "a story appeared on two pages"
        assert first[0].title == "story 00"

    def test_an_offset_past_the_end_is_empty_rather_than_wrong(self, session):
        """Which is what a stale `?page=9` link produces."""
        make(session, "the only story")

        rows, total = queries.news_listing(session, limit=20, offset=400)

        assert rows == []
        assert total == 1

    def test_the_total_applies_the_filters(self, session):
        """`?source=yahoo_rss&page=2` has to count the yahoo rows, not every row."""
        for index in range(3):
            make(session, f"google {index}", source="google_news")
        for index in range(7):
            make(session, f"yahoo {index}", source="yahoo_rss")

        rows, total = queries.news_listing(session, source="yahoo_rss", limit=2)

        assert len(rows) == 2
        assert total == 7


class TestTheOrderingHasAUniqueTieBreak:
    """`published_at` is not unique, and offset paging over a partial order is wrong.

    Asserted on the compiled ordering rather than on a page's contents: SQLite happens to
    return tied rows in insertion order, so a test that paged through them would pass with
    or without the tie-break and prove nothing. The property that matters is that every
    ordering ends in a unique column, and that is what is checked here.
    """

    @pytest.mark.parametrize("direction", ["asc", "desc"])
    @pytest.mark.parametrize(
        "sort",
        ["priority", "published_at", "materiality", "publisher", "title", "relevance"],
    )
    def test_every_sort_ends_in_the_id_in_the_same_direction(self, sort, direction):
        sql = str(
            select(NewsItem).order_by(*queries._news_order(sort, direction)).compile()
        )

        assert "ORDER BY" in sql
        assert f"news_item.id {direction.upper()}" in sql, sql
        # The id must be the *last* key: anything after it would be the real tie-break
        # and the id would be doing nothing.
        assert sql.rstrip().endswith(f"news_item.id {direction.upper()}"), sql

    def test_a_tied_timestamp_still_pages_cleanly(self, session):
        """The live shape of the risk: one feed's batch, one timestamp, 60 rows."""
        stamp = utcnow() - dt.timedelta(hours=3)
        for index in range(60):
            make(session, f"batch {index:02d}", published_at=stamp)

        seen: list[int] = []
        for offset in range(0, 60, 20):
            rows, total = queries.news_listing(session, limit=20, offset=offset)
            seen.extend(row.id for row in rows)

        assert total == 60
        assert len(seen) == 60
        assert len(set(seen)) == 60, "a tied row was served on two pages"


class TestTheGroupingIsNewestFirst:
    """Sorting a column must not put the oldest story in a group at the top.

    Found on the deployed page rather than in a test: `?sort=materiality&direction=desc`
    returned a critical story dated **2026-05-05** as its first row, above stories from
    October, because the tie-break ran on the row id and a backfilled story gets a high
    one. The ordering answered "which is most severe" and then interleaved the answer by
    arrival, which reads as a broken sort.
    """

    def test_within_one_materiality_the_newest_story_comes_first(self, session):
        make(session, "an old critical", materiality="critical", hours_ago=24 * 120)
        make(session, "a recent critical", materiality="critical", hours_ago=2)
        make(session, "an ordinary story", materiality="mild", hours_ago=1)

        rows, _ = queries.news_listing(session, sort="materiality", direction="desc")

        assert [row.title for row in rows] == [
            "a recent critical",
            "an old critical",
            "an ordinary story",
        ]

    def test_an_old_backfilled_story_does_not_lead_its_group(self, session):
        """The exact live shape: the *older* story is the one with the higher id."""
        recent = make(session, "recent", materiality="critical", hours_ago=2)
        old = make(session, "old", materiality="critical", hours_ago=24 * 150)
        assert old.id > recent.id, "the fixture must reproduce the live ordering of ids"

        rows, _ = queries.news_listing(session, sort="materiality", direction="desc")

        assert [row.title for row in rows] == ["recent", "old"]

    def test_the_freshest_group_member_leads_however_the_primary_ran(self, session):
        """Ascending materiality runs the other way, and the groups still lead fresh."""
        make(session, "an old mild", materiality="mild", hours_ago=24 * 90)
        make(session, "a recent mild", materiality="mild", hours_ago=3)
        make(session, "a critical one", materiality="critical", hours_ago=1)

        rows, _ = queries.news_listing(session, sort="materiality", direction="asc")

        assert [row.title for row in rows] == [
            "a recent mild",
            "an old mild",
            "a critical one",
        ], "mild is the milder level, so ascending puts it first"


class TestThePriorityOrdering:
    """Sorting by priority, and the two implementations of it that must agree.

    ``web/queries.py`` computes ``materiality x credibility x recency`` in SQL because
    there is no other way to order 27,895 rows by it -- measured 2026-10-09, hydrating
    them takes 2.0s on its own -- and ``analysis.relevance.priority`` computes the same
    formula in Python for the number the column prints. Two implementations of one rule
    is precisely the shape of bug this codebase keeps recording, so they are compared
    here on data built to separate them. The tests also pin the portability decision: the
    decay is a registered Python function rather than SQLite's ``exp``, which the
    interpreter running this suite does not have.
    """

    @staticmethod
    def _appraise(session, item, subject_type, subject_id, credibility):
        session.add(
            NewsAnalysis(
                news_item_id=item.id,
                subject_type=subject_type,
                subject_id=subject_id,
                credibility=credibility,
            )
        )
        session.flush()

    def test_the_sql_ranking_is_the_python_ranking(self, session):
        """The order the table is sorted by is the score it prints beside each row."""
        for index, (materiality, credibility, hours) in enumerate(
            [
                ("critical", 0.9, 1.0),
                ("critical", 0.05, 1.0),
                ("material", 0.9, 4.0),
                ("moderate", 0.5, 20.0),
                ("none", 1.0, 0.5),
                ("critical", 0.9, 200.0),
                ("mild", 0.2, 60.0),
            ]
        ):
            item = make(
                session,
                f"story {index}",
                tickers=["ACME_US_EQ"],
                materiality=materiality,
                hours_ago=hours,
            )
            self._appraise(session, item, "instrument", "ACME_US_EQ", credibility)
        session.flush()

        rows, _ = queries.news_listing(session, sort="priority", direction="desc")

        # The Python side of the same rule, using the appraisal the table shows: the
        # primary subject's, which is what `_serialise` reads too.
        appraisals = appraisals_for(session, list(rows))
        expected = sorted(
            rows,
            key=lambda row: (
                priority(
                    materiality=row.materiality,
                    credibility=(
                        appraisals[row.id].credibility if row.id in appraisals else None
                    ),
                    published_at=row.published_at,
                )[0],
                row.id,
            ),
            reverse=True,
        )

        assert [row.id for row in rows] == [row.id for row in expected]

    def test_the_ranking_actually_separates_the_stories(self, session):
        """A guard on the test above: if every score were equal it would pass vacuously."""
        for index, (materiality, credibility, hours) in enumerate(
            [("critical", 0.9, 1.0), ("none", 0.05, 200.0), ("mild", 0.5, 30.0)]
        ):
            item = make(
                session,
                f"story {index}",
                tickers=["ACME_US_EQ"],
                materiality=materiality,
                hours_ago=hours,
            )
            self._appraise(session, item, "instrument", "ACME_US_EQ", credibility)

        rows, _ = queries.news_listing(session, sort="priority", direction="desc")
        appraisals = appraisals_for(session, list(rows))
        scores = [
            priority(
                materiality=row.materiality,
                credibility=appraisals[row.id].credibility,
                published_at=row.published_at,
            )[0]
            for row in rows
        ]

        assert len(set(scores)) == len(scores), "the fixture cannot detect a wrong order"
        assert rows[0].materiality == "critical", "the fresh critical should lead"

    def test_an_instrument_appraisal_outranks_the_sector_one(self, session):
        """``primary_subject`` is instruments-first, and the SQL ordering must match.

        A story naming both a sector and a company has two appraisals, and the table
        shows the company's. If the ordering picked the sector's instead, the rank beside
        a row would not be the number the row's own appraisal produced.
        """
        both = make(session, "company and sector", tickers=["AAA_US_EQ"], sectors=["Energy"])
        self._appraise(session, both, "sector", "Energy", 0.05)
        self._appraise(session, both, "instrument", "AAA_US_EQ", 0.95)

        plain = make(session, "company only", tickers=["BBB_US_EQ"])
        self._appraise(session, plain, "instrument", "BBB_US_EQ", 0.5)

        rows, _ = queries.news_listing(session, sort="priority", direction="desc")

        assert [row.title for row in rows] == ["company and sector", "company only"]

    def test_the_first_instrument_alphabetically_is_the_primary_one(self, session):
        """The other half of the rule: instruments are then taken in id order."""
        two = make(session, "two tickers", tickers=["AAA_US_EQ", "ZZZ_US_EQ"])
        self._appraise(session, two, "instrument", "ZZZ_US_EQ", 0.95)
        self._appraise(session, two, "instrument", "AAA_US_EQ", 0.05)

        plain = make(session, "one ticker", tickers=["MMM_US_EQ"])
        self._appraise(session, plain, "instrument", "MMM_US_EQ", 0.5)

        rows, _ = queries.news_listing(session, sort="priority", direction="desc")

        assert [row.title for row in rows] == ["one ticker", "two tickers"]

    def test_an_appraised_story_outranks_an_unappraised_twin(self, session):
        """No appraisal is not "zero credibility": it is the mid default weight.

        ``priority`` uses ``UNASSESSED_WEIGHT`` where nothing has judged the source, so a
        story with no appraisal can still outrank one whose source was assessed as weak.
        Getting this backwards would bury every story the scepticism pass has not reached.
        """
        judged = make(session, "assessed weak", tickers=["AAA_US_EQ"])
        self._appraise(session, judged, "instrument", "AAA_US_EQ", 0.02)
        make(session, "not assessed", tickers=["BBB_US_EQ"])

        rows, _ = queries.news_listing(session, sort="priority", direction="desc")

        assert [row.title for row in rows] == ["not assessed", "assessed weak"]

    def test_a_story_with_no_appraisal_is_not_dropped(self, session):
        """An outer join that failed would silently lose rows rather than rank them low."""
        make(session, "no appraisal at all", tickers=["AAA_US_EQ"])
        appraised = make(session, "appraised", tickers=["BBB_US_EQ"])
        self._appraise(session, appraised, "instrument", "BBB_US_EQ", 0.5)

        rows, total = queries.news_listing(session, sort="priority")

        assert total == 2
        assert len(rows) == 2

    def test_priority_is_sorted_through_the_url(self, client, session):
        old_but_severe = make(
            session, "an old critical", materiality="critical", hours_ago=24 * 90
        )
        fresh = make(session, "a fresh mild", materiality="mild", hours_ago=1)
        session.commit()

        body = client.get("/news?sort=priority&direction=desc").text

        assert body.index("a fresh mild") < body.index("an old critical"), (
            "the three-day half-life should sink a month-old story below this morning's"
        )
        assert old_but_severe.id != fresh.id

    def test_the_priority_header_is_a_sort_link(self, client, session):
        make(session, "a story", materiality="critical")
        session.commit()

        body = client.get("/news").text

        assert 'href="/news?sort=priority"' in body


class TestTheFilters:
    def test_the_window_excludes_older_stories(self, session):
        make(session, "recent", hours_ago=2)
        make(session, "old", hours_ago=24 * 30)

        rows, total = queries.news_listing(
            session, since=utcnow() - dt.timedelta(days=14)
        )

        assert total == 1
        assert rows[0].title == "recent"

    def test_materiality_narrows_the_total_as_well_as_the_page(self, session):
        make(session, "a warning", materiality="critical")
        make(session, "noise", materiality="none")

        rows, total = queries.news_listing(session, materiality="critical")

        assert total == 1
        assert rows[0].title == "a warning"

    def test_an_unassessed_story_is_a_third_state_and_not_a_no(self, session):
        """``relevant IS NULL`` is "nothing has judged this", not "judged irrelevant".

        The model keeps the two apart on purpose, and a filter that collapsed them would
        make the unjudged population invisible -- which is the population that says how
        far the classifier has got.
        """
        make(session, "yes", relevant=True)
        make(session, "no", relevant=False)
        make(session, "unjudged", relevant=None)

        judged_no, _ = queries.news_listing(session, relevant=False)
        unjudged, total = queries.news_listing(session, unassessed=True)

        assert [row.title for row in judged_no] == ["no"]
        assert [row.title for row in unjudged] == ["unjudged"]
        assert total == 1

    def test_the_instrument_filter_uses_the_judged_tickers_not_the_headline(self, session):
        """A ticker on the row is a judgement, not a string match on the title.

        The feeds tag a story with what it was fetched for, and the classifier then
        decides whether it is *about* that company. The listing matches the row's own
        tickers, so a story that merely names ACME in its headline and was never tagged
        with it is not returned -- which is the difference between "concerns" and
        "mentions".
        """
        make(session, "Acme wins a contract", tickers=["ACME_US_EQ"])
        make(session, "Someone else entirely", tickers=["OTHER_US_EQ"])
        make(session, "ACME is mentioned in passing")  # no ticker at all

        rows, total = queries.news_listing(session, ticker="ACME_US_EQ")

        assert total == 1
        assert rows[0].title == "Acme wins a contract"

    def test_search_matches_the_headline_or_the_source(self, session):
        make(session, "Golar LNG gains", source="google_news")
        make(session, "Something else", source="yahoo_rss")

        by_title, _ = queries.news_listing(session, search="golar")
        by_source, _ = queries.news_listing(session, search="yahoo")

        assert [row.title for row in by_title] == ["Golar LNG gains"]
        assert [row.title for row in by_source] == ["Something else"]


class TestTheSeverityOrdering:
    def test_critical_sorts_above_none_when_descending(self, session):
        """The point of the column: sorting the table to find the profit warnings.

        Alphabetical order would put ``critical`` first by accident and ``material``
        above ``mild`` -- but ``none`` before ``moderate``, which is the failure. The
        order is the severity ladder, derived from the analysis layer's own list.
        """
        for level in ("none", "mild", "moderate", "material", "critical"):
            make(session, f"a {level} story", materiality=level)

        rows, _ = queries.news_listing(session, sort="materiality", direction="desc")

        assert [row.materiality for row in rows] == [
            "critical",
            "material",
            "moderate",
            "mild",
            "none",
        ]

    def test_an_unassessed_story_sorts_below_none(self, session):
        """"Nothing has judged this" is less usable than "judged unimportant"."""
        make(session, "judged", materiality="none")
        make(session, "unjudged", materiality=None)

        rows, _ = queries.news_listing(session, sort="materiality", direction="desc")

        assert [row.materiality for row in rows] == ["none", None]


class TestTheFilterDeclarations:
    """The URL vocabulary, tested with no database at all."""

    def test_every_sort_the_table_offers_is_one_the_query_understands(self):
        """One fact, two consumers. A column header linking to a sort the query does not
        know would silently render an unsorted table rather than failing."""
        from typing import get_args

        assert {option.value for option in filters.NEWS_SORT_OPTIONS} == set(
            get_args(queries.NewsSortKey)
        )

    def test_every_window_choice_has_an_age(self):
        """A control entry with no translation would filter by nothing while appearing
        to filter -- the table would look narrowed and not be."""
        assert {option.value for option in filters.NEWS_WINDOW_OPTIONS} == set(
            filters.NEWS_WINDOW_AGES
        )
        for option in filters.NEWS_WINDOW_OPTIONS:
            assert filters.news_window(option.value) is not None

    def test_an_unknown_window_is_no_window_rather_than_a_guess(self):
        assert filters.news_window("banana") is None

    def test_materiality_options_are_most_severe_first_without_the_null(self):
        rows = [("none", 13_976), ("critical", 242), ("mild", 8_614), (None, 57)]

        options = filters.materiality_options(rows)

        assert [option.value for option in options] == [
            "critical",
            "mild",
            "none",
        ], "severity order, not popularity or alphabet"
        assert next(o.note for o in options if o.value == "critical") == "242"
        assert None not in {option.value for option in options}, (
            "the unassessed state is asked about by the relevance control"
        )

    def test_source_options_are_busiest_first(self):
        options = filters.source_options(
            [("finnhub", 1), ("google_news", 26_580), ("edgar", 13)]
        )

        assert [option.value for option in options] == ["google_news", "edgar", "finnhub"]

    def test_an_unknown_filter_value_is_recorded_rather_than_applied(self):
        """The module's whole premise: a URL that asked for something impossible must
        say so, not show a different table quietly."""
        spec = filters.FilterSet.parse(
            filters.news_specs(sources=(filters.FilterOption("edgar", "edgar"),)),
            {"source": "nope", "window": "7d"},
        )

        assert [bad.name for bad in spec.ignored] == ["source"]
        assert spec.opt("source") is None
        assert spec.value("window") == "7d"


class TestThePageItself:
    def test_the_page_lists_stories_newest_first(self, client, session):
        make(session, "the older story", hours_ago=5)
        make(session, "the newer story", hours_ago=1)
        session.commit()

        body = client.get("/news").text

        assert "the newer story" in body
        assert body.index("the newer story") < body.index("the older story")

    def test_the_page_shows_what_the_ticker_cannot(self, client, session):
        """The reason the page exists: the curated set is a small slice of the corpus.

        A story classified ``none`` can never clear the ticker's materiality floor, and a
        story assessed as not relevant is excluded from it by `_visible_to_the_banner`.
        Both belong here.
        """
        make(session, "an unimportant story", materiality="none")
        make(session, "a story about nothing", relevant=False, materiality="mild")
        session.commit()

        body = client.get("/news").text

        assert "an unimportant story" in body
        assert "a story about nothing" in body

    def test_paging_does_not_repeat_page_one(self, client, session):
        for index in range(60):
            make(session, f"story {index:02d}", hours_ago=index + 1)
        session.commit()

        first = client.get("/news?per_page=20")
        second = client.get("/news?per_page=20&page=2")

        assert first.status_code == second.status_code == 200
        assert "story 00" in first.text
        assert "story 00" not in second.text, "page two repeated page one"
        assert "Page 2 of 3" in second.text

    def test_a_page_past_the_end_says_so_rather_than_500ing(self, client, session):
        make(session, "the only story")
        session.commit()

        body = client.get("/news?page=99").text

        assert "past" in body and "1 page" in body
        assert "the only story" not in body

    def test_a_nonsensical_page_is_refused_rather_than_served(self, client):
        """`page` is one of the two parameters a reader never types, so a bad value is a
        bug worth refusing rather than a stale bookmark to tolerate."""
        assert client.get("/news?page=0").status_code == 422
        assert client.get("/news?per_page=5000").status_code == 422

    def test_a_bad_sort_is_reported_and_the_table_still_renders(self, client, session):
        make(session, "a story worth listing")
        session.commit()

        body = client.get("/news?sort=banana").text
        # Collapsed, because template prose wraps and the sentence spans lines. Comparing
        # the raw HTML would assert the indentation of the markup as well as the message.
        text = " ".join(body.split())

        assert "Ignored 1 filter value" in text
        assert "<code>sort=banana</code>" in body
        assert "a story worth listing" in body, "the unfiltered table is shown, not nothing"

    def test_a_bad_source_is_reported(self, client, session):
        make(session, "a story worth listing", source="edgar")
        session.commit()

        body = client.get("/news?source=nope").text

        assert "Ignored 1 filter value" in " ".join(body.split())
        assert "a story worth listing" in body

    def test_a_sort_link_carries_the_filters_the_reader_set(self, client, session):
        """The failure `filters.py` exists to prevent: a filter applied but not carried
        silently drops the moment the reader clicks a column header.

        The active column's link drops `sort=published_at` because it is the default --
        carrying it would be five defaults in every URL -- so the filter and the flipped
        direction are what a reader can see arrived.
        """
        make(session, "a critical story", materiality="critical")
        session.commit()

        body = client.get("/news?materiality=critical").text

        assert 'href="/news?materiality=critical&amp;direction=asc"' in body, (
            "the header of the current sort keeps the filter and flips the direction"
        )
        assert 'href="/news?materiality=critical&amp;sort=title"' in body, (
            "every other header keeps the filter too"
        )

    def test_sorting_by_materiality_through_the_url_works(self, client, session):
        make(session, "a mild story", materiality="mild")
        make(session, "a critical story", materiality="critical")
        session.commit()

        body = client.get("/news?sort=materiality&direction=desc").text

        assert body.index("a critical story") < body.index("a mild story")

    def test_the_headline_links_to_the_story_page_not_the_publisher(self, client, session):
        """The same rule the instrument and sector lists follow: the article is the
        *input* to an assessment, and the assessment is here."""
        row = make(session, "a story worth appraising")
        session.commit()

        body = client.get("/news").text

        assert f'href="/news/{row.id}"' in body
        assert f'href="{row.url}"' not in body
        # Followed rather than assumed: a heading pointing at a 404 would satisfy the
        # assertion above and be worse than the external link it replaced.
        assert client.get(f"/news/{row.id}").status_code == 200

    def test_a_headline_shows_the_relevance_reason_on_hover(self, client, session):
        """The classifier's sentence, where the reader decides whether to open the story.

        The story page prints it in full; the list is where the decision is made. A story
        no classifier has judged says nothing -- an empty `title` would be a tooltip that
        pops up blank.
        """
        make(
            session,
            "a judged story",
            relevant=True,
        )
        unjudged = make(session, "an unjudged story", relevant=None, materiality=None)
        # The reason is written by the classifier, not by the fixture, so it is set here
        # to the same shape `news_relevance` stores.
        judged = session.execute(
            select(NewsItem).where(NewsItem.title == "a judged story")
        ).scalar_one()
        judged.relevance_reason = "Names the instrument and states a direction."
        session.commit()

        body = client.get("/news").text

        assert 'title="Relevance: Names the instrument and states a direction."' in body
        assert body.count('title="Relevance:') == 1, (
            "one judged story, one tooltip -- the unjudged one says nothing"
        )
        assert unjudged.relevance_reason is None

    def test_the_nav_marks_the_news_page_active(self, client, session):
        make(session, "a story")
        session.commit()

        body = client.get("/news").text

        assert '<a href="/news" class="active">News</a>' in body

    def test_the_nav_marks_a_story_page_as_the_news_section(self, client, session):
        """The reader arrived from the corpus and the nav should keep saying so."""
        row = make(session, "a story")
        session.commit()

        body = client.get(f"/news/{row.id}").text

        assert '<a href="/news" class="active">News</a>' in body

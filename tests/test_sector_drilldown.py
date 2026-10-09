"""The filter system, and the sector drill-down built on it.

Two failures these prevent, both silent.

The first is a link that drops a filter. The recommendations page used to carry
its query state in a hand-written ``params()`` macro listing each parameter by
name, kept in step with the route, the query call and the form by nothing but
care. When the lists disagreed the page still rendered, still returned 200, and
quietly showed a different table than the reader had asked for.

The second is a sector name that does not survive the trip through a URL. These
are SEC SIC industry strings, so they contain commas, ampersands, parentheses and
slashes -- ``Surgical & Medical Instruments & Apparatus`` is a real one. An
unescaped ampersand does not fail loudly; it truncates the parameter and filters
on a sector that does not exist, which looks exactly like a sector with no
instruments to its name.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse

import pytest

from awltux.web import filters

#: A sector name with everything that breaks naive querystring building.
AWKWARD = "Surgical & Medical Instruments & Apparatus, NEC (incl. dental)"
PLAIN = "Pharmaceutical Preparations"

#: The coarse sector both SIC strings above are derived into. It has a space, so the
#: sector-page URLs exercise escaping too.
GROUP = "Health Care"


def visible_text(html: str) -> str:
    """The page as a reader sees it: markup and attribute values removed.

    Used to assert that a URL sentinel stays in the URL. It has to appear in
    ``href`` and ``value`` attributes -- that is what makes the filter work -- so
    "not in the response" would be testing the wrong thing entirely, and would
    pass only by accident while the filter was broken.
    """
    return re.sub(r"<[^>]*>", " ", html)


@pytest.fixture
def specs():
    """The real specs, with a small sector list so the tests are readable."""
    return filters.recommendation_specs(
        sectors=(
            filters.FilterOption(PLAIN, PLAIN, "23"),
            filters.FilterOption(AWKWARD, AWKWARD, "9"),
            filters.FilterOption(filters.UNCLASSIFIED, "Unclassified", "194"),
        )
    )


def parse(specs, **params):
    return filters.FilterSet.parse(specs, {k: str(v) for k, v in params.items()})


class TestParsing:
    def test_an_absent_filter_takes_its_default(self, specs):
        spec = parse(specs)

        assert spec.value("sector") == ""
        assert spec.value("view") == "all"
        assert spec.value("horizon") == "long_term"
        assert spec.value("sort") == "composite_score"
        assert not spec.given("sector")

    def test_a_known_value_is_kept(self, specs):
        assert parse(specs, sector=PLAIN).value("sector") == PLAIN

    def test_an_unknown_value_is_refused_and_reported(self, specs):
        """Not silently ignored: the table is then not the one the URL describes.

        Refusing to render would punish a stale bookmark; ignoring it quietly
        would show a filtered-looking page that is not filtered. The reader is
        told which value was dropped.
        """
        spec = parse(specs, sector="Nonexistent Industries")

        assert spec.value("sector") == "", "an unknown sector must not be applied"
        assert [bad.name for bad in spec.ignored] == ["sector"]
        assert spec.ignored[0].value == "Nonexistent Industries"

    def test_a_text_filter_accepts_anything(self, specs):
        """A search box has no option list, so it cannot be validated against one."""
        spec = parse(specs, q="  dental supplies  ")

        assert spec.value("q") == "dental supplies"
        assert not spec.ignored

    def test_every_sort_key_the_query_understands_is_accepted(self, specs):
        """The options are derived from `queries.SortKey`, so this cannot drift."""
        from typing import get_args

        from awltux.web.queries import SortKey

        for key in get_args(SortKey):
            spec = parse(specs, sort=key)
            assert spec.value("sort") == key
            assert not spec.ignored, key


class TestQuerystrings:
    def test_defaults_are_omitted(self, specs):
        """Which is what keeps a drill-down link readable."""
        assert parse(specs).query() == ""

    def test_a_sector_survives_the_round_trip(self, specs):
        query = parse(specs, sector=AWKWARD).query()

        assert query.startswith("?sector=")
        # The raw ampersands must not be in the querystring: they would split it
        # into three parameters, two of which this page has never heard of.
        assert query.count("&") == 0
        assert urllib.parse.parse_qs(query[1:])["sector"] == [AWKWARD]

    def test_parsing_its_own_output_is_idempotent(self, specs):
        """The property that makes a link a link: following it changes nothing."""
        once = parse(specs, sector=AWKWARD, q="dental", sort="name", direction="asc")
        again = filters.FilterSet.parse(specs, dict(urllib.parse.parse_qsl(once.query()[1:])))

        assert again.query() == once.query()

    def test_a_none_override_clears_only_that_filter(self, specs):
        spec = parse(specs, sector=PLAIN, q="dental")

        cleared = spec.query(sector=None)

        assert "sector" not in cleared
        assert "q=dental" in cleared

    def test_overrides_win(self, specs):
        assert parse(specs, view="held").query(view="all") == ""

    def test_href_adds_the_path(self, specs):
        assert parse(specs, sector=PLAIN).href("/dashboard") == (
            "/dashboard?sector=" + urllib.parse.quote(PLAIN, safe="")
        )

    def test_clearing_keeps_the_ordering(self, specs):
        """`Clear all` means the filters, not the arrangement of the table."""
        spec = parse(specs, sector=PLAIN, q="x", sort="name", direction="asc")

        cleared = spec.clear_href("/dashboard")

        assert "sector" not in cleared and "q=" not in cleared
        assert "sort=name" in cleared and "direction=asc" in cleared


class TestTheFormCarriesState:
    def test_it_carries_what_has_no_control_of_its_own(self, specs):
        """Otherwise submitting a sector silently re-sorts and un-holds the table."""
        spec = parse(specs, view="held", horizon="short_term", sort="name")

        hidden = {item.name for item in spec.hidden}

        assert {"view", "horizon", "sort"} <= hidden

    def test_it_does_not_carry_the_page_number(self, specs):
        """A changed filter is a new query.

        Carrying the page lands the reader past the end of a narrower result set:
        an empty table that reads as "no matches" when there are three rows on
        page one. The page number stays in *links* -- moving between pages is the
        one thing it is for -- so this asserts the form's carried state, not
        `query()`.
        """
        spec = parse(specs, page=7, sector=PLAIN)

        assert "page" not in {item.name for item in spec.hidden}
        assert "page=7" in spec.query(sector=PLAIN)

    def test_every_control_is_rendered(self, specs):
        """The form and the validator read the same declaration.

        The list is exact on purpose: a filter that exists in the URL and is missing
        from the form is one a reader can only reach by editing the address bar, and a
        control missing from the *validator* would be silently dropped on submit. So a
        new filter is a deliberate edit here.
        """
        assert [item.name for item in parse(specs).controls] == [
            "q",
            "sector",
            "action",
            "engine",
            "horizon_fit",
            "attention",
        ]


class TestActiveChips:
    def test_a_default_produces_none(self, specs):
        assert parse(specs).active() == ()

    def test_it_names_the_value_as_the_control_does(self, specs):
        """A chip reading `__unclassified__` would be a URL leaking onto the page."""
        chips = parse(specs, sector=filters.UNCLASSIFIED).active()

        assert len(chips) == 1
        assert chips[0].shown == "Unclassified"
        assert chips[0].label == "Sector"

    def test_each_chip_clears_only_itself(self, specs):
        """Both directions, because clearing the wrong one also "works" visually."""
        chips = parse(specs, sector=PLAIN, q="dental").active()

        by_name = {chip.name: chip for chip in chips}

        # Clearing the sector leaves the search standing...
        assert "sector=" not in by_name["sector"].clear_query
        assert "q=dental" in by_name["sector"].clear_query

        # ...and clearing the search leaves the sector standing.
        assert "q=" not in by_name["q"].clear_query
        assert "sector=" in by_name["q"].clear_query

    def test_ordering_is_not_a_filter(self, specs):
        """A chip for `sort` would offer to clear something the reader did not set."""
        assert parse(specs, sort="name").active() == ()


class TestSectorOptions:
    def test_busiest_first_and_unclassified_last(self):
        options = filters.sector_options(
            [(PLAIN, 3), (AWKWARD, 30), (None, 194), ("Empty", 0)]
        )

        assert [o.value for o in options] == [AWKWARD, PLAIN, "Empty", filters.UNCLASSIFIED]
        assert options[-1].note == "194"

    def test_unclassified_is_omitted_when_there_is_none(self):
        """An option that matches nothing is worse than no option."""
        options = filters.sector_options([(PLAIN, 3)])

        assert filters.UNCLASSIFIED not in {o.value for o in options}

    def test_a_nameless_row_is_counted_not_dropped(self):
        """Dropping it would make those instruments unreachable by any sector."""
        options = filters.sector_options([(None, 194)])

        assert len(options) == 1
        assert options[0].value == filters.UNCLASSIFIED


class TestTheSectorTranslation:
    def test_a_named_sector_passes_through(self):
        assert filters.sector_filter(PLAIN) == (PLAIN, False)

    def test_the_sentinel_becomes_an_empty_column(self):
        assert filters.sector_filter(filters.UNCLASSIFIED) == (None, True)

    def test_no_filter_asks_for_neither(self):
        assert filters.sector_filter(None) == (None, False)


# --------------------------------------------------------------------------- #
# the drill-down, end to end through the page
# ---------------------------------------------------------------------------


@pytest.fixture
def sectors(session):
    """Instruments across two coarse sectors, plus one with no sector at all.

    The counts are deliberately uneven so a test can tell "filtered to the right
    sector" from "returned everything". Sector sentiment is seeded too, keyed on the
    SIC industry string the older jobs still write.

    ``sector_group`` is what the sector *pages* are keyed on, and it is set to match
    the SIC string here the way ``analysis/sectors.assign`` would derive it -- a test
    fixture that set only one of the two would let a page filter on a column nothing
    had populated and still look correct.
    """
    from awltux.db import SentimentSeries
    from tests.helpers import make_instrument

    session.add(
        make_instrument(
            "PHRM_US_EQ", name="Pharma One", sector=PLAIN, sector_group=GROUP, isin="US1"
        )
    )
    session.add(
        make_instrument(
            "PHRM2_US_EQ", name="Pharma Two", sector=PLAIN, sector_group=GROUP, isin="US2"
        )
    )
    session.add(
        make_instrument(
            "SURG_US_EQ", name="Surgical One", sector=AWKWARD, sector_group=GROUP, isin="US3"
        )
    )
    session.add(
        make_instrument("NONE_US_EQ", name="No Sector", sector=None, isin="US4")
    )
    today = dt.date.today()
    for scope_id, score in ((PLAIN, 0.4), (AWKWARD, -0.2)):
        session.add(
            SentimentSeries(
                scope_type="sector",
                scope_id=scope_id,
                date=today,
                score=score,
                article_count=3,
            )
        )
    # Committed, not merely flushed: the request runs in its own session and
    # cannot see rows this one has not published.
    session.commit()
    return {"plain": PLAIN, "awkward": AWKWARD, "none": "NONE_US_EQ", "group": GROUP}


def landing(html: str, ticker: str) -> bool:
    return f"/instrument/{ticker}" in html


class TestTheSectorsPageLinksIntoTheTable:
    """The index lists the *coarse* sectors and links each to its own page.

    It used to list the SIC industry strings and link into the recommendations table's
    query string. That made the drill-down a filter rather than a view -- no news, no
    sentiment, and a "sector" of one company -- so the link now goes to a page, and the
    table it contains is the same template the dashboard renders.
    """

    def test_each_sector_name_is_a_link_to_its_own_page(self, client, sectors):
        body = client.get("/sectors").text

        assert f"/sectors/{urllib.parse.quote(GROUP, safe='')}" in body

    def test_a_sector_name_with_a_space_is_escaped_in_the_link(self, client, sectors):
        """`Health Care` unescaped would be a URL with a space in it, which the browser
        fixes and a test would not notice."""
        body = client.get("/sectors").text

        assert urllib.parse.quote(GROUP, safe="") in body
        assert "/sectors/Health Care" not in body, "the space was left raw"

    def test_following_the_link_from_the_page_works(self, client, sectors):
        """The end-to-end path, using the href the page actually emitted.

        Asserting the two halves separately would not catch a link that is built
        correctly and routed differently -- the failure this module exists for.
        """
        page = client.get("/sectors").text
        href = re.search(r'href="(/sectors/[^"]+)"', page)

        assert href, "the Sectors page emitted no drill-down link"

        body = client.get(href.group(1)).text

        assert landing(body, "PHRM_US_EQ")
        assert landing(body, "SURG_US_EQ"), "both industry strings are in this group"
        assert not landing(body, "NONE_US_EQ"), "an unclassified instrument leaked in"

    def test_the_unclassified_bucket_is_reachable(self, client, sectors):
        """185 in-universe instruments have no group, and an index that omitted them
        would make a third of the universe unreachable from the sector pages."""
        body = client.get("/sectors").text

        assert "/sectors/Unclassified" in body

        page = client.get("/sectors/Unclassified").text
        assert landing(page, "NONE_US_EQ")

    def test_the_count_column_is_present(self, client, sectors):
        body = client.get("/sectors").text

        assert "Instruments" in body


class TestASectorPage:
    def test_an_unknown_sector_is_a_404_not_an_empty_page(self, client, sectors):
        """"No such sector" and "a sector with nothing in it" are different answers,
        and the second is already reachable."""
        assert client.get("/sectors/Vibes").status_code == 404

    def test_it_carries_the_sector_own_news(self, client, session, sectors):
        """The point of the page: an industry's stories, appraised *for the industry*."""
        from awltux.db import NewsAnalysis, NewsItem, utcnow

        item = NewsItem(
            source="google_news",
            url="https://x.test/sector-news",
            url_hash="sector-news-1",
            title="Pharma pricing pressure builds in Washington",
            published_at=utcnow(),
            tickers=[],
            sectors=[GROUP],
            materiality="material",
            direction="negative",
            relevant=True,
            created_at=utcnow(),
        )
        session.add(item)
        session.flush()
        session.add(
            NewsAnalysis(
                news_item_id=item.id,
                subject_type="sector",
                subject_id=GROUP,
                source_domain="x.test",
                evidence_grade="weak",
                credibility=0.4,
                scepticism_summary="One unnamed source and no filing behind it.",
                flags=[],
                warnings=[],
                caveats=[],
                claims=[],
                omissions=[],
                techniques=[],
                source_biases=[],
                factors={},
                analysed_at=utcnow(),
                created_at=utcnow(),
            )
        )
        session.commit()

        body = client.get(f"/sectors/{urllib.parse.quote(GROUP, safe='')}").text

        assert "Pharma pricing pressure builds" in body
        assert "One unnamed source and no filing behind it." in body, (
            "the sector's own appraisal, not a company's"
        )

    def test_a_headline_shows_the_relevance_reason_on_hover(self, client, session, sectors):
        """The sector list carries the same sentence the story page prints.

        A sector story's relevance is the classifier's judgement that it is a claim about
        a price at all; on the list it rides along on hover, and a story that was never
        judged has no tooltip rather than a blank one.
        """
        from awltux.db import NewsItem, utcnow

        judged = NewsItem(
            source="google_news",
            url="https://x.test/relevance-judged",
            url_hash="relevance-judged",
            title="Drug pricing rules reach committee",
            published_at=utcnow(),
            tickers=[],
            sectors=[GROUP],
            materiality="material",
            relevant=True,
            relevance_reason="Names the sector and states a direction.",
        )
        session.add(judged)
        session.commit()

        body = client.get(f"/sectors/{urllib.parse.quote(GROUP, safe='')}").text

        assert 'title="Relevance: Names the sector and states a direction."' in body
        assert body.count('title="Relevance:') == 1

    def test_sorting_stays_on_the_sector(self, client, sectors):
        """A column heading on a sector page must re-sort the sector. Pointing it at
        `/dashboard` would silently widen the view to the whole universe."""
        body = client.get(f"/sectors/{urllib.parse.quote(GROUP, safe='')}").text

        assert f"/sectors/{urllib.parse.quote(GROUP, safe='')}?sort=" in body
        assert 'href="/dashboard?sort=' not in body


class TestTheDrillDownLands:
    def test_it_shows_only_the_selected_sector(self, client, sectors):
        body = client.get(f"/dashboard?{urllib.parse.urlencode({'sector': PLAIN})}").text

        assert landing(body, "PHRM_US_EQ")
        assert landing(body, "PHRM2_US_EQ")
        assert not landing(body, "SURG_US_EQ"), "a different sector leaked into the view"
        assert not landing(body, "NONE_US_EQ"), "an unclassified instrument leaked in"

    def test_the_page_says_what_it_is_filtered_by(self, client, sectors):
        """Arriving from the Sectors page, a filtered table with no visible reason
        is indistinguishable from missing data."""
        body = client.get(f"/dashboard?{urllib.parse.urlencode({'sector': PLAIN})}").text

        assert "Filtered by" in body
        assert PLAIN in body
        assert "2 instruments" in body

    def test_an_awkward_name_filters_correctly(self, client, sectors):
        """`&` in the sector name would truncate the parameter if unescaped."""
        body = client.get(f"/dashboard?{urllib.parse.urlencode({'sector': AWKWARD})}").text

        assert landing(body, "SURG_US_EQ")
        assert not landing(body, "PHRM_US_EQ")

    def test_the_unclassified_sentinel_selects_the_empty_column(self, client, sectors):
        body = client.get(f"/dashboard?sector={filters.UNCLASSIFIED}").text

        assert landing(body, "NONE_US_EQ")
        assert not landing(body, "PHRM_US_EQ")
        assert "Unclassified" in body

    def test_a_sector_name_never_appears_as_its_sentinel(self, client, sectors):
        """The sentinel belongs in the URL, not on the page.

        It has to appear in `href` and `value` attributes -- that is the filter
        working -- so this reads the rendered page rather than the response text,
        which would only pass while the filter was broken.
        """
        body = client.get(f"/dashboard?sector={filters.UNCLASSIFIED}").text

        assert "Unclassified" in visible_text(body)
        assert filters.UNCLASSIFIED not in visible_text(body)


class TestFiltersCompose:
    def test_the_sector_narrows_the_search(self, client, sectors):
        """Two filters applied together must both hold, not replace each other."""
        body = client.get(
            f"/dashboard?{urllib.parse.urlencode({'sector': PLAIN, 'q': 'Two'})}"
        ).text

        assert landing(body, "PHRM2_US_EQ")
        assert not landing(body, "PHRM_US_EQ"), "the search term was dropped"

    def test_clearing_the_sector_restores_the_others(self, client, sectors):
        """The chip's clear link, followed."""
        spec = parse(
            filters.recommendation_specs(sectors=()), sector=PLAIN, q="Pharma"
        )
        chips = {chip.name: chip for chip in spec.active()}

        query = chips["sector"].clear_query

        assert "sector" not in query
        assert "q=Pharma" in query

    def test_an_unknown_sector_shows_the_table_and_says_so(self, client, sectors):
        """Reported rather than refused, and rather than an empty table.

        A stale bookmark must not look like "this sector holds nothing".
        """
        response = client.get("/dashboard?sector=No+Such+Sector")

        assert response.status_code == 200
        assert "Ignored" in response.text
        assert "No Such Sector" in response.text
        assert landing(response.text, "PHRM_US_EQ"), "the unfiltered table was not shown"


class TestTheSectorLinkOnARow:
    """The reverse drill-down: table to sector page.

    The row shows the *industry string* and links on the *group*, which is the one
    place both vocabularies appear together -- the string is what the register said,
    the group is what has a page.
    """

    def test_each_row_links_to_its_sector_page(self, client, sectors):
        body = client.get("/dashboard").text

        assert "/sectors/" + urllib.parse.quote(GROUP, safe="") in body

    def test_the_industry_string_is_still_shown(self, client, sectors):
        """The link is the group, but the reader still sees what EDGAR recorded --
        the group is a derivation and hiding its input would make it unauditable."""
        body = client.get("/dashboard").text

        assert PLAIN in body

    def test_an_unclassified_row_links_to_the_unclassified_page(self, client, sectors):
        body = client.get("/dashboard").text

        assert "/sectors/Unclassified" in body
        assert f"sector={filters.UNCLASSIFIED}" not in body, (
            "the row no longer filters the dashboard; it opens the sector page"
        )

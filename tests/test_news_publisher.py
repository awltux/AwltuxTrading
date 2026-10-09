"""Who actually published a story, and what the appraisals were rated against.

Asked for directly: *"I think the Source should be the real source, not the feed."*

The measurement that makes this a correctness fix rather than a display one, taken
2026-10-09 over the 27,895 stories then stored:

* **26,591 (95.3%) carry a `news.google.com` URL** — a redirect into the Google News
  reader — so `lookup(url)` answers "Google News, kind aggregator" and no amount of
  reading the URL names the writer. The masthead Google News appends to the headline
  does: 99.7% of those rows carry one.
* **6,700 of the 6,974 stored appraisals recorded `source_name = "Google News"`**, because
  `appraise_item` took the publisher from the URL. `source_kind` feeds `source_weight`,
  the first factor of credibility.

So the tests below are about three things: the parse names the right organisation, the
rating follows the name into the appraisal, and the columns the page reads are pinned to
the publisher rather than to the feed.
"""

from __future__ import annotations

import pytest

from awltux.analysis import sources
from awltux.analysis.news_analysis import (
    APPRAISAL_COLUMNS,
    MODEL_COLUMNS,
    backfill_publishers,
    rerate_publishers,
)
from awltux.db import NewsAnalysis, NewsItem, utcnow
from awltux.web import queries


class TestTheMasthead:
    def test_it_reads_the_publisher_off_the_end_of_a_headline(self):
        assert (
            sources.masthead("Acme wins the contract - Yahoo Finance") == "Yahoo Finance"
        )

    def test_a_separator_inside_a_headline_is_not_a_masthead(self):
        """The guard `title_key` carries, and it has to hold for this reader too.

        "Form 8.3 - [...]" is a filing headline whose middle is full of separator-looking
        dashes; reading "02 10 2026]" as the publisher would put a date in the Source
        column. The threshold is exactly why the same split is shared rather than copied.
        """
        headline = "Form 8.3 - [ADVANCED MEDICAL SOLUTIONS GROUP PLC - 02 10 2026]"

        assert sources.masthead(headline) is None

    def test_a_headline_with_no_separator_has_no_masthead(self):
        assert sources.masthead("Acme wins the contract") is None

    def test_the_split_returns_both_halves(self):
        head, publisher = sources.split_masthead("Acme wins the contract - MarketBeat")

        assert head == "Acme wins the contract"
        assert publisher == "MarketBeat"


class TestIdentify:
    def test_a_google_news_url_does_not_name_google(self):
        """The whole reason this exists. `lookup` says Google News; the writer is not."""
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/CBMiXYZ",
            title="Acme wins the contract - MarketBeat",
        )

        assert publisher.name != "Google News"
        assert publisher.kind != "aggregator"

    def test_a_publishers_own_url_is_used_directly(self):
        """`yahoo_rss` stores the article's own address, so no parse is needed."""
        publisher = sources.identify(
            url="https://finance.yahoo.com/news/acme-wins-123.html",
            title="Acme wins the contract",
        )

        assert publisher.name == "Yahoo Finance"

    def test_a_rated_masthead_is_returned_as_its_registry_entry(self):
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/XYZ",
            title="Acme wins the contract - Seeking Alpha",
        )

        assert publisher.name == "Seeking Alpha"
        assert publisher.assessed
        assert publisher.kind == "opinion"

    def test_a_country_edition_resolves_to_its_parent(self):
        """"Yahoo Finance UK" is Yahoo Finance, and 621 rows say exactly that."""
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/XYZ",
            title="Acme wins the contract - Yahoo Finance UK",
        )

        assert publisher.name == "Yahoo Finance"
        assert publisher.assessed

    def test_punctuation_does_not_stop_the_match(self):
        """"Yahoo! Finance Canada" against a registry that spells it without the bang."""
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/XYZ",
            title="Acme wins the contract - Yahoo! Finance Canada",
        )

        assert publisher.name == "Yahoo Finance"

    def test_a_masthead_that_is_a_domain_is_resolved_as_one(self):
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/XYZ",
            title="A reasonably long headline about something - finance.yahoo.com",
        )

        assert publisher.name == "Yahoo Finance"

    def test_an_unrated_masthead_keeps_its_name_and_says_it_is_unrated(self):
        """Names the publisher and admits we have nothing on file for it.

        Throwing the name away for "Unrecognised publisher" would lose the only thing the
        row knows about who wrote it; rating it as anything would be inventing a
        judgement. `assessed` false is how the scepticism layer already spells "unrated".
        """
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/XYZ",
            title="A reasonably long headline about something - The Acme Gazette",
        )

        assert publisher.name == "The Acme Gazette"
        assert not publisher.assessed
        assert publisher.kind == "unknown"
        assert "masthead" in publisher.basis

    def test_a_rated_publisher_wins_over_a_short_prefix(self):
        """`_by_prefix` takes the *longest* name, so a short one cannot shadow it."""
        assert sources.by_name("Yahoo Finance") is not None
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/XYZ",
            title="A reasonably long headline about something - Investing.com UK",
        )

        assert publisher.name == "Investing.com"

    def test_with_nothing_to_read_the_url_answer_stands(self):
        """No masthead and a redirect host: "Google News" is the honest answer.

        Nothing else on the row says who wrote it, and inventing an attribution would be
        worse than naming the pipe the story actually came through.
        """
        publisher = sources.identify(
            url="https://news.google.com/rss/articles/XYZ",
            title="A headline with no masthead at all on it",
        )

        assert publisher.name == "Google News"

    def test_a_story_with_no_url_at_all_still_gets_its_masthead_read(self):
        publisher = sources.identify(url=None, title="Acme wins - MarketBeat")

        assert publisher.name == "MarketBeat"

    def test_by_name_ignores_a_leading_the(self):
        """Both directions: the registry has "The Wall Street Journal", a masthead may not."""
        assert sources.by_name("The Wall Street Journal") is not None
        assert sources.by_name("wall street journal") is not None
        assert sources.by_name("Nobody At All") is None


class TestTitleKeyStillAgrees:
    """The split is shared, so `title_key`'s behaviour must not have moved."""

    def test_the_key_ignores_the_masthead(self):
        from awltux.ingest.news import title_key

        # Long enough that the key's own 25-character guard keeps the split; a shorter
        # head is refused there and this would compare two whole titles.
        headline = "Acme wins the northern region contract - Yahoo Finance"
        other = "Acme wins the northern region contract - GlobeNewswire"

        assert title_key(headline) == title_key(other)

    def test_a_headline_too_short_to_key_still_keys_as_a_whole(self):
        """`title_key`'s guard is about keying, and it stays with the key.

        "Acme wins - Yahoo Finance" is a perfectly good attribution and a bad key: the
        remainder is short enough that the separator may have been part of the headline.
        The two callers ask different questions, and this is what separates them.
        """
        from awltux.ingest.news import title_key

        assert title_key("Acme wins - Yahoo Finance") != title_key(
            "Acme wins - GlobeNewswire"
        )

    def test_the_key_keeps_a_headline_whose_dash_is_not_a_masthead(self):
        from awltux.ingest.news import title_key

        headline = "Form 8.3 - [ADVANCED MEDICAL SOLUTIONS GROUP PLC - 02 10 2026]"
        other = "Form 8.3 - [ADVANCED MEDICAL SOLUTIONS GROUP PLC - 03 10 2026]"

        assert title_key(headline) != title_key(other)


def _story(session, title, *, url, source="google_news", publisher=None):
    row = NewsItem(
        source=source,
        url=url,
        url_hash=title,
        title=title,
        publisher=publisher,
        summary="",
        published_at=utcnow(),
        tickers=["ACME_US_EQ"],
        sectors=[],
        materiality="material",
        direction="positive",
        relevance=0.5,
        relevant=True,
    )
    session.add(row)
    session.flush()
    return row


class TestTheBackfill:
    def test_it_names_every_story_from_its_headline(self, session):
        masthead = _story(
            session,
            "Acme wins the contract - MarketBeat",
            url="https://news.google.com/rss/articles/A",
        )
        own_url = _story(
            session,
            "Acme wins the contract",
            url="https://finance.yahoo.com/news/a.html",
            source="yahoo_rss",
        )

        report = backfill_publishers(session)

        assert report["named"] == 2
        assert masthead.publisher == "MarketBeat"
        assert own_url.publisher == "Yahoo Finance"

    def test_running_it_twice_writes_nothing_the_second_time(self, session):
        _story(session, "Acme wins - MarketBeat", url="https://news.google.com/rss/a")

        backfill_publishers(session)
        second = backfill_publishers(session)
        session.commit()

        assert second["named"] == 0
        assert second["already_named"] == 1


class TestTheRatingFollowsTheName:
    """The half that is not cosmetic: what the appraisal was graded against."""

    @staticmethod
    def _appraise(session, item, credibility=0.5, name="Google News"):
        row = NewsAnalysis(
            news_item_id=item.id,
            subject_type="instrument",
            subject_id="ACME_US_EQ",
            source_domain="news.google.com",
            source_name=name,
            source_kind="aggregator",
            source_reliability=0.55,
            source_independence=0.30,
            source_biases=["aggregator"],
            source_basis="as stored before the fix",
            source_assessed=True,
            credibility=credibility,
            evidence_grade="mixed",
            claims=[{"text": "Acme won a contract", "claim_type": "filed_record",
                     "checkable": True, "support": 0.8}],
            omissions=["nothing"],
            scepticism_summary="The model read this.",
            techniques=["urgency"],
            engine="deepseek",
            analysed_at=utcnow(),
        )
        session.add(row)
        session.flush()
        return row

    def test_an_appraisal_is_re_attributed_to_the_real_publisher(self, session):
        item = _story(
            session,
            "Acme wins the contract - Seeking Alpha",
            url="https://news.google.com/rss/articles/A",
        )
        row = self._appraise(session, item)

        report = rerate_publishers(session)

        assert report["renamed"] == 1
        assert row.source_name == "Seeking Alpha"
        assert row.source_kind == "opinion"
        assert row.source_assessed

    def test_the_paid_half_is_not_thrown_away(self, session):
        """Re-rating must not lose what the model was paid to read.

        The claims, the omissions and the deep summary are the expensive part, and
        nothing about them was wrong -- the publisher was. This is the assertion that the
        rebuild is deterministic-only rather than a quiet re-appraisal.
        """
        item = _story(
            session,
            "Acme wins the contract - Seeking Alpha",
            url="https://news.google.com/rss/articles/A",
        )
        row = self._appraise(session, item)

        rerate_publishers(session)

        assert row.claims[0]["text"] == "Acme won a contract"
        assert row.omissions == ["nothing"]
        assert row.scepticism_summary == "The model read this."
        assert row.techniques == ["urgency"]
        assert row.engine == "deepseek"
        assert row.source_basis != "as stored before the fix"

    def test_the_credibility_moves_with_the_publisher(self, session):
        """The point of the exercise: an aggregator default is not a real rating.

        Google News is rated ``aggregator`` (reliability 0.55, independence 0.30, and a
        self-interest discount); a rated publisher is not, so the weight it contributes
        to the sentiment aggregate changes. Asserted as a *change*, not a direction --
        which way it moves depends on the publisher.
        """
        item = _story(
            session,
            "Acme wins the contract - Seeking Alpha",
            url="https://news.google.com/rss/articles/A",
        )
        row = self._appraise(session, item)
        before = row.credibility

        rerate_publishers(session)

        assert row.credibility != before

    def test_an_unrated_publisher_is_flagged_rather_than_trusted(self, session):
        item = _story(
            session,
            "Acme wins the contract - The Acme Gazette",
            url="https://news.google.com/rss/articles/A",
        )
        row = self._appraise(session, item)

        rerate_publishers(session)

        assert row.source_name == "The Acme Gazette"
        assert not row.source_assessed
        assert "unrated_source" in row.flags

    def test_running_it_twice_changes_nothing_the_second_time(self, session):
        item = _story(
            session,
            "Acme wins the contract - Seeking Alpha",
            url="https://news.google.com/rss/articles/A",
        )
        row = self._appraise(session, item)

        rerate_publishers(session)
        first = (row.source_name, row.credibility)
        second = rerate_publishers(session)

        assert second["renamed"] == 0
        assert second["rewritten"] == 0
        assert (row.source_name, row.credibility) == first

    def test_every_appraisal_of_a_story_is_re_rated(self, session):
        """A story about three things has three rows, and all of them were mis-rated."""
        item = _story(
            session,
            "Acme and the sector - Seeking Alpha",
            url="https://news.google.com/rss/articles/A",
        )
        self._appraise(session, item)
        session.add(
            NewsAnalysis(
                news_item_id=item.id,
                subject_type="sector",
                subject_id="Energy",
                source_name="Google News",
                source_kind="aggregator",
                credibility=0.5,
                analysed_at=utcnow(),
            )
        )
        session.flush()

        report = rerate_publishers(session)

        assert report["appraisals"] == 2
        assert report["renamed"] == 2

    def test_a_story_with_no_appraisal_is_untouched(self, session):
        _story(
            session,
            "Acme wins the contract - Seeking Alpha",
            url="https://news.google.com/rss/articles/A",
        )

        report = rerate_publishers(session)

        assert report["appraisals"] == 0


class TestTheModelColumnsAreReal:
    def test_every_model_column_is_an_appraisal_column(self):
        """A typo in the list would be a column silently not carried across."""
        assert set(MODEL_COLUMNS) <= set(APPRAISAL_COLUMNS)

    def test_the_source_columns_are_not_model_columns(self):
        """They are what the re-rating recomputes; carrying them would undo it."""
        for column in ("source_name", "source_kind", "credibility", "evidence_grade"):
            assert column not in MODEL_COLUMNS


class TestThePageShowsThePublisher:
    def _seed(self, session, *, publisher, feed="google_news", title="a story"):
        row = NewsItem(
            source=feed,
            url=f"https://news.google.com/rss/{title.replace(' ', '-')}",
            url_hash=title,
            title=title,
            publisher=publisher,
            summary="",
            published_at=utcnow(),
            tickers=[],
            sectors=[],
            materiality="mild",
            direction="positive",
            relevant=True,
        )
        session.add(row)
        session.flush()
        return row

    def test_the_column_names_the_writer_and_the_feed_beneath_it(self, client, session):
        self._seed(session, publisher="MarketBeat")
        session.commit()

        body = " ".join(client.get("/news").text.split())

        assert "MarketBeat" in body
        assert "via google_news" in body, "the pipe is kept, in small type"

    def test_the_feed_is_not_repeated_when_it_is_the_publisher(self, client, session):
        self._seed(session, publisher="edgar", feed="edgar", title="a filing")
        session.commit()

        body = " ".join(client.get("/news").text.split())

        assert "via edgar" not in body

    def test_filtering_by_publisher(self, client, session):
        self._seed(session, publisher="MarketBeat", title="from marketbeat")
        self._seed(session, publisher="Seeking Alpha", title="from seeking alpha")
        session.commit()

        body = client.get("/news?publisher=MarketBeat").text

        assert "from marketbeat" in body
        assert "from seeking alpha" not in body

    def test_the_feed_filter_still_works(self, client, session):
        """Renaming the column must not drop the feed as a filterable fact."""
        self._seed(session, publisher="MarketBeat", feed="google_news", title="via google")
        self._seed(session, publisher="sec.gov", feed="edgar", title="via edgar")
        session.commit()

        body = client.get("/news?source=edgar").text

        assert "via edgar" in body
        assert "via google" not in body

    def test_the_source_header_sorts_by_publisher(self, client, session):
        self._seed(session, publisher="Zeta News", title="zeta story")
        self._seed(session, publisher="Alpha News", title="alpha story")
        session.commit()

        body = client.get("/news?sort=publisher&direction=asc").text

        assert body.index("alpha story") < body.index("zeta story")

    def test_the_search_box_reaches_the_publisher(self, client, session):
        self._seed(session, publisher="The Acme Gazette", title="an unrelated headline")
        session.commit()

        body = client.get("/news?q=acme+gazette").text

        assert "an unrelated headline" in body

    def test_a_story_with_no_publisher_says_so_rather_than_guessing(self, client, session):
        self._seed(session, publisher=None, title="nobody knows who wrote this")
        session.commit()

        body = " ".join(client.get("/news").text.split())

        assert "nobody knows who wrote this" in body
        assert "via google_news" in body


class TestTheQueryLayer:
    def test_the_listing_filters_on_the_publisher(self, session):
        _story(session, "one", url="https://a.example/1", publisher="MarketBeat")
        _story(session, "two", url="https://a.example/2", publisher="Seeking Alpha")

        rows, total = queries.news_listing(session, publisher="MarketBeat")

        assert total == 1
        assert rows[0].title == "one"

    def test_the_listing_still_filters_on_the_feed(self, session):
        _story(session, "one", url="https://a.example/1", source="edgar")
        _story(session, "two", url="https://a.example/2", source="google_news")

        rows, total = queries.news_listing(session, source="edgar")

        assert total == 1
        assert rows[0].title == "one"

    def test_publisher_counts_leave_out_the_unnamed(self, session):
        _story(session, "one", url="https://a.example/1", publisher="MarketBeat")
        _story(session, "two", url="https://a.example/2", publisher=None)

        counts = dict(queries.news_publisher_counts(session))

        assert counts == {"MarketBeat": 1}


class TestTheVocabulary:
    def test_the_page_offers_a_publisher_filter_and_a_feed_filter(self):
        from awltux.web import filters

        names = [spec.name for spec in filters.news_specs()]

        assert "publisher" in names
        assert "source" in names

    def test_the_sort_keys_match_the_query(self):
        from typing import get_args

        from awltux.web import filters

        assert {option.value for option in filters.NEWS_SORT_OPTIONS} == set(
            get_args(queries.NewsSortKey)
        )

    def test_source_is_no_longer_a_sort_key(self):
        """The column is the publisher now, so the key had to move with it."""
        from typing import get_args

        assert "source" not in get_args(queries.NewsSortKey)
        assert "publisher" in get_args(queries.NewsSortKey)


@pytest.mark.parametrize(
    "host",
    ["news.google.com"],
)
def test_the_feed_hosts_are_the_redirects(host):
    """The list is measured, not guessed: every other host in the column is real.

    Re-measure with::

        select substr(url, ...) from news_item group by 1

    A new redirect feed belongs in `FEED_HOSTS`; a publisher's own host does not, or its
    stories would be attributed from their masthead instead of from the address that
    actually served them.
    """
    assert host in sources.FEED_HOSTS

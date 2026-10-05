"""News relevance, priority, and the page that explains both.

The rule is conjunctive and that is the whole point: a story is relevant only if
it names something *and* says which way that something moves. Two failure modes
follow from getting that wrong, and both are tested here:

* a story that names a holding but says nothing about it is not a signal, and
  showing it in the flash banner is how a feed becomes noise;
* a story with a direction but nothing to attach it to is a fact about the world,
  and there is no holding for it to change the price of.

The page then has to *explain* the verdict. "Not relevant" on its own is
unarguable, so the reason says which half of the rule held or failed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis.relevance import (
    HALF_LIFE_DAYS,
    MATERIALITY_WEIGHT,
    assess,
    priority,
    recency_weight,
)


class TestTheRule:
    def test_naming_an_instrument_and_a_direction_is_relevant(self):
        verdict = assess(
            tickers=["VODl_EQ"], sectors=[], direction="negative", materiality="material"
        )
        assert verdict.relevant is True
        assert verdict.has_target and verdict.directional
        assert "VODl_EQ" in verdict.reason
        assert "negative" in verdict.reason

    def test_naming_nothing_is_not_relevant(self):
        verdict = assess(tickers=[], sectors=[], direction="positive")
        assert verdict.relevant is False
        assert "nothing to attach it to" in verdict.reason

    def test_carrying_no_direction_is_not_relevant(self):
        verdict = assess(tickers=["VODl_EQ"], sectors=[], direction="neutral")
        assert verdict.relevant is False
        assert "not a claim about the share price" in verdict.reason

    def test_neither_half_is_reported_as_neither(self):
        verdict = assess(tickers=[], sectors=[], direction=None)
        assert verdict.relevant is False
        assert "names no instrument or sector" in verdict.reason
        assert "no direction" in verdict.reason

    def test_a_sector_alone_can_be_a_target(self):
        verdict = assess(tickers=[], sectors=["Healthcare"], direction="positive")
        assert verdict.relevant is True
        assert "sector:Healthcare" in verdict.reason

    def test_a_story_the_classifier_says_is_not_about_the_company_has_no_target(self):
        """The ticker on an item usually comes from the feed it was fetched by, not
        from the article: a Google News search for one company returns pieces that
        merely mention it. Without this, every mention would count as a connection.
        """
        verdict = assess(
            tickers=["VODl_EQ"],
            sectors=[],
            direction="negative",
            about=False,
        )
        assert verdict.relevant is False
        assert "mention rather than a connection" in verdict.reason

    def test_being_unimportant_does_not_make_a_story_irrelevant(self):
        """Relevant and low priority are different states; priority is the sort."""
        verdict = assess(
            tickers=["VODl_EQ"], sectors=[], direction="positive", materiality="none"
        )
        assert verdict.relevant is True
        assert "sorts low" in verdict.reason

    def test_the_verdict_serialises_its_working(self):
        payload = assess(tickers=["A"], sectors=["B"], direction="positive").as_dict()
        assert payload["relevant"] is True
        assert payload["targets"] == ["A", "sector:B"]
        assert set(payload) == {"relevant", "has_target", "directional", "reason", "targets"}


class TestRecency:
    def test_a_new_story_weighs_almost_one(self):
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        assert recency_weight(now, now=now) == pytest.approx(1.0)

    def test_it_halves_over_the_half_life(self):
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        older = now - dt.timedelta(days=HALF_LIFE_DAYS)
        assert recency_weight(older, now=now) == pytest.approx(0.5)

    def test_a_story_with_no_timestamp_is_not_treated_as_new(self):
        assert recency_weight(None) == 0.5

    def test_a_future_timestamp_does_not_exceed_one(self):
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        assert recency_weight(now + dt.timedelta(days=5), now=now) == 1.0

    def test_a_naive_timestamp_is_read_as_utc(self):
        """SQLite round-trips can drop tzinfo; that must not make the age wrong."""
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        naive = dt.datetime(2026, 5, 1, 12)
        assert recency_weight(naive, now=now) == pytest.approx(1.0)


class TestPriority:
    def _score(self, **kwargs):
        score, inputs = priority(
            materiality=kwargs.pop("materiality", "material"),
            credibility=kwargs.pop("credibility", 0.8),
            published_at=kwargs.pop("published_at", dt.datetime.now(dt.UTC)),
            **kwargs,
        )
        return score, inputs

    def test_materiality_orders_the_levels(self):
        scores = [self._score(materiality=level)[0] for level in MATERIALITY_WEIGHT]
        assert scores == sorted(scores, reverse=True)

    def test_a_critical_story_outranks_a_mild_one_published_at_the_same_moment(self):
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        critical, _ = priority(
            materiality="critical", credibility=0.8, published_at=now, now=now
        )
        mild, _ = priority(materiality="mild", credibility=0.8, published_at=now, now=now)
        assert critical > mild

    def test_a_fresh_minor_story_outranks_a_stale_one_that_was_more_important(self):
        """The reason priority exists: ordering by arrival made a routine note from
        a minute ago outrank a profit warning from this morning."""
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        fresh, _ = priority(
            materiality="moderate",
            credibility=0.8,
            published_at=now - dt.timedelta(hours=1),
            now=now,
        )
        stale, _ = priority(
            materiality="material",
            credibility=0.8,
            published_at=now - dt.timedelta(days=14),
            now=now,
        )
        assert fresh > stale

    def test_low_credibility_pushes_a_story_down(self):
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        believed, _ = priority(
            materiality="material", credibility=0.9, published_at=now, now=now
        )
        doubted, _ = priority(
            materiality="material", credibility=0.1, published_at=now, now=now
        )
        assert believed > doubted

    def test_an_unappraised_story_is_neither_trusted_nor_discarded(self):
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        unassessed, inputs = priority(
            materiality="material", credibility=None, published_at=now, now=now
        )
        assert inputs["credibility_assessed"] is False
        assert 0 < unassessed < self._score(credibility=1.0)[0]

    def test_every_input_is_returned_with_the_score(self):
        _, inputs = self._score()
        assert set(inputs) == {
            "materiality_weight",
            "credibility",
            "credibility_assessed",
            "recency_weight",
            "formula",
        }

    def test_an_out_of_range_credibility_cannot_dominate(self):
        now = dt.datetime(2026, 5, 1, 12, tzinfo=dt.UTC)
        _, inputs = priority(
            materiality="material", credibility=12.0, published_at=now, now=now
        )
        assert inputs["credibility"] == 1.0

    def test_an_unknown_materiality_does_not_crash_the_sort(self):
        score, inputs = self._score(materiality="unheard_of")
        assert score > 0
        assert inputs["materiality_weight"] == 0.1


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #


def _raw(url: str, *, tickers: list[str], title: str = "Acme warns on profit"):
    from awltux.providers.news_rss import RawNewsItem

    return RawNewsItem(title=title, url=url, source="test", tickers=tickers)


def _classifier(**updates):
    def classify(item, instrument):
        return {
            "materiality": "material",
            "direction": "negative",
            "reasoning": "a profit warning is a negative claim about the share price",
            "is_about_this_company": True,
            **updates,
        }

    return classify


class TestPersistingRelevance:
    def test_a_relevant_story_is_stored_with_the_verdict_and_the_reason(self, session):
        from awltux.db import NewsItem
        from awltux.ingest.news import persist_items

        persist_items(
            session,
            [_raw("https://example.test/1", tickers=["ACME_US_EQ"])],
            classifier=_classifier(),
        )
        session.flush()

        row = session.query(NewsItem).filter_by(url_hash=_hash("https://example.test/1")).one()
        assert row.relevant is True
        assert "profit warning" in row.relevance_reason

    def test_a_story_with_no_direction_is_stored_as_not_relevant(self, session):
        from awltux.db import NewsItem
        from awltux.ingest.news import persist_items

        persist_items(
            session,
            [_raw("https://example.test/2", tickers=["ACME_US_EQ"])],
            classifier=_classifier(direction="neutral", materiality="none"),
        )
        session.flush()

        row = session.query(NewsItem).filter_by(url_hash=_hash("https://example.test/2")).one()
        assert row.relevant is False

    def test_a_passing_mention_is_not_a_connection(self, session):
        """The ticker comes from the feed; the classifier decides whether the
        article is actually about the company."""
        from awltux.db import NewsItem
        from awltux.ingest.news import persist_items

        persist_items(
            session,
            [_raw("https://example.test/3", tickers=["ACME_US_EQ"])],
            classifier=_classifier(is_about_this_company=False),
        )
        session.flush()

        row = session.query(NewsItem).filter_by(url_hash=_hash("https://example.test/3")).one()
        assert row.relevant is False

    def test_an_unclassified_story_is_left_unassessed_rather_than_irrelevant(self, session):
        """NULL and False are different states: one is a gap worth chasing, the
        other a settled answer. Defaulting to False would hide the gap forever."""
        from awltux.db import NewsItem
        from awltux.ingest.news import persist_items

        persist_items(session, [_raw("https://example.test/4", tickers=["ACME_US_EQ"])])
        session.flush()

        row = session.query(NewsItem).filter_by(url_hash=_hash("https://example.test/4")).one()
        assert row.relevant is None

    def test_the_same_story_from_a_second_feed_keeps_both_instruments(self, session):
        """The news page exists to show which instruments a story concerns, and a
        story about two companies is exactly that case. This used to `continue`
        without recording the second ticker, so every stored item in a database of
        five thousand had exactly one."""
        from awltux.db import NewsItem
        from awltux.ingest.news import persist_items

        persist_items(
            session,
            [_raw("https://example.test/5", tickers=["ACME_US_EQ"])],
            classifier=_classifier(),
        )
        persist_items(
            session,
            [_raw("https://example.test/5", tickers=["OTHER_US_EQ"])],
            classifier=_classifier(),
        )
        session.flush()

        row = session.query(NewsItem).filter_by(url_hash=_hash("https://example.test/5")).one()
        assert set(row.tickers) == {"ACME_US_EQ", "OTHER_US_EQ"}

    def test_storing_a_reason_does_not_overwrite_the_models_own_words(self, session):
        from awltux.db import NewsItem
        from awltux.ingest.news import persist_items

        persist_items(
            session,
            [_raw("https://example.test/6", tickers=["ACME_US_EQ"])],
            classifier=_classifier(),
        )
        session.flush()

        row = session.query(NewsItem).filter_by(url_hash=_hash("https://example.test/6")).one()
        assert row.relevance_reason == "a profit warning is a negative claim about the share price"


def _hash(url: str) -> str:
    from awltux.providers.news_rss import RawNewsItem

    return RawNewsItem(title="", url=url, source="test").url_hash

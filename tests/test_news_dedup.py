"""Judging a syndicated headline once.

`news_classification` was 21,343 of 24,544 model calls -- roughly one per stored story.
A wire story carried by two outlets arrives as two rows with two URLs, so `url_hash`
cannot see the duplication and each copy bought its own call. Measured 2026-10-07:
1,570 of 26,008 stored headlines (6.0%) were the same headline under a different
masthead.

The property these assert is *not* "fewer calls". It is **the right verdict on the right
row**: reuse is only correct when the story really is the same, and only when the earlier
verdict was reached about the same instrument. A test that only counted calls would pass
while attaching one company's judgement to another company's story.
"""

from __future__ import annotations

import pytest

from awltux.db import NewsItem
from awltux.ingest.news import NewsIngestReport, persist_items, title_key
from awltux.providers.news_rss import RawNewsItem
from tests.helpers import make_instrument


def _raw(url: str, *, title: str, tickers: list[str], source: str = "test") -> RawNewsItem:
    return RawNewsItem(title=title, url=url, source=source, tickers=tickers)


def _hash(url: str) -> str:
    return RawNewsItem(title="", url=url, source="test").url_hash


def _counting_classifier(**updates):
    """A classifier that records every headline it was asked about."""
    asked: list[str] = []

    def classify(item, _instrument):
        asked.append(item.title)
        return {
            "materiality": "material",
            "direction": "negative",
            "engine": "deepseek:test-model",
            "reasoning": "a profit warning is a negative claim about the share price",
            "is_about_this_company": True,
            **updates,
        }

    return classify, asked


def _instrument(session, ticker: str = "AAPL_US_EQ"):
    row = make_instrument(ticker)
    session.add(row)
    session.flush()
    return row


class TestTheTitleKey:
    """What counts as "the same headline", and what must not."""

    def test_the_masthead_does_not_change_the_key(self):
        assert title_key("Apple warns on profit for the quarter - Yahoo Finance") == title_key(
            "Apple warns on profit for the quarter - GlobeNewswire"
        )

    def test_case_and_spacing_do_not_change_the_key(self):
        assert title_key("Apple  warns on   profit - Yahoo") == title_key(
            "apple warns on profit - yahoo"
        )

    def test_a_short_opening_is_not_treated_as_a_headline(self):
        """`Form 8.3 - [ADVANCED MEDICAL SOLUTIONS - 02 10 2026]` keys on the whole line.

        The separator is part of the headline here, not a masthead, and stripping it
        would merge every filing of that kind into one verdict.
        """
        assert title_key("Form 8.3 - [ADVANCED MEDICAL SOLUTIONS GROUP PLC]") != title_key(
            "Form 8.3 - [A DIFFERENT COMPANY PLC]"
        )

    def test_stories_that_merely_open_alike_get_different_keys(self):
        """The measurement that rejected a 40-character prefix.

        These two share their first 40 characters -- the boilerplate opening of a
        forecast page -- and are about **different companies**. A prefix key would copy
        one company's verdict onto the other's row and nothing would say so. Measured
        over the stored table: 972 prefixes merge two or more different headlines,
        covering 2,723 rows.
        """
        first = "What is the current Price Target and Forecast for 5E Advanced Materials (FEAM)"
        second = "What is the current Price Target and Forecast for Aeon Biopharma, Inc. (AEON)"
        assert first.lower()[:40] == second.lower()[:40], "the premise: a shared opening"
        assert title_key(first) != title_key(second), "different companies, different keys"


class TestASyndicatedCopyReusesTheVerdict:
    def test_the_second_masthead_costs_no_model_call(self, session):
        instrument = _instrument(session)
        classify, asked = _counting_classifier()
        report = NewsIngestReport()

        first = "Apple warns on profit for the quarter - Yahoo Finance"
        second = "Apple warns on profit for the quarter - GlobeNewswire"

        persist_items(
            session,
            [_raw("https://a.test/1", title=first, tickers=["AAPL_US_EQ"])],
            classifier=classify,
            report=report,
            instrument=instrument,
        )
        session.flush()
        persist_items(
            session,
            [_raw("https://b.test/2", title=second, tickers=["AAPL_US_EQ"])],
            classifier=classify,
            report=report,
            instrument=instrument,
        )
        session.flush()

        assert asked == [first], f"exactly one call expected, got {asked}"
        assert report.classified == 1
        assert report.reused == 1

    def test_the_copy_carries_the_same_verdict_and_its_own_identity(self, session):
        instrument = _instrument(session)
        classify, _asked = _counting_classifier()
        report = NewsIngestReport()

        persist_items(
            session,
            [
                _raw(
                    "https://a.test/1",
                    title="Apple warns on profit for the quarter - Yahoo Finance",
                    tickers=["AAPL_US_EQ"],
                )
            ],
            classifier=classify,
            report=report,
            instrument=instrument,
        )
        session.flush()
        original = session.query(NewsItem).filter_by(url_hash=_hash("https://a.test/1")).one()

        persist_items(
            session,
            [
                _raw(
                    "https://b.test/2",
                    title="Apple warns on profit for the quarter - GlobeNewswire",
                    tickers=["AAPL_US_EQ"],
                )
            ],
            classifier=classify,
            report=report,
            instrument=instrument,
        )
        session.flush()
        copy = session.query(NewsItem).filter_by(url_hash=_hash("https://b.test/2")).one()

        assert copy is not original
        assert copy.materiality == original.materiality
        assert copy.direction == original.direction
        assert copy.engine == original.engine
        assert copy.relevant == original.relevant
        assert copy.relevance_reason == original.relevance_reason
        assert copy.url == "https://b.test/2"
        assert copy.tickers == ["AAPL_US_EQ"]


class TestWhenTheVerdictMustNotBeReused:
    """The half that keeps the saving honest."""

    def test_another_instruments_verdict_is_not_borrowed(self, session):
        """`is_about_this_company` is answered against a subject.

        A headline judged for Apple is not an answer about Microsoft, so the second
        instrument's copy has to be classified on its own terms.
        """
        apple = _instrument(session, "AAPL_US_EQ")
        microsoft = _instrument(session, "MSFT_US_EQ")
        classify, asked = _counting_classifier()
        report = NewsIngestReport()

        title = "Apple warns on profit for the quarter - Yahoo Finance"
        persist_items(
            session,
            [_raw("https://a.test/1", title=title, tickers=["AAPL_US_EQ"])],
            classifier=classify,
            report=report,
            instrument=apple,
        )
        session.flush()

        persist_items(
            session,
            [_raw("https://b.test/2", title=title, tickers=["MSFT_US_EQ"])],
            classifier=classify,
            report=report,
            instrument=microsoft,
        )
        session.flush()

        assert len(asked) == 2, "the second instrument's copy is its own question"
        assert report.reused == 0

    def test_a_different_headline_is_classified(self, session):
        instrument = _instrument(session)
        classify, asked = _counting_classifier()
        report = NewsIngestReport()

        persist_items(
            session,
            [
                _raw(
                    "https://a.test/1",
                    title="Apple warns on profit for the quarter - Yahoo Finance",
                    tickers=["AAPL_US_EQ"],
                ),
                _raw(
                    "https://b.test/2",
                    title="Microsoft raises its dividend for the year - Yahoo Finance",
                    tickers=["AAPL_US_EQ"],
                ),
            ],
            classifier=classify,
            report=report,
            instrument=instrument,
        )
        session.flush()

        assert len(asked) == 2
        assert report.reused == 0

    def test_a_row_that_was_never_classified_is_not_a_source_of_truth(self, session):
        """`engine IS NULL` means nobody judged it, which is not a verdict to copy."""
        instrument = _instrument(session)
        title = "Apple warns on profit for the quarter - Yahoo Finance"

        # Stored without a classifier, so it has no engine.
        persist_items(
            session,
            [_raw("https://a.test/1", title=title, tickers=["AAPL_US_EQ"])],
            classifier=None,
            report=NewsIngestReport(),
            instrument=instrument,
        )
        session.flush()
        assert session.query(NewsItem).filter_by(url_hash=_hash("https://a.test/1")).one().engine is None

        classify, asked = _counting_classifier()
        report = NewsIngestReport()
        persist_items(
            session,
            [
                _raw(
                    "https://b.test/2",
                    title="Apple warns on profit for the quarter - GlobeNewswire",
                    tickers=["AAPL_US_EQ"],
                )
            ],
            classifier=classify,
            report=report,
            instrument=instrument,
        )
        session.flush()

        assert len(asked) == 1
        assert report.classified == 1
        assert report.reused == 0

    def test_without_an_instrument_nothing_is_reused(self, session):
        """A caller with no subject has no basis for saying a verdict transfers."""
        instrument = _instrument(session)
        classify, _asked = _counting_classifier()
        persist_items(
            session,
            [
                _raw(
                    "https://a.test/1",
                    title="Apple warns on profit for the quarter - Yahoo Finance",
                    tickers=["AAPL_US_EQ"],
                )
            ],
            classifier=classify,
            report=NewsIngestReport(),
            instrument=instrument,
        )
        session.flush()

        report = NewsIngestReport()
        persist_items(
            session,
            [
                _raw(
                    "https://b.test/2",
                    title="Apple warns on profit for the quarter - GlobeNewswire",
                    tickers=["AAPL_US_EQ"],
                )
            ],
            classifier=classify,
            report=report,
            instrument=None,
        )
        session.flush()

        assert report.reused == 0
        assert report.classified == 1


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_headline_does_not_crash_the_key(blank: str):
    assert title_key(blank) == title_key("")

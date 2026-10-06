"""What the news poll says while it is running.

The reader's report: *"news_rss only returns a start INFO and then goes silent."* The
job runs for hours over a 500-instrument universe and wrote exactly one line at the
start, so a working run and a hung one looked identical for the whole of it -- which is
the same failure the per-job progress log was built to end, in the one loop that never
got a note.

Two throttles, and the tests are about why there are two rather than one.
"""

from __future__ import annotations

import pytest

from awltux.ingest import news


@pytest.fixture
def notes(monkeypatch) -> list[str]:
    """Capture `progress.note` instead of writing a log file per test."""
    captured: list[str] = []
    monkeypatch.setattr(news.progress, "note", captured.append)
    return captured


def _raw(index: int):
    from awltux.providers.news_rss import RawNewsItem

    return RawNewsItem(
        title=f"Acme story {index}",
        url=f"https://example.test/{index}",
        source="test",
        tickers=["ACME_US_EQ"],
    )


def _classifier(**updates):
    def classify(item, instrument):
        return {
            "materiality": "material",
            "direction": "negative",
            "reasoning": "a claim about the share price",
            "is_about_this_company": True,
            **updates,
        }

    return classify


class TestTheArticleThrottle:
    def test_a_line_lands_every_tenth_article(self, session, notes):
        news.persist_items(
            session,
            [_raw(i) for i in range(25)],
            classifier=_classifier(),
        )

        assert [note.split()[0] for note in notes] == ["10", "20"]

    def test_it_reports_what_the_run_has_done_not_only_how_far_it_is(self, session, notes):
        """A count with no outcome is a heartbeat; the outcome is what says it works."""
        news.persist_items(session, [_raw(i) for i in range(10)], classifier=_classifier())

        assert "articles" in notes[0]
        assert "new" in notes[0] and "classified" in notes[0]

    def test_a_run_shorter_than_the_throttle_says_nothing(self, session, notes):
        """Deliberately silent rather than noisy: the closing INFO line already reports
        the totals, and a line per article on a short poll is worse than none."""
        news.persist_items(session, [_raw(i) for i in range(9)], classifier=_classifier())

        assert notes == []

    def test_the_count_keeps_climbing_across_batches(self, session, notes):
        """The throttle is on the run's total, not on each call.

        The poll calls `persist_items` once per instrument, so a counter that restarted
        at every feed would emit a line only for instruments carrying ten or more new
        stories -- which is to say, almost never. It works because the caller threads
        one report through every call, so the test does the same.
        """
        report = news.NewsIngestReport()
        for batch in range(3):
            news.persist_items(
                session,
                [_raw(batch * 4 + i) for i in range(4)],
                classifier=_classifier(),
                report=report,
            )

        assert [note.split()[0] for note in notes] == ["10"], (
            "12 articles across three feeds is one line, at the tenth"
        )
        assert report.fetched == 12

    def test_a_fresh_report_restarts_the_count(self, session, notes):
        """The other side of the same coin, stated so the dependency is not a surprise:
        the throttle lives on the report, so a caller that does not share one gets a
        line per batch instead of one per run."""
        for batch in range(2):
            news.persist_items(
                session,
                [_raw(batch * 10 + i) for i in range(10)],
                classifier=_classifier(),
            )

        assert [note.split()[0] for note in notes] == ["10", "10"]

    def test_it_names_the_instrument_when_one_is_given(self, session, notes):
        """The instrument is free here and is the thing a reader checking a specific
        feed wants to see."""
        session.add(_instrument("ACME_US_EQ"))
        session.flush()

        news.persist_items(
            session,
            [_raw(i) for i in range(10)],
            classifier=_classifier(),
            instrument=session.get(news.Instrument, "ACME_US_EQ"),
        )

        assert "ACME_US_EQ" in notes[0]


class TestTheInstrumentThrottle:
    """A second throttle, because the article count can stand still for a long time.

    `gather_for_instrument` makes one to three requests and can come back with nothing
    new. During a stretch like that no article count moves, so an article-only line goes
    quiet in exactly the case that most looks like a hang.
    """

    def test_the_loop_reports_instrument_position(self, session, notes, monkeypatch):
        instruments = [_instrument(f"T{i:03d}_US_EQ") for i in range(news.PROGRESS_EVERY_INSTRUMENTS)]
        for row in instruments:
            session.add(row)
        session.flush()

        monkeypatch.setattr(
            news, "gather_for_instrument", lambda instrument, **kwargs: []
        )
        monkeypatch.setattr(news, "RssNewsProvider", _stub_provider)
        monkeypatch.setattr(news, "FinnhubNewsProvider", _stub_provider)
        monkeypatch.setattr(news, "MarketauxNewsProvider", _stub_provider)

        from awltux.config import get_settings

        news.ingest_rss_news(session, settings=get_settings(), classifier=None)

        assert any("instruments" in note for note in notes), notes
        assert f"{news.PROGRESS_EVERY_INSTRUMENTS} of" in notes[0]

    def test_an_empty_stretch_still_produces_a_line(self, session, notes, monkeypatch):
        """The property that matters: silence is bounded by instruments, not by news."""
        for index in range(news.PROGRESS_EVERY_INSTRUMENTS * 2):
            session.add(_instrument(f"T{index:03d}_US_EQ"))
        session.flush()

        monkeypatch.setattr(news, "gather_for_instrument", lambda instrument, **kwargs: [])
        monkeypatch.setattr(news, "RssNewsProvider", _stub_provider)
        monkeypatch.setattr(news, "FinnhubNewsProvider", _stub_provider)
        monkeypatch.setattr(news, "MarketauxNewsProvider", _stub_provider)

        from awltux.config import get_settings

        news.ingest_rss_news(session, settings=get_settings(), classifier=None)

        assert len(notes) >= 2, "two full instrument batches with no news at all"


class _stub_provider:
    """A provider that answers nothing and needs no credential."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def close(self) -> None:
        pass


def _instrument(ticker: str):
    from tests.helpers import make_instrument

    return make_instrument(ticker, name=ticker)

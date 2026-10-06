"""The news poll's cursor: where it resumes, and how it wraps.

The reader's question: *"Does this restart from the beginning of the list each time it
runs? Could it keep a progress counter so that it picks up from where it left off"* --
and then, *"resetting the counter once it gets to the end"*.

Both are the same mechanism. Ordering the walk by a per-instrument timestamp makes each
run continue where the last stopped, and makes the sweep wrap on its own: once every row
carries a stamp, the least recently polled is the one that was polled first last time.

The property these tests exist for is the one that cannot be seen from a green suite --
`news_rss` had **0 successful runs in 7 attempts** and takes hours, so "did this run
resume" is only answerable by asserting the order.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.ingest import news
from awltux.timezones import as_utc


class _NoProvider:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def poll(monkeypatch):
    """Run `ingest_rss_news` with the network removed, recording the order walked."""
    walked: list[str] = []

    def gather(instrument, **kwargs):
        walked.append(instrument.t212_ticker)
        return []

    monkeypatch.setattr(news, "gather_for_instrument", gather)
    monkeypatch.setattr(news, "RssNewsProvider", _NoProvider)
    monkeypatch.setattr(news, "FinnhubNewsProvider", _NoProvider)
    monkeypatch.setattr(news, "MarketauxNewsProvider", _NoProvider)

    def run(session):
        from awltux.config import get_settings

        walked.clear()
        news.ingest_rss_news(session, settings=get_settings(), classifier=None)
        return list(walked)

    return run


def _instrument(ticker: str, *, polled_at: dt.datetime | None = None):
    from tests.helpers import make_instrument

    instrument = make_instrument(ticker, name=ticker)
    instrument.news_polled_at = polled_at
    return instrument


class TestTheOrder:
    def test_never_polled_instruments_go_first(self, session, poll):
        """A universe that has never been polled is all nulls, and the first run is the
        one that has to cover the whole list."""
        now = dt.datetime.now(dt.UTC)
        session.add(_instrument("POLLED_US_EQ", polled_at=now - dt.timedelta(hours=1)))
        session.add(_instrument("NEVER_US_EQ"))
        session.flush()

        assert poll(session) == ["NEVER_US_EQ", "POLLED_US_EQ"]

    def test_the_least_recently_polled_goes_first(self, session, poll):
        now = dt.datetime.now(dt.UTC)
        session.add(_instrument("RECENT_US_EQ", polled_at=now - dt.timedelta(minutes=5)))
        session.add(_instrument("STALE_US_EQ", polled_at=now - dt.timedelta(hours=3)))
        session.add(_instrument("MIDDLE_US_EQ", polled_at=now - dt.timedelta(hours=1)))
        session.flush()

        assert poll(session) == ["STALE_US_EQ", "MIDDLE_US_EQ", "RECENT_US_EQ"]

    def test_a_run_continues_where_the_last_one_stopped(self, session, poll):
        """The property the reader asked for, and the one an interrupted run depends on.

        Nothing about the *articles* changes between the two runs here: the instruments
        whose feeds carried nothing are still at the front after the first sweep, which
        is exactly the case that would starve them under a cursor derived from stored
        news. The cursor records attempts, not results.
        """
        for index in range(4):
            session.add(_instrument(f"T{index}_US_EQ"))
        session.flush()

        first = poll(session)
        # Simulate the run being interrupted after two instruments by putting the
        # cursor back where a killed run would have left it.
        for ticker in first[:2]:
            session.get(news.Instrument, ticker).news_polled_at = None
        session.flush()

        second = poll(session)

        assert second[:2] == first[:2], "the two unpolled instruments resume first"

    def test_the_sweep_wraps_once_it_reaches_the_end(self, session, poll):
        """No counter is reset and none needs to be: after one full sweep the oldest
        stamp is the one taken first, so the next run starts at the same place."""
        for index in range(4):
            session.add(_instrument(f"T{index}_US_EQ"))
        session.flush()

        first = poll(session)
        second = poll(session)

        assert len(first) == 4
        assert second == first, "the walk should have wrapped to the beginning"

    def test_every_instrument_is_stamped_by_a_run(self, session, poll):
        session.add(_instrument("A_US_EQ"))
        session.add(_instrument("B_US_EQ"))
        session.flush()

        poll(session)

        stamps = [
            as_utc(session.get(news.Instrument, ticker).news_polled_at)
            for ticker in ("A_US_EQ", "B_US_EQ")
        ]
        assert all(stamp is not None for stamp in stamps)

    def test_a_rationed_poll_still_advances(self, session, poll, monkeypatch):
        """`limit_instruments` prioritises held names, and the obvious implementation
        re-sorts by ticker -- which would start every rationed run at the same
        instrument and leave the cursor frozen."""
        for index in range(4):
            session.add(_instrument(f"T{index}_US_EQ"))
        session.flush()

        walked: list[str] = []
        monkeypatch.setattr(
            news,
            "gather_for_instrument",
            lambda instrument, **kwargs: walked.append(instrument.t212_ticker) or [],
        )
        from awltux.config import get_settings

        news.ingest_rss_news(session, settings=get_settings(), classifier=None, limit_instruments=2)
        first = list(walked)

        walked.clear()
        news.ingest_rss_news(session, settings=get_settings(), classifier=None, limit_instruments=2)

        assert first == ["T0_US_EQ", "T1_US_EQ"]
        assert walked == ["T2_US_EQ", "T3_US_EQ"], "the second rationed run must move on"

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


class TestStoppingTheWalk:
    """`awltux quiet` has to reach inside a walk that is already running.

    The walk is hours long, so a `quiet` that only paused scheduling waited for the
    whole of it and the rebuild killed the run anyway. These pin where it leaves and
    what it leaves behind: the instrument it finished is stamped and committed, the
    ones it never started are not stamped, and no provider request is spent on an
    instrument the walk was never going to poll.
    """

    def _walk(self, monkeypatch, session, *, stop_after: int, early_persist: bool = False):
        """Run the poll, requesting a stop once ``stop_after`` instruments are gathered."""
        from awltux.config import get_settings
        from awltux.scheduler import progress

        walked: list[str] = []

        def gather(instrument, **kwargs):
            walked.append(instrument.t212_ticker)
            if len(walked) >= stop_after:
                progress.request_stop()
            return []

        monkeypatch.setattr(news, "gather_for_instrument", gather)
        monkeypatch.setattr(news, "RssNewsProvider", _NoProvider)
        monkeypatch.setattr(news, "FinnhubNewsProvider", _NoProvider)
        monkeypatch.setattr(news, "MarketauxNewsProvider", _NoProvider)

        if early_persist:
            # The mid-feed case: `persist_items` leaves without raising so that the
            # articles already classified are still committed by the caller.
            def persist(session_, items, *, classifier=None, report=None, instrument=None):
                report.stopped_early = True
                return report

            monkeypatch.setattr(news, "persist_items", persist)

        with pytest.raises(progress.Stopped):
            news.ingest_rss_news(session, settings=get_settings(), classifier=None)

        return walked

    def _stamps(self, session, tickers) -> dict[str, dt.datetime | None]:
        from awltux.db import Instrument

        rows = (
            session.query(Instrument)
            .filter(Instrument.t212_ticker.in_(list(tickers)))
            .all()
        )
        return {row.t212_ticker: row.news_polled_at for row in rows}

    def test_it_leaves_at_the_instrument_boundary_and_spends_nothing_further(
        self, session, monkeypatch
    ):
        from awltux.scheduler import progress

        for ticker in ("A_US_EQ", "B_US_EQ", "C_US_EQ"):
            session.add(_instrument(ticker))
        session.flush()

        walked = self._walk(monkeypatch, session, stop_after=1)

        assert walked == ["A_US_EQ"], "no request is spent on an instrument it will not poll"
        assert progress.stop_requested() is True

    def test_the_instrument_it_finished_is_stamped_and_the_rest_are_not(
        self, session, monkeypatch
    ):
        """The cursor must advance over exactly what was polled, no more.

        A stamp is the record that an instrument was polled. Stamping one the walk never
        reached would drop its stories until the sweep came round -- an hour on an
        hourly interval, and up to a full pass over the universe.
        """
        for ticker in ("A_US_EQ", "B_US_EQ", "C_US_EQ"):
            session.add(_instrument(ticker))
        session.flush()

        self._walk(monkeypatch, session, stop_after=1)

        stamps = self._stamps(session, ("A_US_EQ", "B_US_EQ", "C_US_EQ"))

        assert stamps["A_US_EQ"] is not None, "the instrument that was polled is stamped"
        assert stamps["B_US_EQ"] is None
        assert stamps["C_US_EQ"] is None

    def test_leaving_part_way_through_a_feed_does_not_stamp_that_instrument(
        self, session, monkeypatch
    ):
        """The half-read feed is polled again first next run.

        `stopped_early` means the rest of that instrument's articles were never read, so
        the cursor must not claim it was done -- the articles already written are
        committed either way, and re-polling costs nothing because a stored story is
        recognised by its `url_hash` and is not classified twice.
        """
        for ticker in ("A_US_EQ", "B_US_EQ"):
            session.add(_instrument(ticker))
        session.flush()

        self._walk(monkeypatch, session, stop_after=1, early_persist=True)

        stamps = self._stamps(session, ("A_US_EQ", "B_US_EQ"))

        assert stamps["A_US_EQ"] is None, "a half-read feed is not a polled instrument"
        assert stamps["B_US_EQ"] is None, "and the walk never reached this one"


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

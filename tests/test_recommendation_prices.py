"""The one-day change on the recommendations table, which prices it reads.

The column is `(newest close - the close before it) / the close before it`, and the query
behind it was rewritten on 2026-10-20: it ranked all **241,000** `price_bar` rows with a
window function and filtered to the top two afterwards (369 ms), where three correlated seeks
per instrument do the same work in **3.5 ms**.

That is a rewrite of the only query that answers "which bars are the newest", and nothing in
the suite asserted the column -- so these tests pin the three answers it can give: a pair of
bars, one bar, and no bars at all.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.web import queries
from tests.helpers import make_bars, make_instrument

TICKER = "PRICE_US_EQ"


def _instrument(session, ticker: str = TICKER) -> None:
    session.add(make_instrument(ticker))
    session.flush()


def _bars(session, closes: list[float], *, ticker: str = TICKER, start=None) -> None:
    session.add_all(
        make_bars(
            ticker,
            closes,
            start=start or (dt.date.today() - dt.timedelta(days=len(closes) + 2)),
        )
    )
    session.flush()


def _row(session, ticker: str = TICKER) -> queries.RecommendationRow:
    rows, _ = queries.recommendations(session)
    return next(row for row in rows if row.ticker == ticker)


class TestTheOneDayChange:
    def test_it_uses_the_newest_two_bars_not_the_first_two(self, session):
        """Three bars, so a query that took the oldest pair would be visible.

        10 -> 20 -> 30 is +100% from the first pair and **+50%** from the last pair, and the
        table means the last pair: the change is "today against yesterday".
        """
        _instrument(session)
        _bars(session, [10.0, 20.0, 30.0])

        row = _row(session)

        assert row.price == pytest.approx(30.0)
        assert row.change_pct == pytest.approx(50.0)

    def test_one_bar_is_a_price_with_no_change(self, session):
        """`None`, not zero: a first observation is not a flat day."""
        _instrument(session)
        _bars(session, [42.0])

        row = _row(session)

        assert row.price == pytest.approx(42.0)
        assert row.change_pct is None
        assert row.price_at is not None, "the freshness gate reads the bar's date"

    def test_no_bars_is_no_price_and_no_change(self, session):
        _instrument(session)

        row = _row(session)

        assert row.price is None
        assert row.change_pct is None
        assert row.price_at is None

    def test_the_bar_date_reaches_the_freshness_gate(self, session):
        """`price_at` is midnight UTC of the newest bar's date, which is what the gate ages.

        The same rule as `decision/service.py`: a daily bar is dated by its session, so its
        age is measured from midnight rather than from when it was fetched.
        """
        _instrument(session)
        _bars(session, [10.0, 11.0], start=dt.date(2026, 5, 1))

        row = _row(session)

        assert row.price_at == dt.datetime(2026, 5, 2, tzinfo=dt.UTC)

    def test_each_instrument_gets_its_own_pair(self, session):
        """The property the window function had to hold too: partitioning, not a global rank.

        Two instruments with different series -- if the query ranked globally, the second one
        would borrow the first one's bars and report a change it never had.
        """
        _instrument(session)
        _bars(session, [10.0, 20.0, 30.0])
        session.add(make_instrument("OTHER_US_EQ", isin="US0000000002", yahoo_symbol="OTHER"))
        session.flush()
        _bars(session, [100.0, 50.0], ticker="OTHER_US_EQ")

        other = _row(session, "OTHER_US_EQ")

        assert other.price == pytest.approx(50.0)
        assert other.change_pct == pytest.approx(-50.0)

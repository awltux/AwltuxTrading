"""A sector's price line: the arithmetic, the job that stores it, and the page that draws it.

The average cannot be an average of prices: a £30 share and a 3,000p share are not on the
same scale, and a sector's constituents report in different currencies. So the line is an
index -- each instrument rebased to 100 at its first bar in the window, the level the mean of
those ratios -- and the tests here pin the three properties that make it readable: a price
level cannot dominate, changing membership cannot move the line, and no FX rate is involved.

Stored rather than derived on the page, because deriving it means reading every constituent's
bars: measured 2026-10-08 on the live database, 20,753 rows and 135 ms for Information
Technology, 61,728 and 445 ms for the unclassified bucket.
"""

from __future__ import annotations

import datetime as dt

from awltux.analysis.sectors import index_from_closes
from awltux.db import PriceBar, SectorPriceIndex
from awltux.ingest.jobs import SECTOR_INDEX_DAYS, rebuild_sector_index
from tests.helpers import make_instrument

DAY = dt.date(2026, 10, 1)


def _closes(*rows: tuple[str, int, float]) -> list[tuple[str, dt.date, float]]:
    return [(ticker, DAY + dt.timedelta(days=day), close) for ticker, day, close in rows]


class TestTheArithmetic:
    def test_a_high_priced_share_cannot_dominate(self):
        """The reason for rebasing rather than averaging: 1000p beside 10p is not an average.

        Both instruments rise 50%, so the index must rise 50% however far apart their price
        levels are.
        """
        series = index_from_closes(
            _closes(
                ("BIG_US_EQ", 0, 1000.0),
                ("SMALL_US_EQ", 0, 10.0),
                ("BIG_US_EQ", 1, 1500.0),
                ("SMALL_US_EQ", 1, 15.0),
            )
        )

        assert [round(level, 4) for _, level, _ in series] == [100.0, 150.0]

    def test_a_share_that_falls_drags_the_index_with_its_weight(self):
        series = index_from_closes(
            _closes(
                ("A_US_EQ", 0, 100.0),
                ("B_US_EQ", 0, 20.0),
                ("A_US_EQ", 1, 200.0),
                ("B_US_EQ", 1, 20.0),
            )
        )

        assert round(series[1][1], 4) == 150.0, "a doubling and a flat are a 50% mean"

    def test_a_constituent_listing_mid_window_joins_at_its_own_hundred(self):
        """It must not move the line by its price level when it appears.

        A raw mean of closes would put this day at (55 + 900) / 2 = 477.5. Rebased, the new
        instrument contributes exactly 1.0 -- it dilutes the mean toward 100 rather than
        dragging it to its own scale -- and from then on it moves the line with its own return.
        """
        series = index_from_closes(
            _closes(
                ("OLD_US_EQ", 0, 50.0),
                ("OLD_US_EQ", 1, 55.0),
                ("NEW_US_EQ", 1, 900.0),
                ("OLD_US_EQ", 2, 55.0),
                ("NEW_US_EQ", 2, 990.0),
            )
        )

        assert [round(level, 4) for _, level, _ in series] == [100.0, 105.0, 110.0]
        assert [contributors for _, _, contributors in series] == [1, 2, 2]

    def test_a_missing_bar_narrows_the_mean_rather_than_counting_as_zero(self):
        series = index_from_closes(
            _closes(
                ("A_US_EQ", 0, 100.0),
                ("B_US_EQ", 0, 100.0),
                ("A_US_EQ", 1, 200.0),
                ("A_US_EQ", 2, 200.0),
                ("B_US_EQ", 2, 100.0),
            )
        )

        by_date = {date: (round(level, 4), contributors) for date, level, contributors in series}
        assert by_date[DAY + dt.timedelta(days=1)] == (200.0, 1), "only A traded"
        assert by_date[DAY + dt.timedelta(days=2)] == (150.0, 2)

    def test_currencies_cancel_because_only_the_ratio_is_used(self):
        """One instrument in pounds and one in pence, both up 10%.

        Nothing here needs an FX rate: each ratio is dimensionless, and pence against pounds
        is a constant factor that cancels inside it.
        """
        series = index_from_closes(
            _closes(
                ("GBP_US_EQ", 0, 12.0),
                ("GBX_EQ", 0, 1200.0),
                ("GBP_US_EQ", 1, 13.2),
                ("GBX_EQ", 1, 1320.0),
            )
        )

        assert round(series[1][1], 4) == 110.0

    def test_a_zero_or_negative_close_drops_that_instrument_that_day(self):
        """A zero would divide the instrument out of every later date, and a negative one
        would invert it -- both silently."""
        series = index_from_closes(
            _closes(
                ("A_US_EQ", 0, 100.0),
                ("B_US_EQ", 0, 100.0),
                ("A_US_EQ", 1, 0.0),
                ("B_US_EQ", 1, 110.0),
                ("A_US_EQ", 2, -5.0),
                ("B_US_EQ", 2, 121.0),
            )
        )

        by_date = {date: (round(level, 4), contributors) for date, level, contributors in series}
        assert by_date[DAY + dt.timedelta(days=1)] == (110.0, 1)
        assert by_date[DAY + dt.timedelta(days=2)] == (121.0, 1)

    def test_nothing_to_index_is_an_empty_series(self):
        assert index_from_closes([]) == []


class TestTheJob:
    def _sector(self, session, ticker: str, group: str | None, closes: list[float]):
        session.add(make_instrument(ticker, sector_group=group, yahoo_symbol=ticker))
        session.flush()
        for offset, close in enumerate(closes):
            session.add(
                PriceBar(
                    instrument_t212_ticker=ticker,
                    date=DAY + dt.timedelta(days=offset),
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adj_close=close,
                    volume=1_000.0,
                    currency="USD",
                    raw_currency="USD",
                    raw_multiplier=1.0,
                    raw_close=close,
                    source="test",
                    source_rank=20,
                )
            )
        session.flush()

    def test_a_row_per_day_per_sector_with_its_basis(self, session):
        self._sector(session, "A_US_EQ", "Energy", [100.0, 110.0, 121.0])
        self._sector(session, "B_US_EQ", "Energy", [10.0, 10.0, 10.0])
        session.commit()

        result = rebuild_sector_index()

        rows = (
            session.query(SectorPriceIndex)
            .filter_by(sector="Energy")
            .order_by(SectorPriceIndex.date)
            .all()
        )
        assert len(rows) == 3, result.detail
        assert [round(row.level, 4) for row in rows] == [100.0, 105.0, 110.5]
        assert rows[0].base_date == DAY
        assert all(row.contributors == 2 for row in rows)
        assert result.items_written == 3

    def test_an_instrument_with_no_group_is_indexed_as_unclassified(self, session):
        """One of the eleven is not the only bucket: 174 in-universe instruments have no
        group at all, and they have a page."""
        self._sector(session, "A_US_EQ", None, [100.0, 200.0])
        session.commit()

        rebuild_sector_index()

        rows = session.query(SectorPriceIndex).filter_by(sector="Unclassified").all()
        assert len(rows) == 2

    def test_a_second_run_replaces_the_series_rather_than_extending_it(self, session):
        """The base date is the oldest bar in the window, so rows from two runs are on
        different bases and must never be plotted as one line."""
        self._sector(session, "A_US_EQ", "Energy", [100.0, 110.0])
        session.commit()

        rebuild_sector_index()
        first = session.query(SectorPriceIndex).filter_by(sector="Energy").all()

        # The window slides: a newer bar arrives, so the base moves with it.
        session.add(
            PriceBar(
                instrument_t212_ticker="A_US_EQ",
                date=DAY + dt.timedelta(days=2),
                open=121.0, high=121.0, low=121.0, close=121.0, adj_close=121.0,
                volume=1_000.0, currency="USD", raw_currency="USD", raw_multiplier=1.0,
                raw_close=121.0, source="test", source_rank=20,
            )
        )
        session.commit()
        rebuild_sector_index()

        rows = (
            session.query(SectorPriceIndex)
            .filter_by(sector="Energy")
            .order_by(SectorPriceIndex.date)
            .all()
        )
        assert len(rows) == 3, "still one row per day, not the previous run's plus this one"
        assert rows[0].base_date == DAY
        assert len(first) == 2

    def test_a_sector_with_no_bars_is_named_rather_than_written(self, session):
        self._sector(session, "A_US_EQ", "Energy", [100.0])
        self._sector(session, "B_US_EQ", "Utilities", [])
        session.commit()

        result = rebuild_sector_index()

        assert "Utilities" in result.detail["skipped"]
        assert session.query(SectorPriceIndex).filter_by(sector="Utilities").count() == 0

    def test_the_scope_is_ignored_because_an_index_needs_the_whole_sector(self, session):
        """A refresh of one company must not rewrite the sector's line from one constituent."""
        self._sector(session, "A_US_EQ", "Energy", [100.0, 110.0])
        self._sector(session, "B_US_EQ", "Energy", [50.0, 55.0])
        session.commit()

        rebuild_sector_index(["A_US_EQ"])

        rows = session.query(SectorPriceIndex).filter_by(sector="Energy").all()
        assert len(rows) == 2
        assert all(row.contributors == 2 for row in rows), "both constituents, not the scope"

    def test_nothing_stored_is_explained_rather_than_reported_as_zero(self, session):
        result = rebuild_sector_index()

        assert result.items_written == 0
        assert result.note is not None
        assert "no sector" in result.note

    def test_the_window_is_the_same_length_the_instrument_page_charts(self):
        assert SECTOR_INDEX_DAYS == 400


class TestThePage:
    def _indexed(self, session, sector: str = "Energy"):
        session.add(make_instrument("A_US_EQ", sector_group=sector, yahoo_symbol="A"))
        session.flush()
        for offset, level in enumerate((100.0, 105.0, 110.0)):
            session.add(
                SectorPriceIndex(
                    sector=sector,
                    date=DAY + dt.timedelta(days=offset),
                    level=level,
                    contributors=7,
                    base_date=DAY,
                )
            )
        session.commit()

    def test_the_page_draws_the_line_it_has(self, client, session):
        self._indexed(session)

        body = client.get("/sectors/Energy").text

        assert 'id="sector-chart"' in body
        assert "data-series='[100.0, 105.0, 110.0]'" in body
        assert "Index level 100 on 2026-10-01" in body
        assert "7 instruments" in body
        assert "no dividends" in body

    def test_a_sector_with_no_line_says_which_job_produces_it(self, client, session):
        session.add(make_instrument("A_US_EQ", sector_group="Energy", yahoo_symbol="A"))
        session.commit()

        body = client.get("/sectors/Energy").text

        assert 'id="sector-chart"' not in body
        assert "sector_index" in body
        assert "price_eod" in body

"""Storing a price series, and refusing one whose unit contradicts the instrument's.

The bug these guard, reported 2026-10-09: ``VWRLl_EQ`` showed a last close of **1.41 GBP**
against a true **141.30**, and its price chart drew a flat line pinned to the axis because the
broker's own trade markers (136.92, 99.05) stretched the scale. Every refresh re-fetched it and
re-applied the same conversion, so a refresh could never fix it.

The cause was the unit: ``refresh_prices`` fetches in batches, and a batch used the ``.L``
suffix convention -- "LSE means pence" -- as the unit for every symbol in the request. An LSE
line *can* be quoted in a major unit, and this ETF is: Yahoo's own metadata says ``GBP``, and
Trading 212's ``currencyCode`` for the instrument says ``GBP``. The stored bars said ``GBX``
with a 0.01 multiplier, and the row was still labelled ``GBP`` afterwards, so nothing looked
wrong.

Measured across the 488 instruments holding prices: 482 agreed with the broker's currency code
and six did not. Three of those six were this 100x error -- ``VWRLl_EQ`` (GBP),
``AEEEl_EQ`` (EUR) and ``RNEWl_EQ`` (USD) -- and three were LSE shells whose stored close is
~1e-5 with no conversion at all, which is a different question and is queued in ``TODO.md``.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from awltux.db import Instrument, InstrumentBlocker, PriceBar
from awltux.ingest.prices import (
    JOB,
    refresh_prices,
    store_bar_series,
)
from awltux.providers.yahoo import Bar, BarSeries
from tests.helpers import make_instrument


def _blockers(session) -> list[InstrumentBlocker]:
    """The blockers this job still holds, oldest first.

    Unresolved only: `clear_blocker` stamps `resolved_at` rather than deleting the row, so an
    instrument that was fixed keeps the record of having been broken.
    """
    return list(
        session.execute(
            select(InstrumentBlocker)
            .where(InstrumentBlocker.job == JOB)
            .where(InstrumentBlocker.resolved_at.is_(None))
            .order_by(InstrumentBlocker.id)
        ).scalars()
    )

#: The instrument as the broker describes it: quoted in **pounds**, which is what the pipeline
#: has to believe. Its sibling below is quoted in pence, which is the ordinary LSE case.
POUNDS = "VWRLl_EQ"
PENCE = "VODl_EQ"


def _series(symbol: str, *, currency: str, multiplier: float, close: float) -> BarSeries:
    series = BarSeries(
        symbol=symbol, currency="GBP", raw_currency=currency, raw_multiplier=multiplier
    )
    series.bars.append(
        Bar(
            date=dt.date(2026, 6, 1),
            open=close,
            high=close,
            low=close,
            close=close * multiplier,
            adj_close=close * multiplier,
            volume=1_000.0,
        )
    )
    return series


def _instruments(session) -> None:
    session.add(
        make_instrument(
            POUNDS,
            name="Vanguard FTSE All-World",
            currency_code="GBP",
            yahoo_symbol="VWRL.L",
            exchange_name="LSE",
        )
    )
    session.add(
        make_instrument(
            PENCE,
            name="Vodafone",
            currency_code="GBX",
            yahoo_symbol="VOD.L",
            exchange_name="LSE",
        )
    )
    session.commit()


class TestTheStoreRefusesAUnitItCannotReconcile:
    def test_a_pence_priced_instrument_stores_its_conversion(self, session):
        """The case that was always right: 64.25 pence is £0.6425, and the row proves it."""
        _instruments(session)

        written = store_bar_series(
            session,
            session.get(Instrument, PENCE),
            _series("VOD.L", currency="GBp", multiplier=0.01, close=64.25),
        )
        session.commit()

        assert written == 1
        row = session.execute(select(PriceBar).where(PriceBar.instrument_t212_ticker == PENCE)).scalar_one()
        assert row.close == pytest.approx(0.6425)
        assert row.raw_multiplier == pytest.approx(0.01)
        assert row.raw_close == pytest.approx(64.25)

    def test_a_pound_priced_instrument_is_refused_when_the_bars_say_pence(self, session):
        """The bug, refused at the point of storing. A £141.30 unit price arriving with a 0.01
        multiplier is 100x wrong and entirely plausible-looking, so it is not stored at all --
        the instrument is left visibly unpriced, and the run says which one and why."""
        _instruments(session)

        written = store_bar_series(
            session,
            session.get(Instrument, POUNDS),
            _series("VWRL.L", currency="GBX", multiplier=0.01, close=141.30),
        )
        session.commit()

        assert written == 0
        assert session.execute(select(PriceBar)).scalars().all() == [], "nothing stored"

    def test_the_refusal_is_recorded_against_the_instrument_and_the_run(self, session):
        """Visible twice, because either alone is easy to miss: a blocker on the instrument
        (which the Operations page reports) and a count in the run's own report."""
        from awltux.ingest.prices import PriceIngestReport

        _instruments(session)
        report = PriceIngestReport()

        store_bar_series(
            session,
            session.get(Instrument, POUNDS),
            _series("VWRL.L", currency="GBX", multiplier=0.01, close=141.30),
            report=report,
        )
        session.commit()

        assert report.tickers_unit_mismatch == [POUNDS]
        assert report.as_dict()["unit_mismatch_count"] == 1
        blockers = _blockers(session)
        assert [blocker.instrument_t212_ticker for blocker in blockers] == [POUNDS]
        assert "out by 100x" in blockers[0].reason

    def test_a_stored_series_clears_a_blocker_a_previous_run_recorded(self, session):
        """The lifecycle in one place: whatever refused it, a series that stores clears it."""
        _instruments(session)
        store_bar_series(
            session,
            session.get(Instrument, POUNDS),
            _series("VWRL.L", currency="GBX", multiplier=0.01, close=141.30),
        )
        session.commit()
        assert _blockers(session)

        store_bar_series(
            session,
            session.get(Instrument, POUNDS),
            _series("VWRL.L", currency="GBP", multiplier=1.0, close=141.30),
        )
        session.commit()

        assert _blockers(session) == []

    def test_an_instrument_with_no_currency_code_is_not_refused(self, session):
        """The check needs something to compare against. Without a broker code there is no
        statement about the unit to contradict, and refusing would drop prices for an
        instrument we simply have no record for."""
        session.add(
            make_instrument(
                "UNKNOWNl_EQ",
                currency_code=None,
                yahoo_symbol="UNK.L",
                exchange_name="LSE",
            )
        )
        session.commit()

        written = store_bar_series(
            session,
            session.get(Instrument, "UNKNOWNl_EQ"),
            _series("UNK.L", currency="GBp", multiplier=0.01, close=50.0),
        )

        assert written == 1


class TestTheRefreshTellsTheProviderTheUnit:
    """`refresh_prices` is the only thing that writes bars, so this is where the unit has to
    come from. The provider is *told* rather than asked: a batch cannot say."""

    def test_every_instrument_s_own_currency_code_is_what_the_provider_is_given(
        self, session, monkeypatch
    ):
        _instruments(session)
        asked: dict = {}

        class RecordingProvider:
            def get_history_batch(self, symbols, *, period="2y", interval="1d", currencies=None):
                asked.update({"symbols": list(symbols), "currencies": dict(currencies or {})})
                return {
                    "VWRL.L": _series(
                        "VWRL.L", currency="GBP", multiplier=1.0, close=141.30
                    ),
                    "VOD.L": _series("VOD.L", currency="GBp", multiplier=0.01, close=64.25),
                }

        refresh_prices(
            session,
            tickers=[POUNDS, PENCE],
            provider=RecordingProvider(),
            update_turnover=False,
        )

        assert asked["currencies"] == {"VWRL.L": "GBP", "VOD.L": "GBX"}
        assert sorted(asked["symbols"]) == ["VOD.L", "VWRL.L"]

    def test_the_bars_land_at_the_right_magnitude_for_both(self, session):
        """End to end through the store: a £141.30 ETF and a 64.25p share, in one run, each
        read in its own unit."""
        _instruments(session)

        class Provider:
            def get_history_batch(self, symbols, *, period="2y", interval="1d", currencies=None):
                return {
                    "VWRL.L": _series("VWRL.L", currency="GBP", multiplier=1.0, close=141.30),
                    "VOD.L": _series("VOD.L", currency="GBp", multiplier=0.01, close=64.25),
                }

        report = refresh_prices(
            session, tickers=[POUNDS, PENCE], provider=Provider(), update_turnover=False
        )
        session.commit()

        closes = {
            row.instrument_t212_ticker: row.close
            for row in session.execute(select(PriceBar)).scalars().all()
        }
        assert closes[POUNDS] == pytest.approx(141.30)
        assert closes[PENCE] == pytest.approx(0.6425)
        assert report.tickers_unit_mismatch == []

class TestTheJobTheRefreshButtonRuns:
    """`refresh_prices_eod` is what the scheduler and the instrument page's Refresh button run,
    and it fetches in its own batch loop rather than through `refresh_prices`. It is the path
    the reported bug came down, so it is the one that has to be tested -- `refresh_prices` is
    only used by the CLI and by tests."""

    def test_the_units_reach_the_provider_from_the_job_too(self, session, monkeypatch):
        _instruments(session)
        asked: dict = {}

        class RecordingProvider:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def get_history_batch(self, symbols, *, period="2y", interval="1d", currencies=None):
                asked.update({"currencies": dict(currencies or {})})
                return {}

        monkeypatch.setattr("awltux.providers.yahoo.YahooProvider", RecordingProvider)

        from awltux.ingest.jobs import refresh_prices_eod

        refresh_prices_eod(tickers=[POUNDS, PENCE])

        assert asked["currencies"] == {"VWRL.L": "GBP", "VOD.L": "GBX"}, (
            "the job has to pass the broker's own unit, or the provider falls back to the "
            ".L suffix and divides a pound-quoted ETF by 100"
        )


class TestTheRunLineSaysWhatWasRefused:
    def test_a_unit_refusal_is_named_in_the_run_report(self):
        """The runner's one-line outcome is what a reader sees on the Operations page; a
        refusal that only appears in the JSON detail is a refusal nobody notices."""
        from awltux.scheduler.outcomes import outcome

        text = outcome(
            job="price_eod",
            detail={
                "tickers_requested": 40,
                "tickers_returned": 39,
                "bars_written": 19_500,
                "unit_mismatch_count": 1,
                "unit_mismatch": ["VWRLl_EQ"],
                "failed_count": 0,
            },
        )

        assert "1 refused as a unit mismatch (VWRLl_EQ)" in text
        assert "returned nothing" not in text, "the provider answered; it was refused"


class TestTheRecordOutlivesTheRefreshThatRewritesIt:
    def test_a_refresh_rewrites_a_row_the_bug_wrote(self, session):
        """Why a refresh could not fix it and now can: the same source rank is not *higher*
        than what is stored, so the row is overwritten -- with the right unit this time."""
        _instruments(session)
        store_bar_series(
            session,
            session.get(Instrument, POUNDS),
            _series("VWRL.L", currency="GBX", multiplier=0.01, close=141.30),
        )
        session.commit()
        assert session.execute(select(PriceBar)).scalars().all() == [], (
            "the wrong-unit series was refused, so start from a row that was stored"
        )

        # The row as the bug left it: written before the guard existed.
        session.add(
            PriceBar(
                instrument_t212_ticker=POUNDS,
                date=dt.date(2026, 6, 1),
                close=1.413,
                raw_close=141.30,
                currency="GBP",
                raw_currency="GBX",
                raw_multiplier=0.01,
                source="yahoo",
                source_rank=20,
            )
        )
        session.commit()

        class Provider:
            def get_history_batch(self, symbols, *, period="2y", interval="1d", currencies=None):
                return {"VWRL.L": _series("VWRL.L", currency="GBP", multiplier=1.0, close=141.30)}

        refresh_prices(session, tickers=[POUNDS], provider=Provider(), update_turnover=False)
        session.commit()

        row = session.execute(select(PriceBar).where(PriceBar.instrument_t212_ticker == POUNDS)).scalar_one()
        assert row.close == pytest.approx(141.30)
        assert row.raw_multiplier == 1.0

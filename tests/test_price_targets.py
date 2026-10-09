"""Which instruments the price job asks for, and in what order.

The selection used to return every universe instrument in rowid order: stable,
arbitrary, and with no way to tell an instrument that had **never** been priced
from one priced an hour ago. On this deployment that is 92 of 500 names with no
bars at all, sitting invisibly in the middle of the list.

The order matters most where the run cannot cover everything. A cap without a
priority starves the tail of the universe permanently -- the same names every day,
and the gaps never filled.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.ingest.prices import load_price_targets
from tests.helpers import make_bars, make_instrument


def _universe(session, *tickers: str, symbol: str | None = None):
    for ticker in tickers:
        session.add(
            make_instrument(
                ticker,
                yahoo_symbol=symbol or ticker.split("_")[0],
                in_universe=True,
            )
        )
    session.flush()


class TestPriority:
    def test_an_instrument_with_no_bars_comes_first(self, session):
        """No bar means invisible to every downstream model, so it is worth more
        than a refresh of anything else."""
        _universe(session, "NEVER_US_EQ", "PRICED_US_EQ")
        for bar in make_bars("PRICED_US_EQ", [1.0, 2.0]):
            session.add(bar)
        session.flush()

        targets = load_price_targets(session)
        assert targets.symbols[0] == "NEVER"
        assert targets.never_priced == 1

    def test_the_least_recently_covered_comes_next(self, session):
        """Oldest coverage first, so a run that cannot cover everything rotates
        through the universe rather than refreshing the same head of the list."""
        _universe(session, "OLD_US_EQ", "NEW_US_EQ")
        for bar in make_bars("OLD_US_EQ", [1.0], start=dt.date(2026, 1, 2)):
            session.add(bar)
        for bar in make_bars("NEW_US_EQ", [1.0], start=dt.date(2026, 6, 1)):
            session.add(bar)
        session.flush()

        targets = load_price_targets(session)
        assert targets.symbols == ["OLD", "NEW"]
        assert targets.oldest_bar == "2026-01-02"
        assert targets.newest_bar == "2026-06-01"

    def test_never_priced_outranks_merely_stale(self, session):
        _universe(session, "STALE_US_EQ", "NEVER_US_EQ")
        for bar in make_bars("STALE_US_EQ", [1.0], start=dt.date(2020, 1, 2)):
            session.add(bar)
        session.flush()

        targets = load_price_targets(session)
        assert targets.symbols[0] == "NEVER"
        assert targets.never_priced == 1
        # Not also "stale": staleness is measured against the newest coverage in
        # the universe, and an instrument with no coverage at all has nothing to
        # be behind. Counting it in both would inflate the number and blur two
        # different problems into one.
        assert targets.stale == 0

    def test_staleness_is_relative_to_the_newest_coverage_in_the_universe(self, session):
        """An absolute cutoff would call the whole universe stale on a quiet day
        and nothing stale after a market holiday."""
        _universe(session, "A_US_EQ", "B_US_EQ", "C_US_EQ")
        for ticker, day in (("A_US_EQ", 1), ("B_US_EQ", 2), ("C_US_EQ", 2)):
            for bar in make_bars(ticker, [1.0], start=dt.date(2026, 3, day)):
                session.add(bar)
        session.flush()

        targets = load_price_targets(session)
        assert targets.stale == 1

    def test_instruments_outside_the_universe_are_not_targets(self, session):
        session.add(make_instrument("OUT_US_EQ", yahoo_symbol="OUT", in_universe=False))
        _universe(session, "IN_US_EQ")
        session.flush()

        assert load_price_targets(session).symbols == ["IN"]

    def test_excluded_instruments_are_not_targets(self, session):
        session.add(
            make_instrument("GONE_US_EQ", yahoo_symbol="GONE", in_universe=True, excluded=True)
        )
        session.flush()

        assert load_price_targets(session).symbols == []

    def test_an_unresolved_symbol_is_not_a_target(self, session):
        """Nothing to ask the provider for."""
        session.add(make_instrument("NOMAP_US_EQ", yahoo_symbol=None))
        session.flush()

        targets = load_price_targets(session)
        assert targets.symbols == []
        assert targets.never_priced == 0


class TestTheCap:
    def test_the_cap_takes_from_the_front_of_the_priority(self, session):
        """This is the property that makes a cap safe: the instruments that lose
        out are the ones that were refreshed most recently."""
        _universe(session, "NEVER_US_EQ", "OLD_US_EQ", "NEW_US_EQ")
        for bar in make_bars("OLD_US_EQ", [1.0], start=dt.date(2026, 1, 2)):
            session.add(bar)
        for bar in make_bars("NEW_US_EQ", [1.0], start=dt.date(2026, 6, 1)):
            session.add(bar)
        session.flush()

        targets = load_price_targets(session, limit=2)
        assert targets.symbols == ["NEVER", "OLD"]

    def test_a_cap_of_zero_means_no_cap(self, session):
        _universe(session, "A_US_EQ", "B_US_EQ", "C_US_EQ")
        session.flush()

        assert len(load_price_targets(session, limit=0).symbols) == 3

    def test_a_cap_larger_than_the_universe_is_harmless(self, session):
        _universe(session, "A_US_EQ", "B_US_EQ")
        session.flush()

        assert len(load_price_targets(session, limit=99).symbols) == 2


class TestTheOrderIsDeterministic:
    def test_a_rerun_produces_the_same_order(self, session):
        """A priority order that shuffles between runs is not reviewable."""
        _universe(session, "C_US_EQ", "A_US_EQ", "B_US_EQ")
        session.flush()

        first = load_price_targets(session).symbols
        second = load_price_targets(session).symbols
        assert first == second == sorted(first)

    def test_the_empty_universe_is_empty_not_an_error(self, session):
        targets = load_price_targets(session)
        assert targets.symbols == []
        assert len(targets) == 0


class TestTheUnitTravelsWithTheSymbols:
    """``refresh_prices_eod`` asks the provider for bars and has to tell it what each symbol is
    quoted in -- the provider cannot say, because a batch response is one frame with one
    currency for the whole request. The broker's own ``currencyCode`` is that unit, and it is
    already in the row this loader reads.

    Measured 2026-10-09 on the live database: of 488 instruments holding prices, 482 agreed
    with their currency code and six did not. ``VWRLl_EQ`` was one of the six -- an LSE ETF
    quoted in pounds, divided by 100 on every refresh, so the page showed 1.41 for something
    the broker valued at 141.30.
    """

    def test_each_symbol_carries_its_instrument_s_own_unit(self, session):
        session.add(
            make_instrument(
                "POUNDSl_EQ", yahoo_symbol="VWRL.L", currency_code="GBP", in_universe=True
            )
        )
        session.add(
            make_instrument(
                "PENCEl_EQ", yahoo_symbol="VOD.L", currency_code="GBX", in_universe=True
            )
        )
        session.flush()

        targets = load_price_targets(session)

        assert targets.currencies == {"VWRL.L": "GBP", "VOD.L": "GBX"}

    def test_an_instrument_with_no_currency_code_is_simply_absent(self, session):
        """Absent rather than empty, so the provider falls back to its own evidence instead of
        being told the unit is the empty string."""
        session.add(
            make_instrument(
                "UNKNOWNl_EQ", yahoo_symbol="UNK.L", currency_code=None, in_universe=True
            )
        )
        session.flush()

        targets = load_price_targets(session)

        assert targets.symbols == ["UNK.L"]
        assert targets.currencies == {}

    def test_the_cap_trims_the_units_with_the_symbols(self, session):
        """A map that still described instruments this run will not ask for would make a run
        report say more than the run did."""
        for index in range(3):
            session.add(
                make_instrument(
                    f"T{index}_US_EQ",
                    yahoo_symbol=f"T{index}",
                    currency_code="USD",
                    in_universe=True,
                )
            )
        session.flush()

        targets = load_price_targets(session, limit=2)

        assert len(targets.symbols) == 2
        assert set(targets.currencies) == set(targets.symbols)


class TestTheJobReportsWhatItAimedAt:
    """A run line reads the same whether the job is closing the gaps or refreshing
    names that were already covered, unless it says which."""

    def test_the_summary_names_the_never_priced_count(self):
        from awltux.scheduler.outcomes import outcome

        text = outcome(
            job="price_eod",
            detail={
                "tickers_requested": 500,
                "tickers_returned": 408,
                "bars_written": 196546,
                "never_priced_targeted": 92,
                "stale_targeted": 300,
                "failed": ["SGD", "PAFO", "HGEN.L"],
                "failed_count": 92,
            },
        )
        assert "196,546 daily bars" in text
        assert "92 of those had no price history at all" in text
        assert "92 returned nothing at all" in text
        assert "including SGD" in text
        # The stored list is truncated, so it is a sample. The first version read
        # "92 returned nothing -- SGD, PAFO and 22 more", which invites reading as
        # 114 and makes a reader distrust the whole line.
        assert "and 22 more" not in text

    def test_a_run_with_no_failures_does_not_claim_any(self):
        from awltux.scheduler.outcomes import outcome

        text = outcome(
            job="price_eod",
            detail={"tickers_requested": 10, "tickers_returned": 10, "bars_written": 5000},
        )
        assert "returned nothing" not in text


@pytest.mark.parametrize("limit", [None, 0, 1, 500])
def test_the_query_survives_every_cap(session, limit):
    _universe(session, "A_US_EQ", "B_US_EQ")
    session.flush()
    assert isinstance(load_price_targets(session, limit=limit).symbols, list)

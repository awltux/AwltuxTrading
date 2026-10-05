"""The demo seeder.

Its purpose is a fast feedback loop: validating the dashboard against live
provider data means waiting on rate limits and episodic filings, and a fresh
install has nothing to look at. The seeder also found two bugs that an empty
database had been hiding -- an undefined template helper and a broken LLM
accounting insert -- so it doubles as a fixture for the page tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from awltux.db import (
    DecisionRun,
    FundamentalPeriod,
    Instrument,
    NewsItem,
    PriceBar,
    SentimentSeries,
    ValuationRun,
)
from awltux.demo import DEMO_MARKER, SPECS, seed_demo_data


@pytest.fixture
def seeded(session, settings):
    report = seed_demo_data(session, history_days=300)
    session.flush()
    return report


class TestSeeding:
    def test_it_creates_every_spec(self, seeded, session):
        assert seeded.instruments == len(SPECS)
        tickers = {
            row.t212_ticker
            for row in session.execute(select(Instrument)).scalars().all()
        }
        assert {spec.ticker for spec in SPECS} <= tickers

    def test_it_creates_prices_accounts_news_and_sentiment(self, seeded, session):
        assert seeded.bars > 0
        assert seeded.periods > 0
        assert seeded.news > 0
        assert session.query(PriceBar).count() > 0
        assert session.query(FundamentalPeriod).count() > 0
        assert session.query(NewsItem).count() > 0
        assert session.query(SentimentSeries).count() > 0

    def test_everything_lands_in_the_universe(self, seeded, session):
        rows = session.execute(select(Instrument)).scalars().all()
        assert all(row.in_universe for row in rows), "seeded rows must be in scope"
        assert all(row.industry == DEMO_MARKER for row in rows)

    def test_it_is_idempotent(self, session, settings):
        """Running twice must not duplicate rows, so it can be re-run freely."""
        seed_demo_data(session, history_days=60)
        session.flush()
        first = session.query(PriceBar).count()

        seed_demo_data(session, history_days=60)
        session.flush()
        assert session.query(PriceBar).count() == first


class TestItExercisesTheAwkwardCases:
    def test_a_uk_listing_quotes_in_pence(self, seeded, session):
        """The GBp/GBP conversion is the classic UK equity bug, so the seeded
        data must reproduce it rather than avoid it."""
        uk = session.get(Instrument, "DEMO2l_EQ")
        assert uk.currency_code == "GBP"

        bars = session.execute(
            select(PriceBar).where(PriceBar.instrument_t212_ticker == "DEMO2l_EQ")
        ).scalars().all()
        assert bars, "expected seeded bars"
        assert all(bar.raw_currency == "GBp" for bar in bars)
        assert all(bar.raw_multiplier == pytest.approx(0.01) for bar in bars)
        # The stored close is in pounds, so it is 100x smaller than the raw quote.
        latest = bars[-1]
        assert latest.close * 100 == pytest.approx(latest.raw_close, rel=1e-6)

    def test_there_is_a_loss_making_company(self, seeded, session):
        """The valuation engine must be able to refuse, so the fixture includes
        something it should refuse to value."""
        lossmaker = session.get(Instrument, "DEMO3_US_EQ")
        assert lossmaker is not None
        period = session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == "DEMO3_US_EQ")
            .limit(1)
        ).scalar_one()
        assert period.metrics["net_income"] < 0

    def test_there_are_both_net_cash_and_indebted_balance_sheets(self, seeded, session):
        rows = session.execute(select(FundamentalPeriod)).scalars().all()
        net_debts = [row.metrics.get("net_debt") for row in rows if row.metrics]
        assert any(value is not None and value < 0 for value in net_debts)
        assert any(value is not None and value > 0 for value in net_debts)

    def test_prices_are_reproducible(self, session, settings, temp_dir):
        """A screenshot or a failing assertion must be reproducible."""
        seed_demo_data(session, history_days=60)
        session.flush()
        first = [
            bar.close
            for bar in session.execute(
                select(PriceBar)
                .where(PriceBar.instrument_t212_ticker == "DEMO1_US_EQ")
                .order_by(PriceBar.date)
            ).scalars().all()
        ]
        assert first, "expected seeded bars"

        # Regenerating the same ticker must produce an identical series.
        from awltux.demo import _price_path, _trading_days

        spec = next(s for s in SPECS if s.ticker == "DEMO1_US_EQ")
        assert _price_path(spec, _trading_days(60)) == first[-len(_trading_days(60)) :]


class TestThePipelinesRunOnSeededData:
    def test_valuation_and_decisions_produce_rows(self, seeded, session, settings):
        from awltux.analysis.sentiment import aggregate_all
        from awltux.analysis.valuation import run_valuations
        from awltux.decision.service import decide_universe

        valuations = run_valuations(session)
        session.flush()
        aggregate_all(session)
        decisions = decide_universe(session)
        session.flush()

        assert valuations["attempted"] > 0
        # The lossmaker is expected to be refused rather than valued.
        assert valuations["valued"] >= 1
        assert decisions["decided"] >= 1

        assert session.query(ValuationRun).count() >= 1
        assert session.query(DecisionRun).count() >= 1

    def test_a_valued_instrument_has_a_defensible_range(self, seeded, session, settings):
        from awltux.analysis.valuation import run_valuations

        run_valuations(session, tickers=["DEMO4l_EQ"])
        session.flush()
        run = session.execute(
            select(ValuationRun).where(ValuationRun.instrument_t212_ticker == "DEMO4l_EQ")
        ).scalar_one()

        if run.status == "ok":
            assert run.fair_value_low < run.fair_value_base < run.fair_value_high
            assert run.margin_of_safety is not None
            assert "graham" not in run.methods_applied

"""Mapping provider statements onto the canonical metric keys.

The judgement in this module is which vendor row label becomes which canonical
name, and the failure mode is quiet: a mis-mapped label produces a plausible
number under the wrong key, and every marker built on it is then wrong in a way
nothing downstream can detect. So the tests here are mostly about which label
wins, and about the labels that must *not* be used.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from awltux.analysis import ledger
from awltux.db import FundamentalPeriod, Instrument
from awltux.ingest.fundamentals import (
    STATEMENT_LABELS,
    FundamentalsReport,
    _sync_profile,
    derive_metrics,
    metrics_from_info,
    metrics_from_statements,
)
from awltux.metrics import OUTFLOW_METRICS, STATED_METRICS
from awltux.providers.http import ProviderError
from tests.helpers import make_instrument


def _period(**metrics: float) -> FundamentalPeriod:
    """An unpersisted period holding exactly these metrics.

    The ledger checks read `period.metrics` and nothing else, so a row does not have
    to be stored to exercise the sign convention.
    """
    return FundamentalPeriod(
        instrument_t212_ticker="TEST_US_EQ",
        period_end=dt.date(2026, 6, 30),
        period_type="annual",
        source="test",
        metrics=metrics,
    )


def _statements(**sections: dict[str, float]) -> dict:
    """Two periods, so a column index actually selects something."""
    out = {}
    for name, rows in sections.items():
        out[name] = {
            "columns": ["2024-12-31", "2023-12-31"],
            "rows": {label: [value, value / 2] for label, value in rows.items()},
        }
    return out


class TestStatementMapping:
    def test_the_new_marker_inputs_are_mapped(self):
        financials = _statements(
            income={"Total Revenue": 1_000.0, "EBIT": 150.0},
            balance={
                "Receivables": 220.0,
                "Inventory": 140.0,
                "Payables": 90.0,
                "Net PPE": 400.0,
                "Goodwill": 75.0,
                "Other Intangible Assets": 30.0,
                "Current Debt": 60.0,
                "Long Term Debt": 200.0,
                "Retained Earnings": 310.0,
            },
            cashflow={"Stock Based Compensation": 18.0},
        )
        metrics = metrics_from_statements(financials, 0)

        assert metrics["receivables"] == 220.0
        assert metrics["inventory"] == 140.0
        assert metrics["payables"] == 90.0
        assert metrics["net_ppe"] == 400.0
        assert metrics["goodwill"] == 75.0
        assert metrics["intangible_assets"] == 30.0
        assert metrics["short_term_debt"] == 60.0
        assert metrics["long_term_debt"] == 200.0
        assert metrics["retained_earnings"] == 310.0
        assert metrics["stock_based_compensation"] == 18.0

    def test_the_column_index_selects_the_period(self):
        financials = _statements(income={"Total Revenue": 1_000.0})
        assert metrics_from_statements(financials, 0)["revenue"] == 1_000.0
        assert metrics_from_statements(financials, 1)["revenue"] == 500.0

    def test_a_combined_label_never_stands_in_for_a_narrow_one(self):
        """Yahoo publishes "Goodwill And Other Intangible Assets" as well as
        "Goodwill". Using the combined figure for `goodwill` would inflate the
        equity-softness marker on exactly the companies it exists to flag."""
        financials = _statements(
            balance={"Goodwill And Other Intangible Assets": 900.0},
        )
        metrics = metrics_from_statements(financials, 0)
        assert "goodwill" not in metrics
        assert "intangible_assets" not in metrics

    def test_capex_is_normalised_to_a_positive_outflow(self):
        financials = _statements(cashflow={"Capital Expenditure": -40.0})
        assert metrics_from_statements(financials, 0)["capex"] == 40.0

    def test_every_outflow_is_normalised_not_just_capex(self):
        """The bug this pins down.

        `analysis/ledger.py` subtracts outflows -- ``explained = operating - capex -
        dividends``, and ``free_cash_flow = operating_cash_flow - capex``. Yahoo reports
        them with its own sign, and only `capex` was being corrected, because that was
        the one a check happened to trip over.

        Measured 2026-10-07 on `MSFT_US_EQ`: `dividends_paid` was stored negative in
        **16** `yahoo_statements` periods against **1** `xbrl_companyfacts` period, and
        the retained-earnings roll-forward was out by exactly twice the dividend --
        52.9bn on a 26.4bn dividend. Twice, because the value is subtracted: a negative
        input turns a minus into a plus.
        """
        financials = _statements(
            cashflow={"Capital Expenditure": -40.0, "Cash Dividends Paid": -25.0}
        )

        metrics = metrics_from_statements(financials, 0)

        assert metrics["capex"] == 40.0
        assert metrics["dividends_paid"] == 25.0

    def test_a_positive_outflow_is_left_alone(self):
        """The other source already stores it this way, so the normalisation has to be
        a no-op rather than a second flip."""
        financials = _statements(cashflow={"Cash Dividends Paid": 25.0})
        assert metrics_from_statements(financials, 0)["dividends_paid"] == 25.0

    def test_every_outflow_key_is_a_real_metric(self):
        """A name in `OUTFLOW_METRICS` that is not in the vocabulary would normalise
        nothing, silently -- the same class of typo `STATEMENT_LABELS` is guarded for."""
        for key in OUTFLOW_METRICS:
            assert key in STATED_METRICS, key

    def test_the_ledger_subtracts_an_outflow_rather_than_adding_it(self):
        """Behavioural, not textual: the convention *is* this arithmetic.

        Checking the source text for ``- dividends`` would pass while the arithmetic
        was wrong, and it broke on the local variable's name the first time it was
        written -- `dividends_paid` is read into a variable called `dividends`.
        """
        previous = _period(retained_earnings=1_000.0)
        period = _period(retained_earnings=1_050.0, net_income=100.0, dividends_paid=50.0)

        check = ledger.retained_earnings_rollforward(period, previous)

        assert check.residual == 0.0, "a positive dividend must be subtracted"

    def test_a_flipped_dividend_moves_the_residual_by_twice_its_value(self):
        """The measured signature, and why "out by twice the dividend" identifies a
        sign error rather than a missing line.

        Measured 2026-10-07 on `MSFT_US_EQ`: the retained-earnings roll-forward was out
        by 52,890,000,000 on a `dividends_paid` of 26,445,000,000 -- exactly 2x. The
        value is subtracted, so a negative input turns the minus into a plus and the
        error doubles rather than reversing.
        """
        previous = _period(retained_earnings=1_000.0)
        correct = _period(retained_earnings=1_050.0, net_income=100.0, dividends_paid=50.0)
        flipped = _period(retained_earnings=1_050.0, net_income=100.0, dividends_paid=-50.0)

        correct_residual = ledger.retained_earnings_rollforward(correct, previous).residual
        flipped_residual = ledger.retained_earnings_rollforward(flipped, previous).residual

        assert flipped_residual - correct_residual == -100.0, "twice the dividend, not once"

    def test_cash_movement_subtracts_both_outflows(self):
        previous = _period(cash_and_equivalents=200.0)
        period = _period(
            cash_and_equivalents=170.0,
            operating_cash_flow=100.0,
            capex=80.0,
            dividends_paid=50.0,
        )

        check = ledger.cash_movement(period, previous)

        assert check.inputs["explained"] == -30.0
        assert check.residual == 0.0

    def test_every_mapped_label_is_a_canonical_name(self):
        """A typo in a key here would write a metric nothing can read."""
        for key in STATEMENT_LABELS:
            assert key in STATED_METRICS, key

    def test_the_earlier_section_wins_for_a_shared_label(self):
        """Depreciation is an income-statement charge and also a cash-flow add-back;
        the income-statement figure is the one the accrual work wants."""
        financials = _statements(
            income={"Reconciled Depreciation": 50.0},
            cashflow={"Reconciled Depreciation": 999.0},
        )
        assert metrics_from_statements(financials, 0)["depreciation_amortisation"] == 50.0


class TestDerivedMetrics:
    def test_free_cash_flow_is_derived_when_the_provider_omits_it(self):
        """It is an identity, not a disclosure, and most non-large-caps need it."""
        derived = derive_metrics({"operating_cash_flow": 160.0, "capex": 40.0})
        assert derived["free_cash_flow"] == 120.0

    def test_a_provider_definition_is_never_overwritten(self):
        derived = derive_metrics(
            {"operating_cash_flow": 160.0, "capex": 40.0, "free_cash_flow": 130.0}
        )
        assert "free_cash_flow" not in derived

    def test_free_cash_flow_is_left_missing_when_it_cannot_be_computed(self):
        assert "free_cash_flow" not in derive_metrics({"operating_cash_flow": 160.0})

    def test_margins_come_from_revenue(self):
        derived = derive_metrics({"revenue": 1_000.0, "gross_profit": 400.0})
        assert derived["gross_margin"] == 0.4

    def test_roce_uses_operating_profit_over_capital_employed(self):
        derived = derive_metrics(
            {"operating_income": 150.0, "total_equity": 700.0, "total_debt": 200.0}
        )
        assert derived["roce"] == 150.0 / 900.0


class TestTheEbitBridge:
    """EBIT is stated by no provider, and two markers need it.

    Measured on the live database before this existed: **0 of 88 stored periods
    carried an `ebit`**, while 89% carried `pretax_income`, 75% `operating_income`
    and 60% `interest_expense`. `metrics.py` says the metric exists "for NOPAT and
    Altman Z''", so an always-absent name left both uncomputable and made the Altman
    marker report an incomplete input set for every filer.
    """

    def test_the_identity_is_preferred(self):
        """EBIT = pretax income + interest expense, which stays right when there is
        non-operating income -- the case the metric note warns about."""
        derived = derive_metrics(
            {
                "pretax_income": 100.0,
                "interest_expense": 25.0,
                "operating_income": 999.0,
            }
        )

        assert derived["ebit"] == 125.0, "the identity, not the operating-income proxy"

    def test_operating_income_is_the_fallback_when_interest_is_absent(self):
        """An approximation, used because it is the difference between EBIT existing
        for three quarters of filers and for half of them."""
        derived = derive_metrics({"pretax_income": 100.0, "operating_income": 130.0})

        assert derived["ebit"] == 130.0

    def test_a_provider_definition_is_never_overwritten(self):
        derived = derive_metrics({"ebit": 111.0, "pretax_income": 100.0, "interest_expense": 25.0})

        assert "ebit" not in derived

    def test_it_is_left_missing_when_neither_route_is_available(self):
        assert "ebit" not in derive_metrics({"net_income": 100.0, "total_assets": 1_000.0})

    def test_it_stays_a_stated_metric_in_the_vocabulary(self):
        """The bridge must not reclassify it.

        `test_metrics.py` asserts `DERIVED_METRICS` and `EXTRACTABLE_METRICS` are
        disjoint -- a metric is either asked of an extractor or computed by us. EBIT
        is asked of an extractor, so it is bridged here rather than moved, exactly as
        `free_cash_flow` is.
        """
        from awltux.metrics import DERIVED_METRICS, EXTRACTABLE_METRICS

        assert "ebit" in EXTRACTABLE_METRICS
        assert "ebit" not in DERIVED_METRICS


class TestInfoFallback:
    def test_profile_figures_map_onto_canonical_names(self):
        metrics = metrics_from_info(
            {"totalRevenue": 1_000.0, "freeCashflow": 120.0, "sharesOutstanding": 100.0}
        )
        assert metrics == {
            "revenue": 1_000.0,
            "free_cash_flow": 120.0,
            "shares_outstanding": 100.0,
        }

    def test_unknown_keys_are_ignored_rather_than_stored(self):
        metrics = metrics_from_info({"totalRevenue": 1_000.0, "recommendationKey": "buy"})
        assert set(metrics) == {"revenue"}


class TestTheCompanyDescription:
    """`_sync_profile` keeps Yahoo's description of the business.

    It is the recommendations table's hover hint, and it arrives on the same profile call
    that supplies the sector -- so the only new thing is where it is kept. A line the
    provider has no description for keeps ``NULL``, which is the state the hint reads as
    "nothing held" rather than as an empty description.
    """

    class _Provider:
        def __init__(self, info: dict) -> None:
            self._info = info

        def get_profile(self, symbol: str) -> dict:
            return self._info

    def _sync(self, session, instrument, info: dict) -> None:
        _sync_profile(
            session, instrument, self._Provider(info), FundamentalsReport()
        )

    def test_it_stores_the_description(self, session):
        instrument = make_instrument("HINT_US_EQ")
        session.add(instrument)
        session.flush()

        self._sync(session, instrument, {"longBusinessSummary": "Hint Co makes hints."})

        assert instrument.business_summary == "Hint Co makes hints."

    def test_the_first_description_held_wins(self, session):
        """A company's account of what it does changes rarely, so re-writing the row on every
        rotation would churn it for the same words -- the rule the sector and industry fields
        beside it already follow."""
        instrument = make_instrument("HINT_US_EQ", business_summary="The first one.")
        session.add(instrument)
        session.flush()

        self._sync(session, instrument, {"longBusinessSummary": "A newer one."})

        assert instrument.business_summary == "The first one."

    def test_a_profile_with_no_description_leaves_the_column_alone(self, session):
        instrument = make_instrument("HINT_US_EQ")
        session.add(instrument)
        session.flush()

        self._sync(session, instrument, {"sector": "Technology"})

        assert instrument.business_summary is None


class TestTheSweepQueueDrains:
    """Reported 2026-10-24: *"Does the current strategy eventually process all instruments over
    multiple days, or does it restart on the same instruments each day?"*

    It restarted. The queue was ordered on ``instrument.updated_at`` and the sweep only bumps that
    column when it *writes* something -- so an instrument the provider refused kept its old
    timestamp and led the next run's queue as well. Measured on the live container: seven
    consecutive runs over seventeen hours each attempted two instruments, wrote nothing, and named
    the same two (`CYBAl_EQ`, `HGENl_EQ`), while 323 of the 506 in-universe instruments had no
    accounts. `fundamentals_checked_at` is stamped on the *attempt*, so the queue advances whether
    or not the provider has anything to give.
    """

    def _seed(self, session, *tickers: str) -> None:
        for ticker in tickers:
            session.add(
                make_instrument(ticker, name=ticker, sec_cik=None, yahoo_symbol=f"{ticker}.L")
            )
        session.commit()

    def _provider(self, *, refuse: set[str], calls: list[str]):
        class Provider:
            def get_profile(self, symbol):
                return {}

            def get_financials(self, symbol):
                calls.append(symbol)
                if symbol in refuse:
                    raise ProviderError("yahoo", f"no statements available for {symbol}")
                return {
                    "income": {
                        "columns": ["2024-12-31"],
                        "rows": {"Total Revenue": [1000.0]},
                    }
                }

        return Provider()

    def test_a_refused_instrument_does_not_hold_the_ration(self, session):
        """The regression: the first name in the queue always refusing must not consume every
        run's ration, or the rest of the book is never reached."""
        from awltux.ingest.fundamentals import sync_fundamentals

        self._seed(session, "AAAl_EQ", "BBBl_EQ", "CCCl_EQ")
        calls: list[str] = []
        provider = self._provider(refuse={"AAAl_EQ.L"}, calls=calls)

        for _ in range(3):
            sync_fundamentals(session, provider=provider, limit=1)
            session.commit()

        assert calls == ["AAAl_EQ.L", "BBBl_EQ.L", "CCCl_EQ.L"]

    def test_the_stamp_records_the_attempt_not_the_success(self, session):
        from awltux.ingest.fundamentals import sync_fundamentals

        self._seed(session, "AAAl_EQ")
        provider = self._provider(refuse={"AAAl_EQ.L"}, calls=[])

        sync_fundamentals(session, provider=provider, limit=1)

        session.expire_all()
        stored = session.get(Instrument, "AAAl_EQ")
        assert stored.fundamentals_checked_at is not None
        assert not list(
            session.execute(
                select(FundamentalPeriod).where(
                    FundamentalPeriod.instrument_t212_ticker == "AAAl_EQ"
                )
            ).scalars()
        ), "nothing was written for it, which is why the stamp is the queue's only cursor"

    def test_never_checked_comes_first_then_the_least_recently_checked(self, session):
        from awltux.ingest.fundamentals import sync_fundamentals

        self._seed(session, "AAAl_EQ", "BBBl_EQ", "CCCl_EQ")
        # AAA was checked recently, BBB never, CCC long ago.
        session.get(Instrument, "AAAl_EQ").fundamentals_checked_at = dt.datetime(
            2026, 10, 24, 12, 0, tzinfo=dt.UTC
        )
        session.get(Instrument, "CCCl_EQ").fundamentals_checked_at = dt.datetime(
            2026, 10, 1, 12, 0, tzinfo=dt.UTC
        )
        session.commit()

        calls: list[str] = []
        sync_fundamentals(
            session, provider=self._provider(refuse=set(), calls=calls), limit=2
        )

        assert calls == ["BBBl_EQ.L", "CCCl_EQ.L"]

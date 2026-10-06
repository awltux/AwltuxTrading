"""The coverage column on the Operations page, and the direction it reads.

Every probe answers "how much is still missing", and the page renders that as a
sentence. The sentence was inverted: the branch that fires when work is missing read
"N of M in the universe have {thing}", so a deployment with **no accounts at all**
reported "500 of 500 in the universe have accounts stored".

That is the worst possible direction for the error. This column exists to answer
"is the pipeline working?", and it answered "yes" while every valuation on the site
was failing with "share count unavailable" -- so the page that should have prompted
an investigation instead closed it.
"""

from __future__ import annotations

import datetime as dt

from awltux.analysis.valuation import run_valuations
from awltux.scheduler.dependencies import PROBES
from tests.helpers import make_bars, make_instrument, make_period

UNIVERSE = 4


def _universe(session, *, with_periods: int = 0):
    """``UNIVERSE`` instruments in scope, with accounts on the first N of them."""
    for index in range(UNIVERSE):
        ticker = f"T{index}_US_EQ"
        session.add(make_instrument(ticker, name=f"Test {index}", yahoo_symbol=f"T{index}"))
    session.flush()

    for index in range(with_periods):
        session.add(
            make_period(
                f"T{index}_US_EQ",
                dt.date(2025, 12, 31),
                {
                    "revenue": 1_000_000.0,
                    "net_income": 100_000.0,
                    "shares_outstanding": 100_000.0,
                    "eps_diluted": 1.0,
                },
            )
        )
    session.flush()


class TestTheCoverageSentenceReadsTheRightWayRound:
    def test_nothing_covered_says_nothing_is_covered(self, session):
        """The exact state the deployment was in: four instruments, no accounts."""
        _universe(session, with_periods=0)

        coverage = PROBES["fundamentals"](session)

        assert coverage.missing == UNIVERSE
        assert f"{UNIVERSE} of {UNIVERSE}" in coverage.reason
        assert "still need" in coverage.reason
        assert "have stored accounts" not in coverage.reason, (
            "this is the inverted wording: it reports missing work as done"
        )

    def test_everything_covered_says_so(self, session):
        _universe(session, with_periods=UNIVERSE)

        coverage = PROBES["fundamentals"](session)

        assert coverage.missing == 0
        assert coverage.reason.startswith(f"all {UNIVERSE} in the universe have")

    def test_partial_coverage_names_the_gap_not_the_coverage(self, session):
        """Two of four have accounts, so two are outstanding."""
        _universe(session, with_periods=2)

        coverage = PROBES["fundamentals"](session)

        assert coverage.missing == 2
        assert coverage.reason.startswith(f"2 of {UNIVERSE}")
        assert "still need" in coverage.reason

    def test_every_probe_that_uses_the_sentence_agrees_on_its_direction(self, session):
        """Six probes share `_note`; the inversion reached all of them.

        With an empty universe of work, none of them may claim coverage.
        """
        _universe(session, with_periods=0)
        for ticker in (f"T{i}_US_EQ" for i in range(UNIVERSE)):
            session.add_all(make_bars(ticker, [10.0, 11.0]))
        session.flush()

        for job in ("fundamentals", "filings_edgar", "sentiment", "valuation", "decision"):
            coverage = PROBES[job](session)
            if coverage.missing in (None, 0):
                continue
            assert "still need" in coverage.reason, f"{job} reads as covered: {coverage.reason}"
            assert "in the universe have" not in coverage.reason, job


class TestTheGapThisWasHiding:
    def test_a_universe_with_no_accounts_values_nothing(self, session, settings):
        """Why the inverted sentence mattered: this is the state it described as
        complete. Every instrument fails, and the reason is the share count."""
        _universe(session, with_periods=0)
        for ticker in (f"T{i}_US_EQ" for i in range(UNIVERSE)):
            session.add_all(make_bars(ticker, [10.0, 11.0]))
        session.flush()

        stats = run_valuations(session, tickers=[f"T{i}_US_EQ" for i in range(UNIVERSE)])

        assert stats["valued"] == 0
        assert stats["insufficient_data"] == UNIVERSE
        # And the probe that shares the sentence must not call this covered.
        assert PROBES["valuation"](session).missing == UNIVERSE
        assert PROBES["fundamentals"](session).missing == UNIVERSE

    def test_accounts_without_a_share_count_still_value_nothing(self, session, settings):
        """The real shape of the live gap: periods exist, the share count does not.

        `_probe_fundamentals` counts instruments with a stored period, so it reports
        these as covered -- correctly, by its own definition. The valuation still
        fails, which is why the two are asserted separately rather than conflated.
        """
        _universe(session, with_periods=0)
        for ticker in (f"T{i}_US_EQ" for i in range(UNIVERSE)):
            session.add_all(make_bars(ticker, [10.0, 11.0]))
            # A period with no `shares_outstanding`: present, but unusable.
            session.add(
                make_period(
                    ticker,
                    dt.date(2025, 12, 31),
                    {"revenue": 1_000_000.0, "net_income": 100_000.0},
                )
            )
        session.flush()

        assert PROBES["fundamentals"](session).missing == 0, "periods are stored"

        stats = run_valuations(session, tickers=[f"T{i}_US_EQ" for i in range(UNIVERSE)])
        assert stats["valued"] == 0, "but nothing can be valued from them"

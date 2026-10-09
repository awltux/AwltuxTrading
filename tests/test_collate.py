"""One set of accounts per accounting year: which row stands, and what it displaced.

Measured 2026-10-09 on the live database: 394 stored rows formed 333 accounting years, and
**12 of those years held more than one source** -- 10 carrying the SEC's own tags, a Yahoo
statement and our model's reading of the same 10-K. They are not three years' accounts. These
tests pin the rule that makes them one, and the reporting that keeps the others visible.
"""

from __future__ import annotations

import datetime as dt

from awltux.analysis.collate import (
    GOVERNMENT_SOURCES,
    annual_ends,
    annual_set,
    collate,
    year_for,
)
from awltux.db.models import FundamentalPeriod


def period(
    *,
    source: str,
    period_end: dt.date,
    period_type: str = "annual",
    metrics: dict | None = None,
    id: int | None = None,
) -> FundamentalPeriod:
    """A stored row. No session: the collation is a pure function of rows."""
    row = FundamentalPeriod(
        instrument_t212_ticker="TEST_US_EQ",
        source=source,
        period_end=period_end,
        period_type=period_type,
        currency="USD",
        metrics=metrics if metrics is not None else {"revenue": 1_000.0},
        confidence=0.7,
    )
    if id is not None:
        row.id = id
    return row


JUNE_2025 = dt.date(2025, 6, 30)
JUNE_2026 = dt.date(2026, 6, 30)


class TestWhichRowStands:
    def test_the_filers_own_accounts_replace_the_other_sources(self):
        """The reader's rule: a government source takes precedence, and the others are
        replaced wholesale rather than merged in figure by figure."""
        rows = [
            period(source="yahoo_statements", period_end=JUNE_2025, metrics={"revenue": 1_000.0}),
            period(source="llm_extraction", period_end=JUNE_2025, metrics={"revenue": 1_001.0}),
            period(source="xbrl_companyfacts", period_end=JUNE_2025, metrics={"revenue": 1_002.0}),
        ]

        year = collate(rows)[0]

        assert year.chosen.source == "xbrl_companyfacts"
        assert year.chosen.metrics == {"revenue": 1_002.0}
        assert {row.source for row in year.superseded} == {"yahoo_statements", "llm_extraction"}
        assert "replace them" in year.superseded[0].reason

    def test_a_figure_only_another_source_states_is_not_merged_in(self):
        """A set of accounts no filer published. Yahoo's `total_debt` runs about 10% above the
        filer's on four of the measured years because it includes lease liabilities; taking a
        missing figure from it would assemble a statement from two definitions."""
        rows = [
            period(
                source="xbrl_companyfacts",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000.0},
            ),
            period(
                source="yahoo_statements",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000.0, "total_debt": 500.0, "ebitda": 300.0},
            ),
        ]

        year = collate(rows)[0]

        assert "total_debt" not in year.chosen.metrics
        assert year.superseded[0].only_here == ["ebitda", "total_debt"]
        assert year.excluded_figures == 2

    def test_the_annual_account_replaces_an_interim_for_the_same_year(self):
        """The reader's alignment rule: the year is populated by the quarters until the full
        year's accounts appear."""
        rows = [
            period(
                source="xbrl_companyfacts",
                period_end=dt.date(2026, 3, 31),
                period_type="quarterly",
                metrics={"revenue": 250.0},
            ),
            period(
                source="xbrl_companyfacts",
                period_end=JUNE_2026,
                metrics={"revenue": 1_000.0},
            ),
        ]

        year = collate(rows)[0]

        assert year.chosen.period_end == JUNE_2026
        assert year.provisional is False
        assert [row.period.period_type for row in year.superseded] == ["quarterly"]
        assert "replaces this quarterly" in year.superseded[0].reason

    def test_a_later_interim_replaces_the_earlier_one(self):
        rows = [
            period(
                source="yahoo_statements",
                period_end=dt.date(2026, 3, 31),
                period_type="interim",
                metrics={"revenue": 900.0},
            ),
            period(
                source="yahoo_statements",
                period_end=dt.date(2026, 6, 30),
                period_type="interim",
                metrics={"revenue": 950.0},
            ),
        ]

        year = collate(rows)[0]

        assert year.chosen.metrics["revenue"] == 950.0
        assert year.provisional is True, "no annual account of this year is held"
        assert len(year.superseded) == 1

    def test_the_full_year_wins_over_a_government_interim(self):
        """The one case where the reader's two rules conflict, and the decision.

        A filer's Q3 and a provider's annual for the same year: the slot asks for the accounts
        *of the year*, so the full year stands and the government interim is reported as
        superseded rather than quietly used. Ranking the source first instead is a one-line
        change to `_order`, and this test says which one is in force.
        """
        rows = [
            period(
                source="xbrl_companyfacts",
                period_end=dt.date(2026, 3, 31),
                period_type="quarterly",
                metrics={"revenue": 250.0},
            ),
            period(
                source="yahoo_statements",
                period_end=JUNE_2026,
                metrics={"revenue": 1_000.0},
            ),
        ]

        year = collate(rows)[0]

        assert year.chosen.source == "yahoo_statements"
        assert year.chosen.period_type == "annual"
        assert [row.source for row in year.superseded] == ["xbrl_companyfacts"]

    def test_two_government_sources_are_ordered_and_the_loser_reported(self):
        """Both are the filer's own data by different routes. Neither is dropped silently:
        the disagreement is on the year, with both figures."""
        rows = [
            year_end := period(
                source="xbrl_companyfacts",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000.0},
                id=1,
            ),
            period(
                source="companies_house_ixbrl",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000.0},
                id=2,
            ),
        ]
        assert year_end.source in GOVERNMENT_SOURCES

        year = collate(rows)[0]

        assert sum(1 for row in year.superseded if row.source in GOVERNMENT_SOURCES) == 1
        # Equal ranks are broken by id, so the choice is total rather than query-ordered.
        assert year.chosen.id == 2

    def test_a_rolling_twelve_months_never_stands_for_a_year(self):
        """`ttm` is dated at the moment it was read, not at a period end. 29 live instruments
        carry one; letting it key a slot would let a rolling aggregate displace a filed year.
        """
        rows = [
            period(source="xbrl_companyfacts", period_end=JUNE_2025, metrics={"revenue": 1_000.0}),
            period(
                source="yahoo_info",
                period_end=dt.date(2026, 10, 7),
                period_type="ttm",
                metrics={"revenue": 1_100.0},
            ),
        ]

        years = collate(rows)

        assert len(years) == 1
        assert years[0].chosen.source == "xbrl_companyfacts"
        assert all(row.period.period_type != "ttm" for row in years[0].superseded)


class TestTheAccountingYear:
    def test_the_year_is_anchored_on_the_filings_not_on_a_month(self):
        """Apple's year ends drift: 2024-09-28, then 2025-09-27. A fixed `(9, 27)` rule files
        the first under the *following* year -- which merged six real years in a probe and
        produced collisions that do not exist."""
        rows = [
            period(source="xbrl_companyfacts", period_end=dt.date(2024, 9, 28)),
            period(source="xbrl_companyfacts", period_end=dt.date(2025, 9, 27)),
            period(source="xbrl_companyfacts", period_end=dt.date(2023, 9, 30)),
        ]

        years = collate(rows)

        assert [year.label for year in years] == [
            dt.date(2023, 9, 30),
            dt.date(2024, 9, 28),
            dt.date(2025, 9, 27),
        ]
        assert all(len(year.superseded) == 0 for year in years)

    def test_an_interim_belongs_to_the_year_it_is_reporting_on(self):
        ends = [dt.date(2024, 6, 30), JUNE_2025, JUNE_2026]
        # A third quarter ending in March is inside the year ending the following June.
        march = dt.date(2026, 3, 31)

        assert year_for(period(source="x", period_end=march, period_type="quarterly"), ends) == JUNE_2026

    def test_an_annual_end_is_its_own_boundary(self):
        ends = [JUNE_2025, JUNE_2026]

        assert year_for(period(source="x", period_end=JUNE_2025), ends) == JUNE_2025

    def test_a_period_after_every_annual_end_belongs_to_the_next_year(self):
        """It is the start of the year the next annual will cover, not part of the one that
        just closed -- filing it under the last annual end would put a period that begins
        after the year ended into that year's accounts."""
        rows = [
            period(source="xbrl_companyfacts", period_end=JUNE_2025),
            period(
                source="yahoo_statements",
                period_end=dt.date(2025, 9, 30),
                period_type="quarterly",
            ),
        ]

        years = collate(rows)

        assert len(years) == 2, "the quarter after the year end is its own year"
        closing, next_year = years
        assert closing.label == JUNE_2025 and closing.provisional is False
        assert next_year.label == JUNE_2026, "the boundary the next annual will fall on"
        assert next_year.fiscal_year == 2026
        assert next_year.provisional is True
        assert next_year.chosen.period_type == "quarterly"

    def test_with_no_annual_at_all_the_year_is_still_one_set_of_accounts(self):
        rows = [
            period(source="yahoo_statements", period_end=dt.date(2025, 3, 31), period_type="interim"),
            period(source="yahoo_statements", period_end=dt.date(2025, 6, 30), period_type="interim"),
        ]

        years = collate(rows)

        assert len(years) == 1
        assert years[0].provisional is True
        assert years[0].chosen.period_end == dt.date(2025, 6, 30)

    def test_annual_ends_come_from_any_source(self):
        """A provider's annual is as much evidence that a fiscal year ended on a date as the
        filer's is -- the boundary is what matters here, not the figures behind it."""
        rows = [
            period(source="yahoo_statements", period_end=JUNE_2025),
            period(source="xbrl_companyfacts", period_end=JUNE_2026),
        ]

        assert annual_ends(rows) == [JUNE_2025, JUNE_2026]


class TestTellingTheReader:
    def test_a_figure_rounded_differently_is_not_a_discrepancy(self):
        """Measured: 8 of 99 live collisions agree within 1%. Calling those a disagreement
        would train the reader to ignore the panel."""
        rows = [
            period(
                source="xbrl_companyfacts",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000_000.0},
            ),
            period(
                source="yahoo_statements",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000_500.0},
            ),
        ]

        year = collate(rows)[0]

        assert year.discrepancies == []

    def test_a_real_difference_is_reported_with_both_figures(self):
        rows = [
            period(source="xbrl_companyfacts", period_end=JUNE_2025, metrics={"total_debt": 1_000.0}),
            period(source="yahoo_statements", period_end=JUNE_2025, metrics={"total_debt": 1_100.0}),
        ]

        year = collate(rows)[0]
        found = year.discrepancies[0]

        assert found.metric == "total_debt"
        assert found.chosen_value == 1_000.0
        assert found.other_value == 1_100.0
        assert found.other_source == "yahoo_statements"
        # As a fraction of the larger figure, which is why it is not 10%.
        assert abs(found.relative - 100.0 / 1_100.0) < 1e-9

    def test_a_sign_flip_is_a_discrepancy(self):
        """Measured live: `other_nonoperating_income` is stated +3.05m by the filer and -3.05m
        by our extraction of the same statement."""
        rows = [
            period(
                source="xbrl_companyfacts",
                period_end=JUNE_2025,
                metrics={"other_nonoperating_income": 3_050_000.0},
            ),
            period(
                source="llm_extraction",
                period_end=JUNE_2025,
                metrics={"other_nonoperating_income": -3_050_000.0},
            ),
        ]

        assert collate(rows)[0].discrepancies[0].metric == "other_nonoperating_income"

    def test_a_derived_ratio_is_not_reported_twice(self):
        """Ratios are computed by `derive_metrics` from whatever figures the row holds, so a
        ratio that differs because an input differed repeats the same disagreement."""
        rows = [
            period(
                source="xbrl_companyfacts",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000.0, "net_margin": 0.10},
            ),
            period(
                source="yahoo_statements",
                period_end=JUNE_2025,
                metrics={"revenue": 1_000.0, "net_margin": 0.20},
            ),
        ]

        assert collate(rows)[0].discrepancies == []

    def test_a_month_of_the_panel_names_the_year_and_the_source(self):
        rows = [
            period(source="xbrl_companyfacts", period_end=JUNE_2025, metrics={"revenue": 1_000.0})
        ]

        year = collate(rows)[0]

        assert year.fiscal_year == 2025
        assert year.government is True
        assert year.source == "xbrl_companyfacts"
        assert year.basis == "annual"


class TestDeterminism:
    def test_the_choice_does_not_depend_on_the_order_the_rows_arrive_in(self):
        """A page render and a job can read the same rows in different orders, and two
        answers to "which accounts are these" is the bug this module exists to remove."""
        rows = [
            period(source="yahoo_statements", period_end=JUNE_2025, metrics={"revenue": 1.0}, id=1),
            period(source="llm_extraction", period_end=JUNE_2025, metrics={"revenue": 2.0}, id=2),
            period(source="xbrl_companyfacts", period_end=JUNE_2025, metrics={"revenue": 3.0}, id=3),
        ]

        forward = collate(rows)[0]
        backward = collate(list(reversed(rows)))[0]

        assert forward.chosen.source == backward.chosen.source == "xbrl_companyfacts"
        assert [row.source for row in forward.superseded] == [
            row.source for row in backward.superseded
        ]

    def test_a_tie_on_every_rank_is_broken_by_the_row_id(self):
        rows = [
            period(source="yahoo_statements", period_end=JUNE_2025, metrics={"revenue": 1.0}, id=10),
            period(source="yahoo_statements", period_end=JUNE_2025, metrics={"revenue": 2.0}, id=11),
        ]

        assert collate(rows)[0].chosen.id == 11


class TestWhatTheAnalysisReads:
    def test_the_annual_set_is_one_row_per_year_and_government_preferred(self):
        rows = [
            period(source="yahoo_statements", period_end=dt.date(2024, 6, 30), metrics={"revenue": 1.0}),
            period(source="yahoo_statements", period_end=JUNE_2025, metrics={"revenue": 2.0}),
            period(source="xbrl_companyfacts", period_end=JUNE_2025, metrics={"revenue": 3.0}),
        ]

        chosen = annual_set(rows)

        assert [row.period_end for row in chosen] == [dt.date(2024, 6, 30), JUNE_2025]
        assert [row.source for row in chosen] == ["yahoo_statements", "xbrl_companyfacts"]

    def test_an_interim_slot_is_not_in_the_annual_series(self):
        """A half-year in a series the growth rates are computed across would report a
        collapse in revenue that is really a shorter period."""
        rows = [
            period(source="yahoo_statements", period_end=dt.date(2024, 6, 30), metrics={"revenue": 1.0}),
            period(
                source="yahoo_statements",
                period_end=dt.date(2025, 6, 30),
                period_type="interim",
                metrics={"revenue": 0.5},
            ),
        ]

        assert [row.period_end for row in annual_set(rows)] == [dt.date(2024, 6, 30)]

    def test_no_periods_is_no_years_rather_than_a_crash(self):
        assert collate([]) == []
        assert annual_set([]) == []

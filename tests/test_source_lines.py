"""The captions a source states that this project's vocabulary has no name for.

The failure this closes, measured on `JELl_EQ` (Jersey Electricity) FY2025 from a Yahoo statement:
its income statement states ``Operating Expense`` and ``Other Operating Expenses`` as the same
38,688,000, and 53,465,000 - 38,688,000 = 14,777,000 is the stated operating income to the pound.
The accounts page showed that section *out by 26,867,000* and could offer no way to fix it: the
caption was not in :data:`ingest.fundamentals.STATEMENT_LABELS`, so `metrics_from_statements`
discarded it, and a line learned from a filing is keyed by a taxonomy tag a provider statement does
not have.

So the surplus is kept, and the accounts page can offer it. Nothing is presented automatically: the
same caption means different things to different filers, and to the same filer in different years --
in 2022 Yahoo states this very caption at 29,293,000 *and* the SG&A it duplicates, so mapping it
globally would count that year twice.
"""

from __future__ import annotations

import datetime as dt

from awltux.db import FundamentalPeriod
from awltux.ingest.fundamentals import (
    SOURCE_KEY_PREFIX,
    metrics_from_statements,
    source_key,
    source_lines,
)


def _jel_income() -> dict:
    """Yahoo's income statement for `JEL.L`, FY2025 column and one other, trimmed to what matters.

    Verbatim labels and figures, because the point of the fixture is that the source's *wording* is
    the thing this project cannot anticipate.
    """
    return {
        "income": {
            "columns": ["2025-09-30", "2022-09-30"],
            "rows": {
                "Total Revenue": [146_196_000.0, 117_421_000.0],
                "Cost Of Revenue": [92_731_000.0, 77_242_000.0],
                "Gross Profit": [53_465_000.0, 40_179_000.0],
                "Operating Expense": [38_688_000.0, 29_293_000.0],
                "Other Operating Expenses": [38_688_000.0, 29_293_000.0],
                "Selling General And Administration": [None, 29_293_000.0],
                "Operating Income": [14_777_000.0, 10_886_000.0],
                "Reconciled Depreciation": [11_821_000.0, 11_094_000.0],
                # A stated zero, and a ratio: neither is a line worth offering.
                "Tax Effect Of Unusual Items": [0.0, 0.0],
                "Tax Rate For Calcs": [0.22, 0.2],
            },
        },
        "cashflow": {
            "columns": ["2025-09-30", "2022-09-30"],
            "rows": {
                "Depreciation And Amortization": [11_821_000.0, 11_094_000.0],
                "Operating Cash Flow": [25_299_000.0, 21_219_000.0],
            },
        },
    }


class TestTheCaptionIsTheIdentity:
    def test_a_caption_slugs_to_a_stable_key(self):
        """No tag exists, so the caption is the key -- the same argument `corrections.Line` makes
        for a taxonomy tag, with the caption standing in for one."""
        assert source_key("Other Operating Expenses") == (
            "src:other-operating-expenses"
        )
        assert source_key("  Other Operating Expenses  ") == (
            "src:other-operating-expenses"
        )
        assert source_key("Net Income From Continuing Operations") == (
            "src:net-income-from-continuing-operations"
        )

    def test_a_source_key_cannot_collide_with_a_canonical_metric(self):
        """The colon is what makes that true, exactly as it does for a `taxonomy:Tag`."""
        assert SOURCE_KEY_PREFIX.endswith(":")
        assert ":" in source_key("Revenue")


class TestWhatIsKept:
    def test_the_caption_no_metric_claims_is_kept_with_its_figure(self):
        kept = source_lines(_jel_income(), 0)["profit_and_loss"]

        assert {"label": "Other Operating Expenses", "key": "src:other-operating-expenses",
                "value": 38_688_000.0} in kept
        assert {"label": "Operating Expense", "key": "src:operating-expense",
                "value": 38_688_000.0} in kept

    def test_a_label_a_canonical_metric_reads_is_not_offered_again(self):
        """The chart already has that line under that caption, and offering it twice is how one
        figure comes to be counted in two places."""
        labels = {
            row["label"]
            for rows in source_lines(_jel_income(), 0).values()
            for row in rows
        }

        assert "Total Revenue" not in labels
        assert "Gross Profit" not in labels
        assert "Operating Income" not in labels
        # `Depreciation And Amortization` is a cash flow caption this project *does* map onto a
        # profit and loss line -- which is a whole separate problem, and not one this column adds to.
        assert "Depreciation And Amortization" not in labels

    def test_a_stated_zero_is_not_a_line_to_offer(self):
        labels = {
            row["label"]
            for rows in source_lines(_jel_income(), 0).values()
            for row in rows
        }

        assert "Tax Effect Of Unusual Items" not in labels
        # A rate is kept, because it is a number the source stated under a caption of its own and
        # refusing it would be this project deciding what a reader may put on their own accounts.
        # It is not *offered* anywhere until somebody chooses it.
        assert "Tax Rate For Calcs" in labels
        assert "Operating Expense" in labels

    def test_the_caption_is_read_from_the_column_asked_for(self):
        """A source's later year states the same caption at a different figure, and the figure has
        to come from the column the period is."""
        newer = {
            row["label"]: row["value"]
            for rows in source_lines(_jel_income(), 0).values()
            for row in rows
        }
        older = {
            row["label"]: row["value"]
            for rows in source_lines(_jel_income(), 1).values()
            for row in rows
        }

        assert newer["Other Operating Expenses"] == 38_688_000.0
        assert older["Other Operating Expenses"] == 29_293_000.0

    def test_the_captions_are_grouped_by_the_statement_they_came_from(self):
        """Nothing is kept for the cash flow here, and that is the right answer rather than a gap:
        both of its captions in this fixture are ones a canonical metric already reads."""
        kept = source_lines(_jel_income(), 0)

        assert set(kept) == {"profit_and_loss"}

    def test_a_row_the_statements_do_not_state_is_absent_rather_than_zero(self):
        """Yahoo prints a missing caption as ``None``; a line at 0 would claim the source stated
        nothing there, which is a different fact from it stating nothing at all."""
        assert "Selling General And Administration" not in {
            row["label"]
            for rows in source_lines(_jel_income(), 0).values()
            for row in rows
        }


class TestTheMetrcisStillDropIt:
    def test_the_canonical_metrics_do_not_grow_a_key_for_the_caption(self):
        """The column is the *offer*, not the extraction: a caption becomes a line only when a
        reader places it, and then its figure is written into ``metrics`` by a correction. A
        vocabulary that grew a key for every caption a source uses would be the fixed chart again,
        with more keys."""
        metrics = metrics_from_statements(_jel_income(), 0)

        assert "other_operating_expenses" not in metrics
        assert metrics["operating_income"] == 14_777_000.0
        assert metrics["revenue"] == 146_196_000.0


class TestTheColumnOnTheRow:
    def test_a_period_stores_the_captions_it_was_offered(self):
        """Nothing reads them but the accounts page, so the property to assert is that they survive
        being written to a row and read back -- a column nothing populates is the failure that
        nearly went unnoticed on `filing_id`, where 0 of 824 periods carried one."""
        period = FundamentalPeriod(
            instrument_t212_ticker="JELl_EQ",
            period_end=dt.date(2025, 9, 30),
            period_type="annual",
            currency="GBX",
            source="yahoo_statements",
            metrics={"revenue": 146_196_000.0},
            presentation=source_lines(_jel_income(), 0),
        )

        assert period.presentation["profit_and_loss"][1]["key"] == (
            "src:other-operating-expenses"
        )

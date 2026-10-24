"""Where a line is printed, and what its figure is counted in -- separately from the figure.

Reported 2026-10-25, working through one utility's accounts: *"The yahoo page doesnt put
'Depreciation and amortisation' under operating expenses, but does have 'Other Operating
Expenses'. Removing the Depreciation and adding the Other balances that section. There is little
consistency when naming lines in the accounts. It appears each company can use their own
terminology and accounting practices. So the accounting system cannot depend on where a line title
might end up ... it is difficult to construct accounts from just the prescribed titles, and suggests
a more flexible way of constructing/modifying the accounts is required."*

What was measured on `JELl_EQ` (Jersey Electricity) FY2025, from Yahoo's own income statement:

* ``Operating Expense`` and ``Other Operating Expenses`` are the **same 38,688,000**.
* ``Selling General And Administration`` is absent for 2023-2025, and in 2022 is stated as
  29,293,000 -- the same figure as ``Other Operating Expenses`` in that year.
* ``Depreciation And Amortization`` (11,821,000) is a **cash flow** row, not part of that operating
  expense.
* 53,465,000 - 38,688,000 = 14,777,000, the stated operating income, to the pound.

So the accounts need two freedoms the chart could not express: add a caption the *source* states,
and stop a line being deducted where the source does not deduct it. Neither changes a figure.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis import layout, ledger
from awltux.db import FundamentalPeriod


def _year(metrics: dict[str, float]) -> FundamentalPeriod:
    return FundamentalPeriod(
        instrument_t212_ticker="TEST_US_EQ",
        period_end=dt.date(2025, 9, 30),
        period_type="annual",
        currency="GBX",
        source="yahoo_statements",
        metrics=dict(metrics),
    )


def _jel() -> FundamentalPeriod:
    """Jersey Electricity's FY2025 figures as the source states them, plus ours."""
    return _year(
        {
            "revenue": 146_196_000.0,
            "cost_of_goods_sold": 92_731_000.0,
            "gross_profit": 53_465_000.0,
            "depreciation_amortisation": 11_821_000.0,
            "operating_income": 14_777_000.0,
            "interest_expense": 1_575_000.0,
            "interest_income": 1_883_000.0,
            "pretax_income": 14_190_000.0,
            "tax_expense": 3_126_000.0,
            "net_income": 11_000_000.0,
        }
    )


def _line(statement: ledger.Statement, section: str, key: str) -> ledger.Line:
    for built in statement.sections:
        if built.title == section:
            for line in built.lines:
                if line.key == key:
                    return line
    raise AssertionError(f"no line {key!r} under {section!r}")


class TestTheChartIsTheDefaultPresentation:
    def test_the_default_layout_prints_the_chart_in_its_own_order(self):
        """The chart's order *is* the printed order, section by section -- which is what let one
        table replace the four that used to carry this structure: the `Account.section` field, the
        builders' own line lists, the heading-to-subtotal map and the picker's groups."""
        placed = layout.Layout.default()

        assert placed.sections("profit_and_loss") == (
            "Revenue",
            "Operating expenses",
            "Finance and tax",
            "Memorandum",
        )
        assert [
            placement.key for placement in placed.lines("profit_and_loss", "Revenue")
        ] == ["revenue", "cost_of_goods_sold", "gross_profit"]

    def test_every_chart_line_is_printed_somewhere(self):
        placed = layout.Layout.default()

        printed = {
            placement.key
            for statement in placed.statements()
            for title in placed.sections(statement)
            for placement in placed.lines(statement, title)
        }

        assert printed == {account.key for account in layout.CHART}

    def test_a_heading_names_the_subtotal_its_lines_feed(self):
        """The rule that decides where a figure is counted, stated once.

        `tax_expense` is the exception the heading cannot answer -- it is printed with the interest
        lines and deducted after the profit before tax -- which is why a line can override it.
        """
        placed = layout.Layout.default()

        assert placed.placement("sga_expense").feeds == "operating_income"
        assert placed.placement("revenue").feeds == "gross_profit"
        assert placed.placement("interest_income").feeds == "pretax_income"
        assert placed.placement("tax_expense").feeds == "net_income"
        assert placed.placement("other_noncurrent_liabilities").feeds == (
            "non_current_liabilities"
        )
        # Memoranda are printed and counted nowhere; the flag is what says so.
        assert placed.placement("ebitda").feeds == ""
        assert placed.placement("ebitda").role == "memo"


class TestALineCanBeMovedWithoutTouchingAFigure:
    def test_moving_a_line_takes_it_out_of_the_subtotal_it_was_deducted_from(self):
        """The whole of the Jersey Electricity fix, in one assertion: the section that was out by
        26,867,000 stops being out by it once depreciation is no longer deducted there.

        Nothing is deleted and no figure changes: the line is still printed, under the heading the
        company uses, and `depreciation_amortisation` still holds 11,821,000 in `metrics`.
        """
        placed = layout.Layout.build(
            moves={
                "depreciation_amortisation": layout.Override(
                    section="Depreciation and amortisation", feeds=""
                )
            }
        )

        statement = ledger.profit_and_loss(_jel(), layout=placed)
        section = next(
            item
            for item in statement.sections
            if item.title == "Operating expenses"
        )

        assert "depreciation_amortisation" not in [line.key for line in section.lines]
        assert _line(statement, "Operating expenses", "operating_income").computed == 53_465_000.0
        # Still printed, under the heading the company uses, and still stated.
        assert _line(
            statement, "Depreciation and amortisation", "depreciation_amortisation"
        ).stated == 11_821_000.0

    def test_adding_the_source_s_own_caption_balances_the_section_to_the_pound(self):
        """53,465,000 - 38,688,000 = 14,777,000, the stated operating income.

        The line's key is the caption's, because a provider statement tags nothing: there is no
        taxonomy name to key it by, which is exactly why this could not be done before. Its figure
        is stored negative -- the sign the chosen side implies -- because Yahoo states an expense
        positive and a capex outflow negative in the same document, so its own sign means nothing.
        """
        key = "src:other-operating-expenses"
        period = _jel()
        period.metrics = dict(period.metrics or {}, **{key: -38_688_000.0})
        placed = layout.Layout.build(
            learned=[
                layout.Placement(
                    key=key,
                    label="Other Operating Expenses",
                    statement="profit_and_loss",
                    section="Operating expenses",
                    side="debit",
                    feeds="operating_income",
                )
            ],
            moves={
                "depreciation_amortisation": layout.Override(
                    section="Depreciation and amortisation", feeds=""
                )
            },
        )

        statement = ledger.profit_and_loss(period, layout=placed)
        operating = _line(statement, "Operating expenses", "operating_income")

        assert operating.stated == 14_777_000.0
        assert operating.computed == 14_777_000.0
        assert operating.residual == 0.0
        assert operating.agrees is True

    def test_the_health_check_follows_a_move_because_it_reads_the_same_layout(self):
        """One cascade, two callers. A move the statement honours and the audit does not would be
        two answers to one question, one row apart on the same page."""
        key = "src:other-operating-expenses"
        period = _jel()
        period.metrics = dict(period.metrics or {}, **{key: -38_688_000.0})
        placed = layout.Layout.build(
            learned=[
                layout.Placement(
                    key=key,
                    label="Other Operating Expenses",
                    statement="profit_and_loss",
                    section="Operating expenses",
                    side="debit",
                    feeds="operating_income",
                )
            ],
            moves={
                "depreciation_amortisation": layout.Override(
                    section="Depreciation and amortisation", feeds=""
                )
            },
        )

        check = ledger.profit_articulation(period, placed)

        # The check reads the same cascade the statement prints, so a move it did not honour would
        # be two answers to one question, one row apart on the same page.
        statement = ledger.profit_and_loss(period, layout=placed)
        assert check.inputs["computed"] == _line(
            statement, "Finance and tax", "net_income"
        ).computed
        # And the gap left is a real one, not the layout's: Jersey Electricity's profit before tax
        # of 14,190,000 contains an 895,000 gain on investment securities that Yahoo states on its
        # *cash flow* statement, which is a line this project does not hold. 14,190 + 895 = 15,085
        # of profit before tax from the lines we do hold, less 3,126 of tax is 11,959.
        assert check.inputs["computed"] == 11_959_000.0
        assert check.residual == -959_000.0

    def test_a_new_heading_prints_and_a_heading_nothing_is_left_under_does_not(self):
        """The move *is* the registration. A heading nobody is under is not a heading, which is why
        there is no second list of them to keep true."""
        placed = layout.Layout.build(
            moves={
                "depreciation_amortisation": layout.Override(
                    section="Depreciation and amortisation", feeds=""
                )
            }
        )

        assert "Depreciation and amortisation" in placed.sections("profit_and_loss")

        unmoved = layout.Layout.build()

        assert "Depreciation and amortisation" not in unmoved.sections("profit_and_loss")

    def test_a_moved_line_is_printed_before_the_first_subtotal_it_joins(self):
        """Position is not decoration: a line printed under the total it feeds reads as a
        memorandum, and the point of moving it into a heading is that it is part of that heading."""
        placed = layout.Layout.build(
            moves={"sga_expense": layout.Override(section="Operating expenses")}
        )
        keys = [
            placement.key
            for placement in placed.lines("profit_and_loss", "Operating expenses")
        ]

        assert keys.index("sga_expense") < keys.index("operating_income")


class TestAHeadingCannotSilentlyCountNothing:
    def test_a_line_whose_heading_sums_to_nothing_is_reported(self):
        """A figure that appears in the accounts and moves no total is one a reader will assume is
        counted, so it is said rather than left to be noticed."""
        key = "test:unequity"
        placed = layout.Layout.build(
            learned=[
                layout.Placement(
                    key=key,
                    label="An equity line",
                    statement="balance_sheet",
                    section="Equity",
                    side="credit",
                )
            ]
        )

        assert [placement.key for placement in placed.uncounted("balance_sheet")] == [key]
        assert ledger.uncounted_note(placed, "balance_sheet") is not None

    def test_a_chart_line_moved_out_of_a_cascade_is_not_reported(self):
        """The reader decided it. Saying "counted in nothing" about a line they deliberately took
        out of the cascade would be the page arguing with the record it just made."""
        placed = layout.Layout.build(
            moves={"depreciation_amortisation": layout.Override(feeds="")}
        )

        assert placed.uncounted("profit_and_loss") == ()

    def test_a_memorandum_is_not_reported_either(self):
        """Printed and deliberately not counted is what the role means."""
        assert layout.Layout.default().uncounted("balance_sheet") == ()


class TestFeedsAreChecked:
    @pytest.mark.parametrize("statement", ["profit_and_loss", "balance_sheet", "cash_flow"])
    def test_every_named_subtotal_is_one_the_statement_can_sum(self, statement):
        """A placement naming a subtotal that is not one of these is refused at the route, so a
        typo cannot become a line counted nowhere that a reader believes is counted."""
        assert set(layout.FEEDS[statement]) <= {
            placement.key
            for placement in layout.Layout.default().components(statement, "")
        } | set(layout.FEEDS[statement])

    def test_the_cash_flow_sums_nothing_from_a_group(self):
        """Its subtotal is a formula -- operating cash flow less capital expenditure -- so there is
        no group for a line to join, and a move cannot invent one."""
        assert layout.FEEDS["cash_flow"] == ()

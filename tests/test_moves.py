"""Moving a line, and adding a caption the source states -- through the pages that do it.

The two freedoms the accounts needed, tested where a reader uses them rather than in the pure
functions (`tests/test_layout.py` owns those). Both are about *presentation*: a move changes no
figure at all, and adding a caption the source states writes a figure that is already in the
period's stored payload.

Measured on `JELl_EQ` (Jersey Electricity) FY2025, from Yahoo's own income statement: ``Operating
Expense`` and ``Other Operating Expenses`` are the same 38,688,000, ``Depreciation And
Amortization`` (11,821,000) is a **cash flow** row rather than part of that expense, and
53,465,000 - 38,688,000 = 14,777,000 -- the stated operating income, to the pound. That is the
section that showed *out by 26,867,000* with no way to fix it from the page.
"""

from __future__ import annotations

import datetime as dt

from bs4 import BeautifulSoup

from awltux.analysis import corrections
from awltux.db import AppSetting, FundamentalPeriod
from tests.helpers import make_instrument

CIK = "0000320193"

#: Jersey Electricity's FY2025 figures as Yahoo states them, plus the 38,688,000 caption this
#: project's vocabulary has no name for -- which is the whole subject of the file.
FIGURES = {
    "revenue": 146_196_000.0,
    "cost_of_goods_sold": 92_731_000.0,
    "gross_profit": 53_465_000.0,
    "depreciation_amortisation": 11_821_000.0,
    "operating_income": 14_777_000.0,
    "pretax_income": 14_190_000.0,
    "tax_expense": 3_126_000.0,
    "net_income": 11_000_000.0,
}

SOURCE_KEY = "src:other-operating-expenses"


def _period(
    ticker: str,
    period_end: dt.date,
    metrics: dict | None = None,
    *,
    presentation: dict | None = None,
) -> FundamentalPeriod:
    return FundamentalPeriod(
        instrument_t212_ticker=ticker,
        period_end=period_end,
        period_type="annual",
        currency="GBX",
        source="yahoo_statements",
        metrics=dict(metrics if metrics is not None else FIGURES),
        presentation=presentation,
        confidence=0.7,
    )


def _store(session, ticker: str, *periods, cik: str | None = CIK):
    """The filer, then its periods, committed -- a request runs on another session."""
    session.add(make_instrument(ticker, name="Test Co", sec_cik=cik))
    session.flush()
    for period in periods:
        session.add(period)
    session.flush()
    session.commit()
    return periods[-1] if periods else None


def _row(soup, label: str):
    """The ledger row whose Line cell holds this caption, with the heading it is under."""
    for table in soup.select("table.ledger"):
        heading = table.find_previous("h2")
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if cells and label in cells[0].get_text(" "):
                # The heading's own text rather than everything in it: the "add a line" link lives
                # in the same element and is not part of the name.
                title = heading.contents[0].strip() if heading and heading.contents else ""
                return title, row
    raise AssertionError(f"no row {label!r}")


def _computed(soup, label: str) -> str:
    """The Computed column's figure, without the "out by" link that follows it."""
    _, row = _row(soup, label)
    return row.find_all("td")[2].get_text(" ", strip=True).split(" ")[0]


class TestMovingALine:
    def test_a_move_changes_where_a_line_prints_and_no_figure(self, client, session):
        """The whole of the Jersey Electricity fix: depreciation out of operating expenses and
        under a heading of the company's own, so the section stops claiming an expense the source
        does not put there. Not one number in the row changes."""
        period = _store(session, "TEST_US_EQ", _period("TEST_US_EQ", dt.date(2025, 9, 30)))
        before = client.get(f"/accounts/{period.id}/profit_and_loss").text

        response = client.post(
            f"/accounts/{period.id}/corrections/move",
            data={
                "metric": "depreciation_amortisation",
                "statement": "profit_and_loss",
                "section": "Operating expenses",
                "new_section": "Depreciation and amortisation",
                "counted": "heading",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].endswith("#corrections")
        assert "moved" in response.headers["location"]
        after = BeautifulSoup(
            client.get(f"/accounts/{period.id}/profit_and_loss").text, "lxml"
        )
        heading, row = _row(after, "Depreciation and amortisation")
        # Its own heading, and the figure it always had.
        assert heading == "Depreciation and amortisation"
        assert "11,821,000" in row.get_text(" ")
        # Out of the section it was deducted in, so the section now holds no components at all and
        # the computed operating income is the gross profit -- the residual is exactly the
        # 38,688,000 of operating expense this source states and this project does not hold.
        assert _computed(after, "Operating income") == "53,465,000"
        assert _row(BeautifulSoup(before, "lxml"), "Depreciation and amortisation")[0] == (
            "Operating expenses"
        )
        # And nothing in the stored accounts moved.
        session.expire_all()
        stored = session.get(FundamentalPeriod, period.id)
        assert stored.metrics["depreciation_amortisation"] == 11_821_000.0

    def test_the_row_still_prints_with_nothing_in_it_when_moved_as_a_memorandum(
        self, client, session
    ):
        """A move can say "print it and count it nowhere" instead of "make a heading for it",
        which is what a line the source's own total already includes needs."""
        period = _store(session, "TEST_US_EQ", _period("TEST_US_EQ", dt.date(2025, 9, 30)))

        client.post(
            f"/accounts/{period.id}/corrections/move",
            data={
                "metric": "depreciation_amortisation",
                "statement": "profit_and_loss",
                "section": "Operating expenses",
                "new_section": "Depreciation",
                "counted": "none",
            },
            follow_redirects=False,
        )

        soup = BeautifulSoup(
            client.get(f"/accounts/{period.id}/profit_and_loss").text, "lxml"
        )
        heading, _ = _row(soup, "Depreciation and amortisation")

        assert heading == "Depreciation"
        # Counted in nothing means counted in nothing: the heading sums to no figure, so the
        # section has no components and its total is the gross profit it starts from.
        assert _computed(soup, "Operating income") == "53,465,000"

    def test_the_wider_scope_records_it_against_the_filer_and_reaches_its_other_years(
        self, client, session
    ):
        """A presentation is a habit rather than an event, so the wider scope is offered -- and it
        has to reach the other rows now rather than at each one's next sync, or two years of one
        company would disagree on screen."""
        older = _period("TEST_US_EQ", dt.date(2023, 9, 30), {**FIGURES, "net_income": 9_000_000.0})
        newer = _period("TEST_US_EQ", dt.date(2024, 9, 30))
        _store(session, "TEST_US_EQ", older, newer)

        client.post(
            f"/accounts/{newer.id}/corrections/move",
            data={
                "metric": "depreciation_amortisation",
                "statement": "profit_and_loss",
                "new_section": "Depreciation and amortisation",
                "counted": "none",
                "scope": "filer",
            },
            follow_redirects=False,
        )

        soup = BeautifulSoup(client.get(f"/accounts/{older.id}/profit_and_loss").text, "lxml")
        heading, _ = _row(soup, "Depreciation and amortisation")

        assert heading == "Depreciation and amortisation"
        session.expire_all()
        stored = session.get(AppSetting, corrections.key(CIK))
        assert "depreciation_amortisation" in stored.value["moved"]

    def test_undoing_a_move_puts_the_line_back(self, client, session):
        period = _store(session, "TEST_US_EQ", _period("TEST_US_EQ", dt.date(2025, 9, 30)))
        client.post(
            f"/accounts/{period.id}/corrections/move",
            data={
                "metric": "depreciation_amortisation",
                "statement": "profit_and_loss",
                "new_section": "Depreciation",
                "counted": "none",
            },
            follow_redirects=False,
        )

        response = client.post(
            f"/accounts/{period.id}/corrections/depreciation_amortisation/unmove",
            data={"statement": "profit_and_loss"},
            follow_redirects=False,
        )

        assert "unmoved" in response.headers["location"]
        soup = BeautifulSoup(
            client.get(f"/accounts/{period.id}/profit_and_loss").text, "lxml"
        )
        heading, _ = _row(soup, "Depreciation and amortisation")
        assert heading == "Operating expenses"
        assert _computed(soup, "Operating income").replace(",", "") != "14777000"

    def test_the_panel_lists_the_move_with_its_own_undo(self, client, session):
        """To the reader a move is the same kind of thing as an addition -- a line that is not
        what the source said -- so it is in the same panel, with the undo for its scope."""
        period = _store(session, "TEST_US_EQ", _period("TEST_US_EQ", dt.date(2025, 9, 30)))
        client.post(
            f"/accounts/{period.id}/corrections/move",
            data={
                "metric": "depreciation_amortisation",
                "statement": "profit_and_loss",
                "new_section": "Depreciation",
                "counted": "none",
            },
            follow_redirects=False,
        )

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}").text, "lxml")
        panel = soup.select_one("#corrections")

        assert "moved" in panel.get_text(" ")
        assert f"/accounts/{period.id}/corrections/depreciation_amortisation/unmove" in str(
            panel
        )

    def test_a_key_that_is_not_a_line_of_these_accounts_is_refused(self, client, session):
        period = _store(session, "TEST_US_EQ", _period("TEST_US_EQ", dt.date(2025, 9, 30)))

        response = client.post(
            f"/accounts/{period.id}/corrections/move",
            data={
                "metric": "not_a_line",
                "statement": "profit_and_loss",
                "section": "Operating expenses",
            },
            follow_redirects=False,
        )

        assert response.headers["location"].endswith("corrections=no-line#corrections")

    def test_a_subtotal_that_is_not_one_of_the_statement_is_refused(self, client, session):
        """A placement naming a subtotal nothing sums would be a line counted nowhere that a
        reader believes is counted, so it is refused rather than stored."""
        period = _store(session, "TEST_US_EQ", _period("TEST_US_EQ", dt.date(2025, 9, 30)))

        response = client.post(
            f"/accounts/{period.id}/corrections/move",
            data={
                "metric": "depreciation_amortisation",
                "statement": "profit_and_loss",
                "section": "Operating expenses",
                "counted": "feeds:not_a_subtotal",
            },
            follow_redirects=False,
        )

        assert response.headers["location"].endswith("corrections=no-line#corrections")
        session.expire_all()
        assert session.get(FundamentalPeriod, period.id).corrections is None


class TestAddingACaptionTheSourceStates:
    def _with_source(self, session) -> FundamentalPeriod:
        return _store(
            session,
            "TEST_US_EQ",
            _period(
                "TEST_US_EQ",
                dt.date(2025, 9, 30),
                presentation={
                    "profit_and_loss": [
                        {
                            "label": "Other Operating Expenses",
                            "key": SOURCE_KEY,
                            "value": 38_688_000.0,
                        }
                    ]
                },
            ),
        )

    def test_the_panel_offers_it_with_the_figure_the_source_printed(self, client, session):
        period = self._with_source(session)

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}").text, "lxml")
        panel = soup.select_one("#corrections").get_text(" ")

        assert "Other Operating Expenses" in panel
        assert "38,688,000" in panel
        assert f"metric={SOURCE_KEY.replace(':', '%3A')}" in client.get(
            f"/accounts/{period.id}"
        ).text

    def test_adding_it_deducts_it_when_the_reader_says_it_is_a_debit(self, client, session):
        """A provider states amounts without a sign convention -- Yahoo prints an expense positive
        and a capex outflow negative in the same document -- so the side the reader chose is the
        only statement about direction there is, and the figure is written with its sign."""
        period = self._with_source(session)

        response = client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": SOURCE_KEY,
                "statement": "profit_and_loss",
                "section": "Operating expenses",
                "side": "debit",
                "value": "38688000",
            },
            follow_redirects=False,
        )

        assert "added-line" in response.headers["location"]
        session.expire_all()
        stored = session.get(FundamentalPeriod, period.id)
        assert stored.metrics[SOURCE_KEY] == -38_688_000.0
        soup = BeautifulSoup(
            client.get(f"/accounts/{period.id}/profit_and_loss").text, "lxml"
        )
        heading, _ = _row(soup, "Other Operating Expenses")
        # Printed under the heading the reader chose, and now deducted there: 53,465,000 -
        # 38,688,000 is the stated operating income, to the pound, once depreciation is moved out.
        assert heading == "Operating expenses"
        assert _computed(soup, "Operating income").replace(",", "") != "14777000"

    def test_it_is_learned_for_the_filer_so_the_next_year_offers_it(self, client, session):
        """The same argument a line learned from a filing makes: the caption is the company's, and
        a reader who has placed it once should not have to place it again."""
        period = self._with_source(session)
        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": SOURCE_KEY,
                "statement": "profit_and_loss",
                "section": "Operating expenses",
                "side": "debit",
                "value": "38688000",
            },
            follow_redirects=False,
        )

        session.expire_all()
        rules = corrections.load_filer(session, CIK)

        assert rules.lines[SOURCE_KEY].label == "Other Operating Expenses"
        assert rules.lines[SOURCE_KEY].section == "Operating expenses"

    def test_the_two_edits_together_balance_the_section_to_the_pound(self, client, session):
        """The reader's own words, measured: *"Removing the Depreciation and adding the Other
        balances that section."* Both, through the pages, and the residual is zero."""
        period = self._with_source(session)
        client.post(
            f"/accounts/{period.id}/corrections/move",
            data={
                "metric": "depreciation_amortisation",
                "statement": "profit_and_loss",
                "new_section": "Depreciation and amortisation",
                "counted": "none",
            },
            follow_redirects=False,
        )
        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": SOURCE_KEY,
                "statement": "profit_and_loss",
                "section": "Operating expenses",
                "side": "debit",
                "value": "38688000",
            },
            follow_redirects=False,
        )

        soup = BeautifulSoup(
            client.get(f"/accounts/{period.id}/profit_and_loss").text, "lxml"
        )
        _, row = _row(soup, "Operating income")

        assert "out by" not in row.get_text(" ")
        assert _computed(soup, "Operating income") == "14,777,000"
        assert _row(soup, "Other Operating Expenses")[0] == "Operating expenses"
        assert _row(soup, "Depreciation and amortisation")[0] == (
            "Depreciation and amortisation"
        )

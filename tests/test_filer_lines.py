"""Lines the *filer* names, which this project's chart does not carry.

Asked for directly: *"the 'Which line of the Balance sheet' is limited to pre-defined entries.
This is fine, but I've already found entries in the 10-K that aren't in the pre-defined entries.
offer an alternative entry, along side the pre-defined, consisting of the header extracted from
the 10-K. Add this to the pre-defined list for future accounting periods of this instrument"* --
and then, *"I guess it would need to also define which section of the accounts it belonged to"*.

So four properties, and the last is what makes the feature do anything:

* the confirmation page offers the filing's own header as a line to create, beside the chart's;
* creating it **records the line against the filer**, so the next period's form offers it under
  the same heading without being taught again;
* the line is **printed in the statement** under that heading, or a reader who added it would
  not see it;
* it is **counted in that heading's stated total**, so the residual it was added to fix moves.

The last two are the reason the heading matters rather than being decoration. ``analysis.layout``
decides which subtotal a heading feeds (:data:`layout.SECTION_FEEDS`), and a heading whose lines
are summed by nothing -- "Equity", and every statement's "Memorandum" -- prints the figure and
reports it as uncounted rather than guessing it into a total.
"""

from __future__ import annotations

import datetime as dt

import pytest
from bs4 import BeautifulSoup

from awltux.analysis import corrections, ledger
from awltux.analysis import layout as layout_module
from awltux.db import AppSetting, FundamentalPeriod
from tests.helpers import make_instrument

CIK = "0000320193"

#: A caption and a tag the 10-K carries and the chart does not. Measured on Microsoft's 2026
#: 10-K: its current liabilities are stated at 168,825 against the 93,326 the chart's key list
#: holds, and the difference is captions like this one -- see the entry in `TODO.md`.
CAPTION = "Short-term unearned revenue"
TAG = "us-gaap:ContractWithCustomerLiabilityCurrent"

FIGURES = {
    "revenue": 1_000.0,
    "gross_profit": 400.0,
    "operating_income": 250.0,
    "net_income": 200.0,
    "cash_and_equivalents": 200.0,
    "receivables": 100.0,
    "current_assets": 300.0,
    "total_assets": 900.0,
    "payables": 50.0,
    # Stated 100 above the 50 we hold, so `current_liabilities` has a residual to close.
    "current_liabilities": 150.0,
    "total_liabilities": 400.0,
    "total_equity": 500.0,
    "long_term_debt": 250.0,
}


def _period(ticker: str, end: dt.date, metrics: dict | None = None) -> FundamentalPeriod:
    return FundamentalPeriod(
        instrument_t212_ticker=ticker,
        period_end=end,
        period_type="annual",
        currency="USD",
        source="xbrl_companyfacts",
        metrics=dict(metrics if metrics is not None else FIGURES),
        metric_sources={
            "current_liabilities": {
                "value": FIGURES["current_liabilities"],
                "source": "xbrl_companyfacts",
                "span": "us-gaap:LiabilitiesCurrent",
                "accession": "0000320193-26-000123",
            }
        },
        confidence=0.9,
    )


def _store(session, *periods, cik: str | None = CIK):
    session.add(make_instrument("TEST_US_EQ", name="Test Co", sec_cik=cik))
    session.flush()
    for period in periods:
        session.add(period)
    session.flush()
    session.commit()
    return periods[-1] if periods else None


@pytest.fixture
def two_years(session):
    """One filer, two years, so "future accounting periods" has somewhere to mean something."""
    return _store(
        session,
        _period("TEST_US_EQ", dt.date(2024, 12, 31)),
        _period("TEST_US_EQ", dt.date(2025, 12, 31)),
    )


def _learned(session, cik: str = CIK) -> dict:
    row = session.get(AppSetting, corrections.key(cik))
    return (row.value or {}).get("lines", {}) if row else {}


class TestTheRecord:
    def test_a_learned_line_round_trips_through_the_filer_s_record(self, session):
        """It lives with the removals, because it is the same kind of statement: a fact about
        the filer rather than about one period."""
        rules = corrections.Rules()
        corrections.learn_line(
            rules,
            TAG,
            label=CAPTION,
            statement="balance_sheet",
            section="Current liabilities",
            side=corrections.CREDIT,
            tag=TAG,
        )
        corrections.save_filer(session, CIK, rules)

        stored = _learned(session)[TAG]
        assert stored["label"] == CAPTION
        assert stored["statement"] == "balance_sheet"
        assert stored["section"] == "Current liabilities"
        assert stored["side"] == "credit"
        assert stored["tag"] == TAG
        assert stored["at"], "the record says when the line was learned"
        loaded = corrections.load_filer(session, CIK)
        assert loaded.lines[TAG].label == CAPTION
        assert loaded.lines[TAG].section == "Current liabilities"
        assert loaded

    def test_forgetting_one_leaves_the_others_and_the_removals(self, session):
        rules = corrections.Rules()
        corrections.learn_line(
            rules, TAG, label=CAPTION, statement="balance_sheet", section="Current liabilities"
        )
        rules.removed["inventory"] = corrections.Removal(metric="inventory")
        corrections.save_filer(session, CIK, rules)

        assert corrections.forget_line(rules, TAG) is True
        corrections.save_filer(session, CIK, rules)

        assert _learned(session) == {}
        assert corrections.load_filer(session, CIK).removed["inventory"].was is None
        assert corrections.forget_line(rules, TAG) is False


class TestTheFormOffersIt:
    def test_the_filing_s_own_header_is_offered_beside_the_pre_defined_lines(
        self, client, session, two_years
    ):
        """The request, verbatim: *"offer an alternative entry, along side the pre-defined,
        consisting of the header extracted from the 10-K"*."""
        soup = BeautifulSoup(
            client.get(
                f"/accounts/{two_years.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "metric": "current_liabilities",
                    "value": "72965",
                    "tag": TAG,
                    "caption": CAPTION,
                    "section": "Current liabilities",
                    "origin": "filing",
                },
            ).text,
            "lxml",
        )
        options = {option["value"]: option for option in soup.select("select[name=metric] option")}

        assert f"new:{TAG}" in options, "the 10-K's own header is not on offer"
        assert CAPTION in options[f"new:{TAG}"].get_text(" ")
        assert "payables" in options, "the pre-defined lines are still there"

    def test_the_new_line_is_preselected_because_the_tag_is_not_one_of_ours(
        self, client, session, two_years
    ):
        """The reader came from a residual on `current_liabilities` and clicked a figure for
        something else. Opening on the residual's line would offer to put a missing caption's
        figure on the *total* it is missing from."""
        soup = BeautifulSoup(
            client.get(
                f"/accounts/{two_years.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "metric": "current_liabilities",
                    "tag": TAG,
                    "caption": CAPTION,
                    "section": "Current liabilities",
                },
            ).text,
            "lxml",
        )

        assert soup.select_one("select[name=metric] option[selected]")["value"] == f"new:{TAG}"
        assert "the residual you came from is what sent you looking" in soup.get_text(" ")

    def test_a_tag_that_already_feeds_a_line_is_not_offered_as_a_new_one(
        self, client, session, two_years
    ):
        """`us-gaap:InventoryNet` is the Inventory line. Offering to create the filer's own line
        for it would keep two figures for one caption, which disagree the first time one of them
        is corrected -- so the chart's line is preselected instead."""
        soup = BeautifulSoup(
            client.get(
                f"/accounts/{two_years.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "metric": "total_assets",
                    "tag": "us-gaap:InventoryNet",
                    "caption": "Inventories",
                    "section": "Current assets",
                },
            ).text,
            "lxml",
        )
        options = {option["value"]: option for option in soup.select("select[name=metric] option")}

        assert not any(value.startswith("new:") for value in options)
        assert soup.select_one("select[name=metric] option[selected]")["value"] == "inventory"

    def test_a_line_that_was_taken_out_can_be_created_again(self, client, session, two_years):
        """Reported 2026-10-10, after a reader added a caption from a 20-F and then removed it:
        *"That has broken the 'Add a line to these accounts', it no [longer] gives the option to
        use the line name from the accounts read page."*

        The removal was doing its job too well. A learned line's *key is the filing's tag*, so
        once a figure sits under that key the period's provenance holds a `span` equal to the tag
        -- and the dashboard's tag lookup read that as "this tag already feeds a line", which is
        the one condition that suppresses the offer to create one. It fed a line only while the
        filer still had it; a key the chart does not carry is not a line by itself.

        The three steps are the reader's own, in their order: add the line, take it out of the
        accounts, and stop the filer offering it.
        """
        period = two_years
        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": f"new:{TAG}",
                "value": "72965",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": CAPTION,
                "tag": TAG,
                "origin": "filing",
            },
        )
        client.post(
            f"/accounts/{period.id}/corrections/remove",
            data={"metric": TAG, "statement": "balance_sheet"},
        )
        client.post(
            f"/accounts/{period.id}/filer-lines/forget",
            data={"metric": TAG, "statement": "balance_sheet"},
        )

        soup = BeautifulSoup(
            client.get(
                f"/accounts/{period.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "value": "72965",
                    "tag": TAG,
                    "caption": CAPTION,
                    "section": "Current liabilities",
                    "origin": "filing",
                },
            ).text,
            "lxml",
        )
        options = {option["value"]: option for option in soup.select("select[name=metric] option")}

        assert f"new:{TAG}" in options, "the caption the reader removed cannot be added again"
        assert CAPTION in options[f"new:{TAG}"].get_text(" ")

    def test_a_figure_left_under_a_forgotten_key_does_not_block_the_line(self, client, session):
        """The state the reader was actually in, found in the live database: the figure is back
        in the period's figures and its provenance with no removal marker against it, because the
        removal was undone -- but the filer's line has since been forgotten, so nothing prints it
        and nothing counts it. It is not a line of these accounts, and offering the caption is
        the reader's way to make it one again."""
        period = _store(session, _period("TEST_US_EQ", dt.date(2024, 12, 31)))
        rules = corrections.Rules()
        corrections.learn_line(
            rules,
            TAG,
            label=CAPTION,
            statement="balance_sheet",
            section="Current liabilities",
            tag=TAG,
        )
        corrections.save_filer(session, CIK, rules)
        session.commit()
        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": f"new:{TAG}",
                "value": "72965",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": CAPTION,
                "tag": TAG,
                "origin": "filing",
            },
        )
        # The line is forgotten, and its figure is left exactly where it was put -- which is what
        # `filer-lines/forget` promises: it changes no figure.
        client.post(
            f"/accounts/{period.id}/filer-lines/forget",
            data={"metric": TAG, "statement": "balance_sheet"},
        )

        soup = BeautifulSoup(
            client.get(
                f"/accounts/{period.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "tag": TAG,
                    "caption": CAPTION,
                    "section": "Current liabilities",
                    "origin": "filing",
                },
            ).text,
            "lxml",
        )
        options = {option["value"]: option for option in soup.select("select[name=metric] option")}

        assert f"new:{TAG}" in options

    def test_a_line_that_is_still_there_is_not_offered_as_a_new_one(self, client, session, two_years):
        """The other half, so the fix cannot be "never suppress the offer": a line that *is* one
        of this period's accounts does not want a second copy under the filing's caption."""
        period = two_years
        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": f"new:{TAG}",
                "value": "72965",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": CAPTION,
                "tag": TAG,
                "origin": "filing",
            },
        )

        soup = BeautifulSoup(
            client.get(
                f"/accounts/{period.id}/corrections/new",
                params={
                    "statement": "balance_sheet",
                    "value": "72965",
                    "tag": TAG,
                    "caption": CAPTION,
                    "section": "Current liabilities",
                    "origin": "filing",
                },
            ).text,
            "lxml",
        )
        options = {option["value"]: option for option in soup.select("select[name=metric] option")}

        assert not any(value.startswith("new:") for value in options)

    def test_a_learned_line_is_offered_in_a_later_period(self, client, session):
        """*"Add this to the pre-defined list for future accounting periods of this instrument"*.
        The period doing the offering here is a *different row* from the one that learned it,
        which is the whole point of keeping it against the filer."""
        older = _period("TEST_US_EQ", dt.date(2024, 12, 31))
        newer = _period("TEST_US_EQ", dt.date(2025, 12, 31))
        _store(session, older, newer)
        rules = corrections.Rules()
        corrections.learn_line(
            rules,
            TAG,
            label=CAPTION,
            statement="balance_sheet",
            section="Current liabilities",
            tag=TAG,
        )
        corrections.save_filer(session, CIK, rules)
        session.commit()

        soup = BeautifulSoup(
            client.get(
                f"/accounts/{newer.id}/corrections/new", params={"statement": "balance_sheet"}
            ).text,
            "lxml",
        )
        option = next(
            item
            for item in soup.select("select[name=metric] option")
            if item["value"] == TAG
        )

        assert CAPTION in option.get_text(" ")
        # Offered *under its heading* rather than in a list of its own: the picker groups by the
        # headings the statement prints, so where the line belongs is what the group says.
        groups = soup.select("select[name=metric] optgroup")
        owning = next(
            group for group in groups if option in group.select("option")
        )
        assert owning["label"] == "Current liabilities"

    def test_a_line_is_learned_against_the_instrument_when_there_is_no_cik(
        self, client, session
    ):
        """A line belongs to the company that filed it, and a company the SEC does not register is
        named by its instrument.

        This used to be refused with `no-filer`, on the argument that "a line stored on one period
        would silently not reach the next" -- and that was true of a line stored on the *row*. It is
        not true of a line learned against the instrument, which is what happens now: the period
        below is one of two, and the other one is offered the line too. Measured 2026-10-25: 60 of
        the 183 instruments with stored accounts have no SEC CIK, so the old rule left a third of
        them unable to carry a line at all.
        """
        older = _period("TEST_US_EQ", dt.date(2023, 12, 31))
        newer = _period("TEST_US_EQ", dt.date(2024, 12, 31))
        period = _store(session, older, newer, cik=None)

        response = client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": f"new:{TAG}",
                "value": "72965",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": CAPTION,
                "tag": TAG,
                "side": "credit",
            },
            follow_redirects=False,
        )

        assert "added-line" in response.headers["location"]
        session.expire_all()
        assert session.get(FundamentalPeriod, period.id).metrics[TAG] == 72_965.0
        rules = corrections.load_filer(session, "t212:TEST_US_EQ")
        assert rules.lines[TAG].section == "Current liabilities"
        # And the earlier year is offered it, which is the property the old refusal was protecting.
        form = BeautifulSoup(
            client.get(
                f"/accounts/{older.id}/corrections/new",
                params={"statement": "balance_sheet"},
            ).text,
            "lxml",
        )
        assert any(
            option["value"] == TAG for option in form.select("select[name=metric] option")
        )


class TestAddingToANewLine:
    def _add(self, client, period, **overrides):
        data = {
            "metric": f"new:{TAG}",
            "value": "72,965",
            "side": "credit",
            "statement": "balance_sheet",
            "section": "Current liabilities",
            "caption": CAPTION,
            "tag": TAG,
            "origin": "filing",
        }
        data.update(overrides)
        return client.post(
            f"/accounts/{period.id}/corrections/add", data=data, follow_redirects=False
        )

    def test_the_figure_is_stored_under_the_tag_and_the_line_is_learned(
        self, client, session, two_years
    ):
        """The tag is the line's name: it is the identity the *filing* gives the caption, so
        next year's 10-K answers to it without anything having to remember a label."""
        response = self._add(client, two_years)

        assert "corrections=added-line" in response.headers["location"]
        session.expire_all()
        row = session.get(FundamentalPeriod, two_years.id)
        assert row.metrics[TAG] == pytest.approx(72965.0)
        assert row.metric_sources[TAG]["source"] == corrections.MANUAL
        assert row.metric_sources[TAG]["span"] == TAG
        learned = _learned(session)[TAG]
        assert learned["label"] == CAPTION
        assert learned["section"] == "Current liabilities"
        assert learned["statement"] == "balance_sheet"

    def test_the_line_is_printed_in_the_statement_under_its_heading(
        self, client, session, two_years
    ):
        """A line a reader added that the statement does not show is not a line of the accounts."""
        self._add(client, two_years)

        soup = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/balance_sheet").text, "lxml"
        )
        rows = soup.select("table.ledger tbody tr")
        heading = next(
            index
            for index, row in enumerate(soup.select("h2"))
            if "Current liabilities" in row.get_text(" ")
        )
        assert heading >= 0
        assert any(CAPTION in row.get_text(" ") for row in rows), "not printed"
        # And inside the section it was learned under, not the first one that matches.
        section_tables = soup.select("table.ledger")
        liabilities = next(
            table
            for table in section_tables
            if any("Trade payables" in row.get_text(" ") for row in table.select("tbody tr"))
        )
        assert CAPTION in liabilities.get_text(" ")

    def test_the_heading_s_total_counts_it(self, client, session, two_years):
        """The residual is what the line was added to fix, so this is the property that makes the
        feature do anything: current liabilities are stated at 150 against the 50 we hold, and
        the 100 the filing states under a caption we do not carry closes it exactly.

        Read off the health tab rather than by calling `ledger.checks` directly, because the
        wiring that hands the learned line to the ledger is half of what is being tested.
        """
        session.expire_all()
        before = next(
            check
            for check in ledger.checks(session.get(FundamentalPeriod, two_years.id))
            if check.key == "current_liabilities_composition"
        )
        assert before.residual == pytest.approx(100.0)

        self._add(client, two_years, value="100")

        row = self._check_row(client, two_years, "Components sum to stated current liabilities")
        assert "agrees" in row.get_text(" "), row.get_text(" ")

    @staticmethod
    def _check_row(client, period, label: str) -> BeautifulSoup:
        """One row of the accounting-health table, on the health tab the reader sees."""
        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/health").text, "lxml")
        rows = [
            row
            for table in soup.select("table.grid")
            for row in table.select("tbody tr")
        ]
        return next(item for item in rows if label in item.get_text(" "))

    def test_a_heading_that_feeds_no_total_prints_the_line_and_says_so(
        self, client, session, two_years
    ):
        """`Equity` is a heading whose lines no sum on this page adds up, so a figure put there
        is printed and *reported* rather than guessed into a total."""
        self._add(client, two_years, section="Equity")

        soup = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/balance_sheet").text, "lxml"
        )
        text = soup.get_text(" ")

        assert CAPTION in text, "the line is printed"
        assert "added to no total" in text
        assert "not something it will guess" in text
        session.expire_all()
        # Counted nowhere: total liabilities is still the chart's own components against the
        # stated figure, so the residual is unchanged.
        check = self._check_row(client, two_years, "Components sum to stated total liabilities")
        assert "agrees" in check.get_text(" ") or "out" in check.get_text(" ")

    def test_a_heading_the_statement_does_not_print_is_refused(
        self, client, session, two_years
    ):
        """A line under no heading is a line nothing shows, so it is refused with the reason
        rather than stored under a heading that will never render it."""
        response = self._add(client, two_years, section="Nonexistent heading")

        assert "no-section" in response.headers["location"]
        session.expire_all()
        assert TAG not in (session.get(FundamentalPeriod, two_years.id).metrics or {})
        assert _learned(session) == {}

    def test_a_line_with_no_caption_to_name_it_is_refused(self, client, session, two_years):
        """The header *is* the line's label, so there is nothing to create without one."""
        response = self._add(client, two_years, caption="")

        assert "no-line" in response.headers["location"]
        assert _learned(session) == {}

    def test_a_figure_that_is_not_one_is_refused_before_anything_is_learned(
        self, client, session, two_years
    ):
        response = self._add(client, two_years, value="not a number")

        assert "bad-value" in response.headers["location"]
        assert _learned(session) == {}


class TestTheLineIsALineOfTheAccounts:
    def test_the_panel_lists_it_and_forgetting_it_stops_offering_it(
        self, client, session, two_years
    ):
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": f"new:{TAG}",
                "value": "72965",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": CAPTION,
                "tag": TAG,
            },
        )

        panel = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/balance_sheet").text, "lxml"
        ).select_one("#corrections").get_text(" ")
        assert "Lines learned from this company’s filings" in panel
        assert CAPTION in panel

        response = client.post(
            f"/accounts/{two_years.id}/filer-lines/forget",
            data={"metric": TAG, "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "line-forgotten" in response.headers["location"]
        assert _learned(session) == {}
        # The figure stays: only the offering is forgotten.
        session.expire_all()
        assert session.get(FundamentalPeriod, two_years.id).metrics[TAG] == pytest.approx(72965.0)

    def test_the_line_can_be_taken_out_like_any_other(self, client, session, two_years):
        """The ledger offers the same remove link beside it, so the route has to accept a metric
        that is not in the chart -- and only when the filer actually has such a line."""
        client.post(
            f"/accounts/{two_years.id}/corrections/add",
            data={
                "metric": f"new:{TAG}",
                "value": "72965",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": CAPTION,
                "tag": TAG,
            },
        )

        soup = BeautifulSoup(
            client.get(f"/accounts/{two_years.id}/balance_sheet").text, "lxml"
        )
        row = next(item for item in soup.select("table.ledger tbody tr") if CAPTION in item.get_text(" "))
        assert row.select_one("td.act a") is not None, "no remove link on a learned line"

        client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": TAG, "statement": "balance_sheet"},
        )

        session.expire_all()
        assert TAG not in (session.get(FundamentalPeriod, two_years.id).metrics or {})

    def test_a_metric_that_is_neither_a_chart_line_nor_a_learned_one_is_refused(
        self, client, session, two_years
    ):
        response = client.post(
            f"/accounts/{two_years.id}/corrections/remove",
            data={"metric": "us-gaap:NotALineAtAll", "statement": "balance_sheet"},
            follow_redirects=False,
        )

        assert "no-line" in response.headers["location"]


class TestALineTheChartHasCaughtUpWith:
    """`TAG_MAP` grows, and a caption a reader taught the page may be one the chart carries now.

    Where the chart's line holds a figure, the learned line is that same money again -- the
    extractor filled the chart line from the payload while the reader's figure still sits under
    the tag -- so it stops being printed, stops being counted, and is reported.
    """

    def _learn(self, session, tag: str, label: str = "Inventories") -> None:
        rules = corrections.load_filer(session, CIK)
        corrections.learn_line(
            rules,
            tag,
            label=label,
            statement="balance_sheet",
            section="Current assets",
            tag=tag,
        )
        corrections.save_filer(session, CIK, rules)
        session.commit()

    def test_a_learned_line_the_chart_now_carries_is_reported_and_not_printed(
        self, client, session
    ):
        """`us-gaap:InventoryNet` is the Inventory line, and this period holds a figure for it,
        so the learned copy is the same money again."""
        period = _store(
            session,
            _period("TEST_US_EQ", dt.date(2024, 12, 31), {**FIGURES, "inventory": 120.0}),
        )
        self._learn(session, "us-gaap:InventoryNet")
        # And the reader's own figure under the tag, which is what the extractor's Inventory line
        # would now be duplicating.
        client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": "us-gaap:InventoryNet",
                "value": "120",
                "statement": "balance_sheet",
                "tag": "us-gaap:InventoryNet",
            },
        )

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/balance_sheet").text, "lxml")
        panel = soup.select_one("#corrections").get_text(" ")

        assert "Superseded lines" in panel
        assert "no longer printed or counted" in panel
        # Printed once, as the chart's own line -- not twice.
        chart_label = ledger.BY_KEY["inventory"].label
        rows = [
            row
            for row in soup.select("table.ledger tbody tr")
            if chart_label in row.get_text(" ")
        ]
        assert len(rows) == 1, [row.get_text(" ") for row in rows]

    def test_it_keeps_its_place_while_the_chart_s_line_holds_nothing(self, client, session):
        """Nothing else is holding that figure, so hiding it would lose the one set of accounts
        that has it."""
        period = _store(
            session,
            _period("TEST_US_EQ", dt.date(2024, 12, 31), {"revenue": 1_000.0}),
        )
        self._learn(session, "us-gaap:InventoryNet")

        soup = BeautifulSoup(client.get(f"/accounts/{period.id}/balance_sheet").text, "lxml")

        assert "Superseded lines" not in soup.get_text(" "), "the chart's line holds no figure"
        assert any(
            "Inventories" in row.get_text(" ") for row in soup.select("table.ledger tbody tr")
        ), "the learned line is still printed"
        form = BeautifulSoup(
            client.get(
                f"/accounts/{period.id}/corrections/new", params={"statement": "balance_sheet"}
            ).text,
            "lxml",
        )
        assert any(
            option["value"] == "us-gaap:InventoryNet"
            for option in form.select("select[name=metric] option")
        ), "and still offered"


class TestTheLedgerDecidesWhereAHeadingCounts:
    """A pure table, because it is the only place that decides which stated total a learned line
    joins -- and the one heading it deliberately does not decide for.

    It used to be `EXTRA_GROUP`, a mapping from a printed heading to a group, with a second map for
    which totals each group feeds. Both are now one fact per heading (:data:`layout.SECTION_FEEDS`)
    plus one per subtotal (:data:`layout.SUBTOTAL_GROUPS`), and the statement and the checks read them
    through :class:`layout.Layout` -- so the table below is the *only* statement of the rule rather
    than a copy of it.
    """

    def _layout(self, section: str, statement: str = "balance_sheet") -> layout_module.Layout:
        account = ledger.Account(
            key=TAG, label=CAPTION, statement=statement, section=section, side="credit"
        )
        return layout_module.Layout.build(
            learned=[
                layout_module.placement_for(
                    account, statement=statement, section=section
                )
            ]
        )

    @pytest.mark.parametrize(
        "section, group",
        [
            ("Current assets", "current_assets"),
            ("Non-current assets", "non_current_assets"),
            ("Current liabilities", "current_liabilities"),
            ("Non-current liabilities", "non_current_liabilities"),
            ("Equity", ""),
            ("Memorandum", ""),
        ],
    )
    def test_a_heading_decides_which_subtotal_a_line_is_counted_in(self, section, group):
        counted = (
            [placement.key for placement in self._layout(section).components("balance_sheet", group)]
            if group
            else []
        )

        assert (TAG in counted) is bool(group)

    def test_each_stated_subtotal_is_summed_from_the_groups_it_names(self):
        """The two totals the checks measure, and the groups each is summed from.

        `total_assets` is *both* asset groups and not the stated current-assets subtotal, which is
        the choice that keeps the residual against a stated total a measure of the lines we do not
        hold rather than of our own arithmetic. One table, read by the statement and the check.
        """
        assert layout_module.SUBTOTAL_GROUPS == {
            "current_assets": ("current_assets",),
            "total_assets": ("current_assets", "non_current_assets"),
            "current_liabilities": ("current_liabilities",),
            "total_liabilities": ("current_liabilities", "non_current_liabilities"),
        }

    def test_every_counted_heading_is_a_heading_the_statement_prints(self):
        """The table above is keyed by printed headings, so a rename in the chart would silently
        stop counting a line. This is the join between the two, and it is per statement: the map
        covers the balance sheet's four component headings and the profit and loss's three stages,
        and a heading that belongs to one of them proves nothing about the other."""
        for statement, heading in layout_module.SECTION_FEEDS:
            assert heading in layout_module.base_sections(statement), (
                f"{heading!r} is not a heading {statement} prints"
            )

    def test_a_heading_of_another_statement_never_counts(self):
        placed = self._layout("Current assets", statement="cash_flow")

        counted = [
            placement.key
            for placement in placed.components("balance_sheet", "current_assets")
        ]

        assert TAG not in counted

    def test_a_heading_whose_lines_are_summed_by_nothing_is_reported_as_uncounted(self):
        counted = ledger.Account(
            key=TAG, label=CAPTION, statement="balance_sheet", section="Current liabilities",
            side="credit",
        )
        equity = ledger.Account(
            key="test:equity", label="An equity line", statement="balance_sheet",
            section="Equity", side="credit",
        )
        placed = layout_module.Layout.build(
            learned=[
                layout_module.placement_for(
                    account, statement="balance_sheet", section=account.section
                )
                for account in (counted, equity)
            ]
        )

        assert [placement.key for placement in placed.uncounted("balance_sheet")] == [
            "test:equity"
        ]


def _profit_period(**overrides) -> FundamentalPeriod:
    """A year whose stated profit is **60 short of the lines we hold**, on purpose.

    The gap is the whole point: it is the "out by X" a reader adds a line to fix, and a fixture
    where the two already agreed could not tell a counted line from an uncounted one.
    """
    metrics = {
        "revenue": 1_000.0,
        "cost_of_goods_sold": 600.0,
        "sga_expense": 150.0,
        "tax_expense": 0.0,
        # The filing's own figure, 60 below the 250 the three lines above add up to.
        "net_income": 190.0,
    }
    metrics.update(overrides)
    return _period("TEST_US_EQ", dt.date(2024, 12, 31), metrics)


def _learned_for(section: str, *, side: str, key: str | None = None) -> ledger.Account:
    """A line learned from a filing under one heading, as `corrections` would build it."""
    return ledger.Account(
        key=key or f"test:{section.replace(' ', '')}",
        label=f"A {section.lower()} line",
        statement="profit_and_loss",
        section=section,
        side=side,
    )


def _with(accounts) -> ledger.Layout:
    """A layout carrying these learned lines, as `corrections.build_layout` would build it.

    The ledger takes the *presentation*, not a bag of extra accounts: which heading a line was
    learned under is what decides the subtotal it feeds, and the layout is where that is settled.
    """
    return ledger.Layout.build(
        learned=[
            layout_module.placement_for(
                account, statement=account.statement, section=account.section
            )
            for account in accounts
        ]
    )


def _learned_period(
    section: str, value: float, *, side: str
) -> tuple[FundamentalPeriod, list[ledger.Account]]:
    """A year's result plus one figure the filer named, already written onto the period.

    Two things at once, because they are two halves of one act: the line is learned under a
    heading (which decides where it counts) and its figure is written through into ``metrics``
    (which is what the statement sums).
    """
    account = _learned_for(section, side=side)
    return _profit_period(**{account.key: value}), [account]


def _line(statement: ledger.Statement, section: str, key: str) -> ledger.Line:
    for built in statement.sections:
        if built.title != section:
            continue
        for line in built.lines:
            if line.key == key:
                return line
    raise AssertionError(f"no line {key!r} under {section!r}")


class TestALineOnTheProfitAndLossJoinsTheCascade:
    """Reported 2026-10-10: *"I can now add additional figures to the accounts, but they appear
    below the section total and aren't included in the section total calculation, the one
    highlighted as 'out by X'. The point of adding these values is to fix the 'out by X'."*

    Both halves of that, and the rule that makes the second one decidable: the heading says
    which subtotal the line first feeds, and the side the reader posted it on says which way --
    the same convention the chart's own income lines follow and the trial balance posts by.
    """

    def test_a_figure_printed_negative_is_deducted(self):
        """**A learned line's figure is its own direction.** The filing prints a deduction as
        ``(63,061)``, the picker keeps that sign, and the statement adds the figure as it stands
        -- so what the working shows beside a line is exactly what the accounts print for it.

        Reported 2026-10-10, after the side had been read as a direction as well: *"the account
        seems to show the correct values, but the calculation in the 'out by X' hint is using
        invalid signs"*, with dividend income printed at 1,680,000 and subtracted in the working
        because every line the reader had added carried the form's default side.
        """
        period, extra = _learned_period("Operating expenses", -40.0, side="debit")

        statement = ledger.profit_and_loss(period, layout=_with(extra))

        assert _line(statement, "Operating expenses", "operating_income").computed == 210.0
        assert _line(statement, "Finance and tax", "net_income").computed == 210.0
        # And not in the subtotal above it: a line under a heading joins that stage *and
        # everything below*, never the one it was not filed under.
        assert _line(statement, "Revenue", "gross_profit").computed == 400.0

    def test_a_figure_printed_positive_is_added_whatever_side_it_is_posted_on(self):
        """The side is a record, not a direction -- so the same figure moves the same way posted
        either way, and a reader cannot make a line subtract by calling it a debit."""
        for side in ("debit", "credit"):
            account = _learned_for("Finance and tax", side=side)
            period = _profit_period(**{account.key: 1_680_000.0})

            work = _line(
                ledger.profit_and_loss(period, layout=_with([account])),
                "Finance and tax",
                "pretax_income",
            )

            assert work.computed == 250.0 + 1_680_000.0, side

    def test_a_credit_under_revenue_is_added_to_gross_profit_and_below(self):
        period, extra = _learned_period("Revenue", 100.0, side="credit")

        statement = ledger.profit_and_loss(period, layout=_with(extra))

        assert _line(statement, "Revenue", "gross_profit").computed == 500.0
        assert _line(statement, "Operating expenses", "operating_income").computed == 350.0
        assert _line(statement, "Finance and tax", "net_income").computed == 350.0

    def test_a_line_under_finance_and_tax_joins_at_profit_before_tax(self):
        period, extra = _learned_period("Finance and tax", 7.0, side="credit")

        statement = ledger.profit_and_loss(period, layout=_with(extra))

        assert _line(statement, "Operating expenses", "operating_income").computed == 250.0
        assert _line(statement, "Finance and tax", "pretax_income").computed == 257.0
        assert _line(statement, "Finance and tax", "net_income").computed == 257.0

    def test_the_working_beside_the_figure_lists_the_learned_line(self):
        """The hover has to add up to the figure it sits beside, or the residual a reader is
        looking at is explained by arithmetic that does not produce it."""
        period, extra = _learned_period("Operating expenses", -40.0, side="debit")
        account = extra[0]

        work = _line(ledger.profit_and_loss(period, layout=_with(extra)), "Operating expenses", "operating_income")

        contributions = {part.source: part.contribution for part in work.parts}
        # The contribution *is* the stored figure, so the working and the figure column agree.
        assert contributions[account.key] == -40.0
        assert sum(contributions.values()) == work.computed
        assert account.label in work.show_work()

    def test_the_learned_line_is_printed_above_the_subtotal_it_feeds(self):
        """Position is the other half of the report: under the total it reads as a memorandum."""
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")

        statement = ledger.profit_and_loss(period, layout=_with(extra))
        section = next(s for s in statement.sections if s.title == "Operating expenses")
        keys = [line.key for line in section.lines]

        assert keys.index(extra[0].key) < keys.index("operating_income")

    def test_the_balance_sheet_prints_its_learned_lines_above_the_total_too(self):
        """The same rule on the other statement, which is where they were appended after it."""
        account = ledger.Account(
            key=TAG,
            label=CAPTION,
            statement="balance_sheet",
            section="Current liabilities",
            side="credit",
        )
        period = _period("TEST_US_EQ", dt.date(2024, 12, 31), dict(FIGURES))

        statement = ledger.balance_sheet(period, layout=_with([account]))
        section = next(s for s in statement.sections if s.title == "Current liabilities")
        keys = [line.key for line in section.lines]

        assert keys.index(TAG) < keys.index("current_liabilities")

    def test_the_health_check_counts_the_same_lines_the_statement_does(self):
        """One cascade, two callers. A figure the statement counts and the audit does not is the
        disagreement the shared arithmetic exists to prevent -- one row apart on the same page."""
        period, extra = _learned_period("Operating expenses", -40.0, side="debit")

        statement = ledger.profit_and_loss(period, layout=_with(extra))
        check = ledger.profit_articulation(period, _with(extra))

        assert check.inputs["computed"] == _line(statement, "Finance and tax", "net_income").computed
        assert check.inputs["computed"] == 210.0

    def test_the_residual_the_line_was_added_to_fix_moves_by_it(self):
        """The reader's own words for what this is for: *"the point of adding these values is to
        fix the 'out by X' calculations"*. The stated figure does not move; the computed one does,
        by exactly the figure added."""
        before = ledger.profit_articulation(_profit_period())
        period, extra = _learned_period("Operating expenses", -40.0, side="debit")
        after = ledger.profit_articulation(period, _with(extra))

        assert before.residual == -60.0, "the fixture's gap, before anything is added"
        assert after.residual - before.residual == 40.0

    def test_a_heading_whose_lines_are_counted_is_no_longer_reported_as_uncounted(self):
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")

        assert _with(extra).uncounted("profit_and_loss") == ()
        assert ledger.uncounted_note(_with(extra), "profit_and_loss") is None
        assert ledger.uncounted_note(
            _with(
                [
                    ledger.Account(
                        key="test:x",
                        label="x",
                        statement="profit_and_loss",
                        section="Memorandum",
                        side="credit",
                    )
                ]
            ),
            "profit_and_loss",
        ) is not None

    def test_a_figure_the_filing_prints_negative_is_deducted(self):
        """What the filing brackets is a negative, the picker keeps it, and the statement adds it
        as it stands -- the size is the figure's and so is the direction."""
        account = _learned_for("Operating expenses", side="debit")
        period = _profit_period(**{account.key: -40.0})

        work = _line(
            ledger.profit_and_loss(period, layout=_with([account])), "Operating expenses", "operating_income"
        )

        assert work.computed == 210.0
        assert {part.source: part.contribution for part in work.parts}[account.key] == -40.0

    def test_a_chart_line_stored_negative_is_still_deducted(self):
        """Reported 2026-10-10: *"the account display reads the correct sign, but the 'out by X'
        calculation is still using the positive sign"* -- with SG&A taken out and put back by hand
        as `(64,410)`.

        The chart's own weight is the direction for a line it does **not** call ``signed``, so the
        figure is read as a magnitude whether the filing printed it in brackets or not: an expense
        deducted is still deducted, and the number in the working is the number in the figure
        column rather than its opposite.
        """
        period = _profit_period(sga_expense=-150.0)

        work = _line(ledger.profit_and_loss(period), "Operating expenses", "operating_income")

        assert work.computed == 250.0
        assert {part.source: part.contribution for part in work.parts}["sga_expense"] == -150.0

    def test_a_line_the_chart_calls_signed_keeps_its_sign(self):
        """``other_nonoperating_income`` is signed, and that flag means exactly this: a negative
        there is an ordinary reading -- a loss -- rather than a figure the weight has to place."""
        period = _profit_period(other_nonoperating_income=-20.0)

        work = _line(ledger.profit_and_loss(period), "Finance and tax", "pretax_income")

        assert work.computed == 230.0
        assert {part.source: part.contribution for part in work.parts}[
            "other_nonoperating_income"
        ] == -20.0

    def test_a_figure_nobody_stated_is_not_a_component(self):
        """A learned line with no figure under it must not appear as a zero: the working would
        then claim the filing stated nothing there, which is a different fact from our not
        holding it."""
        account = _learned_for("Operating expenses", side="debit", key="test:notheld")
        period = _profit_period()

        work = _line(
            ledger.profit_and_loss(period, layout=_with([account])), "Operating expenses", "operating_income"
        )

        assert work.computed == 250.0
        assert [part.source for part in work.parts if part.source == account.key] == []

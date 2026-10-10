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

The last two are the reason the heading matters rather than being decoration. ``ledger`` decides
which subtotal a heading feeds from :data:`ledger.EXTRA_GROUP`, and the one heading that holds
both liabilities and equity is deliberately not in it: a figure that could be either is printed
and reported as uncounted rather than guessed into a total.
"""

from __future__ import annotations

import datetime as dt

import pytest
from bs4 import BeautifulSoup

from awltux.analysis import corrections, ledger
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
        assert "Current liabilities" in option.get_text(" ")
        labels = [group["label"] for group in soup.select("select[name=metric] optgroup")]
        assert any("Lines from this company" in label for label in labels), labels

    def test_no_filer_no_line_to_create(self, client, session):
        """A line belongs to the company that filed it. Without a CIK there is nothing to record
        it against, and a line stored on one period would silently not reach the next."""
        period = _store(session, _period("TEST_US_EQ", dt.date(2024, 12, 31)), cik=None)

        response = client.post(
            f"/accounts/{period.id}/corrections/add",
            data={
                "metric": f"new:{TAG}",
                "value": "72965",
                "statement": "balance_sheet",
                "section": "Current liabilities",
                "caption": CAPTION,
                "tag": TAG,
            },
            follow_redirects=False,
        )

        assert "no-filer" in response.headers["location"]
        session.expire_all()
        assert "us-gaap:ContractWithCustomerLiabilityCurrent" not in (
            session.get(FundamentalPeriod, period.id).metrics or {}
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
    joins -- and the one heading it deliberately does not decide for."""

    def _account(self, section: str) -> ledger.Account:
        return ledger.Account(
            key=TAG, label=CAPTION, statement="balance_sheet", section=section, side="credit"
        )

    @pytest.mark.parametrize(
        "section, subtotal, counted",
        [
            ("Current assets", "current_assets", True),
            ("Current assets", "total_assets", True),
            ("Non-current assets", "total_assets", True),
            ("Non-current assets", "current_assets", False),
            ("Current liabilities", "current_liabilities", True),
            ("Current liabilities", "total_liabilities", True),
            ("Non-current liabilities", "total_liabilities", True),
            ("Non-current liabilities", "current_liabilities", False),
            ("Equity", "total_liabilities", False),
            ("Memorandum", "total_assets", False),
        ],
    )
    def test_a_heading_feeds_the_totals_it_is_part_of(self, section, subtotal, counted):
        keys = ledger.subtotal_extra_keys([self._account(section)], "balance_sheet", subtotal)

        assert (keys == (TAG,)) is counted

    def test_every_heading_that_is_counted_is_a_heading_the_statement_prints(self):
        """The table above is keyed by printed headings, so a rename in the statement would
        silently stop counting a line. This is the join between the two, and it is per
        statement: the map covers the balance sheet's four component headings and the profit
        and loss's three stages, and a heading that belongs to one of them proves nothing
        about the other."""
        period = FundamentalPeriod(
            instrument_t212_ticker="X",
            period_end=dt.date(2026, 1, 1),
            period_type="annual",
            currency="USD",
            source="xbrl_companyfacts",
            metrics={},
        )

        for statement, heading in ledger.EXTRA_GROUP:
            printed = {
                section.title for section in ledger.statement(period, statement).sections
            }
            assert heading in printed, f"{heading!r} is not a heading {statement} prints"

    def test_a_heading_of_another_statement_never_counts(self):
        account = ledger.Account(
            key=TAG, label=CAPTION, statement="cash_flow", section="Current assets", side="credit"
        )

        assert ledger.subtotal_extra_keys([account], "balance_sheet", "current_assets") == ()

    def test_a_heading_whose_lines_are_summed_by_nothing_is_reported_as_uncounted(self):
        counted = self._account("Current liabilities")
        equity = self._account("Equity")

        assert ledger.uncounted_extras([counted, equity], "balance_sheet") == [equity]


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

    def test_a_debit_under_operating_expenses_is_deducted_from_operating_income_and_below(self):
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")

        statement = ledger.profit_and_loss(period, extra=extra)

        assert _line(statement, "Operating expenses", "operating_income").computed == 210.0
        assert _line(statement, "Finance and tax", "pretax_income").computed == 210.0
        assert _line(statement, "Finance and tax", "net_income").computed == 210.0
        # And not in the subtotal above it: a line under a heading joins that stage *and
        # everything below*, never the one it was not filed under.
        assert _line(statement, "Revenue", "gross_profit").computed == 400.0

    def test_a_credit_under_revenue_is_added_to_gross_profit_and_below(self):
        period, extra = _learned_period("Revenue", 100.0, side="credit")

        statement = ledger.profit_and_loss(period, extra=extra)

        assert _line(statement, "Revenue", "gross_profit").computed == 500.0
        assert _line(statement, "Operating expenses", "operating_income").computed == 350.0
        assert _line(statement, "Finance and tax", "net_income").computed == 350.0

    def test_a_line_under_finance_and_tax_joins_at_profit_before_tax(self):
        period, extra = _learned_period("Finance and tax", 7.0, side="credit")

        statement = ledger.profit_and_loss(period, extra=extra)

        assert _line(statement, "Operating expenses", "operating_income").computed == 250.0
        assert _line(statement, "Finance and tax", "pretax_income").computed == 257.0
        assert _line(statement, "Finance and tax", "net_income").computed == 257.0

    def test_the_working_beside_the_figure_lists_the_learned_line(self):
        """The hover has to add up to the figure it sits beside, or the residual a reader is
        looking at is explained by arithmetic that does not produce it."""
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")
        account = extra[0]

        work = _line(ledger.profit_and_loss(period, extra=extra), "Operating expenses", "operating_income")

        contributions = {part.source: part.contribution for part in work.parts}
        assert contributions[account.key] == -40.0
        assert sum(contributions.values()) == work.computed
        assert account.label in work.show_work()

    def test_the_learned_line_is_printed_above_the_subtotal_it_feeds(self):
        """Position is the other half of the report: under the total it reads as a memorandum."""
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")

        statement = ledger.profit_and_loss(period, extra=extra)
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

        statement = ledger.balance_sheet(period, extra=[account])
        section = next(s for s in statement.sections if s.title == "Current liabilities")
        keys = [line.key for line in section.lines]

        assert keys.index(TAG) < keys.index("current_liabilities")

    def test_the_health_check_counts_the_same_lines_the_statement_does(self):
        """One cascade, two callers. A figure the statement counts and the audit does not is the
        disagreement the shared arithmetic exists to prevent -- one row apart on the same page."""
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")

        statement = ledger.profit_and_loss(period, extra=extra)
        check = ledger.profit_articulation(period, extra)

        assert check.inputs["computed"] == _line(statement, "Finance and tax", "net_income").computed
        assert check.inputs["computed"] == 210.0

    def test_the_residual_the_line_was_added_to_fix_moves_by_it(self):
        """The reader's own words for what this is for: *"the point of adding these values is to
        fix the 'out by X' calculations"*. The stated figure does not move; the computed one does,
        by exactly the figure added."""
        before = ledger.profit_articulation(_profit_period())
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")
        after = ledger.profit_articulation(period, extra)

        assert before.residual == -60.0, "the fixture's gap, before anything is added"
        assert after.residual - before.residual == 40.0

    def test_a_heading_whose_lines_are_counted_is_no_longer_reported_as_uncounted(self):
        period, extra = _learned_period("Operating expenses", 40.0, side="debit")

        assert ledger.uncounted_extras(extra, "profit_and_loss") == []
        assert ledger.uncounted_note(extra, "profit_and_loss") is None
        assert ledger.uncounted_note(
            [
                ledger.Account(
                    key="x",
                    label="x",
                    statement="profit_and_loss",
                    section="Memorandum",
                    side="credit",
                )
            ],
            "profit_and_loss",
        ) is not None

    def test_a_figure_the_filing_prints_negative_still_moves_by_its_side(self):
        """The sign is the figure's and the direction is the side's, so a deduction the filer
        brackets -- which the picker now keeps as a negative -- and the reader posts as a debit
        takes away rather than adding. Reading the sign as a second direction would flip it, and
        that is the case this filing is full of: Danaos prints its operating expenses as
        ``(63,061)`` and ``(208,779)``."""
        account = _learned_for("Operating expenses", side="debit")
        period = _profit_period(**{account.key: -40.0})

        work = _line(
            ledger.profit_and_loss(period, extra=[account]), "Operating expenses", "operating_income"
        )

        assert work.computed == 210.0
        assert {part.source: part.contribution for part in work.parts}[account.key] == -40.0

    def test_a_figure_nobody_stated_is_not_a_component(self):
        """A learned line with no figure under it must not appear as a zero: the working would
        then claim the filing stated nothing there, which is a different fact from our not
        holding it."""
        account = _learned_for("Operating expenses", side="debit", key="test:notheld")
        period = _profit_period()

        work = _line(
            ledger.profit_and_loss(period, extra=[account]), "Operating expenses", "operating_income"
        )

        assert work.computed == 250.0
        assert [part.source for part in work.parts if part.source == account.key] == []

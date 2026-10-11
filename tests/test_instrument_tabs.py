"""The instrument page's tabs, and the summary that sits above them.

Asked for directly: *"The Instrument page is quite long now. Use UI tabs to make the topic
headings easier to navigate. Have a minimal top-of-page summary for the instrument, with the
detail tabs below."*

The page had grown to nine topics on one scroll. The tests below are about the three things
that splitting it can break:

* **A topic must be reachable and must actually be the only one rendered.** Content bleeding
  across tabs would make the split cosmetic, and a topic with no tab at all is the failure a
  reader meets as a blank page.
* **The summary must not duplicate the detail**, or the long page is back -- it is supposed
  to answer "which tab do I want" and stop.
* **A bad `?tab=` must not cost the reader the page.** It is a view selector, not the
  address, so it is ignored *and reported* rather than obeyed or 404'd.
"""

from __future__ import annotations

import datetime as dt

import pytest
from bs4 import BeautifulSoup

from awltux.db import Instrument, PriceBar
from tests.helpers import make_instrument


def _instrument(session, ticker: str = "TEST_US_EQ", **overrides):
    row = make_instrument(ticker, **overrides)
    session.add(row)
    session.flush()
    return row


def _bars(session, ticker: str, closes: list[float]) -> None:
    start = dt.date(2026, 1, 1)
    for index, close in enumerate(closes):
        session.add(
            PriceBar(
                instrument_t212_ticker=ticker,
                date=start + dt.timedelta(days=index),
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                volume=1_000.0,
                currency="USD",
                raw_currency="USD",
                raw_multiplier=1.0,
                raw_close=close,
                source="test",
                source_rank=20,
            )
        )
    session.flush()


class TestTheTabStrip:
    def test_every_topic_has_a_tab(self, client, session):
        _instrument(session)
        session.commit()

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ").text, "lxml")
        labels = [a.get_text(strip=True) for a in soup.select("nav.tabs a")]

        assert labels == [
            "Decision",
            "Valuation",
            "Price history",
            "Published reports",
            "Accounts",
            "News",
            "Research",
            "Position",
            "Refresh",
        ]

    def test_the_tabs_are_links_to_their_own_urls(self, client, session):
        """A strip that only moved a highlight would need JavaScript and would leave "send
        me the news for this company" unanswerable -- the reason `accounts_page` gives."""
        _instrument(session)
        session.commit()

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ").text, "lxml")
        hrefs = {a.get_text(strip=True): a["href"] for a in soup.select("nav.tabs a")}

        assert hrefs["News"] == "/instrument/TEST_US_EQ?tab=news"
        assert hrefs["Refresh"] == "/instrument/TEST_US_EQ?tab=refresh"

    def test_the_current_tab_is_marked(self, client, session):
        _instrument(session)
        session.commit()

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ?tab=valuation").text, "lxml")
        active = soup.select("nav.tabs a.active")

        assert [a.get_text(strip=True) for a in active] == ["Valuation"]
        assert active[0].get("aria-current") == "page"

    def test_a_bare_url_opens_the_decision_tab(self, client, session):
        """"What do you think" is the question the page exists to answer."""
        _instrument(session)
        session.commit()

        body = client.get("/instrument/TEST_US_EQ").text

        assert "<h2>Decision</h2>" in body

    @pytest.mark.parametrize(
        "tab, marker",
        [
            ("decision", "<h2>Decision</h2>"),
            ("valuation", "<h2>Valuation</h2>"),
            ("price", 'id="price-chart"'),
            ("reports", "Published reports"),
            ("accounts", "Accounts"),
            ("news", "News"),
            ("position", "Your position"),
            ("refresh", "Refresh this instrument"),
        ],
    )
    def test_each_tab_renders_its_own_topic(self, client, session, tab, marker):
        _instrument(session)
        session.commit()

        body = client.get(f"/instrument/TEST_US_EQ?tab={tab}").text

        assert marker in body, f"the {tab} tab does not show {marker!r}"

    def test_only_the_current_topic_is_rendered(self, client, session):
        """The point of the split: the other seven topics are not in the document at all.

        Asserted by looking for headings rather than by counting bytes, so the failure this
        catches is content bleeding across tabs -- which would leave the page as long as it
        was while looking as though it had been fixed.
        """
        _instrument(session)
        session.commit()

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ?tab=news").text, "lxml")
        headings = {h.get_text(strip=True) for h in soup.find_all("h2")}

        assert "News" in headings
        assert "Decision" not in headings
        assert "Valuation" not in headings
        assert "Published reports" not in headings
        assert "Your position" not in headings
        assert "Refresh this instrument" not in headings

    def test_an_unknown_tab_is_reported_rather_than_obeyed(self, client, session):
        """A renamed tab should cost a bookmark its tab, not the page.

        `web/filters.py` states the rule for a query parameter: render, and say what was
        ignored. This is a view selector rather than the address, so a 404 -- which is what
        `accounts_page` does for an unknown *statement* in the path -- would be the wrong
        trade here.
        """
        _instrument(session)
        session.commit()

        body = " ".join(client.get("/instrument/TEST_US_EQ?tab=banana").text.split())

        assert "No tab called" in body
        assert "<code>banana</code>" in body
        assert "<h2>Decision</h2>" in body, "and the default topic is shown"

    def test_an_unknown_tab_does_not_appear_in_the_strip(self, client, session):
        _instrument(session)
        session.commit()

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ?tab=banana").text, "lxml")
        active = [a.get_text(strip=True) for a in soup.select("nav.tabs a.active")]

        assert active == ["Decision"]


class TestTheSummary:
    def test_it_states_the_price_and_the_last_close_date(self, client, session):
        _instrument(session)
        _bars(session, "TEST_US_EQ", [100.0, 101.0, 110.0])
        session.commit()

        body = " ".join(client.get("/instrument/TEST_US_EQ").text.split())

        assert "110.00" in body
        assert "last close, 2026-01-03" in body

    def test_the_price_is_the_last_point_of_the_chart(self, client, session):
        """One query behind both, so the strip and the line cannot disagree."""
        _instrument(session)
        _bars(session, "TEST_US_EQ", [100.0, 101.0, 110.0])
        session.commit()

        body = client.get("/instrument/TEST_US_EQ?tab=price").text
        series = body.split("data-series='")[1].split("'")[0]

        assert series.endswith("[100.0, 101.0, 110.0]")
        assert "110.00" in " ".join(body.split()), "the strip agrees with the last bar"

    def test_it_reports_the_change_on_the_day(self, client, session):
        _instrument(session)
        _bars(session, "TEST_US_EQ", [100.0, 110.0])
        session.commit()

        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())

        assert "+10.0%" in text
        assert "on the day" in text

    def test_a_single_bar_shows_a_price_and_no_change(self, client, session):
        """One point is not a movement, and inventing one from nothing would be a claim."""
        _instrument(session)
        _bars(session, "TEST_US_EQ", [100.0])
        session.commit()

        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())

        assert "100.00" in text
        assert "on the day" not in text

    def test_no_bars_says_so_rather_than_showing_zero(self, client, session):
        _instrument(session)
        session.commit()

        text = " ".join(client.get("/instrument/TEST_US_EQ").text.split())

        assert "no price stored" in text
        assert "0.00" not in text

    def test_a_verdict_is_omitted_rather_than_shown_empty(self, client, session):
        """No decision is not "a call was made and came back blank".

        The fixture has no decision row, so the two verdict cells are absent -- printing an
        em dash or a "no call" badge would be the summary claiming the engine had spoken.
        """
        _instrument(session)
        session.commit()

        summary = BeautifulSoup(
            client.get("/instrument/TEST_US_EQ").text, "lxml"
        ).select_one("section.instrument-summary")
        text = summary.get_text(" ", strip=True)

        assert "Long term" not in text
        assert "Short term" not in text
        assert "no call" not in text

    def test_the_reference_detail_is_folded_away(self, client, session):
        """Nine cells of ISIN and CIK opened the page and said nothing about the company."""
        _instrument(session, isin="US0378331005", sec_cik="0000320193")
        session.commit()

        soup = BeautifulSoup(client.get("/instrument/TEST_US_EQ").text, "lxml")
        details = soup.find("details", class_="instrument-details")

        assert details is not None, "the details are gone rather than folded"
        assert not details.has_attr("open"), "and folded closed by default"
        assert "US0378331005" in details.get_text(), "nothing is lost by folding it"

    def test_the_summary_does_not_repeat_the_detail(self, client, session):
        """The valuation's methods, the gate's checks and the trade table stay on their tabs.

        A summary that grew would rebuild the page this replaced, so what it must *not*
        contain is asserted rather than what it must.
        """
        _instrument(session)
        _bars(session, "TEST_US_EQ", [100.0, 101.0])
        session.commit()

        summary = BeautifulSoup(
            client.get("/instrument/TEST_US_EQ").text, "lxml"
        ).select_one("section.instrument-summary")
        text = summary.get_text(" ", strip=True)

        assert "Risk-free rate" not in text
        assert "gate allowed" not in text
        assert "Composite" not in text


class TestTheSummaryIsTheSameOnEveryTab:
    @pytest.mark.parametrize(
        "tab",
        ["decision", "valuation", "price", "reports", "accounts", "news", "position", "refresh"],
    )
    def test_every_tab_carries_the_same_summary(self, client, session, tab):
        """The summary is what a reader navigates by, so it does not move or vanish."""
        _instrument(session)
        _bars(session, "TEST_US_EQ", [100.0, 110.0])
        session.commit()

        body = client.get(f"/instrument/TEST_US_EQ?tab={tab}").text
        summary = BeautifulSoup(body, "lxml").select_one("section.instrument-summary")

        assert summary is not None, f"the {tab} tab has no summary"
        assert "110.00" in summary.get_text()
        assert "last close" in summary.get_text()


class TestTheTabsAreWiredToTheirData:
    def test_the_news_tab_is_the_only_one_that_pays_for_the_news(self, session):
        """The four topic-specific sections are read only when the tab asks for them.

        Asserted on the query layer, because that is where the saving is: a page that
        rendered no news but still grouped events through the embeddings would look right
        and cost the same as before.
        """
        from awltux.web import queries

        _instrument(session)
        session.commit()

        everything = queries.instrument_detail(session, "TEST_US_EQ")
        decision_only = queries.instrument_detail(session, "TEST_US_EQ", sections=())

        assert everything["news_pages"] >= 1
        assert decision_only["news"] == []
        assert decision_only["news_events"] == []
        assert decision_only["filings"] == []
        assert decision_only["fundamentals"] == []
        assert decision_only["trades"] == []
        # The summary is built from these, so they are always read.
        assert decision_only["instrument"] is not None

    def test_an_unknown_instrument_is_still_a_404_on_every_tab(self, client):
        assert client.get("/instrument/NOPE_US_EQ?tab=news").status_code == 404


class TestRemovingFromTheUniverse:
    """The Refresh tab is where an instrument can be taken out of the universe, and the page
    it leads to is where the reader sees what that will cost.

    Asked for directly: *"existing instruments in the universe can be removed using a red
    confirmation button on the instruments refresh tab. All data held on that instrument will
    be removed once confirmed."* The colour is the stylesheet's `.danger` (the palette's
    `--bad`); what is asserted here is the wiring -- that the button appears only where the
    server would allow it, that the confirmation page states the size of the deletion, and that
    confirming does it.
    """

    def _refresh_tab(self, client, ticker: str = "TEST_US_EQ"):
        return BeautifulSoup(client.get(f"/instrument/{ticker}?tab=refresh").text, "lxml")

    def test_the_refresh_tab_offers_the_removal_in_red(self, client, session):
        _instrument(session)
        session.commit()

        page = self._refresh_tab(client)
        block = page.select_one("#remove")

        assert block is not None
        link = block.select_one("a[href='/instrument/TEST_US_EQ/remove']")
        assert link is not None, "the way to the confirmation page"
        assert link.select_one("button.danger") is not None, "and it is the red one"

    def test_a_held_position_is_told_why_instead_of_being_offered_a_button(self, client, session):
        _instrument(session, is_held=True)
        session.commit()

        block = self._refresh_tab(client).select_one("#remove")

        assert block.select_one("button") is None, "a disabled button explains nothing"
        assert "position in your account" in block.get_text(" ")

    def test_another_tab_does_not_read_the_removal_state(self, client, session):
        """`removable` is read only for the tab that offers it, so the Decision tab renders
        the same page whether or not this instrument could be removed."""
        _instrument(session)
        session.commit()

        page = BeautifulSoup(client.get("/instrument/TEST_US_EQ").text, "lxml")

        assert page.select_one("#remove") is None

    def test_the_confirmation_page_states_what_will_be_deleted(self, client, session):
        _instrument(session)
        _bars(session, "TEST_US_EQ", [1.0, 2.0, 3.0])
        session.commit()

        page = BeautifulSoup(client.get("/instrument/TEST_US_EQ/remove").text, "lxml")

        assert "Remove TEST_US_EQ from the universe" in page.get_text(" ")
        # Whole rows, so the counts print as 3 and 615 rather than 3.00: `number` defaults to
        # two decimals, which is right for a price and wrong for a row count.
        rows = {
            row.select("td")[0].get_text(" ", strip=True): row.select("td")[1].get_text(" ", strip=True)
            for row in page.select("table tbody tr")
        }
        assert rows["price bars"] == "3"
        assert rows["rows in total"] == "3"
        assert page.select_one("form[action='/instrument/TEST_US_EQ/remove'] button.danger")

    def test_an_instrument_nothing_is_held_for_says_so(self, client, session):
        _instrument(session)
        session.commit()

        page = BeautifulSoup(client.get("/instrument/TEST_US_EQ/remove").text, "lxml")

        assert "Nothing has been collected about TEST_US_EQ yet" in page.get_text(" ")

    def test_a_held_instrument_gets_no_confirm_button(self, client, session):
        _instrument(session, is_held=True)
        session.commit()

        page = BeautifulSoup(client.get("/instrument/TEST_US_EQ/remove").text, "lxml")

        assert page.select_one("form[action='/instrument/TEST_US_EQ/remove']") is None
        assert "Close the position at the broker first" in page.get_text(" ")

    def test_confirming_removes_it_and_says_so_on_the_dashboard(self, client, session):
        _instrument(session)
        _bars(session, "TEST_US_EQ", [1.0, 2.0, 3.0])
        session.commit()

        response = client.post("/instrument/TEST_US_EQ/remove", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"].startswith("/dashboard?removed=TEST_US_EQ")
        session.expire_all()
        assert session.get(Instrument, "TEST_US_EQ").in_universe is False
        page = client.get(response.headers["location"]).text
        assert "TEST_US_EQ" in page and "removed from the analysed universe" in page

    def test_a_post_the_page_would_not_offer_is_refused(self, client, session):
        """The page is a rendering and this is the act: a hand-made request must not be able to
        do what the page would not offer."""
        _instrument(session, is_held=True)
        session.commit()

        response = client.post("/instrument/TEST_US_EQ/remove", follow_redirects=False)

        assert response.headers["location"] == "/instrument/TEST_US_EQ/remove?why=held"
        session.expire_all()
        assert session.get(Instrument, "TEST_US_EQ").in_universe is True
        page = client.get(response.headers["location"]).text
        assert "Not removed" in page

    def test_an_unknown_instrument_is_a_404(self, client):
        assert client.get("/instrument/NOPE_US_EQ/remove").status_code == 404

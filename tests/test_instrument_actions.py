"""The instrument header's two actions: Refresh and Research, from any tab.

Asked for 2026-10-23: *"Add a Refresh and Research button to the instrument header, so I don't
have to open the equivalent tabs to press the buttons. The primary buttons can stay in the
tabs."*

Two properties, and they are the ones that make the shortcuts safe:

* **they are the same actions, not second implementations.** The Refresh form posts to the route
  the Refresh tab posts to, and the header's dialog is the same partial the Research block
  renders -- so the prompt each one edits is the one the run uses. What the header adds is a way
  in, not a second way to do it.
* **Refresh returns the reader to the tab they pressed it from.** A reader who presses it while
  reading the decision receipt should still be reading the decision receipt, with the outcome
  printed above the tabs. Sending them to the Refresh tab would be the "open the tab" step the
  button exists to remove.
"""

from __future__ import annotations

import datetime as dt

import pytest
from bs4 import BeautifulSoup

from awltux.db import InstrumentRefresh, utcnow
from awltux.scheduler.jobs import JobResult
from tests.helpers import make_instrument

TICKER = "ACTIONS_US_EQ"

#: Every tab the strip offers, so "from any tab" is the assertion rather than one page's.
TABS = ["decision", "valuation", "price", "reports", "accounts", "news", "research", "levers", "position", "refresh"]


@pytest.fixture(autouse=True)
def _no_real_refresh(monkeypatch):
    """Pressing Refresh must not run the pipeline: its steps call providers.

    Autouse because the failure is silent and slow -- the real steps retry HTTP with a backoff
    cap, so the test would pass in half a minute and say nothing about why.
    """
    from awltux.ingest import refresh

    monkeypatch.setattr(
        refresh,
        "_steps_from_registry",
        lambda: (refresh.Step("prices", "Prices", lambda scope: JobResult(note="stubbed")),),
    )


@pytest.fixture
def instrument(session):
    session.add(make_instrument(TICKER, name="Actions Co"))
    session.commit()
    return TICKER


def _page(client, tab: str = "decision") -> BeautifulSoup:
    return BeautifulSoup(client.get(f"/instrument/{TICKER}?tab={tab}").text, "lxml")


class TestTheHeaderOffersBothActions:
    @pytest.mark.parametrize("tab", TABS)
    def test_refresh_is_offered_on_every_tab(self, client, instrument, tab):
        actions = _page(client, tab).select_one(".instrument-actions")

        assert actions is not None, f"the {tab} tab has no header actions"
        assert actions.select_one(f"form[action='/instrument/{TICKER}/refresh']") is not None

    @pytest.mark.parametrize("tab", TABS)
    def test_research_is_offered_on_every_tab(self, client, instrument, tab):
        opener = _page(client, tab).select_one(".instrument-actions .research-open")

        assert opener is not None, f"the {tab} tab has no Research button"
        assert opener["data-dialog"] == "header-research-dialog", (
            "the button must name the dialog it opens, or it does nothing"
        )

    @pytest.mark.parametrize("tab", TABS)
    def test_the_header_dialog_is_on_the_page_it_opens_from(self, client, instrument, tab):
        """A `data-dialog` pointing at an element the page does not have is a dead button."""
        dialog = _page(client, tab).select_one("#header-research-dialog")

        assert dialog is not None, f"the {tab} tab has no header dialog"
        assert dialog.select_one("form")["action"] == f"/instrument/{TICKER}/research", (
            "it must post where the Research tab posts"
        )
        assert dialog.select_one(".research-prompt-holder")["data-prompt-url"] == (
            f"/instrument/{TICKER}/research/prompt"
        )

    def test_the_primary_buttons_stay_in_their_tabs(self, client, instrument):
        """The header is a shortcut, not a replacement -- and the Refresh tab's panel is where
        the progress log lives, so its own control has to keep existing."""
        refresh_tab = _page(client, "refresh")
        research_tab = _page(client, "research")

        assert refresh_tab.select_one("#refresh button[type=submit]") is not None
        assert research_tab.select_one("#research .research-open") is not None
        assert research_tab.select_one("#research-dialog") is not None

    def test_the_research_tab_has_both_dialogs_and_they_have_different_ids(
        self, client, instrument
    ):
        """Two elements cannot share an id, and the page's script finds a dialog *by* id."""
        soup = _page(client, "research")

        assert soup.select_one("#research-dialog") is not None
        assert soup.select_one("#header-research-dialog") is not None

    def test_the_sector_page_has_no_header_actions(self, client, session):
        """A sector has no refresh pipeline, so it gets no Refresh button; the instrument header
        is the instrument page's."""
        session.commit()

        soup = BeautifulSoup(client.get("/sectors/Energy").text, "lxml")

        assert soup.select_one(".instrument-actions") is None


class TestRefreshingFromTheHeader:
    def test_it_returns_to_the_tab_it_was_pressed_on(self, client, instrument):
        response = client.post(
            f"/instrument/{TICKER}/refresh", data={"tab": "valuation"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == (
            f"/instrument/{TICKER}?tab=valuation&refresh=started"
        )

    def test_an_unknown_tab_comes_back_to_the_refresh_panel(self, client, instrument):
        """The progress lives there, so it is the only honest place to land on a value this
        page does not have."""
        response = client.post(
            f"/instrument/{TICKER}/refresh", data={"tab": "banana"}, follow_redirects=False
        )

        assert response.headers["location"] == (
            f"/instrument/{TICKER}?tab=refresh&refresh=started"
        )

    def test_a_post_with_no_tab_still_lands_on_the_refresh_panel(self, client, instrument):
        response = client.post(f"/instrument/{TICKER}/refresh", follow_redirects=False)

        assert response.headers["location"] == (
            f"/instrument/{TICKER}?tab=refresh&refresh=started"
        )

    def test_the_outcome_is_printed_above_the_tabs(self, client, instrument):
        """Pressed from another tab, the reader has to be told it started -- the Refresh panel
        that would normally say so is not on the page."""
        body = client.get(f"/instrument/{TICKER}?tab=valuation&refresh=started").text

        assert "Refresh started" in BeautifulSoup(body, "lxml").select_one(
            "main"
        ).get_text(" ")

    def test_the_outcome_is_not_printed_twice_on_the_refresh_tab(self, client, instrument):
        body = client.get(f"/instrument/{TICKER}?tab=refresh&refresh=started").text

        assert body.count("Refresh started") == 1

    def test_the_button_says_what_is_happening_while_a_refresh_runs(self, client, session, instrument):
        """A second press is refused by the route, so the button says so before the click."""
        session.add(
            InstrumentRefresh(
                instrument_t212_ticker=TICKER,
                token="t",
                state="running",
                started_at=utcnow(),
                expires_at=utcnow() + dt.timedelta(minutes=10),
                steps=[],
            )
        )
        session.commit()

        button = _page(client, "decision").select_one(".instrument-actions button[type=submit]")

        assert button.has_attr("disabled")
        assert "Refreshing" in button.get_text()

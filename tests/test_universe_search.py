"""Finding an instrument Trading 212 lists but this universe does not, and adding it.

Asked for directly: *"If an instrument search (e.g. SCHW) has no results search the trading 212
site to see if there are a match there and display them in the results, but use colour
highlighting to make it very clear they are not currently in the instrument universe. If there
are results, provide an add button on the instrument that adds it to the local universe. Add an
option to do deep research on it as well."*

Three properties matter, and they are three different kinds of test:

* **The offer is a search of the list we already hold**, not a network call -- so these run
  offline like every other test here, and the page cannot be made slow by Trading 212's
  metadata rate limit (one request per 50 seconds).
* **The highlight is the point.** A reader must not mistake one of these for something that has
  been priced, valued or decided, so the block is asserted by its class, its chip and its
  wording rather than by "the ticker appears somewhere on the page".
* **Adding is a promise about the next refresh.** The interesting failure is not the button
  doing nothing; it is the button working until `refresh_universe` next runs and silently
  dropping the instrument again.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from awltux.db import Instrument
from awltux.ingest import universe
from awltux.research.service import Started
from awltux.web import queries
from tests.helpers import make_instrument


def _outside(session, ticker: str = "SCHW_US_EQ", **overrides):
    """An instrument Trading 212 lists that no rule selected for analysis."""
    overrides.setdefault("name", "Charles Schwab")
    overrides.setdefault("yahoo_symbol", "SCHW")
    overrides.setdefault("exchange_name", "NYSE")
    overrides.setdefault("in_universe", False)
    row = make_instrument(ticker, **overrides)
    session.add(row)
    session.flush()
    return row


class _Start:
    """`research.service.start`, stood in for: the real one takes a process-wide permit and
    starts a thread that would read the live database and call a model."""

    def __init__(self, ok: bool = True, message: str = "research started") -> None:
        self.ok = ok
        self.message = message
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> Started:
        self.calls.append(kwargs)
        return Started(self.ok, self.message, 1 if self.ok else None)


@pytest.fixture
def started(monkeypatch) -> _Start:
    stub = _Start()
    monkeypatch.setattr("awltux.research.service.start", stub)
    return stub


class TestTheCandidates:
    """What a search the universe cannot answer offers instead."""

    def test_it_offers_a_stored_instrument_the_universe_does_not_hold(self, session):
        _outside(session)
        session.commit()

        found = queries.candidates_outside_universe(session, "SCHW")

        assert [match["ticker"] for match in found["matches"]] == ["SCHW_US_EQ"]
        assert found["total"] == 1
        assert found["matches"][0]["name"] == "Charles Schwab"
        assert found["matches"][0]["symbol"] == "SCHW"

    def test_it_does_not_offer_what_the_table_already_shows(self, session):
        """The block's whole meaning is "not in the universe". An instrument that is in it
        belongs in the table above, and offering it again with an Add button would be a lie
        about what pressing it does."""
        session.add(make_instrument("SCHW_US_EQ", name="Charles Schwab", yahoo_symbol="SCHW"))
        session.flush()
        session.commit()

        found = queries.candidates_outside_universe(session, "SCHW")

        assert found["matches"] == [] and found["total"] == 0

    def test_an_explicitly_excluded_instrument_is_not_offered(self, session):
        """`excluded` is a decision not to analyse something. Offering it with an Add button
        would put the two decisions in opposition on one page, and the button would win."""
        _outside(session, excluded=True)
        session.commit()

        assert queries.candidates_outside_universe(session, "SCHW")["matches"] == []

    def test_no_search_term_asks_the_database_nothing(self, session):
        """Every page load goes through this, including the ones with no search in the URL."""
        _outside(session)
        session.commit()

        found = queries.candidates_outside_universe(session, "")

        assert found == {"matches": [], "total": 0, "capped": False}

    def test_an_exact_ticker_outranks_a_name_that_merely_contains_it(self, session):
        """Measured on the live data: `schw` matches Charles Schwab on four exchanges plus
        Schweizer Electronic, Schweizerische Nationalbank and Lang & Schwarz. One of them is
        what the reader typed."""
        _outside(session, "SWGd_EQ", name="Charles Schwab", yahoo_symbol="SWG.DE")
        _outside(session, "SCEd1_EQ", name="Schweizer Electronic", yahoo_symbol="SCED1.DE")
        _outside(session, "SCHW_US_EQ")
        session.commit()

        found = queries.candidates_outside_universe(session, "SCHW")

        assert found["total"] == 3
        assert found["matches"][0]["ticker"] == "SCHW_US_EQ"

    def test_several_matches_are_counted_not_just_shown(self, session):
        for ticker in ("SCHW_US_EQ", "SWGd_EQ"):
            _outside(session, ticker)
        session.commit()

        found = queries.candidates_outside_universe(session, "schwab")

        assert found["total"] == 2
        assert found["capped"] is False


class TestTheBlockOnThePage:
    def _page(self, client, query: str = "?q=SCHW") -> BeautifulSoup:
        return BeautifulSoup(client.get(f"/dashboard{query}").text, "lxml")

    def test_the_page_offers_it_and_says_what_it_is(self, client, session):
        _outside(session)
        session.commit()

        soup = self._page(client)
        block = soup.select_one("#outside-universe")

        assert block is not None, "a search with no universe answer offered nothing"
        assert "not in the universe" in block.select_one(".chip").get_text(" ")
        # The highlight is the class the stylesheet colours, not a sentence: the reader has
        # to see it before they read anything.
        assert block.select_one("table.outside"), "the rows carry no highlight class"
        assert block.select_one("tr.outside"), "the rows carry no highlight class"

    def test_it_offers_both_actions(self, client, session):
        _outside(session)
        session.commit()

        block = self._page(client).select_one("#outside-universe")
        forms = block.select("form[action='/instrument/SCHW_US_EQ/include']")

        assert len(forms) == 2, "add and add-and-research are two different asks"
        assert [f.select_one("input[name='research']") is not None for f in forms] == [
            False,
            True,
        ]

    def test_the_block_survives_a_page_change(self, client, session):
        """A page change fetches only the region, so a block built in the page context would
        vanish on page two -- which reads as a result set that changed."""
        _outside(session)
        session.commit()

        fragment = BeautifulSoup(
            client.get("/partials/recommendations?q=SCHW").text, "lxml"
        )

        assert fragment.select_one("#outside-universe") is not None

    def test_no_search_no_block(self, client, session):
        _outside(session)
        session.commit()

        assert self._page(client, "").select_one("#outside-universe") is None

    def test_a_name_search_finds_it_too(self, client, session):
        """The reader may type the company rather than the ticker."""
        _outside(session)
        session.commit()

        assert self._page(client, "?q=Schwab").select_one("#outside-universe") is not None


class TestAdding:
    def test_it_pins_the_instrument_and_sends_the_reader_to_it(self, client, session):
        _outside(session)
        session.commit()

        response = client.post("/instrument/SCHW_US_EQ/include", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/instrument/SCHW_US_EQ?added=1"
        session.expire_all()
        row = session.get(Instrument, "SCHW_US_EQ")
        assert row.pinned is True
        assert row.in_universe is True

    def test_the_pin_is_what_keeps_it_in_the_universe(self, session, settings):
        """The failure this prevents: the button works, and the next `universe_refresh` drops
        the instrument again because the rule that selects the universe has never heard of it.
        Measured against a cap of one, with a name large enough to outrank it on market cap.
        """
        _outside(session)
        session.add(
            make_instrument("BIG_US_EQ", name="Bigger Co", exchange_name="NYSE",
                            market_cap=1_000_000_000_000.0)
        )
        session.flush()
        session.commit()

        assert universe.include(session, "SCHW_US_EQ") is True
        session.commit()

        # `Settings.universe` is a property over `Settings.yaml`, so the cap is changed there
        # rather than on the resolved object -- `model_copy(update={"universe": ...})` sets a
        # key the property shadows and changes nothing at all.
        tiny = settings.model_copy(
            update={
                "yaml": settings.yaml.model_copy(
                    update={
                        "universe": settings.universe.model_copy(update={"size": 1})
                    }
                )
            }
        )
        universe.refresh_universe(session, tiny)
        session.expire_all()

        assert session.get(Instrument, "SCHW_US_EQ").in_universe is True
        assert session.get(Instrument, "BIG_US_EQ").in_universe is False

    def test_an_unknown_ticker_says_so_rather_than_doing_nothing(self, client, session):
        """Not "no such company": the list is synced daily, so an absent ticker means the sync
        predates the listing. Silently redirecting to the dashboard would read as a bug."""
        response = client.post("/instrument/NOPE_US_EQ/include", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard?added=unknown"
        page = client.get("/dashboard?added=unknown").text
        assert "not in the stored Trading 212 instrument list" in page

    def test_adding_and_researching_launches_a_deep_dive(self, client, session, started):
        _outside(session)
        session.commit()

        response = client.post(
            "/instrument/SCHW_US_EQ/include", data={"research": "1"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith(
            "/instrument/SCHW_US_EQ?tab=research&research="
        )
        assert [call["subject_id"] for call in started.calls] == ["SCHW_US_EQ"]
        # The prompt is the template the Research tab would have offered, not an empty one:
        # starting the same run from two places must not produce two different reports.
        assert "Research" in started.calls[0]["prompt"]
        session.expire_all()
        assert session.get(Instrument, "SCHW_US_EQ").pinned is True

    def test_a_refused_deep_dive_still_adds_the_instrument(self, client, session, monkeypatch):
        """The two halves are independent on purpose: the instrument is in the universe either
        way, and the refusal is reported rather than rolled back."""
        stub = _Start(ok=False, message="another deep-dive is already running")
        monkeypatch.setattr("awltux.research.service.start", stub)
        _outside(session)
        session.commit()

        response = client.post(
            "/instrument/SCHW_US_EQ/include", data={"research": "1"}, follow_redirects=False
        )

        assert "research=refused" in response.headers["location"]
        session.expire_all()
        assert session.get(Instrument, "SCHW_US_EQ").in_universe is True

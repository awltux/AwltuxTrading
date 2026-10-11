"""The "What the business is" panel: the deep-dive's account, and the listing beneath it.

Asked for directly: *"Use the Trading 212 API to populate an instrument's basic 'about' data
during initial population and refresh jobs. The Research job can replace or extend this data."*

What that API can and cannot supply is the whole design, so it is asserted rather than assumed:
`/equity/metadata/instruments` returns ten fields and no description of any kind, and there is no
per-instrument endpoint. So:

* the panel's basic half is **derived** from the row the population job writes, not stored beside
  it -- a second copy would go stale every time the daily sync rewrote those fields;
* the deep-dive **replaces** the description and the listing stays under it, because the model's
  prose answers "what does it do" and neither it nor Trading 212 answers "what is it and where";
* the scoped refresh's contribution is the **classification**: its filings steps are what fill in
  a sector for an instrument that had none.

The last two tests are the coupling that makes "populated during those jobs" true rather than
merely claimed -- if a job stops writing one of these fields, they fail.
"""

from __future__ import annotations

import datetime as dt

from bs4 import BeautifulSoup

from awltux.db import Instrument, ResearchReport
from awltux.ingest.universe import synchronize_instruments
from awltux.web import listing
from tests.helpers import FakeT212, make_instrument

#: The listing facts these tests turn on, as `synchronize_instruments` stores them. Merged
#: *under* the caller's overrides so a test can replace any one of them.
_T212_FIELDS = {
    "short_name": "STN",
    "exchange_name": "NYSE",
    "yahoo_symbol": "STN",
    "extended_hours": True,
    "added_on": "2023-11-02T16:28:13.000+02:00",
}


def _instrument(**overrides) -> Instrument:
    """A row shaped the way `synchronize_instruments` leaves one.

    Delegates to the shared builder rather than restating every column: the shared
    defaults only have to exist, and the four listing facts the panel reads are the
    ones pinned here.
    """
    return make_instrument(
        "STN_US_EQ",
        name=overrides.pop("name", "Stantec"),
        isin=overrides.pop("isin", "CA85472N1096"),
        **(_T212_FIELDS | overrides),
    )


class TestWhatTrading212Knows:
    def test_it_reads_the_fields_the_api_publishes(self):
        about = listing.listing_about(_instrument())

        assert about.summary == "Stantec is a stock on NYSE traded in USD."
        assert about.as_listed == "a stock on NYSE traded in USD"
        assert about.identifiers == "ISIN CA85472N1096 · Trading 212's short name for it is STN"
        assert about.note == (
            "Trading 212 has carried it since 2023-11-02 and it trades outside normal hours there."
        )

    def test_a_fund_is_named_as_one(self):
        """`type` is the only description of what the thing *is* that the API carries, so the
        words matter: an ETF is not a stock."""
        about = listing.listing_about(
            _instrument(name="Xtrackers NASDAQ 100", instrument_type="ETF")
        )

        assert about.as_listed.startswith("an exchange-traded fund")

    def test_a_type_nobody_has_mapped_is_named_rather_than_guessed_at(self):
        """Trading 212 can add a type, and "Stantec is CFD on NYSE" reads as a typo, so the raw
        type is named in the identifiers line instead. The sentence still needs a noun phrase
        after "is": dropping the clause left "Stantec is on NYSE traded in USD", which is the
        typo it set out to avoid -- it just looked like a sentence."""
        about = listing.listing_about(_instrument(instrument_type="CFD"))

        assert about.summary == "Stantec is an instrument on NYSE traded in USD."
        assert "Trading 212's type for it is CFD" in about.identifiers

    def test_a_row_with_no_type_still_reads_as_a_sentence(self):
        """The clause is unconditional, so the one row that carries neither a type nor a market
        still produces a grammatical line rather than a bare name and a full stop."""
        about = listing.listing_about(
            _instrument(instrument_type=None, exchange_name=None, currency_code=None)
        )

        assert about.summary == "Stantec is an instrument."

    def test_a_partial_row_says_only_what_it_knows(self):
        about = listing.listing_about(
            _instrument(isin=None, short_name=None, extended_hours=False, added_on=None)
        )

        assert about.summary == "Stantec is a stock on NYSE traded in USD."
        assert about.identifiers == ""
        assert about.note == ""
        assert about.classification == ""

    def test_the_short_name_is_omitted_when_it_repeats_the_ticker(self):
        """A "short name" the reader already has in front of them is noise, not information."""
        about = listing.listing_about(_instrument(short_name="STN_US_EQ"))

        assert about.identifiers == "ISIN CA85472N1096"

    def test_an_unparseable_added_on_drops_that_clause_only(self):
        """It is one fact about the listing, and it must not cost the reader the panel."""
        about = listing.listing_about(_instrument(added_on="not a date"))

        assert about.summary == "Stantec is a stock on NYSE traded in USD."
        assert "carried it since" not in about.note

    def test_the_industry_comes_from_the_filings_and_is_labelled(self):
        about = listing.listing_about(
            _instrument(
                sector="Services-Engineering Services",
                sector_group="Industrials",
                sector_source="edgar_sic",
            )
        )

        assert about.classification == (
            "Industrials — Services-Engineering Services, via edgar_sic"
        )

    def test_a_row_that_knows_nothing_yields_nothing(self):
        """So the panel can say "nothing here yet" rather than print a sentence with holes."""
        assert listing.listing_about(Instrument(t212_ticker="X_EQ", name="")) is None


class TestThePanel:
    def _panel(self, client, ticker: str = "STN_US_EQ"):
        page = BeautifulSoup(client.get(f"/instrument/{ticker}").text, "lxml")
        return page.select_one(".business-profile")

    def _text(self, client, ticker: str = "STN_US_EQ") -> str:
        """The panel's words, whitespace-collapsed. `get_text(" ")` puts a space either side of
        an inline element, so "from <a>the deep-dive</a>" arrives as "from  the deep-dive"."""
        return " ".join(self._panel(client, ticker).get_text(" ").split())

    @staticmethod
    def _deep_dive(subject_id: str = "STN_US_EQ") -> ResearchReport:
        """A finished report carrying the three business fields the panel reads."""
        return ResearchReport(
            subject_type="instrument",
            subject_id=subject_id,
            status="done",
            title="Stantec",
            prompt="p",
            prompt_sha256="0" * 64,
            bytes=1,
            verdict="watch",
            created_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
            result={
                "business": {
                    "summary": "Designs and engineers infrastructure.",
                    "moat": "Long-standing municipal relationships.",
                    "competition": "Fragmented, mostly regional.",
                }
            },
        )

    def test_a_listed_instrument_shows_what_trading_212_says(self, client, session):
        session.add(_instrument())
        session.commit()

        text = self._text(client)

        assert "from the Trading 212 listing" in text
        assert "Stantec is a stock on NYSE traded in USD." in text
        assert "ISIN CA85472N1096" in text
        # And it does not pretend to say what the company does, which that API cannot know.
        assert "publishes no description of any kind" in text
        assert "A deep-dive works that out" in text

    def test_a_deep_dive_replaces_the_description_and_keeps_the_listing(
        self, client, session
    ):
        session.add(_instrument())
        session.add(self._deep_dive())
        session.commit()

        text = self._text(client)

        assert "from the deep-dive of 2026-10-01" in text
        assert "Designs and engineers infrastructure." in text
        assert "Durable advantage." in text
        # The extension: the model's prose does not say what the listing is or where it trades.
        assert "Trading 212 lists it as a stock on NYSE traded in USD" in text

    def test_an_unmapped_type_reads_as_a_sentence_under_a_deep_dive(self, client, session):
        """The extension interpolates `as_listed` after "lists it as", so it must carry its own
        noun phrase. It did not: with a type Trading 212 has not published the panel read
        "Trading 212 lists it as on NYSE traded in USD", which is not a sentence. The deep-dive
        branch is the one place the fragment has a verb in front of it, so it is the one place
        the empty leading clause was actually visible."""
        session.add(_instrument(instrument_type="CFD"))
        session.add(self._deep_dive())
        session.commit()

        text = self._text(client)

        assert "Trading 212 lists it as an instrument on NYSE traded in USD" in text
        assert "lists it as on " not in text

    def test_a_row_that_knows_nothing_still_points_at_the_deep_dive(self, client, session):
        """The old sentence, kept for the one case where there is genuinely nothing to say."""
        session.add(Instrument(t212_ticker="TEST_US_EQ", name="", in_universe=True))
        session.commit()

        text = self._text(client, "TEST_US_EQ")

        assert "no deep-dive yet" in text
        assert "nothing here describes what it does" in text


class TestTheJobsPopulateIt:
    def test_the_population_job_writes_every_field_the_panel_reads(self, session):
        """The link that makes "populated during initial population" true. If the sync stops
        writing one of these, the panel empties out silently -- so this fails instead."""
        synchronize_instruments(session, provider=FakeT212())

        about = listing.listing_about(session.get(Instrument, "AAPL_US_EQ"))

        assert about.summary == "Apple is a stock on NASDAQ traded in USD."
        assert about.identifiers == "ISIN US0378331005 · Trading 212's short name for it is AAPL"
        assert "carried it since 2020-01-01" in about.note

    def test_the_refresh_is_what_adds_the_industry(self, session):
        """A scoped refresh cannot read Trading 212 (there is no per-instrument endpoint), but
        its filings and statements steps are what classify the company -- so the panel gains
        that line as the pipeline runs."""
        synchronize_instruments(session, provider=FakeT212())
        before = listing.listing_about(session.get(Instrument, "AAPL_US_EQ"))
        assert before.classification == "", "nothing has classified it yet"

        apple = session.get(Instrument, "AAPL_US_EQ")
        apple.sector = "Electronic Computers"
        apple.sector_group = "Technology"
        apple.sector_source = "edgar_sic"
        session.flush()

        after = listing.listing_about(apple)

        assert after.classification == "Technology — Electronic Computers, via edgar_sic"

"""The instrument link's hover hint on the recommendations table.

Asked for: *"in recommendations, provide a hover hint on the instrument link about the Company
e.g. Name and overview."*

The app holds no description of a company from Trading 212 -- `web/listing.py` says so on
every instrument that has no deep-dive -- so the hint is assembled from what is held, in
precedence order: the deep-dive's own account of the business, then the provider's stored
summary, then the listing facts alone. **Every row gets something**, because a tooltip that
renders empty on most rows reads as a broken page rather than as a thin one.
"""

from __future__ import annotations

import datetime as dt

from bs4 import BeautifulSoup

from awltux.db import ResearchReport, utcnow
from awltux.web import queries
from tests.helpers import make_instrument

TICKER = "HINT_US_EQ"


def _instrument(session, ticker: str = TICKER, **overrides) -> None:
    session.add(
        make_instrument(
            ticker,
            name=overrides.pop("name", "Hint Co"),
            exchange_name=overrides.pop("exchange_name", "NASDAQ"),
            sector=overrides.pop("sector", "Electronic Computers"),
            **overrides,
        )
    )
    session.flush()


def _report(session, summary: str | None, *, ticker: str = TICKER, when=None) -> None:
    """A finished deep-dive, optionally one that said nothing about the business."""
    session.add(
        ResearchReport(
            subject_type="instrument",
            subject_id=ticker,
            status="done",
            title=f"{ticker} deep-dive",
            prompt="p",
            prompt_sha256="0" * 64,
            bytes=1,
            verdict="watch",
            created_at=when or utcnow(),
            finished_at=when or utcnow(),
            result={"business": {"summary": summary}} if summary is not None else {"business": {}},
        )
    )
    session.flush()


def _row(session, ticker: str = TICKER) -> queries.RecommendationRow:
    rows, _ = queries.recommendations(session)
    return next(row for row in rows if row.ticker == ticker)


class TestWhatTheHintSays:
    def test_it_names_the_company_and_what_the_instrument_is(self, session):
        """The minimum every row gets: no description is needed for a hint to be useful."""
        _instrument(session)

        about = _row(session).about

        assert about.startswith("Hint Co")
        assert "a stock on NASDAQ traded in USD" in about
        assert "Industry: Electronic Computers" in about

    def test_a_provider_summary_is_used_when_there_is_no_deep_dive(self, session):
        _instrument(session, business_summary="Hint Co sells hints to analysts.")

        assert "Hint Co sells hints to analysts." in _row(session).about

    def test_the_deep_dives_own_account_wins_over_the_providers(self, session):
        """The deep-dive read the annual reports; a provider's blurb is a marketing
        paragraph. When both exist the considered one is shown."""
        _instrument(session, business_summary="A provider blurb.")
        _report(session, "Hint Co makes hinting equipment for analysts.")

        about = _row(session).about

        assert "Hint Co makes hinting equipment for analysts." in about
        assert "A provider blurb." not in about

    def test_a_report_that_said_nothing_falls_back_rather_than_erasing(self, session):
        """A description of what a company does does not go stale the way a verdict does, so
        a later report that passed over the business must not take the account away."""
        _instrument(session, business_summary="A provider blurb.")
        _report(session, "", when=utcnow() + dt.timedelta(minutes=1))

        assert "A provider blurb." in _row(session).about

    def test_the_newest_report_that_described_the_business_wins(self, session):
        _instrument(session)
        _report(session, "The older account.", when=utcnow() - dt.timedelta(days=2))
        _report(session, "The newer account.", when=utcnow() - dt.timedelta(days=1))

        assert "The newer account." in _row(session).about

    def test_a_row_we_hold_nothing_about_still_names_itself(self, session):
        """A tooltip that renders empty reads as a broken page rather than a thin one.

        Everything the listing clause could be built from is cleared, so this is the row the
        table has genuinely nothing to say about beyond its ticker.
        """
        session.add(
            make_instrument(
                TICKER,
                name="",
                short_name=None,
                isin=None,
                exchange_name=None,
                currency_code=None,
                instrument_type=None,
                sector=None,
            )
        )
        session.flush()

        assert _row(session).about == TICKER

    def test_the_hint_is_one_trimmed_line(self, session):
        _instrument(session, business_summary=" ".join(["paragraph"] * 300))

        about = _row(session).about

        assert len(about) <= queries.ABOUT_HINT_CHARS + 1
        assert about.endswith("…")
        assert "\n" not in about


class TestTheHintOnThePage:
    def test_the_instrument_link_carries_it(self, client, session):
        _instrument(session, business_summary="Hint Co sells hints to analysts.")
        session.commit()

        body = client.get("/partials/recommendations").text
        link = BeautifulSoup(body, "lxml").select_one(f"a[href='/instrument/{TICKER}']")

        assert link is not None
        assert "Hint Co sells hints to analysts." in link["title"]
        assert "a stock on NASDAQ traded in USD" in link["title"]

    def test_the_link_still_works_without_a_description(self, client, session):
        _instrument(session)
        session.commit()

        body = client.get("/partials/recommendations").text
        link = BeautifulSoup(body, "lxml").select_one(f"a[href='/instrument/{TICKER}']")

        assert link["title"], "an empty tooltip is worse than none"
        assert "Hint Co" in link["title"]

"""Where an accounts page's SOURCE leads.

Asked for 2026-10-23: *"When viewing specific accounts, can the SOURCE item be a link to the
original website the data was gathered from? I don't know if this info is currently held."*

It is held for some sources and derivable for others, and the difference is the point of these
tests: a link must name a place the figures really came from, and a source with no recorded
origin must say so rather than have one invented for it.

Measured on the live database when this was built (824 periods): every ``xbrl_companyfacts`` row
records the SEC accession, and 192 of 234 resolve to a ``filing`` row with the document's own
URL; ``yahoo_*`` rows (559) carry no identifier but come from Yahoo Finance for a symbol the
instrument already holds; ``llm_extraction`` (22) had **no** ``filing_id`` because nothing wrote
the column until this change; ``deep_research`` (9) is this application's own reading.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.db import Filing, FundamentalPeriod, Instrument, utcnow
from awltux.web import sources
from tests.helpers import make_instrument

TICKER = "SRC_US_EQ"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000001/aapl-2025.htm"


@pytest.fixture
def issuer(session):
    """An instrument with every identifier a source link can be derived from, plus one filing.

    The filing is built per test rather than at module level: a mapped instance is attached to
    the session that added it, so a second test inserting the same object fails.
    """
    session.add(
        make_instrument(
            TICKER,
            sec_cik="0000320193",
            yahoo_symbol="AAPL",
            ch_company_number="01234567",
        )
    )
    # Two commits, because the filing's only link to the instrument is the foreign key and
    # SQLAlchemy has no relationship to order the two inserts by: in one flush the filing can
    # be written first, and SQLite refuses it.
    session.commit()
    session.add(
        Filing(
            instrument_t212_ticker=TICKER,
            source="edgar",
            filing_type="10-K",
            title="Annual report",
            filed_at=utcnow(),
            period_end=dt.date(2025, 9, 27),
            url=FILING_URL,
            doc_hash="x",
            raw_path="filings/x.htm",
            status="parsed",
        )
    )
    session.commit()
    return session.get(Instrument, TICKER)


def _filing(session):
    return session.execute(
        Filing.__table__.select().where(Filing.__table__.c.doc_hash == "x")
    ).one()


def _period(
    session,
    *,
    source: str,
    filing_id: int | None = None,
    accession: str | None = None,
    period_end: dt.date = dt.date(2025, 9, 27),
) -> FundamentalPeriod:
    row = FundamentalPeriod(
        instrument_t212_ticker=TICKER,
        period_end=period_end,
        period_type="annual",
        source=source,
        currency="USD",
        metrics={"revenue": 1_000.0},
        metric_sources=(
            {"revenue": {"accession": accession, "source": source}} if accession else None
        ),
        confidence=0.7,
        filing_id=filing_id,
    )
    session.add(row)
    session.commit()
    return row


def origin(session, issuer, period) -> sources.Origin:
    return sources.origins(session, issuer, [period])[period.id]


class TestTheFilingBehindTheFigures:
    def test_a_recorded_filing_is_the_link(self, session, issuer):
        """`filing_id` is a direct reference, so it is believed before anything derived."""
        period = _period(session, source="llm_extraction", filing_id=_filing(session).id)

        resolved = origin(session, issuer, period)

        assert resolved.url == FILING_URL
        assert resolved.site == "www.sec.gov"

    def test_an_xbrl_period_is_tied_to_its_document_by_the_accession(self, session, issuer):
        """An XBRL period never holds a ``filing_id`` -- it records the accession it was filed
        under, which is how the accounts page already finds a filing to open at a line."""
        period = _period(
            session, source="xbrl_companyfacts", accession="0000320193-25-000001"
        )

        resolved = origin(session, issuer, period)

        assert resolved.url == FILING_URL

    def test_without_the_document_the_xbrl_link_is_the_endpoint(self, session, issuer):
        """42 of the 234 live XBRL periods have no held document. Their figures still came from
        the SEC's companyfacts endpoint, which is derivable from the CIK."""
        period = _period(session, source="xbrl_companyfacts")

        resolved = origin(session, issuer, period)

        assert resolved.url == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
        assert resolved.site == "data.sec.gov"
        assert "endpoint" in resolved.note


class TestTheScrapedSources:
    def test_statements_link_yahoos_own_page_for_the_symbol(self, session, issuer):
        period = _period(session, source="yahoo_statements")

        resolved = origin(session, issuer, period)

        assert resolved.url == "https://finance.yahoo.com/quote/AAPL/financials"

    def test_the_profile_source_links_a_different_yahoo_page(self, session, issuer):
        """Two sources, two pages: "financials" and "key statistics" are not the same claim."""
        period = _period(session, source="yahoo_info")

        resolved = origin(session, issuer, period)

        assert resolved.url == "https://finance.yahoo.com/quote/AAPL/key-statistics"

    def test_without_a_symbol_it_says_so_and_links_nothing(self, session):
        session.add(make_instrument(TICKER, yahoo_symbol=None))
        session.commit()
        issuer = session.get(Instrument, TICKER)
        period = _period(session, source="yahoo_statements")

        resolved = origin(session, issuer, period)

        assert resolved.url is None
        assert "no Yahoo symbol" in resolved.note


class TestTheSourcesWithNoOutsideSite:
    def test_a_deep_dive_links_this_applications_report_list(self, session, issuer):
        """The reading is ours, so the link is ours -- and it is marked internal, because a
        page of this application opening in a new tab is not what an external link means."""
        period = _period(session, source="deep_research")

        resolved = origin(session, issuer, period)

        assert resolved.url == f"/instrument/{TICKER}?tab=research"
        assert resolved.external is False

    def test_an_extraction_written_before_the_link_was_recorded_admits_it(self, session, issuer):
        period = _period(session, source="llm_extraction")

        resolved = origin(session, issuer, period)

        assert resolved.url is None
        assert "not recorded" in resolved.note

    def test_an_unknown_source_has_no_link(self, session, issuer):
        period = _period(session, source="something_else")

        resolved = origin(session, issuer, period)

        assert resolved.url is None
        assert "no origin is recorded" in resolved.note


class TestThePage:
    def _page(self, client, session, issuer) -> str:
        period = _period(
            session, source="xbrl_companyfacts", accession="0000320193-25-000001"
        )
        return client.get(f"/accounts/{period.id}").text

    def test_the_source_is_a_link_to_the_filing(self, client, session, issuer):
        body = self._page(client, session, issuer)

        assert f'href="{FILING_URL}"' in body
        assert 'target="_blank"' in body
        assert "www.sec.gov" in body

    def test_a_source_with_no_origin_is_printed_without_a_link(self, client, session, issuer):
        period = _period(session, source="llm_extraction")
        body = client.get(f"/accounts/{period.id}").text

        assert "llm_extraction" in body
        assert "the specific document is not recorded" in body

    def test_the_sources_it_displaced_are_linked_too(self, client, session, issuer):
        """The superseded table is where a reader checks another source's own figures, so
        "which site said this" has to be answerable there as well."""
        chosen = _period(session, source="xbrl_companyfacts", accession="0000320193-25-000001")
        _period(session, source="yahoo_statements", period_end=dt.date(2025, 9, 27))

        body = client.get(f"/accounts/{chosen.id}").text

        assert "https://finance.yahoo.com/quote/AAPL/financials" in body

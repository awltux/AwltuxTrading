"""A stored filing must know the period it reports on.

``Filing.period_end`` is the citation link between a document and the figures taken
from it: it is what lets a stored ``FundamentalPeriod`` be traced back to the filing
that reports it -- and it is the only way to find that filing's own calculation
linkbase, which is what would settle the accounting-equation failures recorded in
``TODO.md``.

Measured before this was written: **0 of 4,958** stored filings had a period, because
``reportDate`` -- the filer's own statement of the period, as distinct from the date
it reached EDGAR -- was never read out of EDGAR's submissions payload. The tests here
pin the three cases that matter: a period is stored, an existing row gains the period
it was missing, and a filing that states no period gets ``None`` rather than a guess.
"""

from __future__ import annotations

import datetime as dt

from awltux.db import Filing
from awltux.ingest.edgar import sync_filings
from tests.helpers import make_instrument


class _FakeProvider:
    """The two provider calls ``sync_filings`` makes, answered from a list."""

    def __init__(self, entries: list[dict[str, object]]) -> None:
        self.entries = entries

    def get_recent_filings(self, cik: str | int, *, limit: int = 40) -> list[dict[str, object]]:
        return self.entries

    def get_sic(self, cik: str | int) -> tuple[str | None, str | None]:
        return None, None


def _entry(url: str, *, report_date: str | None, filed: str = "2026-02-01") -> dict[str, object]:
    return {
        "form": "10-K",
        "filing_date": filed,
        "accession_number": "000032019326000111",
        "primary_document": "aapl-20250927.htm",
        "description": "Annual report",
        "report_date": report_date,
        "url": url,
    }


def _seed(session) -> None:
    session.add(
        make_instrument("AAPL_US_EQ", yahoo_symbol="AAPL", sec_cik="0000320193")
    )
    session.commit()


class TestTheReportedPeriod:
    def test_a_new_filing_records_the_period_it_reports_on(self, session, settings):
        _seed(session)
        report = sync_filings(
            session,
            settings=settings,
            provider=_FakeProvider([_entry("https://sec.test/a.htm", report_date="2025-09-27")]),
        )

        stored = session.query(Filing).one()

        assert stored.period_end == dt.date(2025, 9, 27)
        assert stored.filed_at is not None and stored.filed_at.date() == dt.date(2026, 2, 1)
        assert report.filings_written == 1

    def test_a_stored_filing_gains_the_period_it_was_missing(self, session, settings):
        """The backfill, which is why this is not merely a new-column change.

        Every filing stored before this fix has a null period, and EDGAR's
        submissions window holds only the last thousand filings -- so a period not
        filled on this pass may be unreachable later. The row is otherwise left
        alone: nothing was filed, so ``filings_written`` stays zero.
        """
        _seed(session)
        url = "https://sec.test/old.htm"
        session.add(
            Filing(
                instrument_t212_ticker="AAPL_US_EQ",
                source="edgar",
                filing_type="10-K",
                url=url,
                status="pending",
            )
        )
        session.commit()

        report = sync_filings(
            session,
            settings=settings,
            provider=_FakeProvider([_entry(url, report_date="2025-09-27")]),
        )

        stored = session.query(Filing).one()

        assert stored.period_end == dt.date(2025, 9, 27)
        assert report.periods_backfilled == 1
        assert report.filings_written == 0
        assert session.query(Filing).count() == 1

    def test_a_filing_that_states_no_period_gets_none(self, session, settings):
        """An 8-K reports an event, not a period, and EDGAR's field is empty.

        The temptation is to fall back to ``filingDate``, which is always present.
        It would be wrong by months for an annual report and would put a fabricated
        period into the citation link -- so ``None`` is stored and the row is
        expected to say so.
        """
        _seed(session)
        sync_filings(
            session,
            settings=settings,
            provider=_FakeProvider([_entry("https://sec.test/8k.htm", report_date=None)]),
        )

        stored = session.query(Filing).one()

        assert stored.period_end is None
        assert stored.filed_at is not None

    def test_an_existing_period_is_not_overwritten(self, session, settings):
        """Re-issued documents exist; a period already known is left as it is."""
        _seed(session)
        url = "https://sec.test/old.htm"
        session.add(
            Filing(
                instrument_t212_ticker="AAPL_US_EQ",
                source="edgar",
                filing_type="10-K",
                url=url,
                period_end=dt.date(2024, 9, 28),
                status="pending",
            )
        )
        session.commit()

        report = sync_filings(
            session,
            settings=settings,
            provider=_FakeProvider([_entry(url, report_date="2025-09-27")]),
        )

        assert session.query(Filing).one().period_end == dt.date(2024, 9, 28)
        assert report.periods_backfilled == 0

    def test_the_same_url_twice_in_one_payload_is_stored_once(self, session, settings):
        """EDGAR's parallel arrays can repeat a row across pages; the loop must not."""
        _seed(session)
        entry = _entry("https://sec.test/a.htm", report_date="2025-09-27")

        report = sync_filings(
            session, settings=settings, provider=_FakeProvider([entry, dict(entry)])
        )

        assert session.query(Filing).count() == 1
        assert report.filings_written == 1

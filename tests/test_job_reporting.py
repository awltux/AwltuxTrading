"""A job that did nothing must say *why*.

`news_rss` reported `written: 0` and looked identical whether it had polled the
whole universe and found no news, or had nothing to poll because the universe was
empty. The second case is a setup problem the operator can fix in a minute; the
first is a normal quiet day. Reporting them the same way wastes that minute.

These tests cover the explanation, and the two distinct causes behind it.
"""

from __future__ import annotations

import pytest

from awltux.db import Instrument
from awltux.ingest.jobs import empty_universe_note, universe_is_empty
from awltux.scheduler.jobs import JobResult
from tests.helpers import make_instrument


class TestUniverseDetection:
    def test_an_empty_database_is_reported_as_empty(self, session):
        assert universe_is_empty(session) is True

    def test_instruments_outside_the_universe_still_count_as_empty(self, session):
        """The distinction that caused the confusing zero."""
        session.add(make_instrument("TEST_US_EQ", in_universe=False))
        session.flush()
        assert universe_is_empty(session) is True

    def test_an_excluded_instrument_does_not_populate_the_universe(self, session):
        session.add(make_instrument("TEST_US_EQ", in_universe=True, excluded=True))
        session.flush()
        assert universe_is_empty(session) is True

    def test_a_populated_universe_is_not_empty(self, session):
        session.add(make_instrument("TEST_US_EQ", in_universe=True))
        session.flush()
        assert universe_is_empty(session) is False


class TestExplanation:
    def test_nothing_stored_at_all_points_at_the_instruments_job(self, session):
        note = empty_universe_note(session)
        assert note is not None
        assert "t212_instruments" in note
        assert "Trading 212 API key" in note

    def test_stored_but_unselected_points_at_the_universe_job(self, session):
        """A different fix, so a different message."""
        session.add(make_instrument("TEST_US_EQ", in_universe=False))
        session.flush()
        note = empty_universe_note(session)
        assert note is not None
        assert "universe_refresh" in note
        assert "1 instruments are stored" in note

    def test_a_populated_universe_needs_no_explanation(self, session):
        session.add(make_instrument("TEST_US_EQ", in_universe=True))
        session.flush()
        assert empty_universe_note(session) is None


class TestJobResultsCarryTheNote:
    def test_a_job_result_serialises_its_note_into_the_detail(self):
        """The detail is what reaches the run history, so the note must be there."""
        result = JobResult(note="nothing to do: empty universe", detail={"fetched": 0})
        payload = result.as_dict()
        assert payload["note"] == "nothing to do: empty universe"
        assert payload["fetched"] == 0

    def test_a_job_with_no_note_does_not_claim_one(self):
        assert "note" not in JobResult(detail={"fetched": 5}).as_dict()

    def test_news_rss_explains_an_empty_universe_rather_than_reporting_zero(
        self, session, settings, monkeypatch
    ):
        """End to end on the job the operator actually ran."""
        from awltux.ingest import jobs as ingest_jobs

        # No instruments at all.
        assert session.query(Instrument).count() == 0

        result = ingest_jobs.ingest_news_rss()

        assert result.items_written == 0
        assert result.note is not None
        assert "t212_instruments" in result.note

    def test_filings_explain_a_book_with_no_sec_ciks(
        self, session, settings, monkeypatch
    ):
        """A London-only book legitimately has no EDGAR filings."""
        from awltux.ingest import edgar as edgar_module
        from awltux.ingest import jobs as ingest_jobs

        session.add(make_instrument("VODl_EQ", yahoo_symbol="VOD.L", exchange_name="LSE"))
        session.flush()

        # Stub the network so this stays offline.
        monkeypatch.setattr(
            edgar_module,
            "resolve_ciks",
            lambda session, **kwargs: edgar_module.EdgarSyncReport(),
        )

        result = ingest_jobs.sync_filings()
        assert result.note is not None
        assert "Companies House" in result.note

    @pytest.mark.parametrize(
        "job_name",
        ["ingest_edgar_events", "sync_fundamentals_job"],
    )
    def test_other_universe_driven_jobs_explain_themselves(
        self, session, settings, job_name: str
    ):
        from awltux.ingest import jobs as ingest_jobs

        result = getattr(ingest_jobs, job_name)()
        assert result.note is not None, f"{job_name} reported a bare zero"

"""The per-instrument blocker record: upserted while broken, stamped when fixed.

This exists because a job's inability to fetch one company's accounts was invisible.
It *was* recorded -- as free text in ``IngestRun.detail`` -- and measured 2026-10-07 that
is not a record: scanning the last 400 runs found **5 instruments**, because each job
rations itself to a couple of instruments per run and ``retention`` prunes run detail.

The three properties below are the ones a plausible implementation gets wrong, and each
would leave the dashboard lying in a different direction:

* **Upsert, not append.** "Is this still broken" is the question; a row per failure
  would grow without bound and answer it worse.
* **Occurrences reset when a fixed problem returns.** A blocker that was resolved and
  came back is current, and counting it as 200 occurrences of a 200-day-old problem
  hides that it broke again this morning.
* **Cleared on success, kept as history.** Never cleared makes the filter a list of
  things that used to be broken; deleted makes a provider that fails every other night
  leave no trace at all.
"""

from __future__ import annotations

from awltux.db import InstrumentBlocker
from awltux.ingest.blockers import clear_blocker, record_blocker
from tests.helpers import make_instrument


def _seed(session, ticker: str = "TEST_US_EQ", **overrides) -> None:
    overrides.setdefault("sec_cik", "0000000001")
    session.add(make_instrument(ticker, **overrides))
    session.flush()


def _rows(session) -> list[InstrumentBlocker]:
    return session.query(InstrumentBlocker).order_by(InstrumentBlocker.id).all()


class TestRecording:
    def test_one_row_per_job_and_stage(self, session):
        _seed(session)
        record_blocker(
            session, "TEST_US_EQ", job="xbrl_statements", stage="statements", reason="HTTP 403"
        )
        session.commit()

        rows = _rows(session)
        assert len(rows) == 1
        assert rows[0].occurrences == 1
        assert rows[0].resolved_at is None

    def test_a_repeat_bumps_the_count_rather_than_adding_a_row(self, session):
        """The question is "is this still broken", not "how many times was it logged"."""
        _seed(session)
        for _ in range(3):
            record_blocker(
                session, "TEST_US_EQ", job="xbrl_statements", stage="statements",
                reason="HTTP 403",
            )
        session.commit()

        rows = _rows(session)
        assert len(rows) == 1
        assert rows[0].occurrences == 3

    def test_the_latest_reason_replaces_the_earlier_one(self, session):
        """A provider that changes its error is still one problem, and the current
        wording is the one worth reading."""
        _seed(session)
        record_blocker(
            session, "TEST_US_EQ", job="fundamentals", stage="statements", reason="HTTP 403"
        )
        record_blocker(
            session, "TEST_US_EQ", job="fundamentals", stage="statements", reason="HTTP 429"
        )
        session.commit()

        rows = _rows(session)
        assert len(rows) == 1
        assert rows[0].reason == "HTTP 429"
        assert rows[0].occurrences == 2

    def test_two_stages_of_one_job_are_two_blockers(self, session):
        """Fetching the payload and parsing it are different problems with different
        fixes, so they cannot share a row."""
        _seed(session)
        record_blocker(
            session, "TEST_US_EQ", job="xbrl_statements", stage="statements", reason="HTTP 403"
        )
        record_blocker(
            session, "TEST_US_EQ", job="xbrl_statements", stage="xbrl", reason="KeyError: Assets"
        )
        session.commit()

        assert {row.stage for row in _rows(session)} == {"statements", "xbrl"}

    def test_a_long_reason_is_clipped_rather_than_refused(self, session):
        """A blocker with a clipped explanation is still a blocker: losing it because a
        traceback ran long would be the worst of both."""
        _seed(session)
        record_blocker(
            session, "TEST_US_EQ", job="xbrl", stage="statements", reason="x" * 2000
        )
        session.commit()

        row = _rows(session)[0]
        assert len(row.reason) <= 512
        assert row.reason

    def test_whitespace_in_a_reason_is_collapsed(self, session):
        """Providers return multi-line HTML; a 512-character budget should not be spent
        on indentation."""
        _seed(session)
        record_blocker(
            session, "TEST_US_EQ", job="xbrl", stage="statements", reason="  HTTP 403\n\n  denied "
        )
        session.commit()

        assert _rows(session)[0].reason == "HTTP 403 denied"


class TestClearing:
    def test_a_success_stamps_the_blocker_rather_than_deleting_it(self, session):
        """`first_seen_at` is what says "broken for six weeks, then fixed" -- the fact
        worth having, and the one a delete throws away."""
        _seed(session)
        record_blocker(
            session, "TEST_US_EQ", job="xbrl_statements", stage="statements", reason="HTTP 403"
        )
        session.commit()

        clear_blocker(session, "TEST_US_EQ", job="xbrl_statements", stage="statements")
        session.commit()

        row = _rows(session)[0]
        assert row.resolved_at is not None
        assert row.occurrences == 1

    def test_clearing_something_that_was_never_blocked_is_quiet(self, session):
        """Almost every success is for an instrument that was never blocked, so this
        cannot be a function every call site has to guard."""
        _seed(session)

        clear_blocker(session, "TEST_US_EQ", job="xbrl_statements", stage="statements")

        assert _rows(session) == []

    def test_only_the_named_job_and_stage_are_cleared(self, session):
        """Clearing everything on an instrument would let one job's success hide
        another job's failure."""
        _seed(session)
        record_blocker(session, "TEST_US_EQ", job="a", stage="statements", reason="one")
        record_blocker(session, "TEST_US_EQ", job="b", stage="statements", reason="two")
        session.commit()

        clear_blocker(session, "TEST_US_EQ", job="a", stage="statements")
        session.commit()

        open_now = {row.job for row in _rows(session) if row.resolved_at is None}
        assert open_now == {"b"}


class TestReopening:
    def test_a_fixed_problem_that_returns_starts_counting_again(self, session):
        """Otherwise a blocker with 200 occurrences from last month shows a problem
        that broke again this morning as 201 occurrences of an old one."""
        _seed(session)
        record_blocker(session, "TEST_US_EQ", job="xbrl", stage="statements", reason="HTTP 403")
        session.commit()
        early = _rows(session)[0].first_seen_at
        clear_blocker(session, "TEST_US_EQ", job="xbrl", stage="statements")
        session.commit()

        record_blocker(session, "TEST_US_EQ", job="xbrl", stage="statements", reason="HTTP 500")
        session.commit()

        row = _rows(session)[0]
        assert row.resolved_at is None
        assert row.occurrences == 1
        assert row.reason == "HTTP 500"
        assert row.first_seen_at >= early


class TestWhatTheAttentionRuleSees:
    def test_an_open_blocker_is_a_reason_and_a_resolved_one_is_not(self, session, settings):
        from awltux.analysis import attention

        _seed(session)
        record_blocker(
            session, "TEST_US_EQ", job="xbrl_statements", stage="statements", reason="HTTP 403"
        )
        session.commit()

        assert "blocked" in attention.assess(session, level=1, settings=settings)[
            "TEST_US_EQ"
        ].codes

        clear_blocker(session, "TEST_US_EQ", job="xbrl_statements", stage="statements")
        session.commit()

        assert "blocked" not in attention.assess(session, level=1, settings=settings)[
            "TEST_US_EQ"
        ].codes

    def test_a_blocked_instrument_not_in_the_universe_is_not_assessed(self, session, settings):
        """The dashboard only ever shows the universe, so nothing else needs assessing."""
        from awltux.analysis import attention

        session.add(make_instrument("OUT_US_EQ", sec_cik="0000000002", in_universe=False))
        session.flush()
        record_blocker(session, "OUT_US_EQ", job="xbrl", stage="statements", reason="HTTP 403")
        session.commit()

        assert "OUT_US_EQ" not in attention.assess(session, level=1, settings=settings)


class TestTheJobsThatRecordThem:
    """The wiring, per job, through its own entry point rather than the record.

    Six jobs were named as recording nothing, and five of them can fail one instrument
    and succeed the rest. Measured 2026-10-07: scanning the last 400 `ingest_run.detail`
    payloads for per-instrument failures found **5 instruments**, because the lists are
    free text, each job words its own differently, and `retention` prunes the detail
    away. These tests are what stops a job being unwired again by a refactor.
    """

    def _blockers(self, session) -> dict[tuple[str, str], InstrumentBlocker]:
        return {
            (row.job, row.stage): row
            for row in session.query(InstrumentBlocker).order_by(InstrumentBlocker.id)
        }

    def test_filings_edgar(self, session, settings):
        from awltux.ingest.edgar import sync_filings
        from awltux.providers.http import ProviderError

        _seed(session, "TEST_US_EQ", sec_cik="0000000001")
        session.commit()

        class Refusing:
            def get_recent_filings(self, cik, *, limit: int = 40):
                raise ProviderError("edgar", "HTTP 503", status=503)

            def get_sic(self, cik):
                return None, None

        sync_filings(session, settings=settings, provider=Refusing())

        blocker = self._blockers(session)[("filings_edgar", "filings")]
        assert blocker.resolved_at is None
        assert "HTTP 503" in blocker.reason

        class Answering(Refusing):
            def get_recent_filings(self, cik, *, limit: int = 40):
                return []

        sync_filings(session, settings=settings, provider=Answering())

        assert self._blockers(session)[("filings_edgar", "filings")].resolved_at is not None

    def test_shareholder_reports_records_both_of_its_stages(self, session, settings):
        """The walk and the download are separate steps, so they are separate blockers
        -- a company whose annual forms EDGAR will not list has not had a download
        refused, and the reader is owed the distinction."""
        from awltux.db import Filing
        from awltux.ingest import documents
        from awltux.providers.http import ProviderError

        _seed(session, "TEST_US_EQ", sec_cik="0000000001")
        session.add(
            Filing(
                instrument_t212_ticker="TEST_US_EQ",
                source="edgar",
                filing_type="10-K",
                url="https://sec.test/report.htm",
                status="pending",
            )
        )
        session.commit()

        class Refusing:
            def get_annual_filings(self, cik, *, since, limit: int = 6):
                raise ProviderError("edgar", "HTTP 503", status=503)

            def fetch_document(self, url):
                raise ProviderError("edgar", "connection reset", status=None)

        documents.deepen_annual_history(session, settings=settings, provider=Refusing())
        documents.fetch_annual_reports(session, settings=settings, provider=Refusing())

        blockers = self._blockers(session)
        assert set(blockers) == {
            ("shareholder_reports", "discovery"),
            ("shareholder_reports", "document"),
        }
        assert all(row.resolved_at is None for row in blockers.values())

    def test_shareholder_reports_clears_the_download_when_any_document_arrives(
        self, session, settings
    ):
        """One company has up to `years` reports in the queue, so a blocker recorded and
        cleared inside the same run would depend on which of them was processed last --
        and the honest question is whether *a* document arrived, not whether every one
        did."""
        from awltux.db import Filing
        from awltux.ingest import documents
        from awltux.providers.edgar import Document

        _seed(session, "TEST_US_EQ", sec_cik="0000000001")
        for number in ("1", "2"):
            session.add(
                Filing(
                    instrument_t212_ticker="TEST_US_EQ",
                    source="edgar",
                    filing_type="10-K",
                    url=f"https://sec.test/report{number}.htm",
                    status="pending",
                )
            )
        record_blocker(
            session,
            "TEST_US_EQ",
            job="shareholder_reports",
            stage="document",
            reason="connection reset",
        )
        session.commit()

        class HalfWorking:
            """The first document refuses, the second arrives."""

            def __init__(self) -> None:
                self.calls = 0

            def fetch_document(self, url):
                self.calls += 1
                if self.calls == 1:
                    return Document(url, 403, "text/html", b"")
                return Document(url, 200, "text/html", b"<html><body>10-K</body></html>")

        report = documents.fetch_annual_reports(
            session, settings=settings, provider=HalfWorking()
        )

        assert report.fetched == 1 and report.failed == 1
        assert self._blockers(session)[("shareholder_reports", "document")].resolved_at is not None

    def test_uk_companies(self, session, settings):
        from awltux.ingest.fundamentals import resolve_uk_companies

        _seed(
            session,
            "TEST_US_EQ",
            exchange_name="LSE",
            yahoo_symbol="TEST.L",
            ch_company_number=None,
        )
        session.commit()

        class NoMatch:
            configured = True

            def search_companies(self, name, **kwargs):
                return [{"title": "Something Else", "company_number": "00000001"}]

        resolve_uk_companies(session, settings=settings, provider=NoMatch())

        blocker = self._blockers(session)[("uk_companies", "company_number")]
        assert blocker.resolved_at is None
        assert "no Companies House record matched" in blocker.reason

        class Match:
            configured = True

            def search_companies(self, name, **kwargs):
                return [
                    {
                        "title": "Apple Inc",
                        "company_number": "00000002",
                        "company_type": "plc",
                        "company_status": "active",
                    }
                ]

        resolve_uk_companies(session, settings=settings, provider=Match())

        assert (
            self._blockers(session)[("uk_companies", "company_number")].resolved_at
            is not None
        )

    def test_prices(self, session):
        """Per instrument even though the provider call is per batch: a batch that
        fails at the HTTP level is one fact about the provider, and recording it against
        forty instruments would report a rate limit as forty broken companies."""
        from awltux.ingest.prices import PriceIngestReport, persist_batch

        _seed(session, "TEST_US_EQ", yahoo_symbol="TEST")
        session.commit()

        persist_batch(session, ["TEST"], {}, report=PriceIngestReport())

        blocker = self._blockers(session)[("price_eod", "prices")]
        assert blocker.resolved_at is None
        assert "no bars for TEST" in blocker.reason

    def test_symbol_resolution(self, session, monkeypatch):
        from awltux.ingest import jobs
        from awltux.ingest.identity import SymbolCandidate
        from awltux.providers.http import ProviderError

        _seed(session, "TEST_US_EQ", isin="US0378331005")
        session.commit()

        def refuse(provider, query, instrument, *, by_isin):
            raise ProviderError("yahoo", "HTTP 429", status=429)

        monkeypatch.setattr(jobs, "_lookup_symbol", refuse)
        jobs.resolve_symbols()

        session.expire_all()
        blocker = self._blockers(session)[("symbol_resolution", "symbol")]
        assert blocker.resolved_at is None
        assert "HTTP 429" in blocker.reason

        def resolve(provider, query, instrument, *, by_isin):
            return SymbolCandidate(symbol="AAPL", name="Apple Inc", confidence=0.9, method="isin")

        monkeypatch.setattr(jobs, "_lookup_symbol", resolve)
        jobs.resolve_symbols()

        session.expire_all()
        assert self._blockers(session)[("symbol_resolution", "symbol")].resolved_at is not None


def test_the_model_carries_a_first_and_last_seen_stamp():
    """A blocker with no dates cannot say how long it has been broken, which is the
    second question a reader asks after "what is wrong"."""
    from awltux.db import InstrumentBlocker as Model

    columns = set(Model.__table__.columns.keys())
    assert {"first_seen_at", "last_seen_at", "occurrences", "resolved_at"} <= columns
    # Part of the key, not a free-text field: one job failing at two steps is two
    # different problems and must not overwrite itself.
    unique = {tuple(sorted(c.name for c in constraint.columns)) for constraint in
              Model.__table__.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
    assert ("instrument_t212_ticker", "job", "stage") in unique

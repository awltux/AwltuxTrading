"""Reading the filings we hold: what becomes text, and what is retired.

Measured before this existed: 4,958 filing rows, 601 documents held and **zero** parsed,
so `decision/service.py` always read ``filing.parsed`` as ``None`` and the filing events
it prompts with -- auditor resigned, accounts restated, going-concern language -- never
reached a decision.

The distinctions these tests protect are the ones that decide whether a document is
retried or retired, and each is a different answer for the reader:

* **A format with no text extractor is not a document that says nothing.** A PDF marked
  ``failed`` would be retried for ever; marked ``parsed`` with no metrics it would look
  like a company with no disclosures.
* **The extractor returning nothing is not the document's fault** -- no credential, no
  budget -- so it stays ``fetched`` and is picked up when a key is configured, rather
  than being retired permanently by an unattended run.
"""

from __future__ import annotations

import datetime as dt

from awltux.db import Filing
from awltux.ingest import parsing
from awltux.llm.extractors import ExtractedMetric, ExtractionResult
from tests.helpers import make_instrument


def _seed(session, ticker: str = "TEST_US_EQ") -> None:
    session.add(make_instrument(ticker, sec_cik="0000000001"))
    session.flush()


def _filing(session, *, url: str, raw_path: str, status: str = "fetched") -> Filing:
    filing = Filing(
        instrument_t212_ticker="TEST_US_EQ",
        source="edgar",
        filing_type="10-K",
        filed_at=dt.datetime(2026, 3, 12, tzinfo=dt.UTC),
        period_end=dt.date(2025, 12, 31),
        url=url,
        raw_path=raw_path,
        status=status,
    )
    session.add(filing)
    session.flush()
    return filing


def _document(settings, name: str, body: str | bytes) -> str:
    path = settings.data_dir / "filings" / "TEST_US_EQ"
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_bytes(body.encode("utf-8") if isinstance(body, str) else body)
    return f"filings/TEST_US_EQ/{name}"


class TestTurningADocumentIntoText:
    def test_markup_is_stripped(self, settings):
        raw = _document(
            settings,
            "report.htm",
            "<html><body><h1>Revenue</h1><p>1,234</p></body></html>",
        )

        text = parsing.document_text(settings.data_dir / raw)

        assert "Revenue" in text
        assert "1,234" in text
        # The tags are gone: leaving them in spends the model's context on attribute
        # names and on numbers that appear only as attribute values.
        assert "<h1>" not in text

    def test_plain_text_is_returned_as_it_is(self, settings):
        raw = _document(settings, "notes.txt", "Auditor resigned.")

        assert parsing.document_text(settings.data_dir / raw) == "Auditor resigned."

    def test_a_format_with_no_extractor_is_none_rather_than_empty(self, settings):
        """`None` and `""` are different findings: one is a gap in this codebase, the
        other is a company with nothing to say."""
        raw = _document(settings, "report.pdf", b"%PDF-1.4 not really")

        assert parsing.document_text(settings.data_dir / raw) is None

    def test_a_missing_file_is_none(self, settings):
        assert parsing.document_text(settings.data_dir / "nope.htm") is None

    def test_a_windows_encoded_document_still_reads(self, settings):
        """EDGAR serves mostly UTF-8 and occasionally latin-1, and a decode failure must
        not read as an empty filing."""
        body = "Revenue \u201crestated\u201d".encode("cp1252")
        raw = _document(settings, "old.htm", body)

        text = parsing.document_text(settings.data_dir / raw)

        assert "Revenue" in text
        assert "restated" in text


class TestReadingTheHeldFilings:
    def _result(self, **overrides) -> ExtractionResult:
        metric = ExtractedMetric(
            name="revenue",
            value=1_000_000.0,
            span="Revenue for the year 1,000,000",
            location="Consolidated statements of operations",
        )
        result = ExtractionResult(metrics={"revenue": metric}, confidence=0.8)
        for key, value in overrides.items():
            setattr(result, key, value)
        return result

    def test_a_document_is_read_and_its_events_stored(self, settings, session, monkeypatch):
        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue 1,000,000</p>")
        filing = _filing(session, url="https://sec.test/a.htm", raw_path=raw)
        session.commit()

        monkeypatch.setattr(
            parsing,
            "extract_filing",
            lambda document, **kwargs: self._result(
                auditor={"changed": True, "resigned": False, "qualified": False}
            ),
        )

        report = parsing.extract_held_filings(session, settings=settings)
        session.commit()

        assert report["parsed"] == 1
        assert report["events"] == 1
        stored = session.get(Filing, filing.id)
        assert stored.status == "parsed"
        assert stored.extractor_version == parsing.EXTRACTOR_VERSION
        # The shape `decision/service.py::_extracted_facts` reads.
        assert stored.parsed["extraction"]["filing_events"] == [
            "auditor changed from the prior year"
        ]
        assert stored.parsed["extraction"]["metrics"]["revenue"]["value"] == 1_000_000.0

    def test_a_parsed_filing_is_never_read_again(self, settings, session, monkeypatch):
        """One paid call per document: this is a model read over a document that can be
        hundreds of thousands of characters."""
        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue</p>")
        _filing(session, url="https://sec.test/a.htm", raw_path=raw, status="parsed")
        session.commit()
        called = []
        monkeypatch.setattr(
            parsing, "extract_filing", lambda *a, **k: called.append(1) or self._result()
        )

        report = parsing.extract_held_filings(session, settings=settings)

        assert report["attempted"] == 0
        assert called == []

    def test_a_pdf_is_skipped_with_its_reason_and_not_retried(
        self, settings, session, monkeypatch
    ):
        _seed(session)
        raw = _document(settings, "report.pdf", b"%PDF-1.4")
        filing = _filing(session, url="https://sec.test/a.pdf", raw_path=raw)
        session.commit()
        monkeypatch.setattr(parsing, "extract_filing", lambda *a, **k: self._result())

        report = parsing.extract_held_filings(session, settings=settings)
        session.commit()

        assert report["skipped_no_text"] == 1
        stored = session.get(Filing, filing.id)
        assert stored.status == "skipped"
        assert "no text extractor" in stored.error

    def test_an_extractor_that_returns_nothing_leaves_it_for_next_time(
        self, settings, session, monkeypatch
    ):
        """No credential, no budget or no text is not a property of the document, and
        marking it failed would retire it for ever."""
        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue</p>")
        filing = _filing(session, url="https://sec.test/a.htm", raw_path=raw)
        session.commit()
        monkeypatch.setattr(parsing, "extract_filing", lambda *a, **k: None)

        report = parsing.extract_held_filings(session, settings=settings)
        session.commit()

        assert report["failed"] == 1
        assert session.get(Filing, filing.id).status == "fetched"

    def test_an_extractor_that_raises_retires_the_document_with_the_reason(
        self, settings, session, monkeypatch
    ):
        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue</p>")
        filing = _filing(session, url="https://sec.test/a.htm", raw_path=raw)
        session.commit()

        def boom(document, **kwargs):
            raise ValueError("the model said no")

        monkeypatch.setattr(parsing, "extract_filing", boom)

        report = parsing.extract_held_filings(session, settings=settings)
        session.commit()

        stored = session.get(Filing, filing.id)
        assert stored.status == "failed"
        assert "the model said no" in stored.error
        assert report["errors"]

    def test_a_scoped_run_reads_only_that_instrument(self, settings, session, monkeypatch):
        _seed(session, "ONE_US_EQ")
        session.add(make_instrument("TWO_US_EQ", sec_cik="0000000002"))
        session.flush()
        one = _document(settings, "one.htm", "<p>One</p>")
        two = _document(settings, "two.htm", "<p>Two</p>")
        session.add(
            Filing(
                instrument_t212_ticker="ONE_US_EQ",
                source="edgar",
                filing_type="10-K",
                url="https://sec.test/one.htm",
                raw_path=one,
                status="fetched",
            )
        )
        session.add(
            Filing(
                instrument_t212_ticker="TWO_US_EQ",
                source="edgar",
                filing_type="10-K",
                url="https://sec.test/two.htm",
                raw_path=two,
                status="fetched",
            )
        )
        session.commit()
        read: list[str] = []

        def record(document, *, company_name, **kwargs):
            read.append(company_name)
            return self._result()

        monkeypatch.setattr(parsing, "extract_filing", record)

        report = parsing.extract_held_filings(
            session, tickers=["ONE_US_EQ"], settings=settings
        )

        assert report["parsed"] == 1
        assert len(read) == 1, "only the named instrument's filing is read"

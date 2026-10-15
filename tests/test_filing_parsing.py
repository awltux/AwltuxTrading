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

import pytest
from sqlalchemy import select

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

    def test_the_inline_xbrl_header_is_dropped(self, settings):
        """The header is taxonomy plumbing, and it sits at the front of the document.

        Measured on Microsoft's FY2026 10-K (2026-10-09): the `ix:header` block is 34,137
        of 357,714 characters -- 9.5% of the document and 100% of its first 34,142 -- and
        `llm.extractors.truncate_middle` keeps the front first, so the waste came out of
        the budget before any prose was reached. BeautifulSoup returns the context, unit
        and hidden-fact definitions as text because they are elements, not attributes.
        """
        body = (
            "<html><body><ix:header><ix:hidden>"
            '<ix:nonNumeric name="dei:DocumentType">10-K</ix:nonNumeric>'
            '<xbrli:context id="c1"><xbrli:entity>'
            "<xbrli:identifier scheme=\"http://www.sec.gov/CIK\">0000789019</xbrli:identifier>"
            "</xbrli:entity><xbrli:period><xbrli:instant>2026-06-30</xbrli:instant>"
            "</xbrli:period></xbrli:context>"
            "<xbrli:unit id=\"usd\"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>"
            "</ix:hidden></ix:header>"
            "<h1>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</h1>"
            "<p>Revenue for the year was 331,839</p></body></html>"
        )
        raw = _document(settings, "inline.htm", body)

        text = parsing.document_text(settings.data_dir / raw)

        assert text.startswith("UNITED STATES")
        assert "Revenue for the year was 331,839" in text
        # The plumbing is gone: a CIK and a unit URI are not things the extractor can use,
        # and the dates in a context are not dates the document states in prose.
        assert "0000789019" not in text
        assert "iso4217:USD" not in text
        assert "xbrli" not in text

    def test_a_header_is_not_assumed_to_be_well_formed(self, settings):
        """An unclosed header must not swallow the document.

        EDGAR serves documents that are not valid XML, and the parser that reads them is
        tolerant; a rule that reads to the end of an unclosed element would return a filing
        with no text at all, which reads as a company that disclosed nothing.
        """
        body = (
            "<html><body><ix:header><xbrli:context>2026-06-30"
            "<h1>Revenue rose</h1></body></html>"
        )
        raw = _document(settings, "broken.htm", body)

        text = parsing.document_text(settings.data_dir / raw)

        assert "Revenue rose" in text

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

    def test_the_summary_is_stored_against_the_row(self, settings, session, monkeypatch):
        """`decision/service.py::_filing_summary` reads `parsed["summary"]`, and nothing
        wrote that key -- so the decision state's filing-summary slot was empty on every
        decision this application has ever made."""
        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue 1,000,000</p>")
        filing = _filing(session, url="https://sec.test/a.htm", raw_path=raw)
        session.commit()
        monkeypatch.setattr(parsing, "extract_filing", lambda *a, **k: self._result())
        monkeypatch.setattr(
            parsing,
            "summarise_filing",
            lambda *a, **k: {"business_summary": "Makes things.", "llm_call_id": 7},
        )

        parsing.extract_held_filings(session, settings=settings)
        session.commit()

        stored = session.get(Filing, filing.id)
        assert stored.parsed["summary"]["business_summary"] == "Makes things."

    def test_a_summary_that_cannot_be_had_does_not_cost_the_extraction(
        self, settings, session, monkeypatch
    ):
        """The figures are what every downstream marker runs on and the narrative is a
        bonus, so a summariser that raises must not turn a read filing into a failed one --
        which would also retire it, because only a parsed document is never retried."""
        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue 1,000,000</p>")
        filing = _filing(session, url="https://sec.test/a.htm", raw_path=raw)
        session.commit()
        monkeypatch.setattr(parsing, "extract_filing", lambda *a, **k: self._result())

        def boom(*args, **kwargs):
            raise RuntimeError("the summariser exploded")

        monkeypatch.setattr(parsing, "summarise_filing", boom)

        report = parsing.extract_held_filings(session, settings=settings)
        session.commit()

        assert report["parsed"] == 1
        stored = session.get(Filing, filing.id)
        assert stored.status == "parsed"
        assert stored.parsed["summary"] is None
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


class TestWritingThePeriod:
    """The extraction's figures become a `FundamentalPeriod` the analysis can read.

    Before this they went nowhere: `filing.parsed` held 38-41 cited metrics per filing and
    no period carried the source `llm_extraction`, so the whole 10-K pipeline was a dead
    end -- nothing read those figures, and the metric-field discovery loop had nothing to
    learn from. `analysis/fundamental.py::SOURCE_PREFERENCE` already ranked that source
    **first**, so the consumer existed and only the writer was missing.
    """

    def _run(self, session, settings, monkeypatch, result):
        _seed(session)
        raw = _document(settings, "report.htm", "<p>Total revenue 331,839</p>")
        _filing(session, url="https://sec.test/period.htm", raw_path=raw)
        session.commit()
        monkeypatch.setattr(parsing, "extract_filing", lambda *a, **k: result)
        return parsing.extract_held_filings(session, settings=settings)

    def _result(self, **overrides) -> ExtractionResult:
        metric = ExtractedMetric(
            name="revenue",
            value=331_839.0,
            span="Total revenue 331,839",
            location="Income Statements",
        )
        fields = {
            "metrics": {"revenue": metric},
            "units": "millions",
            "period_end": "2026-06-30",
            "period_type": "annual",
            "confidence": 0.95,
        }
        fields.update(overrides)
        return ExtractionResult(**fields)

    def _period(self, session):
        from sqlalchemy import select

        from awltux.db import FundamentalPeriod

        return session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == "TEST_US_EQ")
            .where(FundamentalPeriod.source == "llm_extraction")
        ).scalar_one_or_none()

    def test_the_figures_are_stored_and_scaled_to_actual_units(self, session, settings, monkeypatch):
        """The measurement this test exists for: MSFT's income statement is in millions,
        so its revenue extracts as 331,839 where the provider sources hold
        331,839,012,864. Stored unscaled, the source that ranks *first* would be the one a
        million times too small -- and no marker would notice, because ratios are
        scale-invariant."""
        report = self._run(session, settings, monkeypatch, self._result())
        session.flush()

        period = self._period(session)

        assert report["periods_stored"] == 1
        assert period is not None
        assert period.period_end == dt.date(2026, 6, 30)
        assert period.period_type == "annual"
        assert period.metrics["revenue"] == 331_839_000_000.0
        assert period.confidence == 0.95

    def test_a_price_per_share_is_not_multiplied_by_the_statements_units(
        self, session, settings, monkeypatch
    ):
        """Measured 2026-10-09 on the ten stored extraction periods: every `eps_diluted` and
        `dividend_per_share` had been multiplied by the document's scale, so MSFT's EPS was
        stored as **17,950,000** and its dividend per share as 3,320,000. A price per share is
        a price: "$17.95" in a statement presented in millions is still seventeen dollars and
        ninety-five cents."""
        result = self._result()
        result.metrics["eps_diluted"] = ExtractedMetric(
            name="eps_diluted", value=17.95, span="Diluted $ 17.95", location="Income Statements"
        )
        result.metrics["dividend_per_share"] = ExtractedMetric(
            name="dividend_per_share",
            value=3.32,
            span="Cash dividends declared per common share $ 3.32",
            location="Income Statements",
        )

        self._run(session, settings, monkeypatch, result)
        session.flush()

        period = self._period(session)
        assert period.metrics["eps_diluted"] == 17.95
        assert period.metrics["dividend_per_share"] == 3.32
        # The monetary figures in the same period are still scaled.
        assert period.metrics["revenue"] == 331_839_000_000.0

    def test_a_share_count_stated_in_millions_is_scaled(self, session, settings, monkeypatch):
        """A count is the one non-monetary figure where the scale can be right: MSFT's balance
        sheet prints "outstanding 7,427 and 7,434", which is millions of shares."""
        result = self._result()
        result.metrics["shares_outstanding"] = ExtractedMetric(
            name="shares_outstanding",
            value=7_427.0,
            span="outstanding 7,427 and 7,434",
            location="Balance Sheets",
        )

        self._run(session, settings, monkeypatch, result)
        session.flush()

        assert self._period(session).metrics["shares_outstanding"] == 7_427_000_000.0

    def test_a_share_count_stated_in_full_is_not_scaled(self, session, settings, monkeypatch):
        """And the case the magnitude test exists for: GWW, DAC and ATMU all quote the count
        itself, and scaling it produced 47,418,781,000,000 shares."""
        result = self._result()
        result.metrics["shares_outstanding"] = ExtractedMetric(
            name="shares_outstanding",
            value=47_418_781.0,
            span="Balance at end of period 47,418,781",
            location="Balance Sheets",
        )

        self._run(session, settings, monkeypatch, result)
        session.flush()

        assert self._period(session).metrics["shares_outstanding"] == 47_418_781.0

    def test_the_citation_survives(self, session, settings, monkeypatch):
        """A figure with a span and a location is the whole reason this source outranks a
        scraped snapshot."""
        self._run(session, settings, monkeypatch, self._result())
        session.flush()

        source = self._period(session).metric_sources["revenue"]

        assert source["span"] == "Total revenue 331,839"
        assert source["location"] == "Income Statements"
        assert source["source"] == "llm_extraction"

    def test_every_filing_in_one_run_leaves_a_queryable_period(
        self, session, settings, monkeypatch
    ):
        """Two filings in a batch, two periods readable when the run returns.

        The row was added and left pending: with no flush in `_store_period` the second
        period only reached the database on the *next* filing's flush or the scope's
        commit, so a probe reading the batch back saw one period where two had been
        stored -- measured on MSFT's two 10-Ks. The other two `_upsert_period` call sites
        flush, and this is the measurement that says why the third must too.
        """
        from sqlalchemy import select

        from awltux.db import FundamentalPeriod

        _seed(session)
        first = _document(settings, "fy2026.htm", "<p>Total revenue 331,839</p>")
        second = _document(settings, "fy2025.htm", "<p>Total revenue 281,724</p>")
        _filing(session, url="https://sec.test/fy2026.htm", raw_path=first)
        _filing(session, url="https://sec.test/fy2025.htm", raw_path=second)
        session.commit()

        def extract(document, **kwargs):
            if "331,839" in document:
                return self._result()
            return self._result(period_end="2025-06-30")

        monkeypatch.setattr(parsing, "extract_filing", extract)

        report = parsing.extract_held_filings(session, settings=settings)

        periods = list(
            session.execute(
                select(FundamentalPeriod)
                .where(FundamentalPeriod.source == "llm_extraction")
                .order_by(FundamentalPeriod.period_end)
            ).scalars()
        )
        assert report["periods_stored"] == 2
        assert [period.period_end for period in periods] == [
            dt.date(2025, 6, 30),
            dt.date(2026, 6, 30),
        ]

    def test_derived_ratios_are_computed_from_the_scaled_figures(self, session, settings, monkeypatch):
        """They are ours, so they are recomputed rather than scaled -- and they carry no
        citation, because claiming the issuer tagged `net_margin` would be a fabricated
        provenance."""
        result = self._result()
        result.metrics["net_income"] = ExtractedMetric(
            name="net_income", value=133_749.0, span="Net income 133,749", location="Income Statements"
        )

        self._run(session, settings, monkeypatch, result)
        session.flush()

        period = self._period(session)

        assert "net_margin" in period.metrics
        assert "net_margin" not in (period.metric_sources or {})

    @pytest.mark.parametrize("unusable", ["", "not stated", "bananas", None])
    def test_units_the_document_did_not_state_lose_the_period(
        self, session, settings, monkeypatch, unusable
    ):
        """Refused rather than assumed to be actual.

        This source outranks every provider, so a period stored at the wrong scale does
        not merely look wrong -- it *wins*. There is no later marker that would catch it,
        because the ratios are scale-invariant.
        """
        report = self._run(session, settings, monkeypatch, self._result(units=unusable))
        session.flush()

        assert report.get("unscaled_period") == 1
        assert self._period(session) is None

    def test_a_period_end_the_document_did_not_state_is_not_stored(
        self, session, settings, monkeypatch
    ):
        report = self._run(
            session, settings, monkeypatch, self._result(period_end=None)
        )
        session.flush()

        assert report.get("unusable_period") == 1
        assert self._period(session) is None

    def test_the_source_outranks_the_providers_it_shares_a_period_with(self):
        """The reason the scaling matters, asserted where it is decided.

        Our reading of the filed document outranks a scraped copy of it -- and the filer's own
        tagged accounts outrank both, which is the reader's rule: *"the accounts from
        government sites take precedence"*. The extraction still matters because most periods
        have no other source, and because a disagreement with the filer's own tags is what the
        accounts page reports.
        """
        from awltux.analysis.collate import GOVERNMENT_SOURCES, SOURCE_RANK

        assert SOURCE_RANK["llm_extraction"] > SOURCE_RANK["yahoo_statements"]
        assert SOURCE_RANK["xbrl_companyfacts"] > SOURCE_RANK["llm_extraction"]
        assert SOURCE_RANK["xbrl_companyfacts"] == max(SOURCE_RANK.values())
        assert "xbrl_companyfacts" in GOVERNMENT_SOURCES


class TestRepairingStoredFigures:
    """The write-time fix stops new mis-scaled figures; these rows already exist.

    Measured 2026-10-09 on the live database: 10 extraction periods, whose `eps_diluted` and
    `dividend_per_share` carry the document's scale (MSFT EPS stored as 17,950,000) and three
    of whose share counts are past a trillion. The repair reads the span each figure was
    quoted from rather than re-extracting, which would cost a model call per filing and could
    change figures for unrelated reasons.
    """

    def test_a_mis_scaled_price_per_share_is_restored_from_its_span(self, session):
        from awltux.db import FundamentalPeriod
        from awltux.ingest import parsing

        session.add(make_instrument("TEST_US_EQ", name="Test Co"))
        session.flush()
        session.add(
            FundamentalPeriod(
                instrument_t212_ticker="TEST_US_EQ",
                source="llm_extraction",
                period_end=dt.date(2026, 6, 30),
                period_type="annual",
                currency="USD",
                metrics={"eps_diluted": 17_950_000.0, "revenue": 331_839_000_000.0},
                metric_sources={
                    "eps_diluted": {"span": "Diluted $ 17.95", "location": "IS"},
                    "revenue": {"span": "Total revenue 331,839", "location": "IS"},
                },
                confidence=0.8,
            )
        )
        session.flush()

        report = parsing.repair_scaled_figures(session)

        assert len(report["changed"]) == 1
        assert report["changed"][0]["metric"] == "eps_diluted"
        assert report["changed"][0]["was"] == 17_950_000.0
        assert report["changed"][0]["now"] == 17.95

        row = session.execute(select(FundamentalPeriod)).scalar_one()
        assert row.metrics["eps_diluted"] == 17.95
        assert row.metrics["revenue"] == 331_839_000_000.0, "a monetary figure is untouched"

    def test_an_impossible_share_count_is_restored_from_its_span(self, session):
        """GWW, DAC and ATMU each quoted the count itself and the scale made it past a
        trillion shares; MSFT's 7,427 really is millions and must be left alone."""
        from awltux.db import FundamentalPeriod
        from awltux.ingest import parsing

        for ticker, stored, span in (
            ("GWW_US_EQ", 4.742e13, "Balance at end of period 47,418,781"),
            ("MSFT_US_EQ", 7.427e9, "outstanding 7,427 and 7,434"),
        ):
            session.add(make_instrument(ticker, name="Test Co"))
            session.flush()
            session.add(
                FundamentalPeriod(
                    instrument_t212_ticker=ticker,
                    source="llm_extraction",
                    period_end=dt.date(2025, 12, 31),
                    period_type="annual",
                    currency="USD",
                    metrics={"shares_outstanding": stored},
                    metric_sources={"shares_outstanding": {"span": span, "location": "BS"}},
                    confidence=0.8,
                )
            )
        session.flush()

        report = parsing.repair_scaled_figures(session)

        assert [entry["ticker"] for entry in report["changed"]] == ["GWW_US_EQ"]
        assert report["changed"][0]["now"] == 47_418_781.0
        rows = {
            row.instrument_t212_ticker: row
            for row in session.execute(select(FundamentalPeriod)).scalars()
        }
        assert rows["MSFT_US_EQ"].metrics["shares_outstanding"] == 7.427e9

    def test_a_figure_already_right_is_left_alone(self, session):
        from awltux.db import FundamentalPeriod
        from awltux.ingest import parsing

        session.add(make_instrument("TEST_US_EQ", name="Test Co"))
        session.flush()
        session.add(
            FundamentalPeriod(
                instrument_t212_ticker="TEST_US_EQ",
                source="xbrl_companyfacts",
                period_end=dt.date(2025, 12, 31),
                period_type="annual",
                metrics={"eps_diluted": 17.95},
                metric_sources={"eps_diluted": {"span": "Diluted $ 17.95"}},
                confidence=0.8,
            )
        )
        session.flush()

        assert parsing.repair_scaled_figures(session)["changed"] == []

    def test_a_dry_run_writes_nothing(self, session):
        from awltux.db import FundamentalPeriod
        from awltux.ingest import parsing

        session.add(make_instrument("TEST_US_EQ", name="Test Co"))
        session.flush()
        session.add(
            FundamentalPeriod(
                instrument_t212_ticker="TEST_US_EQ",
                source="llm_extraction",
                period_end=dt.date(2026, 6, 30),
                period_type="annual",
                metrics={"eps_diluted": 17_950_000.0},
                metric_sources={"eps_diluted": {"span": "Diluted $ 17.95"}},
                confidence=0.8,
            )
        )
        session.flush()

        report = parsing.repair_scaled_figures(session, dry_run=True)

        assert len(report["changed"]) == 1
        session.expire_all()
        assert session.execute(select(FundamentalPeriod)).scalar_one().metrics["eps_diluted"] == 17_950_000.0

    def test_a_span_with_no_number_is_counted_not_guessed(self, session):
        from awltux.db import FundamentalPeriod
        from awltux.ingest import parsing

        session.add(make_instrument("TEST_US_EQ", name="Test Co"))
        session.flush()
        session.add(
            FundamentalPeriod(
                instrument_t212_ticker="TEST_US_EQ",
                source="llm_extraction",
                period_end=dt.date(2026, 6, 30),
                period_type="annual",
                metrics={"eps_diluted": 17_950_000.0},
                metric_sources={"eps_diluted": {"span": "Diluted earnings per share"}},
                confidence=0.8,
            )
        )
        session.flush()

        report = parsing.repair_scaled_figures(session)

        assert report["changed"] == []
        assert report["unreadable"] == 1
        assert session.execute(select(FundamentalPeriod)).scalar_one().metrics["eps_diluted"] == 17_950_000.0

    def test_it_is_idempotent(self, session):
        from awltux.db import FundamentalPeriod
        from awltux.ingest import parsing

        session.add(make_instrument("TEST_US_EQ", name="Test Co"))
        session.flush()
        session.add(
            FundamentalPeriod(
                instrument_t212_ticker="TEST_US_EQ",
                source="llm_extraction",
                period_end=dt.date(2026, 6, 30),
                period_type="annual",
                metrics={"eps_diluted": 17_950_000.0},
                metric_sources={"eps_diluted": {"span": "Diluted $ 17.95"}},
                confidence=0.8,
            )
        )
        session.flush()

        parsing.repair_scaled_figures(session)
        second = parsing.repair_scaled_figures(session)

        assert second["changed"] == [], "a second run finds nothing left to correct"


class TestLearningACaption:
    """The loop the dynamic vocabulary exists for.

    The extractor reports the lines a filing presents that the prompt did not name; the
    ledger says how far the components we hold fall short of a stated subtotal; and a
    caption is *proved* to belong on the list when its value closes that residual. The
    numbers are MSFT's, which is where this was measured: current assets of
    151,802 against a stated 207,710, the difference being exactly its short-term
    investments.
    """

    def _result(self, *, unlisted: dict, metrics: dict) -> ExtractionResult:
        return ExtractionResult(metrics=metrics, unlisted=unlisted, confidence=0.8)

    def _metric(self, name: str, value: float) -> ExtractedMetric:
        return ExtractedMetric(
            name=name,
            value=value,
            span=f"{name} {value:,.0f}",
            location="Consolidated balance sheets",
        )

    def test_a_caption_that_closes_the_gap_is_recorded(self, settings, session, monkeypatch):
        from awltux.analysis import metric_fields

        _seed(session)
        raw = _document(settings, "report.htm", "<p>Short-term investments 55,908</p>")
        _filing(session, url="https://sec.test/msft.htm", raw_path=raw)
        session.commit()

        # Assets we hold sum to 151,802 against a stated 207,710 -- out by 55,908.
        metrics = {
            "cash_and_equivalents": self._metric("cash_and_equivalents", 20_935.0),
            "receivables": self._metric("receivables", 80_876.0),
            "inventory": self._metric("inventory", 1_397.0),
            "other_current_assets": self._metric("other_current_assets", 48_594.0),
            "current_assets": self._metric("current_assets", 207_710.0),
        }
        unlisted = {"short_term_investments": self._metric("short_term_investments", 55_908.0)}
        monkeypatch.setattr(
            parsing,
            "extract_filing",
            lambda document, **kwargs: self._result(unlisted=unlisted, metrics=metrics),
        )

        report = parsing.extract_held_filings(session, settings=settings)

        assert report.get("discovered") == 1
        assert "short_term_investments" in metric_fields.names(session)
        assert metric_fields.load(session)["short_term_investments"].origin == "discovered"

    def test_a_caption_that_does_not_close_the_gap_is_not_recorded(
        self, settings, session, monkeypatch
    ):
        """The safeguard. A model asked which line is missing will always answer, and
        only the arithmetic can tell a right answer from a confident one."""
        from awltux.analysis import metric_fields

        _seed(session)
        raw = _document(settings, "report.htm", "<p>Something 12</p>")
        _filing(session, url="https://sec.test/other.htm", raw_path=raw)
        session.commit()

        metrics = {
            "cash_and_equivalents": self._metric("cash_and_equivalents", 20_935.0),
            "current_assets": self._metric("current_assets", 207_710.0),
        }
        unlisted = {"plausible_but_wrong": self._metric("plausible_but_wrong", 12.0)}
        monkeypatch.setattr(
            parsing,
            "extract_filing",
            lambda document, **kwargs: self._result(unlisted=unlisted, metrics=metrics),
        )

        report = parsing.extract_held_filings(session, settings=settings)

        assert not report.get("discovered")
        assert "plausible_but_wrong" not in metric_fields.names(session)
        assert set(metric_fields.load(session)) == set(metric_fields.seed())

    def test_no_unlisted_captions_is_the_ordinary_answer(self, settings, session, monkeypatch):
        from awltux.analysis import metric_fields

        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue 1</p>")
        _filing(session, url="https://sec.test/plain.htm", raw_path=raw)
        session.commit()

        monkeypatch.setattr(
            parsing,
            "extract_filing",
            lambda document, **kwargs: self._result(
                unlisted={}, metrics={"revenue": self._metric("revenue", 1.0)}
            ),
        )

        report = parsing.extract_held_filings(session, settings=settings)

        assert not report.get("discovered")
        assert len(metric_fields.load(session)) == len(metric_fields.seed())

    def test_a_caption_from_another_statement_cannot_close_a_balance_sheet_gap(
        self, settings, session, monkeypatch
    ):
        """The false positive the first live run produced.

        A pair made of a balance-sheet line and a *revenue* line summed to the residual
        and was promoted -- two unrelated statements adding up to a number is a
        coincidence, and it would have gone into the prompt for every later filing. Only
        captions the model found on the balance sheet may close a balance-sheet residual.
        """
        from awltux.analysis import metric_fields

        _seed(session)
        raw = _document(settings, "report.htm", "<p>Revenue 79,728</p>")
        _filing(session, url="https://sec.test/mixed.htm", raw_path=raw)
        session.commit()

        # Out by 79,728 -- and a revenue line happens to equal it.
        metrics = {
            "cash_and_equivalents": self._metric("cash_and_equivalents", 20_935.0),
            "current_assets": self._metric("current_assets", 100_663.0),
        }
        income_line = ExtractedMetric(
            name="product_revenue",
            value=79_728.0,
            span="Product revenue 79,728",
            location="Income statements",
        )
        monkeypatch.setattr(
            parsing,
            "extract_filing",
            lambda document, **kwargs: self._result(
                unlisted={"product_revenue": income_line}, metrics=metrics
            ),
        )

        report = parsing.extract_held_filings(session, settings=settings)

        assert not report.get("discovered"), "an income line must not close a balance-sheet gap"
        assert "product_revenue" not in metric_fields.names(session)

    def test_a_caption_found_on_the_balance_sheet_still_qualifies(
        self, settings, session, monkeypatch
    ):
        """The other direction, so the filter is not simply refusing everything."""
        from awltux.analysis import metric_fields

        _seed(session)
        raw = _document(settings, "report.htm", "<p>Short-term investments 55,908</p>")
        _filing(session, url="https://sec.test/bs.htm", raw_path=raw)
        session.commit()

        metrics = {
            "cash_and_equivalents": self._metric("cash_and_equivalents", 20_935.0),
            "current_assets": self._metric("current_assets", 76_843.0),
        }
        # `_metric` files everything under "Consolidated balance sheets".
        bs_line = self._metric("short_term_investments", 55_908.0)
        monkeypatch.setattr(
            parsing,
            "extract_filing",
            lambda document, **kwargs: self._result(
                unlisted={"short_term_investments": bs_line}, metrics=metrics
            ),
        )

        report = parsing.extract_held_filings(session, settings=settings)

        assert report.get("discovered") == 1
        assert "short_term_investments" in metric_fields.names(session)


class TestRepairingFilingSummaries:
    """Filings read before the summariser was wired up hold an extraction and no summary.

    A parsed filing is never read again -- that read is the expensive deep model over a whole
    document -- so the only way to finish those rows is this: read the document from disk
    again and ask only the summariser, which runs on the cheap model. Measured 2026-10-15 on
    the live database: 20 filings were in that state.
    """

    @staticmethod
    def _instrument(session) -> None:
        from awltux.db import Instrument

        if session.get(Instrument, "TEST_US_EQ") is None:
            _seed(session)

    def _parsed(self, session, settings, *, name="report.htm", parsed=None) -> Filing:
        """A filing already read, with whatever payload the test wants it to hold."""
        self._instrument(session)
        raw = _document(settings, name, "<p>Revenue 1,000,000</p>")
        filing = _filing(session, url=f"https://sec.test/{name}", raw_path=raw, status="parsed")
        filing.parsed = parsed if parsed is not None else {"extraction": {"metrics": {}}}
        session.flush()
        return filing

    def test_it_summarises_a_filing_that_has_none(self, session, settings, monkeypatch):
        filing = self._parsed(session, settings)
        monkeypatch.setattr(
            parsing,
            "summarise_filing",
            lambda *a, **k: {"business_summary": "Makes things.", "llm_call_id": 7},
        )

        report = parsing.repair_filing_summaries(session, settings=settings)

        assert report["changed_count"] == 1
        stored = session.get(Filing, filing.id)
        assert stored.parsed["summary"]["business_summary"] == "Makes things."
        # And the extraction it already held is untouched: this is not a re-read.
        assert "extraction" in stored.parsed

    def test_a_filing_that_already_has_a_summary_is_never_read_again(
        self, session, settings, monkeypatch
    ):
        """Which is what makes a second run free, and why the command is safe to repeat."""
        self._parsed(
            session,
            settings,
            parsed={"extraction": {"metrics": {}}, "summary": {"business_summary": "Already."}},
        )
        called: list[int] = []
        monkeypatch.setattr(parsing, "summarise_filing", lambda *a, **k: called.append(1) or {})

        report = parsing.repair_filing_summaries(session, settings=settings)

        assert report["already"] == 1
        assert report["changed_count"] == 0
        assert called == []

    def test_a_dry_run_lists_the_candidates_and_calls_nothing(
        self, session, settings, monkeypatch
    ):
        """The run worth checking first is the expensive one: this repair spends money where
        its two siblings re-derive what is already recorded."""
        filing = self._parsed(session, settings)
        called: list[int] = []
        monkeypatch.setattr(parsing, "summarise_filing", lambda *a, **k: called.append(1) or {})

        report = parsing.repair_filing_summaries(session, settings=settings, dry_run=True)

        assert report["changed_count"] == 1
        assert called == []
        assert "summary" not in session.get(Filing, filing.id).parsed

    def test_a_document_that_cannot_be_read_is_left_alone(self, session, settings, monkeypatch):
        """No text extractor for the format, or the file is gone. Either way nothing is
        written and nothing is spent."""
        filing = self._parsed(session, settings, name="report.pdf")
        called: list[int] = []
        monkeypatch.setattr(parsing, "summarise_filing", lambda *a, **k: called.append(1) or {})

        report = parsing.repair_filing_summaries(session, settings=settings)

        assert report["no_text"] == 1
        assert report["changed_count"] == 0
        assert called == []
        assert "summary" not in session.get(Filing, filing.id).parsed

    def test_a_summary_that_comes_back_empty_is_left_for_the_next_run(
        self, session, settings, monkeypatch
    ):
        """No credential, or the budget refused the call. Writing nothing keeps the row a
        candidate, so a later run retries it rather than recording a permanent blank."""
        filing = self._parsed(session, settings)
        monkeypatch.setattr(parsing, "summarise_filing", lambda *a, **k: None)

        report = parsing.repair_filing_summaries(session, settings=settings)

        assert report["failed"] == 1
        assert report["changed_count"] == 0
        assert "summary" not in session.get(Filing, filing.id).parsed

    def test_the_limit_counts_filings_that_still_need_work(self, session, settings, monkeypatch):
        """Not the query's first N: after a first pass the newest parsed filings are the ones
        already finished, so a limit applied there would spend on nothing."""
        self._parsed(session, settings, name="a.htm")
        self._parsed(session, settings, name="b.htm")
        done: list[int] = []
        monkeypatch.setattr(
            parsing,
            "summarise_filing",
            lambda *a, **k: done.append(1) or {"business_summary": "x"},
        )

        report = parsing.repair_filing_summaries(session, settings=settings, limit=1)

        assert report["checked"] == 2
        assert report["changed_count"] == 1
        assert len(done) == 1

    def test_the_count_and_the_repair_agree_on_who_needs_work(
        self, session, settings, monkeypatch
    ):
        """The probe that offers the button and the repair the button starts share one
        definition. Two would drift, and the failure is a page that says "all read filings
        have a summary" while a run would spend money on the ones that do not."""
        from awltux.ingest.parsing import filings_awaiting_summaries

        self._parsed(session, settings, name="needs.htm")
        self._parsed(
            session,
            settings,
            name="has.htm",
            parsed={"extraction": {}, "summary": {"business_summary": "Already."}},
        )
        monkeypatch.setattr(parsing, "summarise_filing", lambda *a, **k: {"business_summary": "x"})

        assert filings_awaiting_summaries(session) == (1, 2)
        report = parsing.repair_filing_summaries(session, settings=settings)
        assert report["changed_count"] == 1
        assert filings_awaiting_summaries(session) == (0, 2)

    def test_the_job_runs_the_repair_and_reports_what_it_did(self, session, settings, monkeypatch):
        """The registered entry point, which is what the Operations button calls.

        Stubbed at ``summarise_filing`` rather than at the client so it exercises the
        session handling, the counting and the detail the run row stores -- the parts the
        CLI cannot show and the page reads back.
        """
        from awltux.ingest.jobs import repair_filing_summaries_job

        self._parsed(session, settings)
        monkeypatch.setattr(parsing, "summarise_filing", lambda *a, **k: {"business_summary": "x"})
        # The job opens its own `session_scope`; this fixture is holding one, so the row
        # has to be committed for the job's session to see it at all.
        session.commit()

        result = repair_filing_summaries_job()

        assert result.items_seen == 1
        assert result.items_written == 1
        assert result.detail["changed_count"] == 1
        assert result.detail["already"] == 0
        # Read back through this session: the job committed its own, and the row a
        # decision reads has to carry the summary by the time it returns.
        session.expire_all()
        stored = session.execute(select(Filing)).scalar_one()
        assert stored.parsed["summary"]["business_summary"] == "x"


class TestWhatTheRepairButtonIsOfferedFor:
    """The coverage probe for the on-demand repair, exercised where parsed filings can
    be built. It lives here rather than with the other probe tests for that reason: the
    claim being checked -- "this many read filings still have no summary" -- is a claim
    about `parsing`, and only this file knows how to make one.

    Wording matters more than usual here, because the probe is the *only* thing standing
    between a press of Run now and a model call per filing.
    """

    @staticmethod
    def _read(session, settings, *, named: str, summarised: bool) -> Filing:
        from awltux.db import Instrument

        if session.get(Instrument, "TEST_US_EQ") is None:
            _seed(session)
        raw = _document(settings, f"{named}.htm", "<p>Revenue 1,000,000</p>")
        filing = _filing(
            session,
            url=f"https://sec.test/{named}.htm",
            raw_path=raw,
            status="parsed",
        )
        filing.parsed = {"extraction": {}} | (
            {"summary": {"business_summary": "Done."}} if summarised else {}
        )
        session.flush()
        return filing

    def test_nothing_read_says_nothing_read(self, session):
        """Not "all 0 filings have a summary", which is the reassuring answer to a
        question nobody asked -- an empty table is not a finished repair."""
        from awltux.scheduler.dependencies import PROBES

        coverage = PROBES["filing_summaries"](session)

        assert coverage.missing == 0
        assert "no filing has been read" in coverage.reason

    def test_the_count_is_of_filings_that_still_need_one(self, session, settings):
        from awltux.scheduler.dependencies import PROBES

        self._read(session, settings, named="needs", summarised=False)
        self._read(session, settings, named="has", summarised=True)

        coverage = PROBES["filing_summaries"](session)

        assert coverage.missing == 1
        assert coverage.total == 2
        assert "1 of 2 read filings" in coverage.reason

    def test_a_finished_repair_says_so(self, session, settings):
        from awltux.scheduler.dependencies import PROBES

        self._read(session, settings, named="has", summarised=True)

        coverage = PROBES["filing_summaries"](session)

        assert coverage.missing == 0
        assert coverage.reason == "all 1 read filings have a summary"

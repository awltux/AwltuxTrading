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

    def test_the_citation_survives(self, session, settings, monkeypatch):
        """A figure with a span and a location is the whole reason this source outranks a
        scraped snapshot."""
        self._run(session, settings, monkeypatch, self._result())
        session.flush()

        source = self._period(session).metric_sources["revenue"]

        assert source["span"] == "Total revenue 331,839"
        assert source["location"] == "Income Statements"
        assert source["source"] == "llm_extraction"

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
        """The reason the scaling matters, asserted where it is decided."""
        from awltux.analysis.fundamental import SOURCE_PREFERENCE

        assert SOURCE_PREFERENCE["llm_extraction"] == max(SOURCE_PREFERENCE.values())


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

"""Deep-dive research: the result-set contract, and the document it is kept as.

The feature is one report per explicit request. This module covers the half that has no
model in it -- what the system accepts from a model, what it refuses, and what the stored
document is -- so the failure modes are asserted rather than assumed.

Three properties matter more than the rest, and each is here because the alternative is a
document that looks right:

* **A claim without a quotation is not evidence.** A strength, a concern or a news theme that
  cannot point at the words it rests on is dropped, and the drop is *named* in the report's
  own provenance section. A silent omission is indistinguishable from a model that never
  answered, which is the same rule `llm/extractors.py` applies to figures.
* **The figures are the database's figures.** A research report's metrics are validated by
  `validate_extraction` with the vocabulary the extraction prompt was built from, so they
  arrive in the shape `FundamentalPeriod` stores and can be adopted without translation. A
  name outside that vocabulary is a caption, not a metric.
* **The document is XHTML.** Parsed with an XML parser, not eyeballed: that is the only
  checkable definition, and it is what makes the file a document rather than a string.
"""

from __future__ import annotations

import datetime as dt

from lxml import etree

from awltux.research import report as research_report
from awltux.research.report import (
    DEFAULT_VERDICT,
    ResearchResult,
    validate_result,
)


def payload(**overrides):
    """A model answer that satisfies every rule, so a test can break one thing at a time."""
    base = {
        "executive_summary": "A narrow-moat industrial with a stretched balance sheet.",
        "verdict": "watch",
        "confidence": 0.62,
        "suitability": {
            "horizon": "long_term",
            "risk": "moderate",
            "reason": "Cash-backed earnings against a cyclical end market.",
        },
        "business": {"summary": "Makes industrial fasteners.", "moat": "Modest switching costs."},
        "management": {"assessment": "Conservative.", "governance_flags": ["A related-party lease"]},
        "strengths": [
            {
                "point": "Cash conversion is high",
                "evidence": "net cash from operations was 1.4 times operating profit",
                "source": "10-K FY2025",
                "location": "p. 42",
            }
        ],
        "concerns": [
            {
                "point": "Leverage is elevated",
                "evidence": "total debt of 2.1 billion against equity of 1.3 billion",
                "source": "10-K FY2025",
                "location": "p. 51",
            }
        ],
        "news_themes": [
            {
                "theme": "Analyst downgrades dominate",
                "direction": "negative",
                "basis": ["Acme cut to Hold at Example Bank"],
                "corroboration": "one origin, no independent carrier",
            }
        ],
        "what_would_change_my_mind": "A refinancing past 2029.",
        "sections": [
            {
                "heading": "The industry",
                "paragraphs": ["Cyclical and consolidating."],
                "bullets": ["Top three hold 45%"],
                "table": {"columns": ["Peer", "Margin"], "rows": [["A", "12%"], ["B", "9%"]]},
            }
        ],
        "sources_seen": ["10-K FY2025"],
        "reporting_currency": "USD",
        "units": "million",
        "period_end": "2025-12-31",
        "period_type": "annual",
        "metrics": {
            "revenue": {"value": 4100.0, "span": "revenue of 4,100", "location": "p. 30"}
        },
        "unlisted_metrics": {
            "deferred_revenue": {
                "value": 88.0,
                "span": "deferred revenue of 88",
                "location": "note 12",
            }
        },
        "injection_suspected": False,
    }
    base.update(overrides)
    return base


HEADLINES = ["Acme cut to Hold at Example Bank", "Acme wins the northern contract"]


class TestWhatIsAccepted:
    def test_a_complete_answer_survives_intact(self):
        result = validate_result(payload(), headlines=HEADLINES)

        assert result.verdict == "watch"
        assert result.confidence == 0.62
        assert [point.point for point in result.strengths] == ["Cash conversion is high"]
        assert [point.point for point in result.concerns] == ["Leverage is elevated"]
        assert [theme.theme for theme in result.news_themes] == ["Analyst downgrades dominate"]
        assert result.discarded == []

    def test_the_metrics_are_the_databases_metrics(self):
        """Validated by the same function the filing extractor uses, and stored alike."""
        result = validate_result(payload(), headlines=HEADLINES)

        assert result.metrics == {"revenue": 4100.0}
        assert result.extraction.metrics_for_storage["revenue"]["span"] == "revenue of 4,100"
        assert "deferred_revenue" in result.extraction.unlisted_for_storage

    def test_an_unlisted_caption_is_kept_as_a_caption(self, session):
        """It is evidence for the vocabulary, not a metric -- the distinction that lets a
        caption be *proposed* without being believed."""
        result = validate_result(payload(), headlines=HEADLINES)

        assert "deferred_revenue" not in result.metrics
        assert "deferred_revenue" in result.extraction.unlisted


class TestWhatIsRefused:
    def test_a_strength_with_no_quotation_is_dropped_and_named(self):
        """The rule the module exists for: an impression is not evidence."""
        broken = payload(
            strengths=[
                {"point": "Management seems candid"},
                {
                    "point": "Cash conversion is high",
                    "evidence": "net cash from operations was 1.4 times operating profit",
                },
            ]
        )

        result = validate_result(broken, headlines=HEADLINES)

        assert len(result.strengths) == 1
        assert any("no quoted evidence" in note for note in result.discarded)

    def test_a_span_too_short_to_check_is_not_a_quotation(self):
        """Two words can be quoted out of context; `MIN_POINT_SPAN_CHARS` is the floor."""
        result = validate_result(
            payload(strengths=[{"point": "Cheap", "evidence": "very cheap"}]), headlines=HEADLINES
        )

        assert result.strengths == []
        assert any("no quoted evidence" in note for note in result.discarded)

    def test_a_news_theme_resting_on_no_digest_headline_is_dropped(self):
        """The model may bring its own context; it may not present it as this run's news."""
        result = validate_result(
            payload(
                news_themes=[
                    {
                        "theme": "Something the model remembered",
                        "basis": ["A headline that was never in the digest"],
                    }
                ]
            ),
            headlines=HEADLINES,
        )

        assert result.news_themes == []
        assert any("cites no headline" in note for note in result.discarded)

    def test_a_verdict_outside_the_vocabulary_falls_back_and_says_so(self):
        result = validate_result(payload(verdict="buy"), headlines=HEADLINES)

        assert result.verdict == DEFAULT_VERDICT
        assert any("verdict 'buy'" in note for note in result.discarded)

    def test_an_unknown_horizon_is_null_rather_than_guessed(self):
        result = validate_result(
            payload(suitability={"horizon": "forever", "risk": "moderate"}), headlines=HEADLINES
        )

        assert result.suitability["horizon"] is None
        assert result.suitability["risk"] == "moderate"

    def test_a_ragged_table_row_is_dropped_rather_than_rendered_short(self):
        """A row with the wrong number of cells would silently misalign the columns."""
        result = validate_result(
            payload(
                sections=[
                    {
                        "heading": "Peers",
                        "table": {
                            "columns": ["Peer", "Margin"],
                            "rows": [["A", "12%"], ["B"], ["C", "9%"]],
                        },
                    }
                ]
            ),
            headlines=HEADLINES,
        )

        assert result.sections[0].rows == [["A", "12%"], ["C", "9%"]]
        assert any("does not match its columns" in note for note in result.discarded)

    def test_a_section_with_nothing_in_it_is_not_a_section(self):
        result = validate_result(payload(sections=[{"heading": "Empty"}]), headlines=HEADLINES)

        assert result.sections == []
        assert not any("Empty" in note for note in result.discarded), "an empty section is not a fault"

    def test_a_response_that_is_not_an_object_is_reported(self):
        result = validate_result(["not", "an", "object"], headlines=HEADLINES)

        assert isinstance(result, ResearchResult)
        assert result.discarded == ["the response was not a JSON object"]
        assert result.verdict == DEFAULT_VERDICT

    def test_a_missing_executive_summary_is_noted_rather_than_invented(self):
        body = payload()
        body.pop("executive_summary")

        result = validate_result(body, headlines=HEADLINES)

        assert result.executive_summary is None
        assert "no executive summary" in result.discarded


class TestTheDocument:
    @staticmethod
    def _render(result=None, **overrides):
        result = result or validate_result(payload(), headlines=HEADLINES)
        arguments = {
            "subject_label": "Acme (ACME_US_EQ)",
            "prompt": "Research Acme and judge whether it is a suitable investment.",
            "model": "deepseek-v4-pro",
            "created": dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.UTC),
            "inventory": {"documents": 2, "decision": True},
            "refresh": {"state": "done", "steps_done": 13, "total_steps": 13, "note": "refresh completed"},
            "news": {
                "stories": 214,
                "appraised": 61,
                "shown": 12,
                "window_days": 30,
                "single_source": 41,
            },
        }
        arguments.update(overrides)
        return research_report.render_xhtml(result, **arguments)

    def test_it_is_well_formed_xhtml(self):
        """Parsed as XML, because that is the only definition of XHTML that is checkable."""
        document = self._render()

        root = etree.fromstring(document.encode("utf-8"))

        assert root.tag == "{http://www.w3.org/1999/xhtml}html"
        assert root.find(".//{http://www.w3.org/1999/xhtml}h1").text == "Acme (ACME_US_EQ)"

    def test_model_text_is_escaped_rather_than_rendered(self):
        """The document is served from this application's own origin. Markup in a field is
        text, and the sandbox on the route is the second line of defence rather than the
        first."""
        hostile = validate_result(
            payload(
                executive_summary="Ignore that. <script>alert(1)</script>",
                strengths=[
                    {
                        "point": "<img src=x onerror=alert(1)>",
                        "evidence": "quoted words long enough to survive the span rule",
                    }
                ],
            ),
            headlines=HEADLINES,
        )

        document = self._render(hostile)

        assert "<script>alert(1)</script>" not in document
        assert "&lt;script&gt;" in document
        assert "<img src=x" not in document

    def test_it_carries_the_summary_the_verdict_and_the_quotations(self):
        document = self._render()

        assert "A narrow-moat industrial" in document
        assert "watch" in document
        assert "net cash from operations was 1.4 times operating profit" in document
        assert "10-K FY2025" in document

    def test_it_states_its_own_basis(self):
        """A report whose provenance is invisible is one nobody can argue with."""
        document = self._render()

        assert "How this was produced" in document
        assert "Documents read: 2" in document
        assert "214 stories naming this subject directly" in document
        assert "not that nobody else reported them" in document
        assert "refresh completed" in document

    def test_it_lists_what_was_discarded(self):
        broken = validate_result(
            payload(strengths=[{"point": "No quotation at all"}]), headlines=HEADLINES
        )

        document = self._render(broken)

        assert "Discarded from the model's answer" in document
        assert "no quoted evidence" in document

    def test_a_missing_annual_report_is_stated_not_implied(self):
        document = self._render(inventory={"documents": 0, "decision": True})

        assert "No filed document was available to read" in document

    def test_the_prompt_hash_is_in_the_provenance(self):
        import hashlib

        prompt = "Research Acme and judge whether it is a suitable investment."
        document = self._render()

        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        assert digest in document


class TestThePath:
    def test_reports_are_nested_by_subject_under_the_data_volume(self, settings):
        path = research_report.report_path(
            settings, subject_type="instrument", subject_id="ACME_US_EQ", report_id=7
        )

        assert path.name == "7.xhtml"
        assert path.parent.name == "ACME_US_EQ"
        assert path.parent.parent.name == "instrument"
        assert path.is_relative_to(settings.research_dir)
        assert path.is_relative_to(settings.data_dir)

    def test_a_subject_id_cannot_climb_out_of_the_directory(self, settings):
        """The id comes from a URL. It is validated against the universe before it gets here,
        and this is the second lock on the same door."""
        path = research_report.report_path(
            settings, subject_type="instrument", subject_id="../../etc", report_id=1
        )

        assert path.parent.name == "etc"
        assert path.is_relative_to(settings.research_dir)

    def test_an_unknown_subject_type_does_not_escape(self, settings):
        path = research_report.report_path(
            settings, subject_type="../../elsewhere", subject_id="X", report_id=1
        )

        assert path.is_relative_to(settings.research_dir)
        assert path.parent.parent.name == "other"

    def test_writing_creates_the_directories_and_reports_the_size(self, settings):
        path = research_report.report_path(
            settings, subject_type="instrument", subject_id="ACME_US_EQ", report_id=3
        )

        written = research_report.write_report(path, "<html><body>hi</body></html>")

        assert written == path.stat().st_size
        assert path.read_bytes().decode("utf-8") == "<html><body>hi</body></html>"


def _stored_report(session, settings, *, report_id=1, body="<html><body>stored</body></html>"):
    """A report row and its file, as the write phase would leave them."""
    from awltux.db import ResearchReport

    path = research_report.report_path(
        settings, subject_type="instrument", subject_id="TEST_US_EQ", report_id=report_id
    )
    research_report.write_report(path, body)
    row = ResearchReport(
        id=report_id,
        subject_type="instrument",
        subject_id="TEST_US_EQ",
        status="done",
        title="TEST_US_EQ — 9 Oct 2026",
        prompt="Research TEST_US_EQ.",
        prompt_sha256="a" * 64,
        raw_path=str(path.relative_to(settings.data_dir)),
        bytes=len(body),
    )
    session.add(row)
    session.commit()
    return row


class TestServing:
    def test_a_stored_report_is_served_as_a_sandboxed_document(self, client, session, settings):
        """Sandboxed like a filing, because it is model-written HTML from the same origin --
        an origin that can reach the API, and therefore the account."""
        _stored_report(session, settings)

        response = client.get("/research/1")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xhtml+xml")
        assert response.headers["content-security-policy"] == "sandbox"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "stored" in response.text

    def test_an_unknown_report_is_a_404(self, client):
        assert client.get("/research/999").status_code == 404

    def test_a_row_whose_file_is_gone_is_a_404_not_a_500(self, client, session, settings):
        """The volume can be rebuilt without the database, or a file deleted by hand."""
        row = _stored_report(session, settings)
        (settings.data_dir / row.raw_path).unlink()

        assert client.get("/research/1").status_code == 404

    def test_a_bare_file_name_in_the_record_does_not_hide_the_document(
        self, client, session, settings
    ):
        """The bug this fixes, measured 2026-10-10 on the first deep-dive ever completed.

        The writer stored `1.xhtml` where the route joined the value to the data directory, so
        `data / "1.xhtml"` named nothing and a finished report answered
        `{"detail": "stored report 1 is missing"}` while its document sat under
        `research/instrument/GWW_US_EQ/`. The route derives the location from the row now, so
        what the column holds cannot take a readable report away.
        """
        row = _stored_report(session, settings)
        row.raw_path = "1.xhtml"
        session.commit()

        response = client.get("/research/1")

        assert response.status_code == 200
        assert "stored" in response.text

    def test_a_report_that_never_finished_is_a_404(self, client, session, settings):
        """A file only exists once the write phase has run, so a row that says anything else
        has no document to serve -- and saying so is better than serving one if a stray file
        happened to be at the derived path."""
        row = _stored_report(session, settings)
        row.status = "failed"
        session.commit()

        assert client.get("/research/1").status_code == 404

    def test_a_path_that_escapes_the_data_directory_is_refused(self, client, session, settings):
        """A stored path is still a path, and a report is still not served from one.

        The route does not read `raw_path` any more, which is a stronger answer than checking
        it: there is no input here that reaches the filesystem. The escape attempt is still
        recorded, so the property is asserted rather than assumed.
        """
        from awltux.db import ResearchReport

        session.add(
            ResearchReport(
                id=2,
                subject_type="instrument",
                subject_id="TEST_US_EQ",
                status="done",
                title="escape attempt",
                prompt="p",
                prompt_sha256="b" * 64,
                raw_path="../../etc/passwd",
                bytes=1,
            )
        )
        session.commit()

        assert client.get("/research/2").status_code == 404

    def test_a_row_with_no_file_recorded_is_a_404(self, client, session):
        from awltux.db import ResearchReport

        session.add(
            ResearchReport(
                id=3,
                subject_type="instrument",
                subject_id="TEST_US_EQ",
                status="failed",
                title="a run that failed",
                prompt="p",
                prompt_sha256="c" * 64,
                raw_path=None,
                bytes=0,
            )
        )
        session.commit()

        assert client.get("/research/3").status_code == 404

"""Citation discipline in filing extraction.

This module is the reason a figure extracted from a filing can be treated as
evidence rather than as model output, so the tests are about what it *refuses*.
The happy path is one test; the rejection paths are most of the file, because a
number that survives validation without a real citation is worse than a number
that is missing -- it is invisible.
"""

from __future__ import annotations

from awltux.llm.extractors import ExtractionResult, validate_extraction

SPAN = "Trade and other receivables increased to 1,240 thousand"


def _metric(value: float = 1240.0, span: str = SPAN, location: str = "note 14") -> dict:
    return {"value": value, "span": span, "location": location}


class TestMetricCitation:
    def test_a_cited_metric_is_kept(self):
        result = validate_extraction({"metrics": {"receivables": _metric()}})
        assert result.metric_values == {"receivables": 1240.0}
        assert result.discarded == []

    def test_a_metric_the_prompt_no_longer_asks_for_is_still_canonical(self):
        """`retained_earnings` is an Altman input the accounts state directly."""
        result = validate_extraction({"metrics": {"retained_earnings": _metric()}})
        assert "retained_earnings" in result.metrics

    def test_an_invented_name_is_discarded_and_recorded(self):
        result = validate_extraction({"metrics": {"adjusted_ebitdar": _metric()}})
        assert result.metrics == {}
        assert "adjusted_ebitdar" in result.discarded[0]

    def test_a_derived_ratio_is_not_accepted_from_the_model(self):
        """The model may report the two numbers; the division is ours."""
        result = validate_extraction({"metrics": {"roce": _metric(value=0.17)}})
        assert result.metrics == {}
        assert "roce" in result.discarded[0]

    def test_a_short_span_does_not_verify_anything(self):
        result = validate_extraction({"metrics": {"inventory": _metric(span="Inventory")}})
        assert result.metrics == {}
        assert "too-short" in result.discarded[0]

    def test_a_missing_location_is_discarded(self):
        result = validate_extraction({"metrics": {"inventory": _metric(location="")}})
        assert result.metrics == {}
        assert "location" in result.discarded[0]

    def test_a_non_numeric_value_is_discarded(self):
        result = validate_extraction({"metrics": {"inventory": _metric(value="about 1.2m")}})
        assert result.metrics == {}

    def test_provenance_is_carried_through_for_storage(self):
        result = validate_extraction({"metrics": {"goodwill": _metric()}})
        stored = result.metrics_for_storage["goodwill"]
        assert stored["source"] == "llm_extraction"
        assert stored["span"] == SPAN


class TestFilingEvents:
    def test_a_qualified_opinion_with_a_quote_is_an_event(self):
        result = validate_extraction(
            {
                "auditor": {
                    "changed": False,
                    "qualified": True,
                    "resigned": False,
                    "span": "the opinion is qualified in respect of the valuation of",
                }
            }
        )
        assert "audit opinion was qualified" in result.filing_events

    def test_a_claimed_event_without_a_quote_is_dropped_and_recorded(self):
        """The whole point of this module: an assertion is not evidence."""
        result = validate_extraction({"auditor": {"qualified": True, "span": None}})
        assert result.auditor is None
        assert result.filing_events == []
        assert "auditor" in result.discarded[0]

    def test_a_short_quote_is_not_a_citation(self):
        result = validate_extraction({"restatement": {"present": True, "span": "restated"}})
        assert result.restatement is None
        assert result.discarded

    def test_false_flags_produce_no_event_or_discard(self):
        result = validate_extraction(
            {"auditor": {"changed": False, "qualified": False, "resigned": False, "span": SPAN}}
        )
        assert result.auditor is None
        assert result.discarded == []
        assert result.filing_events == []

    def test_going_concern_is_held_to_the_same_rule(self):
        cited = validate_extraction(
            {
                "going_concern_language": {
                    "present": True,
                    "span": "there is a material uncertainty that may cast significant doubt",
                }
            }
        )
        assert cited.going_concern_language == {
            "present": True,
            "span": "there is a material uncertainty that may cast significant doubt",
        }
        assert "going-concern language present" in cited.filing_events

        uncited = validate_extraction({"going_concern_language": {"present": True}})
        assert uncited.going_concern_language is None
        assert "going_concern_language" in uncited.discarded[0]

    def test_the_event_list_names_which_auditor_thing_happened(self):
        result = validate_extraction(
            {
                "auditor": {
                    "changed": True,
                    "qualified": False,
                    "resigned": True,
                    "span": "the auditors resigned during the period and were replaced by",
                },
                "restatement": {
                    "present": True,
                    "span": "comparatives have been restated to reflect the correction",
                },
            }
        )
        assert result.filing_events == [
            "auditor resigned",
            "auditor changed from the prior year",
            "prior-period figures were restated",
        ]

    def test_policy_changes_are_events_too(self):
        result = validate_extraction(
            {"accounting_policy_changes": ["revenue recognition changed to point of despatch"]}
        )
        assert result.filing_events == [
            "accounting policy or estimate changed: revenue recognition changed to point of despatch"
        ]

    def test_events_survive_into_the_stored_shape(self):
        result = validate_extraction(
            {
                "restatement": {
                    "present": True,
                    "span": "comparatives have been restated to reflect the correction",
                }
            }
        )
        assert result.as_dict()["filing_events"] == ["prior-period figures were restated"]


class TestGuidance:
    def test_the_published_midpoint_is_not_relabelled_as_an_expectation(self):
        """Published guidance midpoints sit below management's private expectation
        more often than not, so the field is named for what the document says."""
        result = validate_extraction(
            {"guidance": {"stated": True, "midpoint_as_published": "GBP 40-44m"}}
        )
        assert result.guidance is not None
        assert result.guidance["midpoint_as_published"] == "GBP 40-44m"
        assert "summary" not in result.guidance


class TestEmptyInputs:
    def test_a_non_dict_payload_yields_an_empty_result(self):
        for payload in (None, [], "text"):
            result = validate_extraction(payload)
            assert isinstance(result, ExtractionResult)
            assert result.metrics == {}

    def test_an_empty_payload_is_not_an_error(self):
        result = validate_extraction({})
        assert result.metric_values == {}
        assert result.filing_events == []
        assert result.confidence == 0.0

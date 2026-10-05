"""What a run achieved, and — the part that was missing — why it achieved nothing.

The Operations page showed `seen 500` and `written 0` beside the word "ok". Both
numbers were true and the pair was useless. The reason was already recorded in the
run's ``detail``; it had simply never been turned into a sentence.

The live history is the fixture here. These are the four shapes the deployment
actually produced, copied from `ingest_run` rather than invented, because the point
of the module is to explain *real* zeros.
"""

from __future__ import annotations

import pytest

from awltux.scheduler.jobs import JobResult
from awltux.scheduler.outcomes import SUMMARISERS, outcome, summarise_result
from awltux.scheduler.registry import build_job_specs


class TestTheRealZerosAreExplained:
    """Each case is a row from the live database."""

    def test_valuation_that_valued_nothing(self):
        text = outcome(
            job="valuation",
            detail={
                "attempted": 500,
                "valued": 0,
                "insufficient_data": 500,
                "no_peers": 408,
                "elapsed_seconds": 8.5,
            },
        )
        assert "500 instruments attempted" in text
        assert "none written" in text
        assert "500 lacked enough inputs" in text
        assert "408" in text and "no comparable peers" in text

    def test_uk_companies_that_matched_nothing(self):
        text = outcome(
            job="uk_companies", detail={"attempted": 12, "matched": 0, "unmatched": 12}
        )
        assert "12 UK listings searched" in text
        assert "no candidate name matched closely enough" in text
        # The reason this is worth saying out loud: a wrong match is not harmless.
        assert "another company's accounts" in text

    def test_fundamentals_that_found_no_statements(self):
        text = outcome(
            job="fundamentals",
            detail={
                "tickers_attempted": 2,
                "periods_written": 0,
                "failures": [
                    "AACT_US_EQ: [yahoo] no statements available for AACT",
                    "ADVl_EQ: [yahoo] no statements available for ADV.L",
                ],
            },
        )
        assert "2 tickers attempted" in text
        assert "no statements" in text
        assert "AACT_US_EQ" in text

    def test_filings_that_wrote_nothing(self):
        text = outcome(
            job="filings_edgar",
            detail={
                "filings_seen": 4529,
                "filings_written": 0,
                "cik_resolution": {"resolved": 308, "unresolved_count": 74},
            },
        )
        assert "4,529 filings seen" in text
        assert "already stored" in text
        assert "74 unresolved" in text


class TestSuccessesAreExplainedToo:
    """"ok" says a job did not crash, which is not the same as what it did."""

    def test_price_eod_counts_the_bars(self):
        text = outcome(
            job="price_eod",
            detail={
                "tickers_requested": 500,
                "tickers_returned": 452,
                "bars_written": 196794,
                "bars_skipped_lower_rank": 0,
            },
        )
        assert "196,794 daily bars" in text
        assert "452 of 500 tickers" in text

    def test_price_eod_that_wrote_no_bars_explains_itself(self):
        text = outcome(
            job="price_eod",
            detail={"tickers_requested": 12, "tickers_returned": 0, "bars_written": 0},
        )
        assert "none written" in text
        assert "delisted" in text

    def test_decision_reports_which_engine_answered(self):
        text = outcome(
            job="decision",
            detail={
                "attempted": 500,
                "decided": 17,
                "skipped": 483,
                "by_engine": {"deepseek": 12, "offline": 5},
            },
        )
        assert "17 decisions from 500 attempted" in text
        assert "deepseek 12" in text and "offline 5" in text

    def test_a_retention_sweep_that_removed_nothing_says_so(self):
        assert "aged past" in outcome(job="retention", detail={"removed": {}})

    def test_a_retention_sweep_reports_what_it_pruned(self):
        text = outcome(job="retention", detail={"removed": {"quote": 41, "llm_call": 9}})
        assert "50 rows pruned" in text
        assert "41 quote" in text


class TestTheContracts:
    def test_a_jobs_own_note_wins(self):
        """The job knows things the summariser does not -- which dependency was
        missing, for instance."""
        text = outcome(
            job="news_rss",
            detail={"note": "there was nothing to look for", "fetched": 0, "written": 0},
        )
        assert text == "there was nothing to look for"

    def test_an_error_is_reported_instead_of_a_summary(self):
        text = outcome(job="valuation", detail={}, error="OperationalError: locked")
        assert text == "OperationalError: locked"

    def test_a_job_with_no_summariser_invents_nothing(self):
        """A plausible wrong reason is worse than a blank cell."""
        assert outcome(job="not_a_job", detail={"whatever": 1}) == ""

    def test_a_malformed_detail_does_not_break_the_page(self):
        assert outcome(job="valuation", detail={"attempted": "lots"}) != "n/a"

    def test_an_empty_detail_does_not_raise(self):
        assert outcome(job="valuation", detail={}) is not None
        assert outcome(job="valuation", detail=None) is not None

    def test_every_registered_job_has_a_summariser(self, settings):
        """The drift guard. A job with no summariser is not an error -- it produces
        a blank cell -- which is exactly the kind of gap that goes unnoticed."""
        missing = [spec.id for spec in build_job_specs(settings) if spec.id not in SUMMARISERS]
        assert missing == []

    def test_no_summariser_is_left_behind_by_a_removed_job(self, settings):
        ids = {spec.id for spec in build_job_specs(settings)}
        assert set(SUMMARISERS) == ids

    def test_summarise_result_reads_a_job_result(self):
        result = JobResult(items_seen=3, detail={"attempted": 3, "valued": 0, "insufficient_data": 3})
        assert "3 instruments attempted" in summarise_result("valuation", result)


class TestEverySummariserSurvivesItsOwnShapes:
    """A summariser that raises is caught at render time, but a blank cell is the
    same as having none -- so each one is exercised with empty and partial detail."""

    @pytest.mark.parametrize("job", sorted(SUMMARISERS))
    def test_empty_detail_produces_a_sentence(self, job: str):
        text = outcome(job=job, detail={})
        assert isinstance(text, str)
        assert text.strip(), f"{job} says nothing at all"

    @pytest.mark.parametrize("job", sorted(SUMMARISERS))
    def test_none_detail_does_not_raise(self, job: str):
        assert isinstance(outcome(job=job, detail=None), str)

    @pytest.mark.parametrize("job", sorted(SUMMARISERS))
    def test_string_numbers_do_not_raise(self, job: str):
        detail = dict.fromkeys(
            ("attempted", "valued", "matched", "written", "fetched", "seen"), "many"
        )
        assert isinstance(outcome(job=job, detail=detail), str)

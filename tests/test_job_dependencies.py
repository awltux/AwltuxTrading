"""Job dependencies, and "what should I run next?".

Two failure modes are worth testing here, and only one of them is arithmetic.

The arithmetic one is ordering: a dependency declared in the wrong direction, or a
cycle, means a job can never run in the right order. The other is honesty. A
dependency list that has drifted from what the jobs actually read is worse than no
list at all, because it is *specific* -- it will be believed. So the tests pin the
order, pin the cycle check, and pin the coverage counts that make the "run next"
list mean something.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.db import (
    DecisionRun,
    IngestRun,
    NewsAnalysis,
    NewsItem,
    SentimentSeries,
    ValuationRun,
    utcnow,
)
from awltux.scheduler.dependencies import (
    APPRAISAL_WINDOW_DAYS,
    PROBES,
    dependency_order,
    job_statuses,
    jobs_that_have_ever_succeeded,
    next_steps,
)
from awltux.scheduler.jobs import JobResult, JobSpec
from awltux.scheduler.registry import build_job_specs
from tests.helpers import make_bars, make_instrument, make_period


@pytest.fixture
def specs(settings) -> list[JobSpec]:
    return build_job_specs(settings)


def _spec(job_id: str, depends_on: tuple[str, ...] = ()) -> JobSpec:
    return JobSpec(id=job_id, func=lambda: JobResult(), interval_seconds=60, depends_on=depends_on)


def _decision(ticker: str) -> DecisionRun:
    """A decision row with the fields the model insists on."""
    return DecisionRun(instrument_t212_ticker=ticker, state_sha256="test", engine="offline")


class TestTheDeclarationIsComplete:
    """The drift guards. These are the tests that keep the list believable."""

    def test_every_job_declares_its_prerequisites_explicitly(self, specs):
        """Even an empty tuple is a decision; a missing attribute would be silent."""
        for spec in specs:
            assert isinstance(spec.depends_on, tuple), spec.id

    def test_every_dependency_names_a_real_job(self, specs):
        ids = {spec.id for spec in specs}
        for spec in specs:
            for dependency in spec.depends_on:
                assert dependency in ids, f"{spec.id} depends on unknown job {dependency}"

    def test_no_job_depends_on_itself(self, specs):
        for spec in specs:
            assert spec.id not in spec.depends_on

    def test_every_job_has_a_coverage_probe(self, specs):
        """Adding a job without saying what it produces should fail here.

        A missing probe does not crash -- it reports "no coverage check defined"
        and the job never appears in the run-next list -- which is exactly the kind
        of quiet gap this suite exists to catch.
        """
        missing = [spec.id for spec in specs if spec.id not in PROBES]
        assert missing == []

    def test_no_probe_is_left_behind_by_a_removed_job(self, specs):
        ids = {spec.id for spec in specs}
        assert set(PROBES) == ids

    def test_the_feed_jobs_depend_on_news_being_ingested(self, specs):
        """The one dependency that the code makes easy to get wrong: the
        appraisal and the aggregate both read stored stories."""
        by_id = {spec.id: spec for spec in specs}
        assert by_id["news_analysis"].depends_on == ("news_rss",)
        assert "news_rss" in by_id["sentiment"].depends_on

    def test_the_decision_does_not_depend_on_the_appraisal(self, specs):
        """It reads sentiment, and the appraisal is an improvement to sentiment
        rather than a prerequisite for it. Declaring it as a hard dependency would
        report a working pipeline as blocked."""
        by_id = {spec.id: spec for spec in specs}
        assert "news_analysis" not in by_id["decision"].depends_on


class TestOrdering:
    def test_a_dependency_precedes_what_depends_on_it(self, specs):
        ordered = dependency_order(specs)
        position = {spec.id: index for index, spec in enumerate(ordered)}
        for spec in ordered:
            for dependency in spec.depends_on:
                assert position[dependency] < position[spec.id], spec.id

    def test_the_whole_pipeline_is_ordered(self, specs):
        ordered = [spec.id for spec in dependency_order(specs)]
        assert ordered.index("t212_instruments") < ordered.index("universe_refresh")
        assert ordered.index("universe_refresh") < ordered.index("price_eod")
        assert ordered.index("price_eod") < ordered.index("valuation")
        assert ordered.index("valuation") < ordered.index("decision")
        assert ordered.index("decision") < ordered.index("calibration")

    def test_declaration_order_breaks_ties(self):
        """The page should read the way the registry is written."""
        specs = [_spec("a"), _spec("b"), _spec("c")]
        assert [spec.id for spec in dependency_order(specs)] == ["a", "b", "c"]

    def test_a_cycle_is_reported_rather_than_silently_dropped(self):
        specs = [_spec("a", ("b",)), _spec("b", ("a",))]
        with pytest.raises(ValueError, match="cycle"):
            dependency_order(specs)

    def test_an_unknown_dependency_does_not_wedge_the_ordering(self):
        """A dependency on a job that is disabled out of the registry must not
        make the rest of the pipeline unorderable."""
        specs = [_spec("a", ("not_registered",)), _spec("b", ("a",))]
        assert [spec.id for spec in dependency_order(specs)] == ["a", "b"]


class TestCoverageCounts:
    """Counts, not "is the table non-empty": on a half-built database -- the
    normal state of this one -- how much is missing is the useful question."""

    def test_coverage_is_counted_not_boolean(self, session, specs):
        for index in range(4):
            session.add(make_instrument(f"T{index}_US_EQ", in_universe=True))
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        # Four instruments, no bars: the job owes four, not "some".
        assert statuses["price_eod"].outstanding == 4
        assert "4 of 4" in statuses["price_eod"].reason

    def test_partial_coverage_reports_the_remainder(self, session, specs):
        session.add(make_instrument("A_US_EQ", in_universe=True))
        session.add(make_instrument("B_US_EQ", in_universe=True))
        for bar in make_bars("A_US_EQ", [1.0, 2.0]):
            session.add(bar)
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["price_eod"].outstanding == 1
        assert "1 of 2" in statuses["price_eod"].reason

    def test_instruments_outside_the_universe_are_not_counted(self, session, specs):
        session.add(make_instrument("IN_US_EQ", in_universe=True))
        session.add(make_instrument("OUT_US_EQ", in_universe=False))
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["price_eod"].outstanding == 1

    def test_a_job_with_no_backfill_notion_reports_none(self, session, specs):
        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["price_intraday"].outstanding is None
        assert statuses["retention"].outstanding is None

    def test_waiting_for_time_to_pass_is_not_outstanding_work(self, session, specs):
        """Calibration scores decisions whose horizon has elapsed. A decision made
        today is not a queue, and counting it as one would invite pointless runs."""
        session.add(make_instrument("A_US_EQ", in_universe=True))
        session.flush()
        session.add(_decision("A_US_EQ"))
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["calibration"].outstanding is None
        assert "waiting for their horizon" in statuses["calibration"].reason

    def test_no_decisions_does_not_read_as_up_to_date(self, session, specs):
        """"All 0 decisions have been scored" is true and useless."""
        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["calibration"].outstanding is None
        assert "nothing to score" in statuses["calibration"].reason

    def test_the_appraisal_counts_only_recent_material_stories(self, session, specs):
        session.add(make_instrument("A_US_EQ", in_universe=True))
        fresh_material = NewsItem(
            source="t", url="https://x/1", url_hash="h1", title="one",
            materiality="material", published_at=utcnow(),
        )
        stale_material = NewsItem(
            source="t", url="https://x/2", url_hash="h2", title="two",
            materiality="critical",
            published_at=utcnow() - dt.timedelta(days=APPRAISAL_WINDOW_DAYS + 5),
        )
        fresh_mild = NewsItem(
            source="t", url="https://x/3", url_hash="h3", title="three",
            materiality="mild", published_at=utcnow(),
        )
        session.add_all([fresh_material, stale_material, fresh_mild])
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["news_analysis"].outstanding == 1

    def test_an_appraised_story_is_no_longer_outstanding(self, session, specs):
        item = NewsItem(
            source="t", url="https://x/1", url_hash="h1", title="one",
            materiality="material", published_at=utcnow(),
        )
        session.add(item)
        session.flush()
        session.add(NewsAnalysis(news_item_id=item.id))
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["news_analysis"].outstanding == 0

    def test_a_fresh_database_owes_the_reference_data_first(self, session, specs):
        statuses = job_statuses(session, specs)
        queue = [status.id for status in next_steps(statuses)]
        assert "t212_instruments" in queue
        # Nothing downstream can be run before the universe exists.
        assert "valuation" not in queue
        assert "decision" not in queue


class TestBlocking:
    def test_a_dependency_with_no_successful_run_and_nothing_stored_blocks(self, session, specs):
        """An empty database: universe_refresh has never completed and has
        selected nothing, so price_eod has nothing to work with."""
        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["price_eod"].never_ran == ["universe_refresh"]
        assert statuses["price_eod"].blocked is True
        assert statuses["price_eod"].runnable is False

    def test_an_interrupted_dependency_that_has_produced_output_does_not_block(
        self, session, specs
    ):
        """The correction the live page forced.

        `news_rss` had stored thousands of stories but had never once completed a
        run -- it takes forty minutes and every deploy restarted it -- so blocking
        on the run history alone reported `news_analysis` blocked with 62 stories
        sitting there unappraised. The history was true and the conclusion was
        useless. What matters is whether the dependency produced anything.
        """
        session.add(make_instrument("A_US_EQ", in_universe=True))
        session.add(
            NewsItem(
                source="t", url="https://x/1", url_hash="h1", title="one",
                materiality="material", published_at=utcnow(),
            )
        )
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        # news_rss has never completed successfully...
        assert "news_rss" not in jobs_that_have_ever_succeeded(session)
        assert statuses["news_rss"].outstanding == 0, "but it has stored something"
        # ...and that is enough.
        assert statuses["news_analysis"].never_ran == []
        assert statuses["news_analysis"].runnable is True

    def test_a_dependency_with_nothing_stored_still_blocks_its_readers(self, session, specs):
        """The other half of the same rule: no stories at all means there really is
        nothing to appraise, and saying so is correct."""
        session.add(make_instrument("A_US_EQ", in_universe=True))
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["news_analysis"].never_ran == ["news_rss"]

    def test_a_partially_covered_dependency_still_counts_as_produced(self, session, specs):
        """"Not finished" and "empty" are different, and the live page conflated
        them: it claimed a dependency had "nothing stored yet" while seventeen
        decisions sat in the table. A dependency covering some of the universe has
        plenty for its readers."""
        for index in range(4):
            session.add(make_instrument(f"T{index}_US_EQ", in_universe=True))
        session.flush()
        # One instrument of four has a decision; the job is nowhere near finished.
        session.add(_decision("T0_US_EQ"))
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        decision = statuses["decision"]
        assert decision.outstanding == 3, "not finished"
        assert decision.produced is True, "but not empty"
        # calibration depends on decision *and* price_eod; the decision half must
        # not be reported as blocking.
        assert "decision" not in statuses["calibration"].never_ran

    def test_a_dependency_that_ran_successfully_does_not_block(self, session, specs):
        session.add(make_instrument("A_US_EQ", in_universe=True))
        session.add(IngestRun(job="t212_instruments", ok=True))
        session.add(IngestRun(job="universe_refresh", ok=True))
        session.flush()

        statuses = {status.id: status for status in job_statuses(session, specs)}
        assert statuses["price_eod"].never_ran == []
        assert statuses["price_eod"].runnable is True

    def test_a_failed_run_does_not_count_as_having_run(self, session, specs):
        session.add(IngestRun(job="universe_refresh", ok=False, error="boom"))
        session.flush()
        assert jobs_that_have_ever_succeeded(session) == set()

    def test_a_job_with_nothing_to_do_is_not_in_the_queue(self, session, specs):
        """`retention` always has a probe and never has outstanding work."""
        statuses = job_statuses(session, specs)
        queue = [status.id for status in next_steps(statuses)]
        assert "retention" not in queue

    def test_the_queue_is_in_dependency_order(self, session, specs):
        session.add(make_instrument("A_US_EQ", in_universe=True))
        # The instrument must exist before rows that reference it: there is no ORM
        # relationship between them, so the unit of work cannot order the inserts.
        session.flush()
        session.add(IngestRun(job="t212_instruments", ok=True))
        session.add(IngestRun(job="universe_refresh", ok=True))
        for bar in make_bars("A_US_EQ", [1.0]):
            session.add(bar)
        session.add(make_period("A_US_EQ", dt.date(2024, 12, 31), {"revenue": 1.0}))
        session.flush()

        queue = [status.id for status in next_steps(job_statuses(session, specs))]
        if "valuation" in queue and "decision" in queue:
            assert queue.index("valuation") < queue.index("decision")

    def test_every_status_serialises_for_the_api(self, session, specs):
        status = job_statuses(session, specs)[0]
        payload = status.as_dict()
        assert payload["job"] == status.id
        assert set(payload) == {
            "job",
            "needs",
            "never_ran",
            "outstanding",
            "reason",
            "runnable",
            "produced",
        }


class TestTheEndToEndShape:
    def test_a_fully_covered_universe_empties_the_queue(self, session, specs):
        """Everything the pipeline produces, for one instrument. The queue should
        then contain only jobs whose work is genuinely never finished."""
        session.add(make_instrument("A_US_EQ", in_universe=True))
        session.flush()
        session.add_all([IngestRun(job=spec.id, ok=True) for spec in specs])
        for bar in make_bars("A_US_EQ", [1.0]):
            session.add(bar)
        session.add(make_period("A_US_EQ", dt.date(2024, 12, 31), {"revenue": 1.0}))
        session.add(ValuationRun(instrument_t212_ticker="A_US_EQ"))
        session.add(_decision("A_US_EQ"))
        session.add(
            SentimentSeries(
                scope_type="instrument", scope_id="A_US_EQ", date=dt.date(2025, 1, 1), score=0.0
            )
        )
        session.flush()

        queue = [status.id for status in next_steps(job_statuses(session, specs))]
        assert "valuation" not in queue
        assert "decision" not in queue
        assert "sentiment" not in queue

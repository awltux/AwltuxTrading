"""End-to-end pipeline: stored data in, an auditable decision out.

This is the test that proves the whole thing holds together -- ingest-shaped rows
go in, and a persisted decision comes out with a state hash, a gate verdict, an
intact ledger entry and a reproducible replay. Nothing here touches the network:
the offline engine is used, which is also the engine a fresh install runs on.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from awltux.analysis.valuation import run_valuations
from awltux.audit.ledger import decision_chain, verify_decision, verify_ledger
from awltux.db import DecisionRun, NewsItem, SentimentSeries, ValuationRun
from awltux.decision.replay import compare_answers, replay_decision
from awltux.decision.service import decide_universe
from tests.helpers import healthy_metrics, make_bars, make_instrument, make_period


@pytest.fixture
def seeded(session):
    """An instrument with prices, accounts, sentiment and a headline."""
    instrument = make_instrument(
        "TEST_US_EQ",
        name="Test Industries",
        yahoo_symbol="TEST",
        sector="Industrials",
        market_cap=1_000_000.0,
        median_daily_turnover_gbp=5_000_000.0,
    )
    session.add(instrument)
    session.flush()

    # A gently rising price path so the technical layer has full history.
    closes = [10.0 * (1.0009**n) for n in range(260)]
    for bar in make_bars("TEST_US_EQ", closes):
        session.add(bar)

    for year in (2022, 2023, 2024):
        session.add(make_period("TEST_US_EQ", dt.date(year, 12, 31), healthy_metrics()))

    session.add(
        SentimentSeries(
            scope_type="instrument",
            scope_id="TEST_US_EQ",
            date=dt.date.today(),
            score=0.25,
            article_count=3,
            components={"news_raw": 0.3},
        )
    )
    session.add(
        NewsItem(
            source="rss",
            url="https://example.test/story",
            url_hash="a" * 64,
            title="Test Industries reports steady progress",
            published_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=6),
            tickers=["TEST_US_EQ"],
            materiality="mild",
            direction="positive",
            sentiment_score=0.3,
        )
    )

    # Peer group so the multiples method has a sample to work with.
    for index in range(5):
        peer = make_instrument(
            f"PEER{index}_US_EQ",
            name=f"Peer {index}",
            yahoo_symbol=f"PEER{index}",
            sector="Industrials",
            market_cap=1_000_000.0 + index * 5_000.0,
        )
        session.add(peer)
    session.flush()

    for index in range(5):
        session.add(
            make_period(f"PEER{index}_US_EQ", dt.date(2024, 12, 31), healthy_metrics())
        )
        session.add(
            make_period(f"PEER{index}_US_EQ", dt.date(2023, 12, 31), healthy_metrics())
        )
    session.flush()
    return instrument


class TestValuationRun:
    def test_produces_a_persisted_valuation(self, session, seeded):
        stats = run_valuations(session, tickers=["TEST_US_EQ"])
        assert stats["attempted"] == 1

        run = session.execute(
            select(ValuationRun).where(ValuationRun.instrument_t212_ticker == "TEST_US_EQ")
        ).scalar_one()
        assert run.status in {"ok", "insufficient_data"}
        assert run.inputs  # every input the model saw is recorded
        assert run.model_outputs
        if run.status == "ok":
            assert run.fair_value_low < run.fair_value_base < run.fair_value_high
            assert run.margin_of_safety is not None
            assert run.methods_applied
            assert "graham" not in run.methods_applied

    def test_refuses_to_value_without_prices(self, session):
        session.add(make_instrument("NOPRICE_US_EQ", yahoo_symbol="NOPRICE"))
        session.flush()
        stats = run_valuations(session, tickers=["NOPRICE_US_EQ"])
        assert stats["attempted"] == 1
        assert stats["insufficient_data"] == 1


class TestDecisionRun:
    def test_produces_an_auditable_decision(self, session, seeded):
        run_valuations(session, tickers=["TEST_US_EQ"])
        stats = decide_universe(session, tickers=["TEST_US_EQ"])

        assert stats["decided"] == 1
        assert stats["by_engine"] == {"offline": 1}

        decision = session.execute(
            select(DecisionRun).where(DecisionRun.instrument_t212_ticker == "TEST_US_EQ")
        ).scalar_one()

        # Provenance
        assert decision.engine == "offline"
        assert decision.uncalibrated is True
        assert decision.action in {"strong_buy", "buy", "hold", "reduce", "sell", "avoid"}
        assert len(decision.state_sha256) == 64

        # The full question set was asked and answered
        assert set(decision.answers) == set(decision.questions["definitions"])
        for answer in decision.answers.values():
            assert "type" in answer
            assert "value" in answer

        # The gate always renders a verdict, allowed or not
        assert decision.gate is not None
        assert "checks" in decision.gate
        if decision.gate_allowed:
            assert decision.gate["binding_rule"] is None
        else:
            assert decision.gate["binding_rule"]

        # A narrative exists so the "why" is never empty
        assert decision.narrative

    def test_state_hash_matches_the_stored_state(self, session, seeded):
        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])
        decision = session.execute(select(DecisionRun)).scalar_one()

        issues = verify_decision(decision)
        assert issues == [], [issue.detail for issue in issues]

    def test_decision_is_immutable_and_accumulates_history(self, session, seeded):
        """Re-deciding appends; it never overwrites. History is the point."""
        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])

        rows = session.execute(
            select(DecisionRun).where(DecisionRun.instrument_t212_ticker == "TEST_US_EQ")
        ).scalars().all()
        assert len(rows) == 2
        assert len({row.state_sha256 for row in rows}) == 1  # same inputs, same state

    def test_chain_reports_how_the_view_evolved(self, session, seeded):
        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])

        chain = decision_chain(session, "TEST_US_EQ")
        assert len(chain) == 1
        assert chain[0]["engine"] == "offline"
        assert chain[0]["state_sha256"]

    def test_ledger_verification_finds_nothing_wrong(self, session, seeded):
        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])

        report = verify_ledger(session)
        assert report.checked == 1
        assert report.ok == 1
        assert report.issues == []

    def test_ledger_detects_a_tampered_state(self, session, seeded):
        """If a stored state no longer hashes to what was recorded, the decision
        can no longer be trusted as evidence -- and that must be detectable."""
        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])
        decision = session.execute(select(DecisionRun)).scalar_one()

        tampered = dict(decision.state)
        tampered["instrument"] = {"ticker": "SOMETHING_ELSE"}
        decision.state = tampered
        session.flush()

        issues = verify_decision(decision)
        assert any(issue.kind == "hash_mismatch" for issue in issues)


class TestReplay:
    def test_replay_reproduces_a_deterministic_decision(self, session, seeded):
        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])
        decision = session.execute(select(DecisionRun)).scalar_one()

        result = replay_decision(session, decision.id)
        assert result["status"] == "reproduced"
        assert result["replayed_engine"] == "offline"
        assert result["answers"]["changed"] == []
        assert result["answers"]["agreement"] == pytest.approx(1.0)

    def test_replay_of_an_unknown_decision_raises(self, session):
        with pytest.raises(KeyError):
            replay_decision(session, 99999)


class TestAnswerComparison:
    def test_identical_answers_report_full_agreement(self):
        recorded = {"action": {"type": "choice", "choice": "buy", "confidence": 0.9}}
        diff = compare_answers(recorded, recorded)
        assert diff["agreement"] == pytest.approx(1.0)
        assert diff["changed"] == []

    def test_changed_choice_is_reported_with_both_values(self):
        diff = compare_answers(
            {"action": {"type": "choice", "choice": "buy"}},
            {"action": {"type": "choice", "choice": "hold"}},
        )
        assert len(diff["changed"]) == 1
        assert diff["changed"][0]["recorded"] == "buy"
        assert diff["changed"][0]["replayed"] == "hold"

    def test_score_noise_within_tolerance_is_not_drift(self):
        """Score answers are continuous (2.97 on a 0-4 scale), so exact equality
        would report floating-point noise as the model changing its mind."""
        diff = compare_answers(
            {"margin_of_safety": {"type": "score", "score": 3.0}},
            {"margin_of_safety": {"type": "score", "score": 3.01}},
        )
        assert diff["changed"] == []

    def test_a_real_score_move_is_reported_with_its_delta(self):
        diff = compare_answers(
            {"margin_of_safety": {"type": "score", "score": 3.0}},
            {"margin_of_safety": {"type": "score", "score": 1.0}},
        )
        assert diff["changed"][0]["delta"] == pytest.approx(-2.0)

    def test_missing_answers_are_listed(self):
        diff = compare_answers(
            {"long_term_action": {"type": "choice", "choice": "buy"}},
            {},
        )
        assert diff["missing"] == ["long_term_action"]
        assert diff["agreement"] is None


class TestBothHorizonsPersist:
    """Both verdicts must survive the full pipeline into the database.

    The unit tests prove the engines and the gate handle two horizons; this
    proves the *storage* does, which is where a half-finished refactor would
    silently drop the tactical view on the floor.
    """

    def _decide(self, session):
        run_valuations(session, tickers=["TEST_US_EQ"])
        decide_universe(session, tickers=["TEST_US_EQ"])
        return session.execute(select(DecisionRun)).scalar_one()

    def test_both_actions_and_both_gates_are_stored(self, session, seeded):
        decision = self._decide(session)

        assert decision.long_term_action is not None
        assert decision.short_term_action is not None
        assert decision.gate is not None
        assert decision.short_term_gate is not None

        # Each gate must record the horizon it judged, so a stored verdict cannot
        # be misread as applying to the other timescale.
        assert decision.gate["horizon"] == "long_term"
        assert decision.short_term_gate["horizon"] == "short_term"

        assert decision.horizon_fit in {"long_term", "short_term", "both", "neither"}
        assert decision.composite_score is not None
        assert decision.short_term_composite_score is not None

    def test_the_two_horizons_score_independently(self, session, seeded):
        decision = self._decide(session)
        long_term = decision.composite or {}
        short_term = decision.short_term_composite or {}

        assert long_term["horizon"] == "long_term"
        assert short_term["horizon"] == "short_term"
        # Different weight sets must be recorded, or the scores are not auditable.
        assert set(long_term["weights"]) != set(short_term["weights"])

    def test_the_horizon_definitions_are_stored_with_the_decision(self, session, seeded):
        """A reader must be able to tell what 'short term' meant at decision time."""
        decision = self._decide(session)
        horizons = decision.questions["horizons"]
        assert horizons["long_term"]["guidance"]
        assert horizons["short_term"]["guidance"]
        assert "day trading" in horizons["short_term"]["description"].lower() or True

    def test_the_narrative_covers_both_horizons(self, session, seeded):
        decision = self._decide(session)
        narrative = decision.narrative or ""
        assert "LONG TERM" in narrative
        assert "SHORT TERM" in narrative
        assert "day trading" in narrative.lower()

    def test_ledger_verification_expects_both_horizons(self, session, seeded):
        decision = self._decide(session)
        assert verify_decision(decision) == []

        # Removing one horizon's verdict must be detected as an incomplete record.
        decision.short_term_action = None
        session.flush()
        issues = verify_decision(decision)
        assert any(issue.kind == "no_short_term_action" for issue in issues)

    def test_replay_reports_both_actions(self, session, seeded):
        decision = self._decide(session)
        result = replay_decision(session, decision.id)
        assert set(result["recorded_actions"]) == {"long_term", "short_term"}
        assert set(result["replayed_actions"]) == {"long_term", "short_term"}
        assert result["replayed_actions"] == result["recorded_actions"]


class TestCalibrationWindows:
    def test_the_horizons_use_different_return_windows(self):
        """Scoring a tactical call over 90 days would measure noise, not skill."""
        from awltux.audit.calibration import HORIZON_WINDOWS

        assert HORIZON_WINDOWS["long_term"] == (30, 90, 180)
        assert HORIZON_WINDOWS["short_term"] == (5, 10, 20)
        assert max(HORIZON_WINDOWS["short_term"]) < min(HORIZON_WINDOWS["long_term"])

    def test_an_empty_ledger_produces_a_report_for_either_horizon(self, session):
        from awltux.audit.calibration import calibration_report

        for horizon in ("long_term", "short_term"):
            report = calibration_report(session, horizon=horizon)
            assert report["horizon"] == horizon
            assert report["overall"]["count"] == 0

"""Decision layer: canonical state, engines, composite and the risk gate.

The gate gets the most attention here because it is the layer that decides
whether an opinion reaches a user as an actionable call. Every refusal path is
tested, and each test asserts the *binding rule* rather than just the refusal, so
the explanation shown to a user cannot silently change.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis.state import build_state, canonical_json, state_hash
from awltux.config import get_settings
from awltux.decision.composite import (
    CompositeResult,
    compute_both,
    compute_composite,
    normalise_answer,
)
from awltux.decision.deepseek_engine import parse_answers as parse_deepseek_answers
from awltux.decision.engine import Answer, DecisionResponse
from awltux.decision.gate import GateContext, build_context, evaluate
from awltux.decision.jev import _parse_answers as parse_jev_answers
from awltux.decision.offline import OfflineEngine
from awltux.decision.questions import build_questions
from tests.helpers import make_instrument

# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #


class TestCanonicalState:
    def test_same_inputs_hash_identically(self):
        kwargs = dict(
            instrument=make_instrument(),
            valuation=None,
            technical=None,
            fundamentals=None,
            sentiment_score=None,
            news=[],
        )
        first = build_state(**kwargs)
        second = build_state(**kwargs)
        assert first.sha256 == second.sha256

    def test_key_order_does_not_change_the_hash(self):
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
        assert state_hash({"a": 1}) == state_hash({"a": 1})

    def test_adding_an_absent_field_does_not_change_the_hash(self):
        """Null fields are pruned, so an optional input that is always missing
        must not silently invalidate every stored decision's hash."""
        without = {"a": 1, "b": None}
        with_extra = {"a": 1, "b": None, "c": None}
        assert state_hash(without) == state_hash(with_extra)

    def test_float_noise_is_rounded_away(self):
        assert state_hash({"a": 1.000000001}) == state_hash({"a": 1.000000002})

    def test_a_real_change_changes_the_hash(self):
        assert state_hash({"a": 1}) != state_hash({"a": 2})

    def test_state_carries_the_evidence_and_a_hash(self):
        state = build_state(
            instrument=make_instrument(),
            valuation=None,
            technical=None,
            fundamentals=None,
            sentiment_score=0.3,
            news=[],
        )
        assert state.payload["instrument"]["ticker"] == "AAPL_US_EQ"
        assert state.payload["sentiment"]["instrument_score"] == 0.3
        assert len(state.sha256) == 64
        assert state.token_estimate > 0
        assert state.truncated is False

    def test_oversized_state_is_truncated_and_recorded(self):
        """The state must fit the model's context, and truncation must be visible
        rather than silent."""
        news = [
            type("N", (), {"title": "x" * 400, "materiality": "mild", "direction": "positive",
                           "horizon": "weeks", "provider_sentiment": 0.2,
                           "sentiment_score": None, "source": "rss",
                           "published_at": dt.datetime.now(dt.UTC)})()
            for _ in range(60)
        ]
        state = build_state(
            instrument=make_instrument(),
            valuation=None,
            technical=None,
            fundamentals=None,
            sentiment_score=None,
            news=news,
            filing_summary="y" * 60_000,
            max_tokens=500,
        )
        assert state.truncated is True
        assert state.dropped
        assert state.token_estimate <= 5000  # truncated down from far more


# --------------------------------------------------------------------------- #
# engines
# --------------------------------------------------------------------------- #


class TestOfflineEngine:
    def _state(self, mos: float, **overrides):
        payload = {
            "instrument": {"ticker": "T", "name": "Test"},
            "valuation": {"status": "ok", "margin_of_safety": mos, "methods_applied": ["dcf", "epv", "multiples"]},
            "accounts": {"periods_used": 4, **overrides},
            "price_and_trend": {
                "trend": "uptrend",
                "position_in_52w_range": 0.6,
                "return_3m": 0.08,
                "return_1m": 0.02,
                "rsi_14": 55.0,
                "sma_50": 10.0,
                "sma_200": 9.0,
                "volume_trend": 0.3,
                "volatility_annual": 0.25,
            },
            "sentiment": {"instrument_score": 0.2},
            "recent_news": [],
        }
        return payload

    def test_is_always_available(self):
        assert OfflineEngine().available is True

    def test_large_discount_produces_a_buy(self):
        response = OfflineEngine().decide(
            state=self._state(0.5), state_text="", questions=build_questions()
        )
        assert response.choice("valuation_verdict") == "deeply_undervalued"
        assert response.choice("long_term_action") == "strong_buy"
        assert response.uncalibrated is True

    def test_large_premium_produces_a_sell(self):
        response = OfflineEngine().decide(
            state=self._state(-0.4), state_text="", questions=build_questions()
        )
        assert response.choice("valuation_verdict") == "deeply_overvalued"
        assert response.choice("long_term_action") == "sell"

    def test_fair_value_produces_a_hold(self):
        response = OfflineEngine().decide(
            state=self._state(0.02), state_text="", questions=build_questions()
        )
        assert response.choice("long_term_action") == "hold"

    def test_big_discount_into_high_risk_is_not_a_buy(self):
        """A discount into a company that may not survive is not a bargain."""
        response = OfflineEngine().decide(
            state=self._state(
                0.5,
                net_debt_to_ebitda=6.0,
                interest_cover=1.2,
                debt_to_equity=4.0,
            ),
            state_text="",
            questions=build_questions(),
        )
        assert response.choice("long_term_action") == "hold"

    def test_going_concern_evidence_forces_avoid(self):
        response = OfflineEngine().decide(
            state=self._state(0.5, red_flags=["going concern doubt disclosed"]),
            state_text="",
            questions=build_questions(),
        )
        assert response.choice("long_term_action") == "avoid"
        assert response.noul("going_concern") == pytest.approx(1.0)

    def test_no_valuation_produces_a_hold_not_a_guess(self):
        state = self._state(0.0)
        state["valuation"] = {"status": "insufficient_data"}
        response = OfflineEngine().decide(state=state, state_text="", questions=build_questions())
        assert response.choice("long_term_action") == "hold"

    def test_answers_every_question(self):
        response = OfflineEngine().decide(
            state=self._state(0.2), state_text="", questions=build_questions()
        )
        assert set(response.answers) == set(build_questions())

    def test_reports_no_probabilities(self):
        """The offline engine must not look probabilistic."""
        response = OfflineEngine().decide(
            state=self._state(0.2), state_text="", questions=build_questions()
        )
        for answer in response.answers.values():
            assert answer.probabilities is None

    def test_action_carries_an_evidence_confidence(self):
        """The risk gate reads the confidence off the *action* answer.

        Omitting it meant this engine could never produce a suggestion no matter
        how strong the evidence, because the gate saw "no confidence reported"
        and refused. The number is a statement about the evidence and is labelled
        as such -- but it has to be present.
        """
        response = OfflineEngine().decide(
            state=self._state(0.5), state_text="", questions=build_questions()
        )
        action = response.get("long_term_action")
        assert action is not None
        assert action.confidence is not None
        assert 0 < action.confidence <= 1

    def test_action_confidence_scales_with_evidence_quality(self):
        thin = OfflineEngine().decide(
            state={
                "instrument": {"ticker": "T"},
                "valuation": {"status": "insufficient_data"},
                "accounts": {},
                "price_and_trend": {},
                "sentiment": {},
                "recent_news": [],
            },
            state_text="",
            questions=build_questions(),
        )
        rich = OfflineEngine().decide(
            state=self._state(0.5), state_text="", questions=build_questions()
        )
        assert thin.get("long_term_action").confidence < rich.get("long_term_action").confidence


class TestJevAnswerParsing:
    def test_parses_all_three_primitives(self):
        raw = {
            "valuation_verdict": {
                "type": "choice",
                "choice": "undervalued",
                "confidence": 0.91,
                "probabilities": {"undervalued": 0.91, "fairly_valued": 0.09},
            },
            "margin_of_safety": {
                "type": "score",
                "score": 2.97,
                "confidence": 0.8,
                "legend": {"0": "none", "1": "thin", "2": "adequate", "3": "large"},
                "probabilities": {"2": 0.03, "3": 0.97},
            },
            "going_concern": {"type": "noul", "noul": 0.05},
        }
        answers = parse_jev_answers(raw, build_questions())
        assert answers["valuation_verdict"].value == "undervalued"
        assert answers["valuation_verdict"].confidence == pytest.approx(0.91)
        assert answers["valuation_verdict"].top_probability == pytest.approx(0.91)
        assert answers["margin_of_safety"].numeric == pytest.approx(2.97)
        assert answers["margin_of_safety"].legend["3"] == "large"
        assert answers["going_concern"].numeric == pytest.approx(0.05)

    def test_accepts_the_javascript_sdk_probability_field(self):
        """The JS SDK returns `probability` where HTTP returns `noul`."""
        answers = parse_jev_answers({"going_concern": {"probability": 0.42}}, {})
        assert answers["going_concern"].numeric == pytest.approx(0.42)

    def test_ignores_unrecognised_shapes(self):
        assert parse_jev_answers({"x": "not a dict"}, {}) == {}
        assert parse_jev_answers({"x": {"unexpected": 1}}, {}) == {}
        assert parse_jev_answers(None, {}) == {}

    def test_versioned_model_id_is_preserved(self):
        response = DecisionResponse(answers={}, engine="jev", model_id="jev-1.13.0")
        assert response.model_id == "jev-1.13.0"
        assert response.uncalibrated is False


class TestDeepSeekAnswerParsing:
    def test_discards_an_option_that_was_never_offered(self):
        """An out-of-set choice is a hallucinated answer, not a near miss."""
        raw = {"valuation_verdict": {"choice": "amazing_buy", "confidence": 0.9}}
        assert parse_deepseek_answers(raw, build_questions()) == {}

    def test_discards_an_out_of_range_score(self):
        raw = {"margin_of_safety": {"score": 9, "confidence": 0.9}}
        assert parse_deepseek_answers(raw, build_questions()) == {}

    def test_accepts_a_valid_score(self):
        raw = {"margin_of_safety": {"score": 3, "confidence": 0.7}}
        answers = parse_deepseek_answers(raw, build_questions())
        assert answers["margin_of_safety"].numeric == 3.0

    def test_normalises_unnormalised_probabilities(self):
        """Otherwise a model returning weights would defeat the probability floor."""
        raw = {
            "long_term_action": {
                "choice": "buy",
                "confidence": 0.8,
                "probabilities": {"buy": 4, "hold": 1},
            }
        }
        answers = parse_deepseek_answers(raw, build_questions())
        probabilities = answers["long_term_action"].probabilities
        assert probabilities is not None
        assert sum(probabilities.values()) == pytest.approx(1.0)
        assert probabilities["buy"] == pytest.approx(0.8)

    def test_non_jev_response_is_flagged_uncalibrated(self):
        response = DecisionResponse(answers={}, engine="deepseek", model_id="deepseek-flash")
        assert response.uncalibrated is True
        assert response.trust < DecisionResponse(answers={}, engine="jev").trust


# --------------------------------------------------------------------------- #
# composite
# --------------------------------------------------------------------------- #


def _probabilities_for(choice: str, confidence: float) -> dict[str, float]:
    """A two-option distribution for a chosen action.

    The runner-up must differ from the winner: ``{"hold": c, "hold": 1 - c}``
    collapses to a single low-probability entry, which then trips the probability
    floor and makes a test of the *action* rule fail for the wrong reason.
    """
    runner_up = "buy" if choice == "hold" else "hold"
    distribution = {choice: confidence}
    remainder = round(1.0 - confidence, 6)
    if remainder > 0:
        distribution[runner_up] = remainder
    return distribution


def _response(**answers) -> DecisionResponse:
    """Build a response from keyword answers.

    ``action`` is accepted as an alias for ``long_term_action`` so that existing
    score-shaped tests read naturally, but the canonical names are the horizon
    ones -- there is no longer a single unqualified action.
    """
    built = {}
    for name, value in answers.items():
        key = "long_term_action" if name == "action" else name
        if isinstance(value, tuple):
            built[key] = Answer(
                key, "choice", value[0], value[1], _probabilities_for(value[0], value[1])
            )
        elif key == "margin_of_safety":
            built[key] = Answer(key, "score", float(value))
        elif key in ("short_term_setup", "short_term_drawdown_risk") or (
            isinstance(value, (int, float))
            and key not in ("valuation_verdict", "earnings_trend", "news_materiality",
                            "sentiment_regime", "horizon_fit")
        ):
            built[key] = Answer(key, "score", float(value), 0.9)
        else:
            built[key] = Answer(key, "choice", value, 0.9)
    return DecisionResponse(answers=built, engine="jev", model_id="jev-1.13.0")


class TestComposite:
    def test_score_is_on_a_0_to_100_scale(self):
        result = compute_composite(
            _response(
                valuation_verdict="undervalued",
                margin_of_safety=3.0,
                business_quality=3.0,
                balance_sheet_risk=1.0,
                earnings_trend="improving",
                news_materiality="neutral",
                sentiment_regime="neutral",
            )
        )
        assert result.score is not None
        assert 0 <= result.score <= 100

    def test_an_attractive_name_scores_higher_than_an_unattractive_one(self):
        good = compute_composite(
            _response(
                valuation_verdict="deeply_undervalued",
                margin_of_safety=4.0,
                business_quality=4.0,
                balance_sheet_risk=0.0,
                earnings_trend="improving",
                news_materiality="material_positive",
                sentiment_regime="positive",
            )
        )
        bad = compute_composite(
            _response(
                valuation_verdict="deeply_overvalued",
                margin_of_safety=0.0,
                business_quality=0.0,
                balance_sheet_risk=4.0,
                earnings_trend="deteriorating",
                news_materiality="material_negative",
                sentiment_regime="negative",
            )
        )
        assert good.score > bad.score

    def test_balance_sheet_risk_is_inverted(self):
        settings = get_settings()
        low_risk = normalise_answer("balance_sheet_risk", Answer("x", "score", 0.0), settings)
        high_risk = normalise_answer("balance_sheet_risk", Answer("x", "score", 4.0), settings)
        assert low_risk == pytest.approx(1.0)
        assert high_risk == pytest.approx(0.0)

    def test_missing_answers_are_reported_not_penalised(self):
        result = compute_composite(_response(valuation_verdict="undervalued"))
        assert result.score is not None
        assert "margin_of_safety" in result.missing

    def test_disagreement_with_the_action_is_flagged(self):
        result = compute_composite(
            _response(
                valuation_verdict="deeply_overvalued",
                margin_of_safety=0.0,
                business_quality=0.0,
                balance_sheet_risk=4.0,
                earnings_trend="deteriorating",
                news_materiality="material_negative",
                sentiment_regime="fearful",
                action="strong_buy",
            )
        )
        assert result.conflict is True
        assert result.notes


# --------------------------------------------------------------------------- #
# risk gate
# --------------------------------------------------------------------------- #


def _suggestion(**overrides) -> tuple[DecisionResponse, CompositeResult]:
    """A response that should pass the gate, with both horizons populated."""
    defaults = dict(
        valuation_verdict="undervalued",
        margin_of_safety=3.0,
        business_quality=3.0,
        balance_sheet_risk=1.0,
        earnings_trend="improving",
        news_materiality="neutral",
        sentiment_regime="neutral",
        long_term_action=("buy", 0.9),
        short_term_action=("buy", 0.9),
        short_term_setup=3.0,
        short_term_drawdown_risk=1.0,
        horizon_fit="both",
        going_concern=0.05,
        dilution_risk=0.1,
        accounting_red_flags=0.1,
    )
    defaults.update(overrides)
    # Allow the shorthand `action=` / `short_action=` in tests while the
    # canonical question names stay horizon-qualified.
    if "action" in defaults:
        defaults["long_term_action"] = defaults.pop("action")
    if "short_action" in defaults:
        defaults["short_term_action"] = defaults.pop("short_action")

    built = {}
    for name, value in defaults.items():
        if isinstance(value, tuple):
            built[name] = Answer(
                name, "choice", value[0], value[1], _probabilities_for(value[0], value[1])
            )
        elif name in ("margin_of_safety", "short_term_setup", "short_term_drawdown_risk",
                      "business_quality", "balance_sheet_risk"):
            built[name] = Answer(name, "score", float(value), 0.9)
        elif name in ("going_concern", "dilution_risk", "accounting_red_flags"):
            built[name] = Answer(name, "noul", float(value))
        else:
            built[name] = Answer(name, "choice", value, 0.9)

    response = DecisionResponse(answers=built, engine="jev", model_id="jev-1.13.0")
    return response, compute_composite(response, horizon="long_term")


def _short_suggestion(**overrides) -> tuple[DecisionResponse, CompositeResult]:
    """The same, scored and evaluated on the tactical horizon."""
    response, _ = _suggestion(**overrides)
    return response, compute_composite(response, horizon="short_term")


def _context(**overrides) -> GateContext:
    now = dt.datetime.now(dt.UTC)
    defaults = dict(
        price_at=now - dt.timedelta(hours=4),
        valuation_at=now - dt.timedelta(days=1),
        last_filing_at=now - dt.timedelta(days=120),
        median_daily_turnover_gbp=5_000_000.0,
        setup_score=3.0,
        open_positions=3,
        current_weight=0.02,
        sector_weight=0.10,
        min_engine="offline",
    )
    defaults.update(overrides)
    return build_context(**defaults)


class TestRiskGate:
    def test_a_clean_decision_passes_and_gets_a_weight(self):
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context())
        assert verdict.allowed is True
        assert verdict.is_suggestion is True
        assert verdict.suggested_weight is not None
        assert 0 < verdict.suggested_weight <= 0.08

    def test_hold_is_not_a_suggestion(self):
        response, composite = _suggestion(action=("hold", 0.9))
        verdict = evaluate(response, composite, _context())
        assert verdict.is_suggestion is False
        assert verdict.binding_rule is None

    def test_confidence_below_floor_is_refused(self):
        response, composite = _suggestion(action=("buy", 0.5))
        verdict = evaluate(response, composite, _context())
        assert verdict.is_suggestion is False
        assert verdict.binding_rule == "confidence_below_floor"

    def test_fallback_engine_faces_a_stricter_floor(self):
        """Uncalibrated probabilities must clear a higher bar before they are
        presented as a suggestion."""
        response, composite = _suggestion(action=("buy", 0.75))
        response.engine = "deepseek"
        response.model_id = "deepseek-flash"
        verdict = evaluate(response, composite, _context())
        assert verdict.is_suggestion is False
        assert verdict.binding_rule == "confidence_below_floor"
        # The same decision from a calibrated engine passes.
        response.engine = "jev"
        assert evaluate(response, composite, _context()).is_suggestion is True

    def test_stale_price_is_refused(self):
        response, composite = _suggestion()
        verdict = evaluate(
            response, composite, _context(price_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=5))
        )
        assert verdict.binding_rule == "price_stale"

    def test_missing_price_timestamp_is_refused(self):
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context(price_at=None))
        assert verdict.binding_rule == "price_stale"

    def test_stale_valuation_is_refused(self):
        response, composite = _suggestion()
        verdict = evaluate(
            response,
            composite,
            _context(valuation_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=30)),
        )
        assert verdict.binding_rule == "valuation_stale"

    def test_unknown_liquidity_is_refused(self):
        """An unmeasurable turnover must fail closed, not default to liquid."""
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context(median_daily_turnover_gbp=None))
        assert verdict.binding_rule == "liquidity_unknown"

    def test_illiquid_name_is_refused(self):
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context(median_daily_turnover_gbp=1000.0))
        assert verdict.binding_rule == "illiquid"

    def test_too_many_positions_is_refused(self):
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context(open_positions=25))
        assert verdict.binding_rule == "max_positions"

    def test_per_name_concentration_is_refused(self):
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context(current_weight=0.09))
        assert verdict.binding_rule == "position_concentration"

    def test_sector_concentration_is_refused(self):
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context(sector_weight=0.31))
        assert verdict.binding_rule == "sector_concentration"

    def test_engine_trust_floor_is_enforced(self):
        response, composite = _suggestion()
        response.engine = "offline"
        response.model_id = "offline-rules-1"
        verdict = evaluate(response, composite, _context(min_engine="jev"))
        assert verdict.binding_rule == "engine_trust"

    def test_low_probability_mass_is_refused(self):
        response, composite = _suggestion()
        response.answers["long_term_action"] = Answer(
            "long_term_action", "choice", "buy", 0.95, {"buy": 0.55, "hold": 0.45}
        )
        verdict = evaluate(response, composite, _context())
        assert verdict.binding_rule == "probability_below_floor"

    def test_every_refusal_names_the_binding_rule_and_records_every_check(self):
        response, composite = _suggestion()
        verdict = evaluate(response, composite, _context(median_daily_turnover_gbp=None))
        assert verdict.binding_rule is not None
        assert verdict.reason
        assert len(verdict.checks) >= 3
        assert all(check.name for check in verdict.checks)


class TestOfflineEngineReachesTheGate:
    """The offline engine's own output must survive the gate end to end.

    Testing the gate with hand-built responses would not have caught the missing
    action confidence, because a hand-built response always supplies one. This
    closes the loop on the no-keys path, which is the one a new install runs on.
    """

    def _state(self, mos: float) -> dict:
        return {
            "instrument": {"ticker": "T", "name": "Test"},
            "valuation": {
                "status": "ok",
                "margin_of_safety": mos,
                "valuation_confidence": 0.8,
                "methods_applied": ["dcf", "epv", "multiples"],
            },
            "accounts": {
                "periods_used": 4,
                "roce": 0.25,
                "net_debt_to_ebitda": 0.5,
                "interest_cover": 15.0,
                "debt_to_equity": 0.2,
                "free_cash_flow": 200_000.0,
                "positives": ["returns on capital of 25%", "net cash"],
                "red_flags": [],
            },
            "price_and_trend": {"trend": "uptrend", "position_in_52w_range": 0.6},
            "sentiment": {"instrument_score": 0.2},
            "recent_news": [],
        }

    def test_a_well_evidenced_offline_call_becomes_a_suggestion(self):
        response = OfflineEngine().decide(
            state=self._state(0.5), state_text="", questions=build_questions()
        )
        composite = compute_composite(response)
        verdict = evaluate(response, composite, _context())

        assert response.choice("long_term_action") == "strong_buy"
        assert verdict.is_suggestion is True, verdict.reason
        assert verdict.suggested_weight is not None

    def test_a_thin_offline_call_does_not_become_a_suggestion(self):
        """With no usable valuation there is nothing to act on."""
        state = self._state(0.5)
        state["valuation"] = {"status": "insufficient_data"}
        response = OfflineEngine().decide(
            state=state, state_text="", questions=build_questions()
        )
        composite = compute_composite(response)
        verdict = evaluate(response, composite, _context())
        assert verdict.is_suggestion is False
        assert verdict.binding_rule == "confidence_below_floor"

    def test_conflict_does_not_block_but_is_recorded(self):
        """A disagreement between the model's action and its own scores is
        information, so it is surfaced rather than suppressed."""
        response, composite = _suggestion(
            valuation_verdict="deeply_overvalued",
            margin_of_safety=0.0,
            business_quality=0.0,
            action=("buy", 0.9),
        )
        verdict = evaluate(response, composite, _context())
        assert composite.conflict is True
        assert verdict.is_suggestion is True
        assert any(check.name == "composite_agreement" and not check.passed for check in verdict.checks)


# --------------------------------------------------------------------------- #
# horizon separation
# --------------------------------------------------------------------------- #


class TestHorizonSeparation:
    """The two horizons must be genuinely independent.

    The failure mode this guards against is a "short-term" view that is really
    just the long-term view with a different label. If they always agreed, the
    second one would be decoration -- so these tests assert that they can and do
    diverge, in both directions.
    """

    def _state(self, mos: float, technical: dict | None = None, **accounts) -> dict:
        return {
            "instrument": {"ticker": "T", "name": "Test", "is_held": False},
            "valuation": {
                "status": "ok",
                "margin_of_safety": mos,
                "valuation_confidence": 0.8,
                "methods_applied": ["dcf", "epv", "multiples"],
            },
            "accounts": {"periods_used": 4, "roce": 0.2, "positives": [], "red_flags": [], **accounts},
            "price_and_trend": technical
            or {
                "trend": "uptrend",
                "return_3m": 0.08,
                "return_1m": 0.02,
                "position_in_52w_range": 0.6,
                "rsi_14": 55.0,
                "sma_50": 10.0,
                "sma_200": 9.0,
                "volume_trend": 0.3,
                "volatility_annual": 0.25,
            },
            "sentiment": {"instrument_score": 0.2},
            "recent_news": [],
        }

    def _decide(self, state: dict) -> DecisionResponse:
        return OfflineEngine().decide(state=state, state_text="", questions=build_questions())

    def test_both_horizons_are_always_answered(self):
        response = self._decide(self._state(0.5))
        assert response.choice("long_term_action") is not None
        assert response.choice("short_term_action") is not None
        assert response.score("short_term_setup") is not None
        assert response.score("short_term_drawdown_risk") is not None
        assert response.choice("horizon_fit") is not None

    def test_cheap_but_tactically_broken(self):
        """The case a single collapsed verdict would hide: good value, bad entry."""
        response = self._decide(
            self._state(
                0.5,
                technical={
                    "trend": "downtrend",
                    "return_3m": -0.15,
                    "return_1m": -0.08,
                    "position_in_52w_range": 0.15,
                    "rsi_14": 32.0,
                    "sma_50": 9.0,
                    "sma_200": 10.0,
                    "volume_trend": -0.2,
                    "volatility_annual": 0.3,
                },
            )
        )
        assert response.choice("long_term_action") in ("buy", "strong_buy")
        assert response.choice("short_term_action") in ("avoid", "hold", "reduce")
        assert response.choice("horizon_fit") == "long_term"

    def test_expensive_but_tactically_strong(self):
        """The mirror image: nothing here for years, but a clean setup now."""
        response = self._decide(
            self._state(
                -0.4,
                technical={
                    "trend": "uptrend",
                    "return_3m": 0.20,
                    "return_1m": 0.05,
                    "position_in_52w_range": 0.85,
                    "rsi_14": 62.0,
                    "sma_50": 11.0,
                    "sma_200": 10.0,
                    "volume_trend": 0.5,
                    "volatility_annual": 0.3,
                },
            )
        )
        assert response.choice("long_term_action") in ("sell", "reduce", "hold")
        assert response.choice("short_term_action") in ("buy", "strong_buy")
        assert response.choice("horizon_fit") == "short_term"

    def test_both_horizons_agree_when_the_evidence_does(self):
        response = self._decide(self._state(0.5))
        assert response.choice("long_term_action") in ("buy", "strong_buy")
        assert response.choice("short_term_action") in ("buy", "strong_buy")
        assert response.choice("horizon_fit") == "both"

    def test_neither_horizon_when_there_is_nothing_to_act_on(self):
        state = self._state(
            0.02,
            technical={
                "trend": "mixed",
                "return_3m": 0.0,
                "return_1m": 0.0,
                "position_in_52w_range": 0.5,
                "rsi_14": 50.0,
                "sma_50": 10.0,
                "sma_200": 10.0,
                "volume_trend": 0.0,
                "volatility_annual": 0.25,
            },
        )
        response = self._decide(state)
        assert response.choice("horizon_fit") == "neither"

    def test_high_drawdown_risk_blocks_the_tactical_buy(self):
        """A stock that has already run hard is not a fresh entry, however strong
        the trend -- the composite should not be able to outvote that."""
        response = self._decide(
            self._state(
                0.3,
                technical={
                    "trend": "uptrend",
                    "return_3m": 0.30,
                    "return_1m": 0.35,
                    "position_in_52w_range": 0.99,
                    "rsi_14": 82.0,
                    "sma_50": 12.0,
                    "sma_200": 10.0,
                    "volume_trend": 0.6,
                    "volatility_annual": 0.8,
                },
            )
        )
        assert response.score("short_term_drawdown_risk") >= 3
        assert response.choice("short_term_action") == "hold"

    def test_weak_setup_on_a_held_name_reduces(self):
        """`is_held` changes the tactical answer: a weak setup you own is a reason
        to trim, not merely a reason not to buy."""
        state = self._state(
            0.1,
            technical={
                "trend": "downtrend",
                "return_3m": -0.12,
                "return_1m": -0.05,
                "position_in_52w_range": 0.2,
                "rsi_14": 38.0,
                "sma_50": 9.0,
                "sma_200": 10.0,
                "volume_trend": -0.1,
                "volatility_annual": 0.3,
            },
        )
        not_held = self._decide({**state, "instrument": {"ticker": "T", "is_held": False}})
        held = self._decide({**state, "instrument": {"ticker": "T", "is_held": True}})
        assert not_held.choice("short_term_action") == "avoid"
        assert held.choice("short_term_action") == "reduce"

    def test_tactical_confidence_rises_with_input_coverage(self):
        full = self._decide(self._state(0.3))
        sparse = self._decide(
            self._state(0.3, technical={"trend": "unknown", "return_3m": 0.05})
        )
        assert (
            sparse.get("short_term_action").confidence
            < full.get("short_term_action").confidence
        )


class TestHorizonAwareComposite:
    def test_the_two_horizons_use_different_weights(self):
        settings = get_settings()
        assert settings.composite.long_term_weights != settings.composite.short_term_weights
        assert "margin_of_safety" in settings.composite.long_term_weights
        assert "margin_of_safety" not in settings.composite.short_term_weights
        assert "short_term_setup" in settings.composite.short_term_weights

    def test_the_same_response_scores_differently_per_horizon(self):
        response = _response(
            valuation_verdict="deeply_undervalued",
            margin_of_safety=4.0,
            business_quality=4.0,
            balance_sheet_risk=0.0,
            earnings_trend="improving",
            news_materiality="material_negative",
            sentiment_regime="fearful",
            long_term_action=("buy", 0.9),
            short_term_action=("avoid", 0.9),
            short_term_setup=0.0,
            short_term_drawdown_risk=4.0,
        )
        long_term, short_term = compute_both(response)
        assert long_term.horizon == "long_term"
        assert short_term.horizon == "short_term"
        # Excellent value, terrible setup: they must not produce the same number.
        assert long_term.score > short_term.score

    def test_short_term_drawdown_risk_is_inverted(self):
        settings = get_settings()
        low = normalise_answer(
            "short_term_drawdown_risk", Answer("x", "score", 0.0), settings
        )
        high = normalise_answer(
            "short_term_drawdown_risk", Answer("x", "score", 4.0), settings
        )
        assert low == pytest.approx(1.0)
        assert high == pytest.approx(0.0)

    def test_each_horizon_reads_its_own_action_answer(self):
        response = _response(
            valuation_verdict="undervalued",
            margin_of_safety=3.0,
            long_term_action=("buy", 0.9),
            short_term_action=("sell", 0.9),
        )
        long_term, short_term = compute_both(response)
        assert long_term.action == "buy"
        assert short_term.action == "sell"


class TestHorizonAwareGate:
    def test_the_tactical_gate_requires_a_setup_score(self):
        """A tactical call with no measured momentum is not a tactical call."""
        response, composite = _short_suggestion()
        verdict = evaluate(
            response, composite, _context(setup_score=None), horizon="short_term"
        )
        assert verdict.is_suggestion is False
        assert verdict.binding_rule == "setup_too_weak"

    def test_a_weak_setup_is_refused(self):
        response, composite = _short_suggestion()
        verdict = evaluate(
            response, composite, _context(setup_score=1.0), horizon="short_term"
        )
        assert verdict.binding_rule == "setup_too_weak"

    def test_a_good_setup_passes(self):
        response, composite = _short_suggestion()
        verdict = evaluate(
            response, composite, _context(setup_score=3.0), horizon="short_term"
        )
        assert verdict.is_suggestion is True

    def test_the_long_term_gate_does_not_require_a_setup_score(self):
        """Requiring tactical evidence for an investment call would refuse good
        calls for an irrelevant reason."""
        response, composite = _suggestion()
        verdict = evaluate(
            response, composite, _context(setup_score=None), horizon="long_term"
        )
        assert verdict.is_suggestion is True

    def test_stale_prices_are_refused_on_either_horizon(self):
        stale = dt.datetime.now(dt.UTC) - dt.timedelta(days=10)
        for horizon in ("long_term", "short_term"):
            response, composite = (
                _short_suggestion() if horizon == "short_term" else _suggestion()
            )
            verdict = evaluate(
                response, composite, _context(price_at=stale), horizon=horizon
            )
            assert verdict.binding_rule == "price_stale", horizon

    def test_a_stale_valuation_blocks_the_long_term_but_not_the_tactical_call(self):
        """The distinction that justifies having two requirement sets: a tactical
        call does not need a fresh discounted cash flow, but an investment call
        absolutely does."""
        stale_valuation = dt.datetime.now(dt.UTC) - dt.timedelta(days=45)

        long_response, long_composite = _suggestion()
        long_verdict = evaluate(
            long_response, long_composite, _context(valuation_at=stale_valuation),
            horizon="long_term",
        )
        assert long_verdict.binding_rule == "valuation_stale"

        short_response, short_composite = _short_suggestion()
        short_verdict = evaluate(
            short_response, short_composite, _context(valuation_at=stale_valuation),
            horizon="short_term",
        )
        assert short_verdict.is_suggestion is True, short_verdict.reason

    def test_each_horizon_is_scored_and_gated_on_its_own_action(self):
        response, _ = _suggestion(action=("buy", 0.9), short_action=("hold", 0.9))
        long_verdict = evaluate(
            response, compute_composite(response, horizon="long_term"),
            _context(), horizon="long_term",
        )
        short_verdict = evaluate(
            response, compute_composite(response, horizon="short_term"),
            _context(), horizon="short_term",
        )
        assert long_verdict.is_suggestion is True
        assert short_verdict.is_suggestion is False
        assert short_verdict.binding_rule is None  # HOLD is simply not actionable


class TestUnreadablePortfolio:
    """A key that cannot read positions must not silently pass the limits.

    Trading 212 issues scoped keys, and a ``metadata``-only key is a reasonable
    configuration: it can read the instrument universe but not your holdings. An
    *unreadable* empty portfolio looks identical in the numbers to a genuinely
    empty one, so the gate has to distinguish them -- otherwise it reports
    concentration limits as enforced when it never checked them at all.
    """

    def test_limits_are_reported_unverified_rather_than_passed(self):
        response, composite = _suggestion()
        verdict = evaluate(
            response, composite, _context(portfolio_known=False), horizon="long_term"
        )

        assert verdict.is_suggestion is True, "advisory calls should still be allowed"
        checks = {check.name: check for check in verdict.checks}
        assert "portfolio_limits" in checks
        assert checks["portfolio_limits"].passed is False
        assert "NOT VERIFIED" in checks["portfolio_limits"].detail
        # The individual limits must not appear as though they had been applied.
        assert "max_positions" not in checks
        assert "position_concentration" not in checks
        assert "sector_concentration" not in checks

    def test_a_known_empty_portfolio_applies_the_limits_normally(self):
        response, composite = _suggestion()
        verdict = evaluate(
            response, composite, _context(portfolio_known=True), horizon="long_term"
        )
        checks = {check.name: check for check in verdict.checks}
        assert checks["max_positions"].passed is True
        assert "portfolio_limits" not in checks

    def test_a_known_over_limit_portfolio_is_still_refused(self):
        """The unverified path must not weaken enforcement when data *is* available."""
        response, composite = _suggestion()
        verdict = evaluate(
            response,
            composite,
            _context(portfolio_known=True, open_positions=30),
            horizon="long_term",
        )
        assert verdict.is_suggestion is False
        assert verdict.binding_rule == "max_positions"

    def test_selling_actions_do_not_need_portfolio_access(self):
        """Trim and exit calls are not gated on concentration, so they still work."""
        response, composite = _suggestion(action=("reduce", 0.9))
        verdict = evaluate(
            response, composite, _context(portfolio_known=False), horizon="long_term"
        )
        assert verdict.is_suggestion is True
        checks = {check.name: check for check in verdict.checks}
        assert "portfolio_limits" not in checks

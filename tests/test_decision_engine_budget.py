"""The fallback decision engine's output budget.

A response that does not fit is a real failure with a real cost: the instrument
falls through to the deterministic engine and the model's judgement is discarded,
for a reason that is only about output length. Measured on the first eighteen
fallback decisions, the *minimum* output was 2,727 tokens and four of the eighteen
hit the 4,000 ceiling exactly -- one decision in four lost that way.

So these tests cover three things: that the engine no longer asks for output
nothing reads, that it produces a document a model can actually reproduce, and
that a truncated answer is retried rather than abandoned.
"""

from __future__ import annotations

import pytest

from awltux.decision.deepseek_engine import (
    DeepSeekDecisionEngine,
    build_schema,
)
from awltux.decision.engine import DecisionEngineError
from awltux.decision.questions import build_questions
from awltux.llm.deepseek import Completion, TruncatedResponse


def _questions() -> dict:
    return build_questions()


class TestTheSchemaAsksOnlyForWhatIsRead:
    def test_no_per_question_reasoning_is_requested(self):
        """`parse_answers` never reads it and `Answer` has no field for it, so
        every sentence the model wrote per question was discarded on arrival."""
        schema = build_schema(_questions())
        assert '"reasoning": "one sentence"' not in schema

    def test_the_top_level_reasoning_is_still_requested(self):
        """That one *is* used -- it becomes a note on the decision."""
        assert '"reasoning": "2-4 sentences' in build_schema(_questions())

    def test_the_criteria_legend_is_not_inside_the_json(self):
        """It used to be emitted as ``//`` lines between the object's members,
        which is not valid JSON but sits inside a template the model is told to
        reproduce. A model that copies it literally writes an unparseable
        document -- and one live decision failed exactly that way."""
        schema = build_schema(_questions())
        body = schema.split("Return a JSON object of this exact shape:", 1)[1]
        skeleton = body.split("What the options mean", 1)[0]
        assert "//" not in skeleton

    def test_the_legend_still_tells_the_model_what_the_options_mean(self):
        schema = build_schema(_questions())
        assert "What the options mean" in schema
        assert "deeply_undervalued" in schema

    def test_every_question_still_appears_in_the_schema(self):
        schema = build_schema(_questions())
        missing = [name for name in _questions() if f'"{name}"' not in schema]
        assert missing == []


class _FakeClient:
    """Returns the queued completions, recording the budget each call asked for."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.budgets: list[int] = []

    def complete(self, **kwargs):
        self.budgets.append(kwargs.get("max_tokens"))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _completion(text: str, finish_reason: str = "stop") -> Completion:
    return Completion(text=text, model="deepseek-flash", finish_reason=finish_reason)


GOOD = (
    '{"reasoning": "The balance sheet is sound and the price is fair.", "answers": {'
    '"valuation_verdict": {"choice": "fairly_valued", "confidence": 0.6, '
    '"probabilities": {"undervalued": 0.2, "fairly_valued": 0.6, "overvalued": 0.2}}'
    "}}"
)


class _Engine(DeepSeekDecisionEngine):
    """The real engine with its network client replaced, and nothing else."""

    def __init__(self, settings, client) -> None:
        super().__init__(settings)
        self._fake = client

    @property
    def available(self) -> bool:
        return True

    def client(self):  # type: ignore[override]
        return self._fake


class TestATruncatedAnswerIsRetried:
    def _decide(self, settings, client):
        engine = _Engine(settings, client)
        return engine.decide(
            state={"instrument": {"ticker": "TEST_US_EQ"}},
            state_text="some state",
            questions=_questions(),
        )

    def test_a_truncated_response_is_retried_with_more_room(self, settings):
        client = _FakeClient(
            [
                _completion('{"answers": {"valuation_verdict": {"choice": "fai', "length"),
                _completion(GOOD),
            ]
        )
        response = self._decide(settings, client)
        assert response.answers
        assert client.budgets == [6_000, 8_000], "the retry must ask for more"

    def test_the_retry_budget_comes_from_configuration(self, settings):
        """It was a magic 4,000 buried in the engine, with the observed median
        already at ~3,500."""
        assert settings.decision.deepseek_max_tokens > 4_000

    def test_a_second_truncation_fails_rather_than_looping(self, settings):
        truncated = _completion('{"answers": {"valuation_verdict": {"choice": "fai', "length")
        client = _FakeClient([truncated, truncated])
        with pytest.raises(DecisionEngineError, match="did not fit"):
            self._decide(settings, client)
        assert len(client.budgets) == 2, "exactly one retry, not an unbounded loop"

    def test_malformed_json_is_not_retried(self, settings):
        """Only truncation is worth another call; nonsense will be nonsense again,
        and a retry costs money."""
        client = _FakeClient([_completion("not json at all")])
        with pytest.raises(DecisionEngineError) as excinfo:
            self._decide(settings, client)
        assert not isinstance(excinfo.value.__cause__, TruncatedResponse)
        assert len(client.budgets) == 1

    def test_a_successful_first_attempt_is_not_retried(self, settings):
        client = _FakeClient([_completion(GOOD)])
        self._decide(settings, client)
        assert client.budgets == [6_000]

    def test_an_unusable_answer_is_still_an_error(self, settings):
        """The retry must not paper over a response that fits but answers nothing."""
        client = _FakeClient([_completion('{"reasoning": "no answers here"}')])
        with pytest.raises(DecisionEngineError, match="no usable answers"):
            self._decide(settings, client)

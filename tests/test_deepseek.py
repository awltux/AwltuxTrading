"""The DeepSeek client's failure modes, and the classifier's response to them.

A truncated completion used to surface as ``Unterminated string starting at: line 1
column 4146`` — a message that describes a symptom at a character offset and hides
the cause. It reached a decision narrative in that form. These tests pin the
distinction between "the model returned nonsense" and "the model ran out of room",
because only the second one is worth retrying.
"""

from __future__ import annotations

import pytest

from awltux.config import LLMConfig
from awltux.db import LLMCall, utcnow
from awltux.llm.classify import classify_headline
from awltux.llm.deepseek import (
    BudgetExceeded,
    Completion,
    DeepSeekClient,
    DeepSeekError,
    TruncatedResponse,
    spend_report,
)
from awltux.providers.news_rss import RawNewsItem


def completion(text: str, *, finish_reason: str | None = "stop") -> Completion:
    return Completion(
        text=text,
        model="deepseek-flash",
        output_tokens=500,
        finish_reason=finish_reason,
    )


class TestJsonObject:
    def test_a_clean_object_parses(self):
        assert completion('{"materiality": "mild"}').json_object() == {"materiality": "mild"}

    def test_a_fenced_block_is_tolerated(self):
        fenced = "```json\n{\"materiality\": \"mild\"}\n```"
        assert completion(fenced).json_object() == {"materiality": "mild"}

    def test_nonsense_is_reported_as_nonsense(self):
        with pytest.raises(DeepSeekError) as excinfo:
            completion("I cannot help with that").json_object()
        assert not isinstance(excinfo.value, TruncatedResponse)
        assert "did not return valid JSON" in str(excinfo.value)

    def test_a_truncated_object_says_it_was_truncated(self):
        """The whole point: name the cause, not the character offset."""
        with pytest.raises(TruncatedResponse) as excinfo:
            completion('{"materiality": "mild", "reasoning": "the company said', finish_reason="length").json_object()

        message = str(excinfo.value)
        assert "cut off" in message
        assert "max_tokens" in message
        assert "500" in message

    def test_an_empty_response_says_there_is_nothing_to_parse(self):
        """Observed in production as ``Expecting value at char 0``, which sent the
        reader looking for a truncation point in a response that had no content:
        the output budget went before the answer began."""
        with pytest.raises(TruncatedResponse) as excinfo:
            completion("", finish_reason="length").json_object()

        message = str(excinfo.value)
        assert "no content at all" in message
        assert "incomplete" not in message

    def test_json_that_is_not_an_object_is_rejected(self):
        with pytest.raises(DeepSeekError):
            completion("[1, 2, 3]").json_object()

    def test_truncation_is_a_kind_of_deepseek_error(self):
        """Callers that only handle the general case must still catch it."""
        assert issubclass(TruncatedResponse, DeepSeekError)


class TestTheThinkingToggle:
    """Every request turns DeepSeek's thinking mode off, and this pins it.

    Thinking mode is on by default at `high` effort and its chain of thought shares
    `max_tokens` with the answer. That is what produced classifications which spent the
    whole budget deliberating and returned no content -- measured at one to six minutes
    per affected headline against 1-2 seconds for the rest, and the reason `news_rss`
    went seven runs without finishing.

    Measured head to head on this endpoint with a real headline: thinking on, 3.7 s and
    649 output tokens for a 268-character answer, of which 2,419 characters were hidden
    reasoning; thinking off, 0.8 s and 59 tokens for the same answer.

    Asserted on the request body rather than on a constant, because the failure this
    guards is the body losing the field -- which a test of `THINKING` itself would miss.
    """

    @staticmethod
    def _recording_client(monkeypatch, settings):
        from awltux.llm import deepseek as module

        bodies: list[dict] = []

        class _Response:
            def json(self):
                return {
                    "choices": [
                        {"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
                }

        class _Http:
            def post(self, path, *, json_body, retries):
                bodies.append(json_body)
                return _Response()

        monkeypatch.setattr(module.DeepSeekClient, "client", lambda self: _Http())
        return module.DeepSeekClient(settings), bodies

    def test_the_request_turns_thinking_off(self, monkeypatch, settings):
        client, bodies = self._recording_client(monkeypatch, settings)

        client.complete(purpose="test", messages=[{"role": "user", "content": "hi"}])

        assert bodies[0]["thinking"] == {"type": "disabled"}

    def test_it_is_sent_explicitly_rather_than_left_to_the_provider(self, monkeypatch, settings):
        """The provider's default is *on*, so omitting the field is the bug.

        A request that simply does not mention thinking looks correct in the source and
        is the exact configuration that returned empty answers.
        """
        client, bodies = self._recording_client(monkeypatch, settings)

        client.complete(purpose="test", messages=[{"role": "user", "content": "hi"}])

        assert "thinking" in bodies[0], "omitting it would inherit the provider default"

    def test_temperature_survives_the_toggle(self, monkeypatch, settings):
        """It is ignored in thinking mode, so turning that off is what makes a
        `temperature=0.0` request reproducible rather than merely nominally so."""
        client, bodies = self._recording_client(monkeypatch, settings)

        client.complete(
            purpose="test", messages=[{"role": "user", "content": "hi"}], temperature=0.0
        )

        assert bodies[0]["temperature"] == 0.0


class _FakeCompletions:
    """Returns a truncated response once, then a good one."""

    configured = True

    def __init__(self, responses: list[Completion]) -> None:
        self._responses = list(responses)
        self.calls: list[int] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs.get("max_tokens"))
        return self._responses.pop(0)


def make_item() -> RawNewsItem:
    return RawNewsItem(title="Acme warns on profit", url="https://example.test/a", source="test")


class TestClassifierRetry:
    def test_a_truncated_classification_is_retried_with_more_room(self, settings):
        good = completion(
            '{"is_about_this_company": true, "materiality": "material", '
            '"direction": "negative", "sentiment_score": -0.6, "event_type": "guidance"}'
        )
        fake = _FakeCompletions(
            [completion('{"materiality": "mat', finish_reason="length"), good]
        )

        result = classify_headline(
            make_item(), company_name="Acme", ticker="ACME_US_EQ",
            client=fake, settings=settings,
        )

        assert result is not None
        assert result["materiality"] == "material"
        assert fake.calls == [2_000, 8_000], "the retry must ask for more tokens"
        assert fake.calls[0] > 500, (
            "the first budget must cover the reasoning the API does not return, not "
            "just the answer: 6.7% of calls burned a 500-token budget and returned "
            "nothing at all"
        )

    def test_a_second_truncation_gives_up_rather_than_looping(self, settings):
        fake = _FakeCompletions(
            [
                completion('{"materiality": "mat', finish_reason="length"),
                completion('{"materiality": "mat', finish_reason="length"),
            ]
        )
        result = classify_headline(
            make_item(), company_name="Acme", ticker="ACME_US_EQ",
            client=fake, settings=settings,
        )
        assert result is None
        assert len(fake.calls) == 2, "exactly one retry, not an unbounded loop"

    def test_the_budgets_come_from_configuration(self, settings):
        """Both were magic numbers, and the first one was the wrong size."""
        assert settings.news.classify_max_tokens > 1_500
        assert settings.llm.max_output_tokens > settings.news.classify_max_tokens

    def test_malformed_json_is_not_retried(self, settings):
        """Only truncation is worth another call; nonsense will be nonsense again."""
        fake = _FakeCompletions([completion("not json at all")])
        result = classify_headline(
            make_item(), company_name="Acme", ticker="ACME_US_EQ",
            client=fake, settings=settings,
        )
        assert result is None
        assert len(fake.calls) == 1


def _spend(session, total: float) -> None:
    """Record one successful call costing ``total`` in the current month."""
    session.add(
        LLMCall(
            provider="deepseek",
            purpose="test",
            ok=True,
            cost_usd=total,
            created_at=utcnow(),
        )
    )
    session.commit()


class TestTheMonthlyCeiling:
    """Two hundred dollars, in dollars, with no exchange rate in the path.

    The ceiling is this application's own, and it exists because of a fact about this
    installation: the development key and the app's key share one DeepSeek account, so the
    provider's dashboard cannot attribute spend to this app. This ledger is the only
    instrument that can, and the number in it is a policy choice made by the person paying.

    Converted from sterling *once*, by hand, on 2026-10-25 -- not on every check. A ceiling
    that moved with the FX rate would be a budget nobody could predict, and a guard is only
    trusted when its number is fixed. So the figure is USD and it is compared straight
    against ``llm_call.cost_usd``, which DeepSeek bills in.

    These tests exist because the failure mode of this setting is silence: at $40 the
    decision layer degrades to a weaker engine, so a ceiling left too low looks like "the
    model got worse" rather than "the budget ran out". A test that named the figure was the
    only thing that would have caught the rise not being applied.
    """

    def test_the_default_is_the_two_hundred_dollars_it_was_set_to(self):
        assert LLMConfig().monthly_budget_usd == 200.0

    def test_a_month_under_the_ceiling_does_not_refuse_the_call(self, session, settings):
        """$150 spent of $200: the check must pass, and it passed at $40 for years.

        Asserted through the client rather than on the setting, because the bug worth
        catching is the ceiling read in one currency and the spend recorded in another --
        which would refuse a call at $150 just as a $40 default would.
        """
        _spend(session, 150.0)

        DeepSeekClient(settings)._check_budget(0.05)

    def test_a_month_past_it_is_refused_and_the_refusal_names_the_figure(self, session, settings):
        _spend(session, 199.98)

        with pytest.raises(BudgetExceeded) as excinfo:
            DeepSeekClient(settings)._check_budget(0.05)

        message = str(excinfo.value)
        assert "200.00" in message
        assert "199.98" in message

    def test_the_report_and_the_refusal_read_the_same_ceiling(self, session, settings):
        """The strip that explains a refusal must not be able to disagree with it."""
        _spend(session, 50.0)

        report = spend_report(settings)

        assert report.ceiling_usd == settings.llm.monthly_budget_usd
        assert report.month_to_date_usd == pytest.approx(50.0)
        assert report.remaining_usd == pytest.approx(settings.llm.monthly_budget_usd - 50.0)

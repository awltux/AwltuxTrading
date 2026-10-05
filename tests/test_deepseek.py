"""The DeepSeek client's failure modes, and the classifier's response to them.

A truncated completion used to surface as ``Unterminated string starting at: line 1
column 4146`` — a message that describes a symptom at a character offset and hides
the cause. It reached a decision narrative in that form. These tests pin the
distinction between "the model returned nonsense" and "the model ran out of room",
because only the second one is worth retrying.
"""

from __future__ import annotations

import pytest

from awltux.llm.classify import classify_headline
from awltux.llm.deepseek import (
    Completion,
    DeepSeekError,
    TruncatedResponse,
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

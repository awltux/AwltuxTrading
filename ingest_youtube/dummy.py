"""A fake YouTube and a fake clock, so the pacing policy is testable offline.

`conftest.py` in this repo forces every credential to `None`: a test that reaches a
provider is a bug. The same rule applies here for a stronger reason -- the provider in
question locked this IP out once. Every test in `test_pace.py` drives these fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class FakeClock:
    """A clock that only moves when told to, and records every sleep asked of it."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeSnippet:
    text: str


@dataclass
class FakeFetched:
    snippets: list[FakeSnippet]


class VideoUnavailable(Exception):
    """Stands in for the library's own no-caption exception type name."""


class IpBlocked(Exception):
    """Stands in for `youtube_transcript_api._errors.IpBlocked`."""


@dataclass
class FakeApi:
    """Answers per video id according to a script, and counts every ask.

    ``behaviour`` maps a video id to one of:

    * a string -- the transcript to return;
    * ``"blocked"`` -- raise :class:`IpBlocked`;
    * ``"none"`` -- raise :class:`VideoUnavailable` (captions disabled);
    * ``"short"`` -- return 10 characters, which the fetcher must treat as a failure.
    """

    behaviour: dict = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    requests: int = 0

    def fetch(self, video_id: str, languages=None):  # noqa: ARG002 - mirrors the library
        self.calls.append(video_id)
        self.requests += 1
        answer = self.behaviour.get(video_id, "none")
        if answer == "blocked":
            raise IpBlocked(f"429 too many requests for {video_id}")
        if answer == "none":
            raise VideoUnavailable(video_id)
        if answer == "short":
            return FakeFetched(snippets=[FakeSnippet(text="too short")])
        return FakeFetched(
            snippets=[FakeSnippet(text=part) for part in str(answer).split(" | ")]
        )

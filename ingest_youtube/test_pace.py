"""The invariants that keep this IP out of YouTube's naughty corner.

Every test here runs offline against :mod:`dummy`. `conftest.py` in this repo forces
credentials to `None` because a test that reaches a provider is a bug; this provider
locked the machine out once, so the rule is the same with more at stake.

Run: `.venv/Scripts/python.exe -m pytest ingest_youtube/test_pace.py -q`
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fetch  # noqa: E402
from dummy import FakeApi, FakeClock  # noqa: E402
from pace import Allowed, Pacing, Policy, Refusal, looks_blocked  # noqa: E402

#: Scratch for the tests, inside the workspace.
#:
#: pytest's own `tmp_path` is not used: the system temp directory is off-limits to the
#: file sandbox this project runs under, and pytest's attempt to clean it up leaves an
#: unreadable directory behind. The repo's own convention for scratch is
#: `.tests-tmp`/`.tmp`, so that is what this uses.
SCRATCH = HERE / ".work"


@pytest.fixture()
def work() -> Path:
    """A directory of this test's own, removed afterwards so nothing leaks forward."""
    path = SCRATCH / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def pacing(work: Path, clock: FakeClock) -> Pacing:
    return Pacing(work, Policy(), clock=clock.time, sleeper=clock.sleep)


@pytest.fixture()
def store(work: Path) -> Path:
    """A transcript store of its own per test.

    Never the repo's `.tmp/transcripts`: a test that writes into the real corpus can
    pass by finding a transcript a previous test left behind, which is the offline
    version of "the fixture was already committed".
    """
    root = work / "root"
    (root / "transcripts").mkdir(parents=True)
    return root


def transcript(words: int = 80, marker: str = "") -> str:
    """Text long enough to clear `fetch.MIN_USEFUL_CHARS`.

    ``marker`` changes the content, and therefore the MD5, so a test that wants N *distinct*
    videos can have them. The first version returned one identical string for every
    video, which meant the run-cap test silently stopped testing the cap: the duplicate
    detector correctly refused to store the same words nine times, and the test read that
    as a failure only once the detector existed.
    """
    return " ".join(f"word{marker}{index}" for index in range(words))


def distinct(count: int, words: int = 80) -> dict[str, str]:
    """Behaviours for `count` videos, each with different text."""
    return {f"v{index}": transcript(words, marker=f"v{index}-") for index in range(count)}


def videos(*ids: str) -> list[dict]:
    return [
        {"id": video_id, "title": f"video {video_id}", "url": f"https://x/{video_id}"}
        for video_id in ids
    ]


def request_stamps(pacing: Pacing) -> list[float]:
    return [
        float(json.loads(line)["at"])
        for line in pacing.log_path.read_text(encoding="utf-8").splitlines()
    ]


# -- the spacing invariant ------------------------------------------------------


def test_no_two_requests_land_inside_the_minimum_interval(pacing, store):
    """A run cannot burst, whatever the caller asks for.

    The failure this prevents: the first version of the fetch tool made ~12 requests
    at 2 s spacing, then a retry loop, and the resulting block outlived the process by
    over an hour (`TODO.md`, `.tmp/youtube-probe-report-20261007.md`). Measured here as
    the smallest gap between consecutive request stamps.
    """
    api = FakeApi(behaviour=distinct(8))
    fetch.fetch_batch(
        store, videos(*[f"v{index}" for index in range(8)]),
        pacing, dry_run=False, api=api, verbose=lambda *_: None,
    )

    stamps = request_stamps(pacing)
    assert len(stamps) == 8
    gaps = [later - earlier for earlier, later in zip(stamps, stamps[1:], strict=False)]
    assert gaps, "expected more than one request"
    # Jitter only ever widens the interval, so the floor is the base interval exactly.
    assert min(gaps) >= pacing.policy.min_interval - 1e-9, gaps


def test_each_run_stops_at_its_own_cap(work, clock, store):
    """A forgotten script cannot walk a channel: the cap ends the run on its own."""
    pacing = Pacing(work, Policy(max_per_run=3), clock=clock.time, sleeper=clock.sleep)
    api = FakeApi(behaviour=distinct(10))
    summary = fetch.fetch_batch(
        store, videos(*[f"v{index}" for index in range(10)]),
        pacing, dry_run=False, api=api, verbose=lambda *_: None,
    )
    assert api.requests == 3
    assert summary["fetched"] == 3
    assert summary["refused"] is not None and summary["refused"].reason == "run_cap"


# -- the block invariant --------------------------------------------------------


def test_a_block_stops_the_run_and_is_never_retried(pacing, store):
    """The fix for the original ban: one 429 ends the run, and nothing re-asks.

    Measured as the calls the fake API received after the blocked video. The bug this
    pins: a retry on a block is what turned a rate limit into a lockout.
    """
    api = FakeApi(behaviour={"good": transcript(), "boom": "blocked", "later": transcript()})
    summary = fetch.fetch_batch(
        store, videos("good", "boom", "later"),
        pacing, dry_run=False, api=api, verbose=lambda *_: None,
    )

    assert summary["refused"] is not None
    assert summary["refused"].reason == "blocked"
    assert api.calls == ["good", "boom"], f"a request followed the block: {api.calls}"
    assert pacing.cooldown_remaining() > 0
    assert pacing.ledger["boom"]["status"] == "blocked"


def test_the_cooldown_survives_the_process_that_created_it(work, clock, store):
    """A new Pacing object -- a new process -- still refuses.

    The original failure mode in one sentence: the block outlived the script, but the
    script's memory of it did not. State is read from disk, so a restart cannot forget.
    """
    policy = Policy(cooldown_hours=24.0)
    first = Pacing(work, policy, clock=clock.time, sleeper=clock.sleep)
    first.blocked("v1", "IpBlocked: 429")

    second = Pacing(work, policy, clock=clock.time, sleeper=clock.sleep)
    verdict = second.ask("v2")
    assert isinstance(verdict, Refusal)
    assert verdict.reason == "cooldown"
    assert verdict.retry_after_seconds == pytest.approx(24 * 3600)

    clock.advance(24 * 3600 + 1)
    third = Pacing(work, policy, clock=clock.time, sleeper=clock.sleep)
    assert not isinstance(third.ask("v2"), Refusal)


def test_a_blocked_run_makes_no_request_at_all_afterwards(pacing, store):
    """Refusal is a gate, not a warning: the fetch loop does not reach the API."""
    pacing.blocked("v1", "IpBlocked: 429")
    api = FakeApi(behaviour={"v2": transcript()})
    fetch.fetch_batch(store, videos("v2"), pacing, dry_run=False, api=api,
                      verbose=lambda *_: None)
    assert api.requests == 0


# -- the daily budget -----------------------------------------------------------


def test_the_daily_cap_holds_across_separate_runs(work, clock, store):
    """One run cannot spend tomorrow's budget, however many times it is invoked.

    A calendar-day reset would allow a full budget either side of midnight; the window
    is rolling, measured from the request log rather than from anyone's counter, so a
    fresh `Pacing` -- a restarted process -- sees the same budget the last one did.
    """
    policy = Policy()
    api = FakeApi(behaviour=distinct(40))
    batch = videos(*[f"v{index}" for index in range(40)])

    for _ in range(8):  # small runs on separate invocations, as a multi-day plan is
        run = Pacing(work, policy, clock=clock.time, sleeper=clock.sleep)
        summary = fetch.fetch_batch(store, batch, run, dry_run=False, api=api,
                                    verbose=lambda *_: None)
        if summary["refused"] and summary["refused"].reason == "daily_cap":
            break

    assert api.requests == policy.max_per_day, api.requests
    verdict = Pacing(work, policy, clock=clock.time, sleeper=clock.sleep).ask("another")
    assert verdict.reason == "daily_cap"

    clock.advance(24 * 3600 + 1)
    after = Pacing(work, policy, clock=clock.time, sleeper=clock.sleep).ask("another")
    assert not isinstance(after, Refusal), "the rolling window never reopened"


def test_a_dry_run_spends_nothing(pacing, store):
    """`plan` must be free. Otherwise looking at the plan eats the budget."""
    api = FakeApi(behaviour={"v1": transcript()})
    fetch.fetch_batch(store, videos("v1"), pacing, dry_run=True, api=api,
                      verbose=lambda *_: None)
    assert api.requests == 0
    log = pacing.log_path.read_text(encoding="utf-8") if pacing.log_path.exists() else ""
    assert not log.strip()
    assert isinstance(pacing.ask("v1"), Allowed), "planning a run spent its budget"


def test_a_dry_run_reports_the_whole_run_not_just_its_first_item(pacing, store):
    """The plan has to show everything a live run would attempt.

    Measured as the number of items reported. The bug this pins: the dry run advanced
    the live run counter as it went, so it hit the run cap after one item and printed
    "1 fetched" for a hundred-video queue -- a plan that says the queue is one video.
    """
    api = FakeApi(behaviour=distinct(20))
    summary = fetch.fetch_batch(
        store, videos(*[f"v{index}" for index in range(20)]), pacing,
        dry_run=True, api=api, verbose=lambda *_: None,
    )
    assert summary["fetched"] == pacing.policy.max_per_run
    assert api.requests == 0
    assert isinstance(pacing.ask("v0"), Allowed)


# -- attempts, absence and failure ----------------------------------------------


def test_a_video_without_captions_is_absent_and_is_not_re_asked(pacing, store):
    """Absent is not failed, and neither is retried forever.

    `no_captions` and `error` are separate statuses on purpose: merging them is how a
    fetch failure becomes a silent gap in the research.
    """
    api = FakeApi(behaviour={"nocap": "none", "broken": "short"})
    first = fetch.fetch_batch(store, videos("nocap", "broken"), pacing,
                              dry_run=False, api=api, verbose=lambda *_: None)
    assert first["absent"] == 1 and first["failed"] == 1
    assert pacing.status("nocap") == "no_captions"
    assert pacing.status("broken") == "error"

    fetch.fetch_batch(store, videos("nocap", "broken"), pacing,
                      dry_run=False, api=api, verbose=lambda *_: None)
    assert api.calls.count("nocap") == 1, "an absent video was asked twice"
    assert api.calls.count("broken") == 2, "a failed video should get its one retry"


def test_attempts_run_out_rather_than_looping(pacing, store):
    """Past the attempt cap the video is skipped, not re-asked indefinitely."""
    api = FakeApi(behaviour={"flaky": "short"})
    for _ in range(4):
        fetch.fetch_batch(store, videos("flaky"), pacing, dry_run=False,
                          api=api, verbose=lambda *_: None)
    assert api.calls.count("flaky") == pacing.policy.max_attempts_per_video


def test_a_transcript_already_on_disk_is_never_requested(pacing, store):
    """Re-fetching what is already held is the most expensive mistake available.

    Measured as zero requests for a video whose text is already in the store.
    """
    (store / "transcripts" / "held.txt").write_text(transcript(120), encoding="utf-8")
    api = FakeApi(behaviour={"held": transcript()})
    summary = fetch.fetch_batch(store, videos("held"), pacing, dry_run=False,
                                api=api, verbose=lambda *_: None)
    assert api.requests == 0
    assert summary["skipped"] == 1


def test_a_re_upload_is_recognised_by_content_and_not_stored_twice(pacing, store):
    """The same lecture under a second video id is one transcript, not two.

    The same talk appears on several of these channels and channels re-upload, so this
    is expected rather than surprising. Measured by MD5 of the text: one file on disk,
    the duplicate recorded in the ledger against the original, and both requests still
    accounted for -- the request was spent either way, so only the second copy is saved.
    """
    same = "the discount rate and the cost of capital " * 30
    normalised = " ".join(same.split())
    api = FakeApi(behaviour={"original": same, "reupload": same, "other": transcript(90)})
    summary = fetch.fetch_batch(
        store, videos("original", "reupload", "other"),
        pacing, dry_run=False, api=api, verbose=lambda *_: None,
    )

    assert summary["fetched"] == 2
    assert summary["duplicate"] == 1
    assert sorted(path.stem for path in (store / "transcripts").glob("*.txt")) == [
        "original", "other",
    ]
    assert pacing.ledger["reupload"]["status"] == "duplicate"
    assert pacing.ledger["reupload"]["duplicate_of"] == "original"
    # MD5 of the *stored* form: the fetcher normalises whitespace, so hashing the raw
    # fixture would compare two different strings and appear to be a detector bug.
    assert pacing.ledger["reupload"]["content_md5"] == fetch.content_hash(normalised)
    assert (store / "transcripts" / "original.txt").read_text(
        encoding="utf-8"
    ) == normalised
    # Both requests happened, so both are on the record: a duplicate saves storage,
    # not quota, and a ledger that hid the second would misreport what was spent.
    assert summary["requests"] == 3


def test_duplicate_detection_spans_runs(pacing, store):
    """A re-upload is caught against content fetched in an earlier run, not just this one."""
    same = "operating income and reinvestment " * 30
    api = FakeApi(behaviour={"first": same})
    fetch.fetch_batch(store, videos("first"), pacing, dry_run=False, api=api,
                      verbose=lambda *_: None)

    later = FakeApi(behaviour={"second": same})
    summary = fetch.fetch_batch(store, videos("second"), pacing, dry_run=False,
                                api=later, verbose=lambda *_: None)
    assert summary["duplicate"] == 1
    assert not (store / "transcripts" / "second.txt").exists()


def test_the_duplicate_map_is_written_for_the_report(pacing, store):
    same = "terminal value and stable growth " * 30
    api = FakeApi(behaviour={"a": same, "b": same})
    fetch.fetch_batch(store, videos("a", "b"), pacing, dry_run=False, api=api,
                      verbose=lambda *_: None)

    recorded = fetch.load_duplicates(store)
    assert recorded == {fetch.content_hash(" ".join(same.split())): ["b"]}


# -- block detection ------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("IpBlocked: ...", True),
        ("HTTP Error 429: Too Many Requests", True),
        ("Sign in to confirm you're not a bot", True),
        ("NoTranscriptFound: no captions", False),
        ("VideoUnavailable", False),
    ],
)
def test_block_detection_matches_both_libraries(message, expected):
    """Missing a block is the expensive direction; the predicate errs towards stopping."""
    assert looks_blocked(message) is expected

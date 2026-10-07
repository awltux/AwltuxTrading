"""The download record, and when the next run may safely happen.

The requirement: *the script can be re-run at any time and not cause a rate limit.*
Two halves, and they are different things:

* **Enforcement** -- a request past the rolling cap is refused before it is made, so a
  re-run cannot over-spend. `test_pace.py` covers that.
* **Answerability** -- the record says what was downloaded, when, and exactly when the
  next request becomes possible. That is this file. Without it, "safe to re-run" is
  true but useless, because the operator cannot tell whether to wait two minutes or a
  day, and the tempting move is to try and see.

Run: `.venv/Scripts/python.exe -m pytest ingest_youtube/test_quota.py -q -p no:cacheprovider
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

from dummy import FakeClock  # noqa: E402
from pace import (  # noqa: E402
    DAY_SECONDS,
    Pacing,
    Policy,
    day_stamp,
    start_of_local_day,
)

SCRATCH = HERE / ".work"
HOUR = 3600.0


@pytest.fixture()
def work() -> Path:
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
    return Pacing(work, Policy(max_per_day=5, max_per_run=2), clock=clock.time,
                  sleeper=clock.sleep)


def spend(pacing: Pacing, video_id: str) -> None:
    """One request, logged the way the fetcher logs it."""
    assert not isinstance(pacing.ask(video_id), type(None))
    pacing.spend(video_id, f"https://youtu.be/{video_id}")


# -- the schedule ---------------------------------------------------------------


def test_the_schedule_names_the_moment_the_nth_slot_frees(pacing, clock):
    """With the window full, the next slot is the oldest request's 24h expiry.

    The failure this prevents is the one that caused the original block: trying again
    to find out. The answer is a timestamp, not an experiment.
    """
    for index in range(5):
        spend(pacing, f"v{index}")
        clock.advance(HOUR)

    now = clock.time()
    slots = pacing.slots(count=3)
    assert [nth for _, nth in slots] == [1, 2, 3]
    # Oldest request expires 24h after it was made; each subsequent one an hour later.
    assert slots[0][0] == pytest.approx(pacing._requests()[0] + DAY_SECONDS)
    assert slots[1][0] - slots[0][0] == pytest.approx(HOUR)
    assert all(instant > now for instant, _ in slots)


def test_free_slots_come_first_and_start_now(pacing, clock):
    """A window with room answers "now" rather than inventing a delay."""
    for index in range(2):
        spend(pacing, f"v{index}")
        clock.advance(HOUR)

    slots = pacing.slots(count=4)
    assert slots[0][0] == pytest.approx(clock.time())
    # Three free (5 - 2), then the window starts expiring.
    assert slots[2][0] == pytest.approx(clock.time())
    assert slots[3][0] == pytest.approx(pacing._requests()[0] + DAY_SECONDS)


def test_the_schedule_keeps_going_beyond_the_first_window(pacing, clock):
    """Ten slots are projected, crossing into a second window.

    A schedule that stopped at the first expiry would say "come back tomorrow" and be
    wrong by hours for everything after the first few.
    """
    for index in range(5):
        spend(pacing, f"v{index}")
        clock.advance(HOUR)

    slots = pacing.slots(count=10)
    assert len(slots) == 10
    days = {int(instant) // int(DAY_SECONDS) for instant, _ in slots}
    assert len(days) > 1, "the projection never left the first window"
    # Monotonic: a schedule that went backwards would name a time already passed.
    assert [instant for instant, _ in slots] == sorted(instant for instant, _ in slots)


def test_a_cooldown_projects_nothing(pacing):
    """A block is the far end saying stop; there is no schedule through it."""
    pacing.blocked("v1", "IpBlocked: 429")
    assert pacing.slots(count=5) == []
    availability = pacing.availability()
    assert availability["cooldown_seconds"] > 0
    assert availability["slots"] == []


def test_availability_reports_what_is_spendable_now(pacing, clock):
    for index in range(3):
        spend(pacing, f"v{index}")
    state = pacing.availability()
    assert state["in_window"] == 3
    assert state["per_day"] == 5
    assert state["free"] == 2
    assert state["next_at"] is None, "the window is not full, so nothing is blocked"

    clock.advance(HOUR)
    spend(pacing, "v3")
    spend(pacing, "v4")
    full = pacing.availability()
    assert full["free"] == 0
    assert full["next_at"] == pytest.approx(pacing._requests()[0] + DAY_SECONDS)


# -- the record -----------------------------------------------------------------


def test_history_groups_requests_by_local_day(work):
    """The record the task asked for: what was downloaded, on which day, at what times.

    Built from the same log the caps are enforced from. A separate counter would be a
    second source of truth and would eventually disagree with the one that limits.

    The clock is pinned to a *local* midnight rather than left at the fake's default
    epoch: the first version started 73 minutes before midnight, so "advance a day" and
    "advance an hour" landed on three dates instead of two and the assertion depended on
    the calendar rather than on the grouping.
    """
    midnight = start_of_local_day() + 12 * HOUR
    clock = FakeClock(start=midnight)
    pacing = Pacing(work, Policy(max_per_day=5, max_per_run=2), clock=clock.time,
                    sleeper=clock.sleep)

    spend(pacing, "aaa")
    clock.advance(2 * HOUR)
    spend(pacing, "bbb")
    clock.advance(10 * HOUR + 60)  # past local midnight, into the next day
    spend(pacing, "ccc")

    history = pacing.history()
    assert len(history) == 2, [record["date"] for record in history]
    first, second = history
    assert first["date"] < second["date"]
    assert first["requests"] == 2
    assert first["videos"] == ["aaa", "bbb"]
    assert first["last"] - first["first"] == pytest.approx(2 * HOUR)
    assert second["requests"] == 1
    assert second["videos"] == ["ccc"]
    # The printed record uses local time, which is what the reader's clock shows.
    assert day_stamp(first["first"]).startswith(first["date"])


def test_history_survives_a_restart(pacing, work, clock):
    """The record is on disk, so a new process reads the same days."""
    spend(pacing, "aaa")
    clock.advance(HOUR)
    spend(pacing, "bbb")

    reopened = Pacing(work, Policy(max_per_day=5), clock=clock.time, sleeper=clock.sleep)
    history = reopened.history()
    assert len(history) == 1
    assert history[0]["videos"] == ["aaa", "bbb"]
    assert history[0]["requests"] == 2


def test_history_ignores_an_unreadable_log_line(pacing, work):
    """A truncated tail must not take the record with it."""
    spend(pacing, "aaa")
    with pacing.log_path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    assert pacing.history()[0]["requests"] == 1


def test_the_record_and_the_cap_read_the_same_log(pacing, work):
    """One source of truth: the count in the record is the count the cap enforces."""
    for index in range(4):
        spend(pacing, f"v{index}")
    recorded = sum(record["requests"] for record in pacing.history())
    logged = len([line for line in pacing.log_path.read_text(encoding="utf-8").splitlines() if line])
    assert recorded == logged == pacing.availability()["in_window"]
    # And the JSON on disk is what the record claims it is.
    first = json.loads(pacing.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert set(first) >= {"at", "video", "url"}

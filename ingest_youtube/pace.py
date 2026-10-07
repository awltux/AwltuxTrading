"""The pacing policy: when this machine is allowed to ask YouTube for anything.

The single measured fact this module exists for: this IP was blocked from YouTube's
caption endpoint once, by a run that **retried a `429`**. The block outlived the
process that caused it by more than an hour (`.tmp/youtube-probe-report-20261007.md`).
Nothing here retries a block, and every other number is chosen to be wider than the
run that caused it.

The module owns two things that must not be duplicated elsewhere:

* **The decision**, as a pure function of (policy, state, now) -> `Allowed` or
  `Refusal`. Time is injected, so the whole policy is testable without sleeping.
* **The record**, on disk, because a cooldown that lives only in memory guarantees a
  repeat: the process that gets blocked is not the process that has to remember it.

A refusal is not a warning. When `ask()` refuses, no request leaves the machine.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Seconds between two caption requests, before jitter.
#:
#: Measured: ~12 transcripts at 2 s spacing were fine, then a sustained retry loop
#: triggered a block. 6 s is not a target to tune down -- the cost of being too slow
#: is a run that takes longer, the cost of being too fast is another lockout.
DEFAULT_MIN_INTERVAL = 6.0

#: Fraction by which each interval is randomised. A perfectly regular interval is a
#: signature in itself and puts every request on the same second boundary.
DEFAULT_JITTER = 0.3

#: Most requests one run will make. `youtube-transcript-api` issue #467 reports the
#: endpoint answering 429 after roughly 2-3 requests on some addresses, so the safe
#: zone is small and the run should stop well inside it on its own.
DEFAULT_MAX_PER_RUN = 12

#: Most requests in any 24 hours, counted from the request log rather than the
#: calendar. A calendar day resets at midnight, which allows a full budget either
#: side of it; a rolling window cannot be gamed that way.
DEFAULT_MAX_PER_DAY = 15

#: How long to refuse everything after a block. The measured fact is "> 1 hour"; 12 h
#: is the skill's conservative default and 24 h is the cheap side of the bet for a
#: corpus that is being fetched over weeks anyway. This is **this project's number,
#: not YouTube's** -- the official terms state no cooldown duration at all.
DEFAULT_COOLDOWN_HOURS = 24.0

#: How many times one video may be attempted before it is left alone. A video that
#: yields no captions yields none on the second ask either; the ledger records it and
#: the run moves on.
MAX_ATTEMPTS_PER_VIDEO = 2

DAY_SECONDS = 86_400.0


@dataclass(frozen=True)
class Policy:
    """Every knob the pacing decision reads, in one place."""

    min_interval: float = DEFAULT_MIN_INTERVAL
    jitter: float = DEFAULT_JITTER
    max_per_run: int = DEFAULT_MAX_PER_RUN
    max_per_day: int = DEFAULT_MAX_PER_DAY
    cooldown_hours: float = DEFAULT_COOLDOWN_HOURS
    max_attempts_per_video: int = MAX_ATTEMPTS_PER_VIDEO


@dataclass(frozen=True)
class Allowed:
    """The request may proceed. ``delay`` is what the caller must sleep first."""

    delay: float
    run_calls: int
    day_calls: int


@dataclass(frozen=True)
class Refusal:
    """The request must not be made. ``reason`` is a stable token for the report."""

    reason: str
    detail: str
    retry_after_seconds: float = 0.0


@dataclass
class _State:
    """Mutable view of the two files, held only for the duration of one decision."""

    cooldown: dict = field(default_factory=dict)
    ledger: dict = field(default_factory=dict)
    log: list = field(default_factory=list)


class Pacing:
    """The gate every YouTube request passes through.

    ``clock`` and ``sleeper`` are injected so a test can drive weeks of policy in
    microseconds. Nothing in this class makes a network call; nothing in the fetcher
    makes a request without calling :meth:`ask` first.
    """

    def __init__(
        self,
        root: Path,
        policy: Policy | None = None,
        clock=time.time,
        sleeper=time.sleep,
    ) -> None:
        self.root = Path(root)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.cooldown_path = self.state_dir / "cooldown.json"
        self.ledger_path = self.state_dir / "ledger.json"
        self.log_path = self.state_dir / "requests.jsonl"
        self.policy = policy or Policy()
        self.clock = clock
        self.sleeper = sleeper
        self.run_calls = 0

    # -- persistence ------------------------------------------------------------

    def _read_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return default

    def _write_json(self, path: Path, payload) -> None:
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    @property
    def ledger(self) -> dict:
        return self._read_json(self.ledger_path, {})

    def record(self, video_id: str, **fields) -> None:
        """Merge ``fields`` into one video's ledger entry and write it immediately.

        Written after every video rather than at the end of the run: a run that is
        killed has to leave behind an accurate account of what it already spent.
        """
        ledger = self.ledger
        entry = ledger.get(video_id) or {}
        entry.update(fields)
        entry["updated_at"] = self.clock()
        ledger[video_id] = entry
        self._write_json(self.ledger_path, ledger)

    def attempts(self, video_id: str) -> int:
        return int((self.ledger.get(video_id) or {}).get("attempts") or 0)

    def status(self, video_id: str) -> str:
        return (self.ledger.get(video_id) or {}).get("status") or "todo"

    # -- the request log --------------------------------------------------------

    def _requests(self) -> list[float]:
        """Every request timestamp on record, newest last."""
        if not self.log_path.exists():
            return []
        stamps: list[float] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                stamps.append(float(json.loads(line)["at"]))
            except (ValueError, KeyError, TypeError):
                continue
        return stamps

    def _note_request(self, video_id: str, url: str) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"at": self.clock(), "video": video_id, "url": url}) + "\n"
            )

    # -- the gate ---------------------------------------------------------------

    def ask(self, video_id: str, url: str = "") -> Allowed | Refusal:
        """Whether one more request may be made right now, and how long to wait first.

        The checks are ordered by what binds first: a live cooldown beats everything
        (the remote end has said stop), then the video's own attempt count (re-asking
        a video that has already failed twice is how a run turns into a retry loop),
        then the per-run cap, then the rolling daily cap.
        """
        now = self.clock()
        policy = self.policy

        cooldown = self._read_json(self.cooldown_path, {})
        until = float(cooldown.get("until") or 0.0)
        if until > now:
            return Refusal(
                "cooldown",
                f"blocked at {_stamp(cooldown.get('started'))}; "
                f"{_duration(until - now)} of the {policy.cooldown_hours:g}h cooldown remain",
                retry_after_seconds=until - now,
            )

        attempts = self.attempts(video_id)
        if attempts >= policy.max_attempts_per_video:
            return Refusal(
                "attempts_exhausted",
                f"{video_id} attempted {attempts}x already "
                f"(status {self.status(video_id)}); not asking again",
            )

        if self.run_calls >= policy.max_per_run:
            return Refusal(
                "run_cap",
                f"this run has made {self.run_calls} requests "
                f"(cap {policy.max_per_run}); stop here and start a later run",
            )

        recent = [at for at in self._requests() if now - at < DAY_SECONDS]
        if len(recent) >= policy.max_per_day:
            oldest = min(recent)
            wait = DAY_SECONDS - (now - oldest)
            return Refusal(
                "daily_cap",
                f"{len(recent)} requests in the last 24h (cap {policy.max_per_day}); "
                f"the window frees in {_duration(wait)}",
                retry_after_seconds=wait,
            )

        delay = self._spacing_delay(now, recent)
        return Allowed(delay=delay, run_calls=self.run_calls, day_calls=len(recent))

    def _spacing_delay(self, now: float, recent: list[float]) -> float:
        """Seconds to sleep so this request is not too close to the previous one.

        Randomised *upward only* around the base interval: the jitter exists to break
        the regularity of the pattern, and it must not be able to produce a gap
        shorter than the interval that was measured to be safe.
        """
        if not recent:
            return 0.0
        last = max(recent)
        target = self.policy.min_interval * (1.0 + random.uniform(0.0, self.policy.jitter))
        return max(0.0, target - (now - last))

    def spend(self, video_id: str, url: str = "") -> None:
        """Record that a request was actually made. Called *after* it succeeds."""
        self.run_calls += 1
        self._note_request(video_id, url)

    # -- outcomes ---------------------------------------------------------------

    def blocked(self, video_id: str, detail: str) -> Path:
        """A block signal: stop everything for the cooldown and record why.

        Called from the fetcher the moment a block is seen, before any other request
        is considered. This is the whole difference between a rate limit and a ban.
        """
        now = self.clock()
        until = now + self.policy.cooldown_hours * 3600
        self._write_json(
            self.cooldown_path,
            {
                "started": now,
                "until": until,
                "hours": self.policy.cooldown_hours,
                "video": video_id,
                "detail": detail[:300],
                "reason": "blocked: stop, do not retry",
            },
        )
        self.record(video_id, status="blocked", error=detail[:200], attempts=self.attempts(video_id))
        return self.cooldown_path

    def clear_cooldown(self) -> None:
        if self.cooldown_path.exists():
            self.cooldown_path.unlink()

    def cooldown_remaining(self, now: float | None = None) -> float:
        until = float(self._read_json(self.cooldown_path, {}).get("until") or 0.0)
        return max(0.0, until - (now if now is not None else self.clock()))

    def next_run_hint(self) -> str:
        """When a later run could start, for the operations report."""
        remaining = self.cooldown_remaining()
        if remaining > 0:
            return f"cooldown: wait {_duration(remaining)}"
        now = self.clock()
        recent = [at for at in self._requests() if now - at < DAY_SECONDS]
        if len(recent) >= self.policy.max_per_day:
            return f"daily cap: wait {_duration(DAY_SECONDS - (now - min(recent)))}"
        return f"ready now ({len(recent)}/{self.policy.max_per_day} in the last 24h)"

    # -- the schedule -----------------------------------------------------------

    def slots(self, count: int = 10, now: float | None = None) -> list[tuple[float, int]]:
        """When the next ``count`` requests become available, as ``(instant, nth)``.

        The whole point is that the script can be re-run at any time without risk and
        without guesswork: the next run's *earliest* moment is a fact rather than an
        estimate, because it is computed from the request log rather than remembered.

        A rolling window is what makes this answerable. The Nth future slot is the
        moment the Nth-oldest logged request falls exactly 24 h into the past -- and,
        once those are consumed, the slot after them. So the schedule is built by
        replaying the window that is known: for the free slots first, then by expiring
        the oldest recorded request and asking again.

        A cooldown is not a slot: it is the far end saying stop, so nothing is projected
        through it.
        """
        now = self.clock() if now is None else now
        cooldown = self.cooldown_remaining(now)
        if cooldown > 0:
            return []

        logged = sorted(at for at in self._requests() if at <= now)
        # Instants at which the window has room, working forward from now.
        plan: list[tuple[float, int]] = []
        future = list(logged)
        moment = now
        nth = 0
        while len(plan) < count:
            window = [at for at in future if moment - at < DAY_SECONDS]
            if len(window) < self.policy.max_per_day:
                nth += 1
                plan.append((moment, nth))
                # A request made now is itself in the window for the next 24 h.
                future.append(moment)
                if len(plan) >= count:
                    break
                continue
            # Full: the next moment anything can happen is when the oldest of the
            # requests still inside the window expires.
            moment = min(window) + DAY_SECONDS
        return plan

    def history(self) -> list[dict]:
        """Requests grouped by local date, for the record the task asked to keep.

        Built from the same log the caps are enforced from, so the record cannot drift
        from what is actually being limited -- a separate counter is a second source of
        truth and would eventually disagree with the one that matters.
        """
        days: dict[str, dict] = {}
        for entry in self._request_entries():
            day = _stamp(entry["at"])[:10]
            record = days.setdefault(
                day, {"date": day, "requests": 0, "first": None, "last": None, "videos": []}
            )
            record["requests"] += 1
            record["first"] = entry["at"] if record["first"] is None else min(record["first"], entry["at"])
            record["last"] = entry["at"] if record["last"] is None else max(record["last"], entry["at"])
            record["videos"].append(entry.get("video"))
        return [days[day] for day in sorted(days)]

    def _request_entries(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        entries: list[dict] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                float(entry["at"])
            except (ValueError, KeyError, TypeError):
                continue
            entries.append(entry)
        return sorted(entries, key=lambda entry: entry["at"])

    def availability(self, now: float | None = None) -> dict:
        """The whole answer: spendable now, when the window frees, and the schedule."""
        now = self.clock() if now is None else now
        recent = [at for at in self._requests() if now - at < DAY_SECONDS]
        free = max(0, self.policy.max_per_day - len(recent))
        return {
            "now": now,
            "in_window": len(recent),
            "per_day": self.policy.max_per_day,
            "per_run": self.policy.max_per_run,
            "free": free,
            "cooldown_seconds": self.cooldown_remaining(now),
            "next_at": (min(recent) + DAY_SECONDS) if free == 0 and recent else None,
            "slots": self.slots(now=now),
        }


def looks_blocked(message: str) -> bool:
    """Whether error text means *stop*, as opposed to *that one did not work*.

    Matches both libraries' vocabulary -- `IpBlocked` from youtube-transcript-api,
    `HTTP Error 429` from yt-dlp, and the bot wall's "sign in to confirm" -- so a
    block cannot be handled in one code path and missed in the other. Missing a block
    is the expensive direction, so the predicate errs towards calling things blocks.
    """
    lowered = (message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "ipblocked",
            "ip blocked",
            "429",
            "too many requests",
            "sign in to confirm",
            "captcha",
        )
    )


def _stamp(value) -> str:
    return day_stamp(value)


def day_stamp(value) -> str:
    """A local-time timestamp, for the record a reader has to make sense of.

    Local rather than UTC because the record exists to be read by someone deciding
    whether to run the fetch now, and "18:26" in the log has to mean the same thing as
    the clock on the wall. The window itself is computed in UTC seconds and does not
    care about the timezone.
    """
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except (TypeError, ValueError):
        return "unknown"


def start_of_local_day(when: float | None = None) -> float:
    """The local midnight at or before ``when``, as a Unix timestamp.

    Exists so the daily record groups by the day a reader recognises. The *window* is
    a rolling 24 hours and needs no such thing; only the printed history does.
    """
    moment = time.localtime(time.time() if when is None else float(when))
    midnight = time.struct_time(
        (moment.tm_year, moment.tm_mon, moment.tm_mday, 0, 0, 0, moment.tm_wday,
         moment.tm_yday, moment.tm_isdst)
    )
    return time.mktime(midnight)


def _duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"

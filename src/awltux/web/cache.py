"""A small in-process cache for rendered pages, with an expiry.

**Why this exists.** The instrument page is twenty queries and a Jinja render, and the browser
asks for *the same URL* again whenever a reader comes Back, reloads, or duplicates a tab. After
the page was trimmed (2026-10-20) a load is **69-87 ms** warm -- and this cache is what turns a
repeat of the same URL in the same few seconds into a dictionary lookup.

**What it is not for.** Ten tabs on ten *different* instruments share nothing, which is why the
ten-tab problem is a process-count problem rather than a cache problem. This helps the case it
can see: the same page asked for twice.

**Only pages that cannot be visibly stale.** The entry holds a rendered string, so no ORM object
outlives its session, and the TTL is short enough that a decision made a moment ago shows up. A
route that *mutates* the page clears it (see `dashboard.instrument_refresh`); the TTL is the
backstop for the routes that do not.

Keyed by a tuple the caller builds, and per-process: with several uvicorn workers each would
hold its own, which is fine for a cache whose entries expire in seconds.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

#: How long a rendered page may be reused.
#:
#: Five seconds is the compromise the page's own freshness allows: the summary strip carries a
#: price and a decision that change hourly, and the only thing a reader does inside five seconds
#: of a page is come back to it.
PAGE_TTL_SECONDS = 5.0

#: How many pages to keep. The universe is 500 instruments, so this is a cache for what a reader
#: is actually moving between, not for the whole table.
MAX_PAGES = 64


@dataclass(frozen=True, slots=True)
class _Entry:
    body: str
    expires_at: float


class TTLCache:
    """Bounded, expiring, thread-safe. One lock, no background sweeper.

    No sweeper on purpose: a timestamp per entry and a purge on write is enough at this size,
    and a thread per cache would be a thread the process does not need.
    """

    def __init__(self, *, seconds: float = PAGE_TTL_SECONDS, entries: int = MAX_PAGES) -> None:
        self._seconds = seconds
        self._entries = entries
        self._lock = threading.Lock()
        self._values: dict[tuple[object, ...], _Entry] = {}
        #: How many reads were served from memory, and how many missed. Read by tests and by
        #: anyone asking whether the cache is doing anything at all.
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[object, ...]) -> str | None:
        now = time.monotonic()
        with self._lock:
            entry = self._values.get(key)
            if entry is None or entry.expires_at <= now:
                self._values.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return entry.body

    def set(self, key: tuple[object, ...], body: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._values) >= self._entries:
                self._purge(now)
            self._values[key] = _Entry(body=body, expires_at=now + self._seconds)

    def invalidate(self, prefix: tuple[object, ...]) -> int:
        """Drop every entry whose key starts with ``prefix``. Returns how many went.

        A mutation route calls this with the ticker, because a page that shows a refresh's
        outcome must not be a page rendered before it started.
        """
        with self._lock:
            doomed = [key for key in self._values if key[: len(prefix)] == prefix]
            for key in doomed:
                del self._values[key]
            return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def _purge(self, now: float) -> None:
        """Drop expired entries, then the oldest, until there is room. Caller holds the lock."""
        for key in [key for key, entry in self._values.items() if entry.expires_at <= now]:
            del self._values[key]
        while len(self._values) >= self._entries:
            oldest = min(self._values, key=lambda key: self._values[key].expires_at)
            del self._values[oldest]

    def __len__(self) -> int:
        return len(self._values)

"""Store UTC, show the viewer's clock.

Two rules, and they are separate rules:

**Store UTC.** Every timestamp written to the database is UTC. That is already how
``utcnow()`` works, but "already" is not the same as "checked" -- ``date.today()``
returns a *local* date, and a local date used as a storage key or a cutoff is
wrong by a day for part of every day. :func:`utc_today` exists so the distinction
is visible at the call site instead of hiding inside a stdlib name that reads as
harmless.

**Display the viewer's zone.** A timestamp rendered in UTC is correct and, for
anyone not on UTC, useless: "the price was observed at 08:30" is a different fact
in London and in New York. So the display zone is resolved per request:

1. the ``awltux_tz`` cookie, which the browser sets from
   ``Intl.DateTimeFormat().resolvedOptions().timeZone`` -- the actual zone the
   reader's clock is in, including where daylight saving puts it;
2. the configured ``app.timezone``;
3. UTC.

The zone is never guessed from an IP address or a language header, because both
are wrong often enough to matter and neither is the reader's clock.

Every rendered time carries its zone, so a screenshot of the dashboard is never
ambiguous about what "14:32" meant. The stored value is always UTC and the API
returns ISO-8601 with an offset, so nothing downstream has to know about this.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: The cookie the browser uses to tell the server which clock it is on.
ZONE_COOKIE = "awltux_tz"

#: Used when nothing is configured. UTC is the honest default: it is what the
#: database holds and it cannot be wrong about daylight saving.
FALLBACK_ZONE_NAME = "UTC"

#: Longest zone name we will even look at. Real ones are well under this.
_MAX_ZONE_NAME = 64

_UTC_ZONE = ZoneInfo(FALLBACK_ZONE_NAME)


@lru_cache(maxsize=1)
def known_zones() -> frozenset[str]:
    """Every zone name the tz database on this machine knows.

    Used as the validator. ``ZoneInfo`` keys are filesystem paths under the tz
    data directory, so accepting an arbitrary cookie value would hand a remote
    string to a path lookup; checking membership in the real set first is both
    safer and simpler than trying to sanitise the string.
    """
    from zoneinfo import available_timezones

    try:
        return frozenset(available_timezones()) | {FALLBACK_ZONE_NAME}
    except Exception:  # pragma: no cover - only if the tz database is unreadable
        return frozenset({FALLBACK_ZONE_NAME})


def parse_zone(name: Any) -> ZoneInfo | None:
    """A :class:`ZoneInfo` for a name, or ``None`` if it is not a real zone."""
    if not isinstance(name, str):
        return None
    candidate = name.strip()
    if not candidate or len(candidate) > _MAX_ZONE_NAME:
        return None
    if candidate not in known_zones():
        return None
    try:
        return ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def resolve_zone(cookie_value: Any, configured: str | None = None) -> ZoneInfo:
    """The zone to render in: the reader's, else the configured one, else UTC."""
    return parse_zone(cookie_value) or parse_zone(configured) or _UTC_ZONE


def utc_today() -> dt.date:
    """Today in UTC.

    Not the same as ``date.today()``, which is today *here*, whoever "here" is.
    Use this for anything that becomes a stored key or a comparison against stored
    data.
    """
    return dt.datetime.now(dt.UTC).date()


def utc_day_start(moment: dt.datetime | None = None) -> dt.datetime:
    """Midnight UTC of the day containing ``moment`` (default: now)."""
    moment = moment or dt.datetime.now(dt.UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Normalise a datetime read back from storage to aware UTC.

    SQLite returns naive datetimes however the column was declared, so this is
    needed far more often than it looks. Comparing a naive value to an aware one
    raises rather than returning a wrong answer, which is the good failure mode,
    but it still fails.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def to_zone(value: dt.datetime, zone: ZoneInfo) -> dt.datetime:
    """Convert a stored timestamp into the display zone."""
    aware = as_utc(value)
    assert aware is not None
    return aware.astimezone(zone)


def zone_label(moment: dt.datetime, zone: ZoneInfo) -> str:
    """Short zone label, e.g. ``BST``, ``EST``, ``UTC``, or an offset.

    Falls back to a numeric offset because not every zone has an abbreviation, and
    a time with no zone at all is the thing this module exists to avoid.
    """
    local = to_zone(moment, zone)
    name = local.tzname()
    if name and not name.startswith(("+", "-")):
        return name
    offset = local.utcoffset() or dt.timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def format_moment(
    value: dt.datetime | None,
    fmt: str = "%Y-%m-%d %H:%M",
    *,
    zone: ZoneInfo | None = None,
    with_zone: bool | None = None,
) -> str:
    """Render a stored timestamp in the display zone, labelled with its zone.

    ``with_zone`` defaults to "yes when the format shows a time of day". A date
    with no clock has no zone to disambiguate, and appending one would be noise.
    """
    if value is None:
        return "—"
    zone = zone or current_zone()
    local = to_zone(value, zone)
    text = local.strftime(fmt)
    if with_zone is None:
        with_zone = "%H" in fmt or "%I" in fmt
    if with_zone:
        text = f"{text} {zone_label(value, zone)}"
    return text


def format_iso(value: dt.datetime | None) -> str | None:
    """ISO-8601 with an explicit offset, always in UTC.

    What the API returns and what goes into a ``<time datetime>`` attribute: an
    unambiguous instant that any consumer can localise for itself.
    """
    aware = as_utc(value)
    return aware.isoformat() if aware else None


# --------------------------------------------------------------------------- #
# per-request display zone
# --------------------------------------------------------------------------- #

#: The zone the current request is being rendered in. A ContextVar rather than a
#: parameter threaded through every template call: a filter that silently falls
#: back to UTC when someone forgets an argument is exactly the kind of quiet
#: wrongness this codebase tries not to ship.
_current_zone: ContextVar[ZoneInfo] = ContextVar("awltux_display_zone", default=_UTC_ZONE)


def current_zone() -> ZoneInfo:
    return _current_zone.get()


def current_zone_name() -> str:
    return _current_zone.get().key


def current_zone_note() -> str:
    """Human description of the display zone, e.g. ``Europe/London (BST)``.

    Shown once per page so a reader always knows which clock they are reading,
    including when daylight saving has moved it. The abbreviation is dropped when
    it merely repeats the name, because "UTC (UTC)" is noise.
    """
    zone = _current_zone.get()
    label = zone_label(dt.datetime.now(dt.UTC), zone)
    return zone.key if label == zone.key else f"{zone.key} ({label})"


@contextmanager
def display_zone(zone: ZoneInfo) -> Iterator[ZoneInfo]:
    token = _current_zone.set(zone)
    try:
        yield zone
    finally:
        _current_zone.reset(token)

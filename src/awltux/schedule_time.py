"""The daily trigger time: where it is stored, and how it becomes an instant.

Asked for 2026-10-23: *"Add a validated time 24hr input field to the Operations page for the
daily trigger time. Populate with the default trigger time. Set default trigger time as 06:00.
Ensure the trigger is caught up if the app wasnt running at the trigger time and the event wasnt
fired."*

**A time of day, in the configured zone, not a UTC offset.** ``06:00`` means six in the morning
where ``app.timezone`` says the reader is, which is what a person means by it; storing an offset
would be wrong for half the year the moment the clocks change. Everything is converted to UTC at
the boundary (:func:`next_anchor`) and nothing downstream knows about zones.

**Two places, and one winner.** ``config/config.yaml`` carries the default
(``schedule.daily_at``), and the Operations page can override it; the override is a row in
``app_setting`` (the same table the universe selection and the learned captions live in) so it
survives a restart without editing a file baked into the image. :func:`effective` is the one
reader, so the page, the scheduler and any test cannot disagree about which value is in force.

**A missed trigger is not a lost one.** The value only decides *when* a cycle is due; whether a
cycle was missed is `scheduler/catchup.py`'s question, and it is answered from the run history
against each job's interval. So an app that was off at 06:00 starts, works out that its jobs are
more than a day past their last success, and runs them -- in dependency order, through the queue.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from zoneinfo import ZoneInfo

    from sqlalchemy.orm import Session

    from awltux.config import Settings

#: The key the override is stored under. Dotted like the config path it shadows, so a reader of
#: `app_setting` can see what it belongs to.
SETTING_KEY = "schedule.daily_at"

#: What an edited value must look like: 24-hour, minutes required, no seconds.
#:
#: ``6:00`` is accepted and normalised to ``06:00``, because refusing it would be pedantry about
#: a value whose meaning is unambiguous -- but ``6``, ``06:00:00`` and ``24:00`` are refused.
_TIME = re.compile(r"^(\d{1,2}):([0-5]\d)$")


def normalise(raw: Any) -> str:
    """``raw`` as ``HH:MM``, or a :class:`ValueError` saying what was expected.

    One function for the config validator, the form and the scheduler's own re-read, so all
    three accept exactly the same thing. The message is written to be shown to a reader: it is
    what the Operations page prints when a submitted time is refused.
    """
    text = str(raw or "").strip()
    match = _TIME.match(text)
    if match is None:
        raise ValueError(f"{text!r} is not a 24-hour time like 06:00")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23:
        raise ValueError(f"{text!r} is not a 24-hour time: the hour must be 00-23")
    return f"{hour:02d}:{minute:02d}"


def parse(value: str) -> tuple[int, int]:
    """The ``(hour, minute)`` of a value :func:`normalise` has already accepted."""
    hour, minute = normalise(value).split(":")
    return int(hour), int(minute)


def next_anchor(now: dt.datetime, daily_at: str, zone: ZoneInfo) -> dt.datetime:
    """The next UTC instant at which ``daily_at`` occurs in ``zone``.

    Today's occurrence if it is still ahead of ``now``, otherwise tomorrow's. The construction is
    local-then-convert rather than "UTC plus an offset", so a schedule set for 06:00 keeps firing
    at 06:00 across a clock change -- the interval between two cycles becomes 23 or 25 hours for
    the one day it happens, which is the honest answer to "six in the morning".

    Two daylight-saving edges, both resolved the way a wall clock resolves them: a time that does
    not exist (the spring-forward gap) fires at the instant the clock jumps over it, and an
    ambiguous time (the autumn fold) takes the first of the two.
    """
    hour, minute = parse(daily_at)
    local_now = now.astimezone(zone)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += dt.timedelta(days=1)
    return candidate.astimezone(dt.UTC)


def stored(session: Session) -> str | None:
    """The override set from the Operations page, or ``None`` when the file's default applies."""
    from awltux.db import AppSetting

    row = session.get(AppSetting, SETTING_KEY)
    if row is None or row.value is None:
        return None
    try:
        return normalise(row.value)
    except ValueError:
        # A stored value nothing could have written through the form. Falling back to the
        # default is better than refusing to schedule, and it is logged rather than swallowed
        # because a schedule nobody asked for would otherwise be silent.
        import logging

        logging.getLogger(__name__).warning(
            "stored %s is not a time (%r); using the configured default", SETTING_KEY, row.value
        )
        return None


def set_stored(session: Session, value: Any) -> str:
    """Write the override. Returns the normalised value; raises ``ValueError`` for a bad one.

    The validation happens here rather than in the route, because this is the only writer and a
    second copy of the rule is a second thing to keep in step.
    """
    from awltux.db import AppSetting

    clean = normalise(value)
    row = session.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        session.add(row)
    row.value = clean
    row.note = "daily trigger time, set from the Operations page"
    session.flush()
    return clean


def clear_stored(session: Session) -> None:
    """Drop the override, so the configured default applies again.

    Deleting the row rather than writing the default into it: the default is ``config.yaml``'s
    to state, and a row holding a copy of it would go stale the moment the file was edited.
    """
    from awltux.db import AppSetting

    row = session.get(AppSetting, SETTING_KEY)
    if row is not None:
        session.delete(row)
        session.flush()


def effective(settings: Settings | None = None, *, session: Session | None = None) -> str:
    """The time in force: the override if there is one, else the configured default.

    A failure to read the database falls back to the default rather than stopping the scheduler:
    an unreadable `app_setting` row is a reason to run the schedule it was built with, not a
    reason to have none.
    """
    if session is not None:
        return stored(session) or _configured(settings)
    from awltux.db import session_scope

    try:
        with session_scope() as opened:
            return stored(opened) or _configured(settings)
    except Exception:  # pragma: no cover - an unreadable DB must not stop the clock
        import logging

        logging.getLogger(__name__).exception(
            "could not read %s; using the configured default", SETTING_KEY
        )
        return _configured(settings)


def _configured(settings: Settings | None) -> str:
    if settings is None:
        from awltux.config import get_settings

        settings = get_settings()
    return normalise(settings.schedule.daily_at)


def zone_for(settings: Settings) -> ZoneInfo:
    """The zone the time of day is read in: the configured one, or UTC if it is unknown.

    Not the viewer's cookie: this is the installation's schedule, and a reader in another zone
    must not move it for everybody.
    """
    from awltux.timezones import parse_zone

    return parse_zone(settings.app.timezone) or dt.UTC


__all__ = [
    "SETTING_KEY",
    "clear_stored",
    "effective",
    "next_anchor",
    "normalise",
    "parse",
    "set_stored",
    "stored",
    "zone_for",
]

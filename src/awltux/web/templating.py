"""Jinja2 environment and display filters.

Formatting lives here rather than in templates so that "how a number is shown"
is one reviewable place -- including the rule that an unknown value renders as a
visible placeholder and never as ``0``, which would read as a real figure.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from awltux.timezones import as_utc, current_zone_name, current_zone_note, format_moment, zone_label
from awltux.web.filters import UNCLASSIFIED
from awltux.web.glossary import explanation

TEMPLATE_DIR = Path(__file__).parent / "templates"


def fmt_number(value: Any, decimals: int = 2) -> str:
    if value is None or value == "":
        return "\u2014"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "\u2014"


def fmt_money(value: Any, currency: str | None = None, decimals: int = 2) -> str:
    if value is None:
        return "\u2014"
    text = fmt_number(value, decimals)
    return f"{text} {currency}" if currency else text


def fmt_pct(value: Any, decimals: int = 1, already_percent: bool = True) -> str:
    """Render a fraction or a percentage with an explicit sign.

    ``already_percent`` distinguishes 0.05 (=5%) from 5.0 (=5%), because silently
    guessing between the two is how a 100x display bug survives review.
    """
    if value is None:
        return "\u2014"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    if not already_percent:
        number *= 100.0
    return f"{number:+,.{decimals}f}%"


def fmt_ratio(value: Any, decimals: int = 2) -> str:
    return fmt_number(value, decimals)


def fmt_datetime(value: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a stored (UTC) timestamp in the viewer's zone, labelled with it.

    The label is not decoration. "14:32" is a different instant in London and in
    New York, and a dashboard screenshot outlives the session that produced it.
    """
    if value is None:
        return "\u2014"
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, dt.datetime):
        return format_moment(value, fmt)
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def fmt_duration(started: Any, finished: Any) -> str:
    """How long a run took, from its two timestamps.

    Duration is not stored: it is the gap between two instants, and storing it
    would create a second source of truth for something already derivable. Rendered
    without a zone label for the same reason ``fmt_ago`` is -- an elapsed span is
    the same number of seconds wherever it is read from.

    An unfinished run says so rather than showing a duration that is still growing.
    """
    if started is None or finished is None:
        return "—"
    start = _as_moment(started)
    end = _as_moment(finished)
    if start is None or end is None:
        return "—"

    seconds = (end - start).total_seconds()
    if seconds < 0:
        # Clock skew, or a row written by a machine whose clock disagrees. Saying
        # so is better than rendering a negative duration as if it meant something.
        return "clock skew"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _as_moment(value: Any) -> dt.datetime | None:
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, dt.datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def fmt_ago(value: Any) -> str:
    """Human-readable age, e.g. "3h ago". Used for the freshness column.

    Deliberately zone-free: an elapsed duration is the same number of seconds
    wherever it is read from, so putting a clock on it would be noise.
    """
    if value is None:
        return "never"
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    if not isinstance(value, dt.datetime):
        return "\u2014"
    when = as_utc(value)
    assert when is not None
    seconds = (dt.datetime.now(dt.UTC) - when).total_seconds()
    if seconds < 0:
        return "just now"
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{int(seconds // 60)}m ago"
    if seconds < 172800:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 2592000:
        return f"{int(seconds // 86400)}d ago"
    return format_moment(when, "%Y-%m-%d")


def fmt_interval(seconds: Any) -> str:
    """A schedule interval as the schedule it actually is.

    **Sub-minute intervals are shown in seconds.** The page used to render every
    interval as minutes rounded to a whole number, so ``edgar_atom_events`` at 45
    seconds printed **"1.0m"** -- a schedule the job does not have. A reader who then
    finds no per-minute history cannot tell a broken scheduler from their own
    misreading, which is exactly how that job's silence went unnoticed.

    The units change with the magnitude for the same reason: ``604800`` rendered as
    "10080.0m" is technically correct and tells a reader nothing.
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "—"

    if value < 90:
        return f"{value:.0f}s"
    if value < 3600:
        return f"{value / 60:.0f}m"
    if value < 86400:
        hours = value / 3600
        return f"{hours:.0f}h" if abs(hours - round(hours)) < 0.05 else f"{hours:.1f}h"
    days = value / 86400
    return f"{days:.0f}d" if abs(days - round(days)) < 0.05 else f"{days:.1f}d"


def action_class(action: str | None) -> str:
    """CSS class for an action badge. Unknown actions are visibly unknown."""
    return {
        "strong_buy": "buy strong",
        "buy": "buy",
        "hold": "hold",
        "reduce": "sell",
        "sell": "sell strong",
        "avoid": "avoid",
    }.get(action or "", "unknown")


def materiality_class(materiality: str | None) -> str:
    return {
        "critical": "critical",
        "material": "material",
        "moderate": "moderate",
        "mild": "mild",
        "none": "none",
    }.get(materiality or "", "none")


def engine_label(engine: str | None, uncalibrated: bool = False) -> str:
    """Never let a fallback decision look like a JEV decision."""
    base = {"jev": "JEV", "deepseek": "DeepSeek", "offline": "offline"}.get(engine or "", "unknown")
    return f"{base} (uncalibrated)" if uncalibrated else base


def grade_class(grade: str | None) -> str:
    """CSS class for an evidence grade. Unknown grades are visibly unknown."""
    return {
        "strong": "good",
        "moderate": "ok",
        "mixed": "warn",
        "weak": "bad",
        "unsupported": "bad",
    }.get(grade or "", "unknown")


def pct0(value: Any) -> str:
    """A 0..1 weight as a whole percentage.

    Deliberately not :func:`fmt_pct`: that adds a sign and assumes a change. A
    credibility or a confidence is a proportion, and rendering it as "+25%" would
    suggest a movement that did not happen.
    """
    if value is None:
        return "\u2014"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "\u2014"


def create_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    env = templates.env
    env.filters.update(
        {
            "number": fmt_number,
            "money": fmt_money,
            "pct": fmt_pct,
            "pct0": pct0,
            "ratio": fmt_ratio,
            "datetime": fmt_datetime,
            "duration": fmt_duration,
            "interval": fmt_interval,
            "ago": fmt_ago,
            "action_class": action_class,
            "materiality_class": materiality_class,
            "grade_class": grade_class,
            "engine_label": engine_label,
        }
    )
    env.globals.update(
        {
            "app_name": "AwltuxTrading",
            # Also exposed as a global, not only as a filter: templates call it as
            # `engine_label(engine, uncalibrated)` because it takes two arguments,
            # and a filter-style call would raise `'engine_label' is undefined`.
            "engine_label": engine_label,
            # The URL value meaning "no sector". A global rather than page state
            # because it is vocabulary, not data: a row links to it and the sector
            # control offers it, and both must spell it the same way. Hard-coding
            # the string in a template would let the two drift apart, and the
            # failure would be a filter that matches nothing rather than an error.
            "unclassified_sector": UNCLASSIFIED,
            # Which clock the times on this page are rendered in. A function, not a
            # value, so it is resolved at render time from the request's context
            # rather than fixed when the environment was built.
            "display_zone": current_zone_name,
            "display_zone_note": current_zone_note,
            "zone_label": zone_label,
            # What a field is and how to read it, so the explanation lives in one
            # place: the same figure appears on the dashboard and on an instrument
            # page, and two copies of an explanation drift like any other duplicate.
            "explain": explanation,
            "disclaimer": (
                "Advisory tooling for personal research only. Not financial advice. "
                "Free-tier market data is unofficial and may be delayed or wrong."
            ),
        }
    )
    return templates


templates = create_templates()

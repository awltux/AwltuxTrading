"""Jinja2 environment and display filters.

Formatting lives here rather than in templates so that "how a number is shown"
is one reviewable place -- including the rule that an unknown value renders as a
visible placeholder and never as ``0``, which would read as a real figure.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.templating import Jinja2Templates

from awltux.analysis import sectors as sector_map
from awltux.timezones import as_utc, current_zone_name, current_zone_note, format_moment, zone_label
from awltux.web.glossary import explanation

logger = logging.getLogger(__name__)

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


def _age_units(seconds: float) -> tuple[int, str]:
    """An elapsed span in the largest unit that keeps it a whole number, and that unit.

    Shared by `fmt_ago` and `fmt_age`, which differ only in what they do past a month: a
    freshness column standing alone falls back to a date, and one printed *beside* a
    timestamp cannot.

    **Fifteen months is "15mo ago", not "1y ago".** Rounding to years at 365 days threw away
    the half of the answer a reader is looking at the age for: the first position on the
    instrument page is 615 days old and read "1y ago" (seen on the page, 2026-10-08).
    """
    if seconds < 90:
        return int(seconds), "s"
    if seconds < 5400:
        return int(seconds // 60), "m"
    if seconds < 172800:
        return int(seconds // 3600), "h"
    if seconds < 2592000:
        return int(seconds // 86400), "d"
    if seconds < 2 * 31557600:
        return int(seconds // 2629800), "mo"
    return int(seconds // 31557600), "y"


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
    if seconds < 2592000:
        count, unit = _age_units(seconds)
        return f"{count}{unit} ago"
    return format_moment(when, "%Y-%m-%d")


def fmt_age(value: Any) -> str:
    """Age in words -- "3h ago", "8mo ago" -- and never a date.

    For places where the timestamp is already on screen. `fmt_ago` ends in a bare
    ``%Y-%m-%d`` once a value is over a month old, which is right for a freshness column
    standing on its own and wrong beside a printed timestamp: the instrument page's opened
    date read "2025-01-31 17:29 GMT · 2025-01-31", stating the same day twice and adding
    nothing (reported 2026-10-08).
    """
    when = None if value is None else _as_moment(value)
    if when is None:
        return "\u2014"
    seconds = (dt.datetime.now(dt.UTC) - when).total_seconds()
    if seconds < 0:
        return "just now"
    count, unit = _age_units(seconds)
    return f"{count}{unit} ago"


def sector_url(name: Any) -> str:
    """The sector page for a label, or ``""`` when that label has no page of its own.

    **Not every sector label on a story is one of the eleven.** `ingest/edgar.py` stores the
    *instrument's* industry string against the story it came from, so the stored values
    include Yahoo's own vocabulary and SIC industries as well as the sector pages -- measured
    2026-10-08 over the live table: 27 distinct labels, of which 11 are pages and 1,829 of the
    ~1,900 tagged stories carry one of those; the other 65 say "Healthcare" (24),
    "Financial Services" (21), "Technology" (6), "Silver Ores", "State Commercial Banks" and
    so on. Linking those to `/sectors/...` would 404, which is why this answers with the
    empty string and the template renders the label without a link.
    """
    text = str(name) if name is not None else ""
    if not text or not sector_map.is_sector_page(text):
        return ""
    return f"/sectors/{quote(text)}"


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


def shorten(text: Any, limit: int) -> str:
    """``text`` as one line, trimmed to ``limit`` at a word boundary.

    **One line, because an HTML ``title`` is.** Whitespace is collapsed first so a
    provider's paragraphs cannot put line breaks inside an attribute, and the cut is taken
    at a space so a tooltip never ends mid-word -- a trimmed word reads as a typo rather
    than as a trim.

    Lives here rather than beside either caller because two of them want it: the hover hint
    on the recommendations table, and the configuration index on the Info page, which shows
    comment blocks that run to dozens of lines.
    """
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0] + "…"


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


def verdict_class(verdict: str | None) -> str:
    """CSS class for a deep-dive's verdict. Unknown verdicts are visibly unknown.

    ``insufficient_evidence`` is deliberately not a failure colour. It is the *stated answer*
    for a company nobody has filed much about -- the most common honest conclusion at this
    system's coverage -- and rendering it red would read as a judgement on the company rather
    than as a statement about how much is known.
    """
    return {
        "attractive": "good",
        "watch": "warn",
        "unattractive": "bad",
        "insufficient_evidence": "unknown",
    }.get(verdict or "", "unknown")


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


def provider_status_for_page() -> dict[str, Any]:
    """The credit banner's data, for a template global.

    Defined here rather than passed through every route's context: it appears on every
    page, and a key each route had to remember is a key one route would forget -- which
    is exactly how `news_events` rendered an empty list on the instrument page.

    A failure to read it must not take the page down, so a database error degrades to
    "nothing to report" and is logged. The banner is a warning *about* the system, and a
    warning that can break the system is worse than no warning.
    """
    from awltux.db.session import session_scope
    from awltux.web import queries

    try:
        with session_scope() as session:
            return queries.provider_status(session)
    except Exception:  # pragma: no cover - a banner must never break a page
        logger.exception("could not read the provider balances for the status banner")
        return {"balances": [], "warnings": [], "readable": False, "floor": 0.0}


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
            "age": fmt_age,
            "sector_url": sector_url,
            "action_class": action_class,
            "materiality_class": materiality_class,
            "grade_class": grade_class,
            "verdict_class": verdict_class,
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
            # The name of the "no sector on file" page. A global rather than page state
            # because it is vocabulary, not data: a row links to it and the sector index
            # offers it, and both must spell it the same way. Deliberately a *different*
            # string from `filters.UNCLASSIFIED`, which is the opaque dropdown value the
            # dashboard's industry-string filter uses -- that one is a query parameter,
            # this one is a URL a reader can read.
            "unclassified_sector": sector_map.UNCLASSIFIED,
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
            # Whether a model provider has run out of money, or nearly. A function
            # rather than page state because it is site-wide: the failure it reports is
            # invisible from every page, since the decision engine falls back to the
            # deterministic rules rather than raising. It opens its own session -- a
            # page render may have one already and `session_scope` is re-entrant per
            # thread, so it joins that rather than opening a second connection.
            "provider_status": provider_status_for_page,
            "disclaimer": (
                "Advisory tooling for personal research only. Not financial advice. "
                "Free-tier market data is unofficial and may be delayed or wrong."
            ),
        }
    )
    return templates


templates = create_templates()

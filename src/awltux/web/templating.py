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
    if value is None:
        return "\u2014"
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.UTC)
        return value.strftime(fmt)
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def fmt_ago(value: Any) -> str:
    """Human-readable age, e.g. "3h ago". Used for the freshness column."""
    if value is None:
        return "never"
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return value
    if not isinstance(value, dt.datetime):
        return "\u2014"
    when = value if value.tzinfo else value.replace(tzinfo=dt.UTC)
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
    return when.strftime("%Y-%m-%d")


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
            "disclaimer": (
                "Advisory tooling for personal research only. Not financial advice. "
                "Free-tier market data is unofficial and may be delayed or wrong."
            ),
        }
    )
    return templates


templates = create_templates()

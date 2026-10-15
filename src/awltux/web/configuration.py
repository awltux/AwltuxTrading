"""The running configuration, as the Info page shows it.

`config/config.yaml` explains every tunable in a comment above it, and those comments are the
only place the reasoning lives: why the decision sweep is rotated, why the news relevance
backfill is capped, what raising the valuation's method floor would do. A reader who has to
open the file to find out what the app is doing has to have the repository in front of them,
which is exactly the situation this page exists to avoid.

So the descriptions here are **read out of that file rather than restated**: the comment block
immediately above a key becomes its description, and an inline `# ...` after the value is used
when there is no block. Rewriting them here would be a second copy that goes stale the first
time someone explains a change in the file and not on this page -- the failure every other
module in this tree records.

**The values are the running process's, not the file's.** They come from the loaded settings,
so a value overridden by the environment shows what the app is actually using. That distinction
is not academic: `llm.monthly_budget_usd` was raised in `config.py`'s default and changed
nothing, because `config.yaml` set it and the YAML wins (`TODO.md` has the measurement).

Only the keys a reader would act on are listed. The file is the reference; this is the index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from awltux.config import Settings, get_settings
from awltux.web.templating import fmt_interval, shorten

#: How much of a comment block to show. Some of them are the record of a measurement and run
#: to dozens of lines; the table is an index, and the file is where the whole argument is.
DESCRIPTION_CHARS = 400

#: `key:` at the start of a line, allowing the dotted names YAML allows.
_KEY = re.compile(r"^(\s*)([A-Za-z0-9_.\-]+):")


@dataclass(frozen=True, slots=True)
class ConfigRow:
    """One tunable: where it is set, what it is set to, and why it is that."""

    name: str
    value: str
    description: str


def annotations(path: Path) -> dict[str, str]:
    """Every key in a YAML file that has a comment, keyed by its dotted path.

    A comment belongs to the key it sits directly above, and a blank line ends the block --
    the same rule a reader applies by eye. The path comes from indentation, so a nested key
    is ``news.embeddings.model`` rather than ``model``, which is the only way two keys with
    the same name in different sections can both be listed.

    An inline ``# ...`` after a value is used when there is no block above it, because that is
    where the schedule section keeps its reasons: ``prices_eod: 86400  # once after the close``
    has no block and would otherwise be undocumented.
    """
    comments: list[str] = []
    stack: list[tuple[int, str]] = []
    found: dict[str, str] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            comments = []
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            comments.append(stripped.lstrip("#").strip())
            continue

        match = _KEY.match(line)
        if match is None:
            comments = []
            continue

        indent = len(match.group(1))
        key = match.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))

        text = " ".join(part for part in comments if part)
        if not text:
            # No block above it, so the comment beside the value is the description.
            _, _, rest = line.partition(":")
            _, hash_mark, inline = rest.partition("#")
            if hash_mark:
                text = inline.split("#", 1)[0].strip()
        if text:
            found[".".join(name for _, name in stack)] = shorten(text, DESCRIPTION_CHARS)
        comments = []

    return found


def _render(value: Any, kind: str) -> str:
    """A value as a reader reads it. ``None`` is an em-dash, never ``0`` or ``null``."""
    if value is None:
        return "—"
    if kind == "seconds":
        return fmt_interval(value)
    if kind == "bool":
        return "yes" if value else "no"
    if kind == "list":
        return ", ".join(str(item) for item in value) if value else "—"
    if kind == "number":
        return f"{value:,}"
    if kind == "percent":
        return f"{float(value):.1%}"
    return str(value)


def _read(settings: Any, path: str) -> Any:
    """Follow a dotted path through the loaded settings, or ``None`` if it is not there."""
    node: Any = settings
    for part in path.split("."):
        if node is None:
            return None
        node = node.get(part) if isinstance(node, dict) else getattr(node, part, None)
    return node


#: The keys worth an index entry, in the order a reader meets them. `(path, how to render)`.
#:
#: Chosen for what a reader can *do* with them: what the app spends, what it fetches and how
#: often, what it holds back, and the thresholds that turn evidence into a verdict. The
#: remaining keys are plumbing -- per-endpoint request budgets, ledger column widths -- and
#: the file is the place to read those.
INTERESTING: tuple[tuple[str, str], ...] = (
    ("app.timezone", "text"),
    ("app.attention_level", "number"),
    ("app.balance_warn_below_usd", "text"),
    ("universe.size", "number"),
    ("universe.exchanges", "list"),
    ("universe.instrument_types", "list"),
    ("universe.min_daily_turnover_gbp", "number"),
    ("schedule.t212_instruments", "seconds"),
    ("schedule.held_refresh", "seconds"),
    ("schedule.prices_eod", "seconds"),
    ("schedule.fundamentals_rotation_per_day", "number"),
    ("schedule.decision_rotation_per_day", "number"),
    ("schedule.valuation", "seconds"),
    ("schedule.decision", "seconds"),
    ("schedule.news_rss", "seconds"),
    ("schedule.provider_balance", "seconds"),
    ("schedule.retention", "seconds"),
    ("llm.model_bulk", "text"),
    ("llm.model_deep", "text"),
    ("llm.monthly_budget_usd", "text"),
    ("llm.max_output_tokens", "number"),
    ("decision.engine_priority", "list"),
    ("decision.min_engine_for_suggestion", "text"),
    ("decision.jev_max_state_tokens", "number"),
    ("decision.deepseek_max_tokens", "number"),
    ("valuation.risk_free_rate_source", "text"),
    ("valuation.risk_free_rate", "percent"),
    ("valuation.equity_risk_premium", "percent"),
    ("valuation.terminal_growth_cap", "percent"),
    ("valuation.forecast_years", "number"),
    ("valuation.min_applicable_methods", "number"),
    ("valuation.max_method_dispersion", "percent"),
    ("gate.min_confidence", "percent"),
    ("gate.min_confidence_fallback_engine", "percent"),
    ("gate.min_confidence_rule_engine", "percent"),
    ("gate.max_positions", "number"),
    ("gate.max_weight_per_name", "percent"),
    ("gate.max_weight_per_sector", "percent"),
    ("news.ticker_min_materiality", "text"),
    ("news.relevance_backfill_per_run", "number"),
    ("news.embeddings.model", "text"),
    ("news.embeddings.same_event_threshold", "text"),
    ("news.embeddings.max_per_run", "number"),
    ("reports.years", "number"),
    ("reports.per_run", "number"),
    ("research.context_tokens", "number"),
    ("research.list_limit", "number"),
    ("research.stale_minutes", "number"),
    ("retention.quote_days", "number"),
    ("retention.news_days", "number"),
    ("retention.llm_call_days", "number"),
)


def rows(settings: Settings | None = None) -> list[ConfigRow]:
    """The index entries, with the running process's values and the file's own reasons.

    A key that has no comment is still listed, with an empty description rather than a
    fabricated one -- the value is the fact and the comment is a bonus. A key the settings do
    not have is skipped: it would be an entry for something this build does not read.
    """
    settings = settings or get_settings()
    described = annotations(settings.env.config_file)
    out: list[ConfigRow] = []
    for path, kind in INTERESTING:
        value = _read(settings, path)
        if value is None and path not in described:
            continue
        out.append(
            ConfigRow(
                name=path,
                value=_render(value, kind),
                description=described.get(path, ""),
            )
        )
    return out


__all__ = ["ConfigRow", "INTERESTING", "annotations", "rows"]

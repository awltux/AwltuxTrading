"""The names the filing extractor may return, and how that list grows.

**Why this exists.** The vocabulary used to be a frozen ``frozenset`` in `metrics.py`
feeding both `prompt_metric_names()` -- which generated the extraction prompt -- and the
`validate_extraction` gate. The consequence is that the model could only ever answer
questions we already knew to ask: a caption outside those names was discarded with
``not a canonical metric name``, and the prompt never offered it in the first place.

That is the whole of the measured extraction gap. Of 187 stored periods, **166 fail a
composition check** -- a stated subtotal against the parts we hold -- and `MSFT_US_EQ`'s
is exactly attributable. Adding up its own 10-K balance sheet:

    current assets      20,935 + [55,908] + 80,876 + 1,397 + 48,594 = 207,710  = stated
    total assets        ... + 313,076 + 24,177 + [36,348] + 119,651 + 18,609 + 38,805 = 758,376
    current liabilities 42,416 + 9,227 + 14,945 + [2,534] + [72,965] + 26,738 = 168,825  = stated

`current_assets_composition` is out by exactly 55,908 and `assets_composition` by exactly
92,256 = 55,908 + 36,348. Those are short-term investments and a non-current investment
line, and neither name is in the vocabulary.

**Code owns the seed, the database owns the additions.** `seed()` is built from
`metrics.STATED_METRICS`, so a name added or renamed in code takes effect immediately and
cannot be shadowed by a stale row; the store holds only what a filing revealed. The
alternative -- seeding the table and reading it as the truth -- would make the code's own
vocabulary the thing that goes stale.

**What is stored is a word, not a number.** The registry records that a caption *exists*
and may be asked for. The value still comes from the extraction, with its span and
location, and is stored per period like every other metric -- so discovery widens what is
asked for without inventing a figure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from awltux.metrics import BALANCE_METRICS, CASH_METRICS, INCOME_METRICS

logger = logging.getLogger(__name__)

#: One key in `app_setting`, in the shape `analysis/macro.py` uses for the observed
#: risk-free rate and `providers/balances.py` for the credit readings. A vocabulary read
#: whole and joined on by nothing is not a table: the same reasoning those two record.
SETTING_KEY = "metric_fields"

INCOME = "income"
BALANCE = "balance"
CASH = "cash"
#: A discovered caption whose statement we cannot place. Kept rather than guessed at,
#: because filing it under the wrong heading is how a prompt teaches a model to look in
#: the wrong statement.
OTHER = "other"

_HEADINGS = (
    (INCOME, "income statement"),
    (BALANCE, "balance sheet"),
    (CASH, "cash flow"),
    (OTHER, "other reported totals"),
)


@dataclass(frozen=True, slots=True)
class Field:
    """One name, and what is known about why it is on the list."""

    name: str
    group: str = OTHER
    #: ``canonical`` for the seeded names, ``discovered`` for one a filing revealed.
    origin: str = "canonical"
    #: For a canonical name, the analysis it feeds. For a discovered one, the residual
    #: it closed -- which is the evidence that it belongs here.
    reason: str | None = None
    #: The instrument whose filing revealed it, so a wrong discovery is traceable.
    discovered_for: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "origin": self.origin,
            "reason": self.reason,
            "discovered_for": self.discovered_for,
        }


def seed() -> dict[str, Field]:
    """The names code declares, which no stored row may override."""
    out: dict[str, Field] = {}
    for group, names in (
        (INCOME, INCOME_METRICS),
        (BALANCE, BALANCE_METRICS),
        (CASH, CASH_METRICS),
    ):
        for name in names:
            out[name] = Field(name=name, group=group, origin="canonical")
    return out


def load(session: Any | None = None) -> dict[str, Field]:
    """Every name the extractor may return: the seed, plus what filings revealed.

    ``session`` is optional so a caller with no database -- a prompt built in a test, a
    CLI that only wants the canonical list -- still gets a usable vocabulary. An
    unreadable store degrades to the seed rather than to nothing, because a vocabulary
    that empties on a database error would silently stop the extractor accepting the
    figures it currently stores.
    """
    fields = seed()
    if session is None:
        return fields
    for name, entry in _stored(session).items():
        if name in fields:
            # The code owns this name. A stored row that disagrees is stale, and
            # letting it win is how a renamed metric stops being extracted.
            continue
        fields[name] = Field(
            name=name,
            group=str(entry.get("group") or OTHER),
            origin="discovered",
            reason=entry.get("reason"),
            discovered_for=entry.get("discovered_for"),
        )
    return fields


def names(session: Any | None = None) -> frozenset[str]:
    """Just the names, for the extraction gate."""
    return frozenset(load(session))


def record(
    session: Any,
    name: str,
    *,
    group: str = OTHER,
    reason: str | None = None,
    discovered_for: str | None = None,
) -> bool:
    """Remember a caption a filing presented. Says whether it was new.

    Refuses a name that is already canonical, and refuses one that does not look like a
    metric key at all -- the registry is a prompt, and a free-text caption in it would
    be offered to a model as a field name.
    """
    if not _plausible(name):
        logger.warning("refusing metric field %r: not a usable name", name)
        return False
    if name in seed():
        return False

    stored = _stored(session)
    if name in stored:
        return False
    stored[name] = {
        "group": group,
        "origin": "discovered",
        "reason": reason,
        "discovered_for": discovered_for,
    }
    _save(session, stored)
    logger.info("metric field discovered: %s (%s) from %s", name, group, discovered_for)
    return True


def prompt_block(fields: dict[str, Field] | None = None) -> str:
    """The vocabulary as the extraction prompt lists it, grouped by statement.

    Generated from the same mapping the gate uses, so the prompt cannot offer a name the
    gate would discard -- which was the invariant `metrics.py` was written to protect,
    and the reason `prompt_metric_names` was generated rather than typed.
    """
    fields = fields if fields is not None else seed()
    lines: list[str] = []
    for group, heading in _HEADINGS:
        members = [field.name for field in fields.values() if field.group == group]
        if members:
            lines.append(f"{heading}: " + ", ".join(sorted(members)))
    return "\n".join(lines)


def _plausible(name: str) -> bool:
    """A lower-case snake_case key of a sensible length.

    The registry feeds a prompt that says "use these names", so anything that is not a
    lookable-up key is worse than absent: a sentence here would be offered to the model
    as a field to fill.
    """
    if not name or len(name) > 48:
        return False
    if not all(character.islower() or character.isdigit() or character == "_" for character in name):
        return False
    return not name.startswith("_") and not name.endswith("_") and "__" not in name


def _stored(session: Any) -> dict[str, dict[str, Any]]:
    from awltux.db import AppSetting

    row = session.get(AppSetting, SETTING_KEY)
    value = row.value if row is not None else None
    if not isinstance(value, dict):
        return {}
    return {str(k): dict(v) for k, v in value.items() if isinstance(v, dict)}


def _save(session: Any, stored: dict[str, dict[str, Any]]) -> None:
    from awltux.db import AppSetting

    row = session.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        session.add(row)
    row.value = stored
    row.note = f"{len(stored)} discovered metric field(s)"
    session.flush()

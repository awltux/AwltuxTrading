"""Is this story relevant, to what, and how much does it matter?

The flash banner used to show every headline the ingest layer stored, ordered by
arrival. Two things were wrong with that, and they are separate questions:

**Relevance.** A headline is only useful here if the system can point at something
it affects *and* say which way. A story that names no instrument and no sector has
nothing to attach to; a story that names one but carries no direction is a fact
about the world, not a reason for a share price to move. Either alone is not
relevant, and the definition is deliberately conjunctive:

    relevant  =  (names an instrument or a sector)  AND  (direction is up or down)

Note what this is *not*: it is not a judgement about whether the story is true.
That is the scepticism layer's job, and it produces a separate weight. Relevance
asks only whether there is a claim here that touches a holding.

**Priority.** Once relevant, ordering by arrival is nearly useless: a routine
analyst note published a minute ago would outrank a profit warning published this
morning. Priority is the product of three things, each recorded:

    materiality  x  credibility  x  recency

The credibility term is the scepticism weight where an appraisal exists, and the
same ``UNASSESSED_WEIGHT`` the sentiment model uses where it does not -- so an
unappraised headline is neither trusted nor discarded, and says which it is.

**Nothing here is a verdict.** A score is a sort order; the page shows every input
that produced it, because a priority that cannot be argued with is a priority
nobody should trust.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

from awltux.analysis.sentiment import UNASSESSED_WEIGHT

#: How much each materiality level contributes to priority.
#:
#: ``critical`` is the level the classifier reserves for bankruptcy, fraud or a
#: halted business, so it is the anchor. The rest are spaced by how much attention
#: each deserves relative to it -- deliberately spread rather than linear, because
#: the difference between "mild" and "none" is much smaller than the difference
#: between "material" and "critical".
MATERIALITY_WEIGHT: dict[str, float] = {
    "critical": 1.0,
    "material": 0.8,
    "moderate": 0.5,
    "mild": 0.25,
    "none": 0.1,
}

#: Priority halves every this many days.
#:
#: The research note is blunt about news decaying: the return signature is pressure
#: followed by *reversal*, and syndicated coverage carries approximately no
#: information at all. A three-day half-life puts a story from this morning well
#: above one from last week without pretending the older one is worthless.
HALF_LIFE_DAYS = 3.0

#: Directions that constitute a claim about the share price.
DIRECTIONAL = ("positive", "negative")


@dataclass(slots=True)
class Relevance:
    """Whether a story touches anything, which way, and why."""

    relevant: bool
    #: An instrument or a sector is named.
    has_target: bool
    #: The direction is positive or negative rather than neutral or absent.
    directional: bool
    #: Plain words, shown on the page. Says which half held or failed, because
    #: "not relevant" on its own is unarguable.
    reason: str
    targets: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "relevant": self.relevant,
            "has_target": self.has_target,
            "directional": self.directional,
            "reason": self.reason,
            "targets": list(self.targets),
        }


def assess(
    *,
    tickers: list[str] | None,
    sectors: list[str] | None,
    direction: str | None,
    materiality: str | None = None,
    about: bool | None = None,
) -> Relevance:
    """Apply the conjunctive rule, and say which half held.

    ``materiality`` is reported but not required. A story can be relevant and
    unimportant -- that is what priority is for -- whereas a story with no target
    or no direction is not relevant at any priority.

    ``about`` is the classifier's ``is_about_this_company``. It matters because a
    ticker on an item usually comes from the *feed it was fetched by*, not from
    the article: a Google News search for one company returns pieces that merely
    mention it in passing. When the classifier says the story is not about the
    company, the ticker is not a connection and the item has no target.
    """
    targets = [str(value) for value in (tickers or []) if value]
    targets += [f"sector:{value}" for value in (sectors or []) if value]
    has_target = bool(targets) and about is not False
    directional = str(direction or "").lower() in DIRECTIONAL

    if has_target and directional:
        where = ", ".join(targets)
        reason = (
            f"names {where} and carries a {direction} direction, "
            f"so it is a claim about the share price"
        )
        if materiality in (None, "none"):
            reason += "; the classifier judged it unimportant, so it sorts low"
        return Relevance(True, True, True, reason, targets)

    if about is False and targets:
        return Relevance(
            False,
            False,
            directional,
            f"was fetched by a feed for {', '.join(targets)} but the classifier "
            "judged it is not about that company, so the ticker is a mention "
            "rather than a connection",
            targets,
        )
    if not has_target and not directional:
        return Relevance(
            False,
            False,
            False,
            "names no instrument or sector, and carries no direction: "
            "nothing here touches a holding",
            targets,
        )
    if not has_target:
        return Relevance(
            False,
            False,
            True,
            f"carries a {direction} direction but names no instrument or sector, "
            "so there is nothing to attach it to",
            targets,
        )
    return Relevance(
        False,
        True,
        False,
        f"names {', '.join(targets)} but carries no direction, so it is not a "
        "claim about the share price",
        targets,
    )


def recency_weight(published_at: dt.datetime | None, *, now: dt.datetime | None = None) -> float:
    """Exponential decay on the story's age, halving every ``HALF_LIFE_DAYS``."""
    if published_at is None:
        return 0.5
    moment = published_at if published_at.tzinfo else published_at.replace(tzinfo=dt.UTC)
    reference = now or dt.datetime.now(dt.UTC)
    age_days = max((reference - moment).total_seconds(), 0.0) / 86400.0
    return math.pow(0.5, age_days / HALF_LIFE_DAYS)


def priority(
    *,
    materiality: str | None,
    credibility: float | None,
    published_at: dt.datetime | None,
    now: dt.datetime | None = None,
    unassessed_weight: float = UNASSESSED_WEIGHT,
) -> tuple[float, dict[str, Any]]:
    """Sort key for the flash banner, with every input returned alongside it."""
    material = MATERIALITY_WEIGHT.get(str(materiality or "none").lower(), 0.1)
    assessed = credibility is not None
    weight = credibility if assessed else unassessed_weight
    # Clamp: a credibility outside 0-1 is a bug upstream, and letting it through
    # would let one row dominate the whole banner.
    weight = min(max(float(weight), 0.0), 1.0)
    recent = recency_weight(published_at, now=now)

    score = material * weight * recent
    return score, {
        "materiality_weight": material,
        "credibility": weight,
        "credibility_assessed": assessed,
        "recency_weight": round(recent, 4),
        "formula": "materiality x credibility x recency",
    }

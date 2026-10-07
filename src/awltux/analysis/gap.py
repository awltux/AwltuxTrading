"""Which of a filing's other captions actually close a composition gap.

**The problem this answers.** `ledger.composition` compares a *stated* subtotal against
the sum of the components we hold, and 166 of 187 stored periods fail it. The residual is
the size of the accounts the vocabulary does not carry -- and a caption the filing itself
presents is a candidate for being one of them.

**Why arithmetic and not the model.** A model asked "which line is missing?" will answer,
and the answer will be plausible; there is no way to tell a right one from a confident
one. But a caption has a *value*, so a candidate is right when it closes the residual
**exactly** and wrong when it does not. That turns discovery from a judgement into a
check, which is the only reason it is safe to let the vocabulary grow on its own.

Measured 2026-10-07 on `MSFT_US_EQ`, whose balance sheet presents:

    current assets      20,935 + [55,908] + 80,876 + 1,397 + 48,594 = 207,710  = stated
    total assets        ... + 313,076 + 24,177 + [36,348] + 119,651 + 18,609 + 38,805 = 758,376

`current_assets_composition` is out by **exactly 55,908** -- the bracketed current-asset
line -- and `assets_composition` by **exactly 92,256 = 55,908 + 36,348**. Neither
`short_term_investments` nor an investment line is in the vocabulary.

**Pairs too, because one caption is not always enough.** A balance sheet can leave two
lines out at once, and requiring a single exact match would report nothing where the
truth is two captions. The search is over combinations up to
:data:`MAX_COMBINATION`, which is small on purpose: three lines that happen to sum to a
residual is a coincidence more often than a discovery.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

#: How many captions may be combined to close one residual. See the module docstring.
MAX_COMBINATION = 2

#: How close is exact. The residual is a difference of figures we already hold, so the
#: tolerance is the same one `ledger.tolerance` applies to the comparison that produced
#: it -- a tighter one would reject a correct match over the filer's own rounding.
TOLERANCE_FRACTION = 0.005
TOLERANCE_FLOOR = 1.0


@dataclass(frozen=True, slots=True)
class Discovery:
    """One or more captions that close a residual, and the residual they close."""

    labels: tuple[str, ...]
    total: float
    residual: float

    @property
    def exact(self) -> bool:
        return len(self.labels) == 1

    def describe(self) -> str:
        shown = " + ".join(self.labels)
        return f"{shown} = {self.total:,.0f} against a residual of {self.residual:,.0f}"


def tolerance(scale: float) -> float:
    """How far two figures may differ and still be called equal."""
    return max(TOLERANCE_FLOOR, abs(scale) * TOLERANCE_FRACTION)


def closing_captions(
    residual: float,
    captions: Mapping[str, float],
    *,
    max_combination: int = MAX_COMBINATION,
) -> list[Discovery]:
    """Captions whose total closes ``residual``, fewest first.

    Ordered so the caller takes the first: a single caption that closes the gap is a far
    better explanation than a pair, and both are better than a triple. Within a size the
    order is the mapping's own, so the same filing always yields the same answer.
    """
    if not captions or residual == 0.0:
        return []

    limit = tolerance(residual)
    usable = {name: value for name, value in captions.items() if value}
    found: list[Discovery] = []
    for size in range(1, max(1, max_combination) + 1):
        for combination in itertools.combinations(sorted(usable), size):
            total = sum(usable[name] for name in combination)
            if abs(total - residual) <= limit:
                found.append(
                    Discovery(labels=tuple(combination), total=total, residual=residual)
                )
    return found


def best(residual: float, captions: Mapping[str, float]) -> Discovery | None:
    """The single best explanation for a residual, or ``None``.

    Ambiguity is declined rather than guessed at: two *different* single captions that
    both close the gap means the arithmetic cannot tell which is the missing line, and
    recording either would be a coin toss written into a prompt.
    """
    found = closing_captions(residual, captions)
    if not found:
        return None
    singles = [discovery for discovery in found if discovery.exact]
    if len(singles) > 1:
        return None
    return found[0]


def unexplained(residual: float, captions: Mapping[str, float]) -> bool:
    """Whether a residual survives every candidate. True is the ordinary answer."""
    return best(residual, captions) is None


def normalise_labels(captions: Iterable[str]) -> dict[str, str]:
    """Caption -> a metric key, for the ones that survive :func:`is_usable`.

    The model is asked for snake_case and will mostly comply, but a label that is not a
    usable key cannot go into a prompt, so the conversion is done here rather than
    trusted -- and the caller is told which were dropped.
    """
    out: dict[str, str] = {}
    for caption in captions:
        key = "".join(
            character if character.isalnum() else "_" for character in caption.strip().lower()
        ).strip("_")
        while "__" in key:
            key = key.replace("__", "_")
        if key:
            out[caption] = key
    return out

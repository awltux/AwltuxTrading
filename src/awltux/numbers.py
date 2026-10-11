"""Reading a number out of a provider's or a model's payload.

Every path in this tree that turns an untrusted value into a float wants the same
rule: it must be something Python can parse, and it must be *finite*. Both halves
matter, and the second is the one that gets forgotten. ``float("nan")`` and
``float("inf")`` parse happily, and they are worse than ``None`` everywhere they
land:

* a NaN propagates silently through arithmetic, and because ``nan != nan`` it also
  survives any filter written as ``value == stored`` -- the row simply disappears
  from a comparison instead of looking wrong;
* an infinity turns a ratio, a price or a probability into nonsense that still
  formats like a number.

That rule used to be written five times under one name with three different
policies -- ``decision/offline.py`` and ``ingest/jobs.py`` rejected NaN and kept
infinity, ``decision/jev.py`` and ``providers/yahoo.py`` accepted both, and
``llm/extractors.py`` rejected both. Which one a caller got depended on which
module it reached for, and nothing said so. This is the one copy.
"""

from __future__ import annotations

import math
from typing import Any


def as_finite_float(value: Any) -> float | None:
    """``value`` as a finite float, or ``None`` when it is not one.

    ``None`` for a value that cannot be parsed at all (including ``None``), for
    NaN, and for either infinity.

    A caller that needs to tell "absent" from "unparseable" from "infinite" apart
    does not want this function -- the three are deliberately one answer here,
    because for every reader in this tree the response to all three is the same:
    treat the figure as missing rather than as a number.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

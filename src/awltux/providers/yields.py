"""A sovereign par yield curve, and the one unit convention that keeps it honest.

Shared by every currency's provider, because each one publishes the same thing in
the same units and the only difference is which country's debt it describes.

**Yields are percentages.** ``5.31`` means 5.31%, not 531% and not 0.0531. The
distinction is the reason :meth:`YieldCurve.fraction` exists as a named method
rather than being left to the caller: a discount rate that is 100x too large or too
small produces a valuation that looks entirely plausible, and the mistake is
invisible in the output.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: Tenor labels used across every provider, so one configured tenor selects the
#: same point on any curve. Providers name their pillars differently -- the US
#: Treasury writes "10 Yr", the Bank of England writes "10yr" -- and normalising
#: here is what stops the label drifting between them.
TENOR_5Y = "5 Yr"
TENOR_10Y = "10 Yr"
TENOR_20Y = "20 Yr"

#: The tenor used for the risk-free rate unless configured otherwise. Ten years is
#: the conventional anchor for a DCF: long enough to span a business cycle, short
#: enough that its price is not dominated by term-premium noise.
DEFAULT_TENOR = TENOR_10Y


@dataclass(frozen=True, slots=True)
class YieldCurve:
    """One day's published par yields, as percentages."""

    as_of: dt.date
    rates: dict[str, float]

    def percent(self, tenor: str) -> float | None:
        return self.rates.get(tenor)

    def fraction(self, tenor: str) -> float | None:
        """The tenor as a decimal fraction, which is what the model wants."""
        value = self.rates.get(tenor)
        return None if value is None else value / 100.0

    def as_dict(self) -> dict[str, float]:
        return dict(self.rates)

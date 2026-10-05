"""Accounting-quality markers: the questions the accounts can answer about themselves.

This module exists because of one distinction in ``docs/investment-markers.md``,
and the distinction drives every design decision in the file:

    **Diagnostic** -- does this tell me something true about the business?
    **Predictive of returns** -- does it make money?

Almost everything in the accounting literature is graded on the second question,
and almost everything fails it. This system is a long-horizon advisory tool, so
the first question is the one worth the most here: a marker that reliably shows
weak earnings quality is valuable even if trading on it earns nothing, because it
changes whether a valuation should be believed at all.

Four rules follow, and they are enforced by the shapes below rather than by good
intentions:

1. **Every marker carries its inputs.** The failure mode of these tools is a
   number that reads as a verdict. A marker here is a :class:`Marker` with the
   figures it was computed from attached, so "accrual ratio 0.09" is always
   accompanied by the profit and the cash flow that produced it.
2. **No colour, no score out of ten, no threshold verdict.** A marker may say
   what it measured and in which direction; it may not say "avoid".
3. **A marker that needs a figure the accounts do not contain is absent**, not
   estimated. Every builder returns ``None`` for exactly this reason, and a
   missing marker is visible as a missing key rather than as a zero.
4. **Scores are rankings within a sector, and never verdicts.** Beneish and
   Altman are classifiers fitted to other firms in another accounting regime.

The evidence tier of each marker is carried on it, taken from the research note,
so a reader can see how much weight it has earned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from awltux.db import FundamentalPeriod
from awltux.metrics import value_of

#: Below this many comparable periods, a "trend" is a difference of two numbers
#: and should not be presented as one. The research note asks for three to five.
MIN_PERIODS_FOR_TREND = 3


@dataclass(slots=True)
class Marker:
    """One computed accounting marker, with everything it was computed from.

    ``value`` is the headline number; ``inputs`` is the audit trail; ``reading``
    is the one sentence a person should read instead of the number. ``tier`` is
    the evidence grade from the research note -- "A" is replicated or mechanical,
    "C" is plausible but thin.
    """

    name: str
    label: str
    tier: str
    unit: str
    reading: str
    value: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    caveat: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": self.label,
            "tier": self.tier,
            "unit": self.unit,
            "value": self.value,
            "reading": self.reading,
        }
        if self.inputs:
            payload["inputs"] = self.inputs
        if self.caveat:
            payload["caveat"] = self.caveat
        return payload


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _period_label(period: FundamentalPeriod) -> str:
    return period.period_end.isoformat()


def _direction(late: float, early: float, *, flat: float) -> str:
    if late - early > flat:
        return "rising"
    if early - late > flat:
        return "falling"
    return "flat"


# --------------------------------------------------------------------------- #
# Accruals and cash conversion
# --------------------------------------------------------------------------- #


def _accrual_ratios(series: list[FundamentalPeriod]) -> list[tuple[str, float, str]]:
    """Accrual ratio per period, cash-flow method, over average total assets.

    ``Total accruals = net income - operating cash flow``, divided by average
    total assets. This is an accounting identity rather than a discovered
    pattern: a company whose profits exceed its operating cash flow is, by
    construction, recognising value it has not collected.

    The **cash-flow method is preferred** over the balance-sheet method for a
    reason that matters here -- it needs two figures rather than seven, and both
    of them are already extracted. The balance-sheet method needs the change in
    every working-capital line, which is more ways to be wrong for no more
    insight. See the research note, section 2.1.

    Each entry carries the denominator it was divided by, so a period where the
    average could not be taken is visible rather than silently different.
    """
    out: list[tuple[str, float, str]] = []
    for index, period in enumerate(series):
        net_income = value_of(period.metrics, "net_income")
        cash_flow = value_of(period.metrics, "operating_cash_flow")
        assets = value_of(period.metrics, "total_assets")
        if net_income is None or cash_flow is None or assets is None:
            continue
        previous = series[index - 1] if index > 0 else None
        previous_assets = value_of(previous.metrics, "total_assets") if previous else None
        # Average assets where the prior period is available, because a company
        # that bought a business mid-year would otherwise show a denominator that
        # never existed. The fallback is recorded rather than hidden.
        if previous_assets is not None and (assets + previous_assets) > 0:
            denominator = (assets + previous_assets) / 2
            basis = "average total assets"
        else:
            denominator = assets
            basis = "closing total assets (no comparable prior period)"
        if denominator <= 0:
            continue
        out.append((_period_label(period), (net_income - cash_flow) / denominator, basis))
    return out


def accrual_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """The strongest diagnostic in the list, presented as a trend."""
    ratios = _accrual_ratios(series)
    if not ratios:
        return None

    latest = ratios[-1][1]
    average = _mean([value for _, value, _ in ratios])
    assert average is not None

    reading = (
        f"profit exceeded operating cash flow by {average:.1%} of assets on average"
        if average > 0
        else f"operating cash flow exceeded profit by {abs(average):.1%} of assets on average"
    )
    if len(ratios) < MIN_PERIODS_FOR_TREND:
        reading += f" (only {len(ratios)} period(s): not yet a trend)"

    return Marker(
        name="accrual_ratio",
        label="Accrual ratio (cash-flow method)",
        tier="A",
        unit="ratio",
        value=average,
        inputs={
            "by_period": {label: value for label, value, _ in ratios},
            "denominator_used": {label: basis for label, _, basis in ratios},
            "latest": latest,
            "periods": len(ratios),
            "method": "net income less operating cash flow",
        },
        reading=reading,
        caveat=(
            "A growing business legitimately absorbs cash into receivables and "
            "inventory, so a single year is noisy and the signal is the persistence "
            "and direction across three to five years. The return anomaly attached "
            "to accruals has decayed; this is a reason to distrust a profit figure, "
            "not a short signal."
        ),
    )


def cash_conversion_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """How much reported profit turned into operating cash, averaged.

    The plainest test in the whole list, and the one most easily distorted by a
    single year -- which is why the average and the direction are the marker and
    the latest year is an input.
    """
    conversions: list[tuple[str, float]] = []
    for period in series:
        net_income = value_of(period.metrics, "net_income")
        cash_flow = value_of(period.metrics, "operating_cash_flow")
        # A loss-making period makes the ratio meaningless and often negative in a
        # way that reads as "terrible conversion" when the business is simply
        # unprofitable. Excluded rather than clamped.
        if cash_flow is None or net_income is None or net_income <= 0:
            continue
        conversions.append((_period_label(period), cash_flow / net_income))
    if not conversions:
        return None

    values = [value for _, value in conversions]
    average = _mean(values)
    assert average is not None
    latest = values[-1]

    inputs: dict[str, Any] = {
        "by_period": {label: value for label, value in conversions},
        "latest": latest,
        "periods": len(conversions),
    }
    direction = ""
    if len(values) >= MIN_PERIODS_FOR_TREND:
        midpoint = len(values) // 2
        early = _mean(values[:midpoint])
        late = _mean(values[midpoint:])
        assert early is not None and late is not None
        trend = late - early
        inputs["trend"] = trend
        direction = f", {_direction(late, early, flat=0.1)} over the period"

    reading = f"{average:.0%} of reported profit converted to operating cash{direction}"
    if len(conversions) < MIN_PERIODS_FOR_TREND:
        reading += f" (only {len(conversions)} period(s): not yet a trend)"

    return Marker(
        name="cash_conversion",
        label="Cash conversion (multi-year)",
        tier="A",
        unit="x",
        value=average,
        inputs=inputs,
        reading=reading,
        caveat=(
            "A serial acquirer or a business that capitalises costs can show good "
            "conversion while deteriorating underneath. Loss-making periods are "
            "excluded because the ratio is meaningless for them."
        ),
    )


def analyse(series: list[FundamentalPeriod]) -> list[Marker]:
    """Every marker the supplied periods support.

    A marker whose inputs are missing is simply not returned. That is deliberate:
    an absent marker is visible as an absent key, whereas a marker carrying a
    guessed or zero-filled input is indistinguishable from a real one.
    """
    if not series:
        return []

    candidates = (
        accrual_marker(series),
        cash_conversion_marker(series),
    )
    return [marker for marker in candidates if marker is not None]

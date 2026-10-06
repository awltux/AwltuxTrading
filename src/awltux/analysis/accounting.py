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


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """A ratio, or nothing. Zero and negative denominators return ``None``.

    A negative denominator silently inverts the sign of the result, which turns a
    meaningful figure into a misleading one -- a current ratio of -2.3 reads as a
    collapse when it usually means negative equity in a loss-making year.
    """
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _latest_pair(series: list[FundamentalPeriod]) -> tuple[FundamentalPeriod, FundamentalPeriod | None]:
    """The newest period, and the one before it if there is one.

    Callers that need two comparable periods check the second for ``None`` rather
    than guessing at a change from a single year, which is a difference with
    nothing to compare against.
    """
    return series[-1], (series[-2] if len(series) >= 2 else None)


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


# --------------------------------------------------------------------------- #
# Piotroski: nine named checks, not a score out of nine
# --------------------------------------------------------------------------- #

#: One answer to one of Piotroski's nine questions. ``answer`` is tri-state
#: because the honest answers are three, not two: yes, no, and *the accounts do
#: not say*. Collapsing the third into "no" is how a checklist becomes a score and
#: starts implying a company failed a test it was never asked.
def _check(question: str, answer: bool | None, detail: str) -> dict[str, Any]:
    return {"question": question, "answer": answer, "detail": detail}


def _current_ratio(period: FundamentalPeriod) -> float | None:
    return _safe_ratio(
        value_of(period.metrics, "current_assets"),
        value_of(period.metrics, "current_liabilities"),
    )


def _turnover(period: FundamentalPeriod) -> float | None:
    return _safe_ratio(
        value_of(period.metrics, "revenue"), value_of(period.metrics, "total_assets")
    )


def _cash_to_assets(period: FundamentalPeriod) -> float | None:
    return _safe_ratio(
        value_of(period.metrics, "operating_cash_flow"),
        value_of(period.metrics, "total_assets"),
    )


def _debt_to_assets(period: FundamentalPeriod) -> float | None:
    debt = value_of(period.metrics, "long_term_debt")
    if debt is None:
        debt = value_of(period.metrics, "total_debt")
    return _safe_ratio(debt, value_of(period.metrics, "total_assets"))


def _rose(late: float | None, early: float | None) -> bool | None:
    if late is None or early is None:
        return None
    return late > early


def piotroski_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """Piotroski's nine tests, answered individually and never summed.

    The research note asks for this shape specifically: *"Not a score out of nine
    -- the individual answers are the value, and they are all verifiable against
    the accounts by the reader."* A nine-point score invites a threshold, and a
    threshold on nine binary questions about one company is a verdict wearing a
    disguise.

    Seven of the nine compare this year with last, so a single year answers two of
    them. ``None`` is a real answer for the rest.
    """
    latest, previous = _latest_pair(series)
    metrics = latest.metrics

    cash_flow = value_of(metrics, "operating_cash_flow")
    roa = value_of(metrics, "roa")
    gross_margin = value_of(metrics, "gross_margin")
    shares = value_of(metrics, "shares_outstanding")

    prior = previous.metrics if previous else {}
    prior_roa = value_of(prior, "roa")
    prior_shares = value_of(prior, "shares_outstanding")
    prior_margin = value_of(prior, "gross_margin")

    cash_to_assets = _cash_to_assets(latest)

    # Computed before the checks rather than inside their detail strings. Python
    # evaluates arguments eagerly, so `_ratio_text(_current_ratio(previous), ...)`
    # calls the helper with `previous=None` even on the branch that discards the
    # result -- which is how a single-period company crashed the marker.
    debt_now, debt_before = _debt_to_assets(latest), _pair(previous, _debt_to_assets)
    ratio_now, ratio_before = _current_ratio(latest), _pair(previous, _current_ratio)
    turn_now, turn_before = _turnover(latest), _pair(previous, _turnover)

    checks = [
        _check("Is the return on assets positive?", None if roa is None else roa > 0,
               f"ROA {roa:.4f}" if roa is not None else "total assets or profit absent"),
        _check("Is operating cash flow positive?", None if cash_flow is None else cash_flow > 0,
               f"operating cash flow {cash_flow:,.0f}" if cash_flow is not None
               else "operating cash flow absent"),
        _check("Did the return on assets improve?", _rose(roa, prior_roa),
               f"{prior_roa:.4f} to {roa:.4f}" if None not in (roa, prior_roa)
               else "needs two years of ROA"),
        _check("Does cash flow exceed profit?", None if None in (cash_to_assets, roa)
               else cash_to_assets > roa,
               f"cash/ assets {cash_to_assets:.4f} vs ROA {roa:.4f}"
               if None not in (cash_to_assets, roa) else "needs cash flow, profit and assets"),
        _check("Did long-term debt fall relative to assets?", _fell(debt_now, debt_before),
               _ratio_text(debt_before, debt_now)),
        _check("Did the current ratio improve?", _rose(ratio_now, ratio_before),
               _ratio_text(ratio_before, ratio_now)),
        _check("Were no new shares issued?",
               None if None in (shares, prior_shares) else shares <= prior_shares,
               _shares_text(prior_shares, shares)),
        _check("Did the gross margin improve?", _rose(gross_margin, prior_margin),
               _ratio_text(prior_margin, gross_margin)),
        _check("Did asset turnover improve?", _rose(turn_now, turn_before),
               _ratio_text(turn_before, turn_now)),
    ]

    answered = [check for check in checks if check["answer"] is not None]
    passed = sum(1 for check in answered if check["answer"] is True)
    return Marker(
        name="piotroski",
        label="Piotroski's nine checks",
        tier="B",
        unit="checks",
        value=None,
        inputs={"checks": checks, "answered": len(answered), "passed": passed},
        reading=(
            f"{passed} of {len(answered)} answerable checks pass"
            + (f"; {len(checks) - len(answered)} could not be answered from these accounts"
               if len(answered) < len(checks) else "")
        ),
        caveat=(
            "Deliberately not a score out of nine. The tests were documented on US "
            "non-financial firms from 1976 and have been found weaker in later "
            "periods and outside that sample, so the useful output is the list of "
            "answers, which a reader can check against the accounts. Seven of the "
            "nine need two consecutive years."
        ),
    )


def _fell(late: float | None, early: float | None) -> bool | None:
    if late is None or early is None:
        return None
    return late < early


def _pair(period: FundamentalPeriod | None, measure) -> float | None:
    """Apply a measure to the prior period, or nothing when there is no prior.

    Exists because Python evaluates call arguments eagerly: writing the guard
    inline in a conditional expression does not stop the discarded branch from
    running, and ``measure(None)`` is an ``AttributeError``.
    """
    return measure(period) if period is not None else None


def _ratio_text(early: float | None, late: float | None) -> str:
    if early is None or late is None:
        return "needs two years"
    return f"{early:.4f} to {late:.4f}"


def _shares_text(early: float | None, late: float | None) -> str:
    if early is None or late is None:
        return "share count absent for one or both years"
    change = late - early
    return f"{early:,.0f} to {late:,.0f} ({change:+,.0f})"


# --------------------------------------------------------------------------- #
# Quality, drift and balance-sheet composition
# --------------------------------------------------------------------------- #

#: Days in the periods these markers are computed over. Every ``FundamentalPeriod``
#: is annual, and a days-outstanding figure is meaningless without saying what a
#: "day" was measured against -- the same ratio over a quarter is four times the
#: number.
DAYS_IN_YEAR = 365


def gross_profitability_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """Gross profit over total assets -- Novy-Marx's profitability measure.

    Uses **gross** profit deliberately: it sits above the line where discretion
    over SG&A, R&D capitalisation, restructuring and one-offs is greatest, so it is
    harder to flatter than net income, and it needs no capital definition and no
    WACC estimate. Two figures and a denominator.
    """
    values: list[tuple[str, float]] = []
    for period in series:
        gross = value_of(period.metrics, "gross_profit")
        if gross is None:
            revenue = value_of(period.metrics, "revenue")
            cogs = value_of(period.metrics, "cost_of_goods_sold")
            gross = revenue - cogs if None not in (revenue, cogs) else None
        ratio = _safe_ratio(gross, value_of(period.metrics, "total_assets"))
        if ratio is not None:
            values.append((_period_label(period), ratio))
    if not values:
        return None

    latest = values[-1][1]
    average = _mean([value for _, value in values])
    assert average is not None
    trend = ""
    if len(values) >= MIN_PERIODS_FOR_TREND:
        midpoint = len(values) // 2
        early, late = _mean([v for _, v in values[:midpoint]]), _mean([v for _, v in values[midpoint:]])
        assert early is not None and late is not None
        trend = f", {_direction(late, early, flat=0.02)} over the period"

    return Marker(
        name="gross_profitability",
        label="Gross profitability (gross profit / total assets)",
        tier="B",
        unit="ratio",
        value=latest,
        inputs={"by_period": dict(values), "average": average, "periods": len(values)},
        reading=f"gross profit is {latest:.1%} of total assets{trend}",
        caveat=(
            "Only meaningful **within** an industry: a software firm and a "
            "distributor have structurally different gross margins, so this is a "
            "cross-sectional ranking and not a threshold. The published result is "
            "a return-prediction claim and therefore subject to the decay that "
            "affects that literature."
        ),
    )


def _days_outstanding(period: FundamentalPeriod, metric: str) -> float | None:
    revenue = value_of(period.metrics, "revenue")
    balance = value_of(period.metrics, metric)
    if revenue is None or balance is None or revenue <= 0:
        return None
    return balance / revenue * DAYS_IN_YEAR


def receivables_drift_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """Days sales outstanding and where it is going.

    A rising DSO means revenue is being recognised faster than it is collected --
    often the first visible symptom of aggressive recognition, and often entirely
    innocent (a large customer negotiating longer terms, a change in mix). High
    diagnostic value, high false-positive rate, so it is a "look here" and not a
    score.
    """
    values = [
        (_period_label(period), dso)
        for period in series
        if (dso := _days_outstanding(period, "receivables")) is not None
    ]
    if not values:
        return None

    latest = values[-1][1]
    average = _mean([value for _, value in values])
    assert average is not None
    direction = "not yet a trend"
    if len(values) >= MIN_PERIODS_FOR_TREND:
        midpoint = len(values) // 2
        early, late = _mean([v for _, v in values[:midpoint]]), _mean([v for _, v in values[midpoint:]])
        assert early is not None and late is not None
        direction = _direction(late, early, flat=5.0)

    return Marker(
        name="receivables_drift",
        label="Days sales outstanding",
        tier="B",
        unit="days",
        value=latest,
        inputs={"by_period": dict(values), "average": average, "periods": len(values)},
        reading=f"{latest:.0f} days of revenue sitting in receivables; trend {direction}",
        caveat=(
            "Innocent causes are common: a large customer negotiating longer terms, "
            "a shift in customer mix, or a change in what is recognised gross "
            "versus net. The signal is a *persistent* rise across three to five "
            "years, not one year's number."
        ),
    )


def inventory_drift_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """Inventory measured against revenue, and the margin while it happens.

    The classic warning shape is unsold goods accumulating while the gross margin
    is being discounted to move them. Either alone is noisy and sector-specific;
    together they are the shape worth reading.
    """
    days: list[tuple[str, float]] = []
    margins: list[tuple[str, float]] = []
    for period in series:
        inventory_days = _days_outstanding(period, "inventory")
        if inventory_days is not None:
            days.append((_period_label(period), inventory_days))
        margin = value_of(period.metrics, "gross_margin")
        if margin is not None:
            margins.append((_period_label(period), margin))
    if not days:
        return None

    latest = days[-1][1]
    latest_margin = margins[-1][1] if margins else None
    trend = _direction(
        days[-1][1], days[0][1], flat=5.0
    ) if len(days) >= MIN_PERIODS_FOR_TREND else "not yet a trend"

    margin_note = ""
    if len(margins) >= MIN_PERIODS_FOR_TREND:
        margin_note = (
            f"; gross margin {_direction(margins[-1][1], margins[0][1], flat=0.01)} "
            f"over the same period"
        )

    return Marker(
        name="inventory_drift",
        label="Inventory days and margin",
        tier="B",
        unit="days",
        value=latest,
        inputs={
            "days_by_period": dict(days),
            "gross_margin_by_period": dict(margins),
            "latest_gross_margin": latest_margin,
            "periods": len(days),
        },
        reading=f"{latest:.0f} days of revenue held as inventory; trend {trend}{margin_note}",
        caveat=(
            "Inventory is structurally different between a retailer and a software "
            "firm, and a company with no inventory at all yields no marker rather "
            "than a zero."
        ),
    )


def goodwill_intensity_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """How much of the balance sheet is past acquisition prices.

    Large goodwill and intangibles relative to assets means two things the reader
    should know: the equity figure is soft, and any future impairment hits earnings
    without touching cash. A serial acquirer's reported earnings can look fine while
    cash conversion quietly deteriorates.
    """
    values: list[tuple[str, float]] = []
    for period in series:
        goodwill = value_of(period.metrics, "goodwill") or 0.0
        intangibles = value_of(period.metrics, "intangible_assets") or 0.0
        assets = value_of(period.metrics, "total_assets")
        if assets is None or assets <= 0:
            continue
        # At least one of the two must be *stated*, or a company that discloses
        # neither would show 0% and read as clean.
        if value_of(period.metrics, "goodwill") is None and (
            value_of(period.metrics, "intangible_assets") is None
        ):
            continue
        values.append((_period_label(period), (goodwill + intangibles) / assets))
    if not values:
        return None

    latest = values[-1][1]
    rising = len(values) >= 2 and values[-1][1] > values[0][1]
    return Marker(
        name="goodwill_intensity",
        label="Goodwill and intangibles as a share of assets",
        tier="B",
        unit="ratio",
        value=latest,
        inputs={
            "by_period": dict(values),
            "periods": len(values),
            "goodwill_latest": value_of(series[-1].metrics, "goodwill"),
            "intangibles_latest": value_of(series[-1].metrics, "intangible_assets"),
        },
        reading=(
            f"{latest:.0%} of assets are goodwill and intangibles"
            + (", and the share is rising" if rising else "")
        ),
        caveat=(
            "Not a red flag on its own -- an acquisitive, well-run company looks "
            "like this too. It changes how much the equity figure should be "
            "trusted, and a rising share alongside rising leverage is the "
            "recognisable failure pattern."
        ),
    )


def beneish_inputs_marker(series: list[FundamentalPeriod]) -> Marker | None:
    """The Beneish indices, each on its own, with no composite score.

    The research note recommends the M-score as a within-sector ranking -- and this
    deliberately stops one step short of it. Two reasons, both about not producing
    a number that reads as more than it is:

    * The five-variable coefficients are not in this repository's evidence base,
      which documents only the eight-variable form. Computing a headline figure
      from constants that cannot be checked here would be unverifiable arithmetic
      presented as a score.
    * A ranking needs a population to rank within. The note is explicit that these
      indices are only meaningful **within** an industry, and with a few hundred
      filers spread across 144 sectors there is usually no population.

    What is left is the part the note says carries the value: the indices, each
    with the two figures that produced it, as a "read this" list.
    """
    latest, previous = _latest_pair(series)
    if previous is None:
        return None

    indices = {
        name: value
        for name, value in (
            ("DSRI days sales in receivables", _index(
                _dso_ratio(latest), _dso_ratio(previous))),
            ("GMI gross margin", _index(
                value_of(previous.metrics, "gross_margin"),
                value_of(latest.metrics, "gross_margin"))),
            ("AQI asset quality", _index(
                _soft_asset_ratio(latest), _soft_asset_ratio(previous))),
            ("SGI sales growth", _index(
                value_of(latest.metrics, "revenue"), value_of(previous.metrics, "revenue"))),
            ("DEPI depreciation", _index(
                _depreciation_rate(previous), _depreciation_rate(latest))),
            ("TATA total accruals to assets", _ratio_difference(latest)),
            ("LVGI leverage", _index(
                _leverage_ratio(latest), _leverage_ratio(previous))),
        )
        if value is not None
    }
    if not indices:
        return None

    return Marker(
        name="beneish_inputs",
        label="Beneish indices (no composite score)",
        tier="B",
        unit="x",
        value=None,
        inputs={"indices": indices, "years": [_period_label(previous), _period_label(latest)]},
        reading=(
            "indices computed for "
            + ", ".join(name.split()[0] for name in indices)
            + "; each is a comparison of this year with last, where a value above 1 "
            "means the ratio moved the way the flag describes"
        ),
        caveat=(
            "An index above 1 is not evidence of manipulation. The M-score is "
            "deliberately absent: its coefficients are not verifiable from this "
            "project's sources, and it is only meaningful ranked within an "
            "industry, which the sector population here rarely allows. A flag means "
            "'read this', never 'this is fraud'."
        ),
    )


def _index(late: float | None, early: float | None) -> float | None:
    """A period-over-period index, guarded against a non-positive base.

    A negative or zero base inverts the reading -- a margin moving from -2% to +3%
    would show as -1.5 and look like deterioration.
    """
    if late is None or early is None or early <= 0:
        return None
    return late / early


def _dso_ratio(period: FundamentalPeriod) -> float | None:
    return _safe_ratio(
        value_of(period.metrics, "receivables"), value_of(period.metrics, "revenue")
    )


def _soft_asset_ratio(period: FundamentalPeriod) -> float | None:
    """Non-current, non-PPE assets as a share of total -- Beneish's AQI numerator."""
    assets = value_of(period.metrics, "total_assets")
    if assets is None or assets <= 0:
        return None
    hard = (value_of(period.metrics, "current_assets") or 0.0) + (
        value_of(period.metrics, "net_ppe") or 0.0
    )
    return max(0.0, 1.0 - hard / assets)


def _depreciation_rate(period: FundamentalPeriod) -> float | None:
    depreciation = value_of(period.metrics, "depreciation_amortisation")
    ppe = value_of(period.metrics, "net_ppe")
    if depreciation is None or ppe is None:
        return None
    return _safe_ratio(depreciation, depreciation + ppe)


def _leverage_ratio(period: FundamentalPeriod) -> float | None:
    debt = value_of(period.metrics, "long_term_debt")
    current = value_of(period.metrics, "current_liabilities")
    if debt is None and current is None:
        return None
    return _safe_ratio((debt or 0.0) + (current or 0.0), value_of(period.metrics, "total_assets"))


def _ratio_difference(period: FundamentalPeriod) -> float | None:
    """TATA: accruals over total assets. Not an index -- it is already a ratio."""
    net_income = value_of(period.metrics, "net_income")
    cash_flow = value_of(period.metrics, "operating_cash_flow")
    if net_income is None or cash_flow is None:
        return None
    assets = value_of(period.metrics, "total_assets")
    return _safe_ratio(net_income - cash_flow, assets)


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
        piotroski_marker(series),
        gross_profitability_marker(series),
        receivables_drift_marker(series),
        inventory_drift_marker(series),
        goodwill_intensity_marker(series),
        beneish_inputs_marker(series),
    )
    return [marker for marker in candidates if marker is not None]

"""Fundamental analysis: turn stored accounts into a quality and trend read.

Everything here is derived from :class:`~awltux.db.models.FundamentalPeriod` rows
that were written by an ingest step, so a snapshot can be recomputed from the
database without touching the network.

Two habits this module keeps:

* **Growth is only reported when the periods are comparable.** Mixing a 9-month
  interim with a 12-month annual would produce a growth rate that means nothing,
  so only same-``period_type`` series are compared.
* **Red flags are named, not scored away.** Each flag is a statement that can be
  shown to a user and argued with, because "quality score 4.2" is not auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from awltux.analysis.accounting import (
    MIN_PERIODS_FOR_TREND,
    Marker,
)
from awltux.analysis.accounting import (
    analyse as analyse_accounting,
)
from awltux.db import FundamentalPeriod
from awltux.metrics import value_of

#: Ordering used to build a chronological series; higher is later.
PERIOD_TYPE_ORDER = {"annual": 3, "ttm": 2, "interim": 1, "quarterly": 0}

#: Preference when two sources describe the same period. A figure extracted from
#: the filed document with a citation beats a scraped snapshot of the same figure.
SOURCE_PREFERENCE = {
    "llm_extraction": 5,
    "edgar_xbrl": 4,
    "companies_house_ixbrl": 3,
    "yahoo_statements": 2,
    "yahoo_info": 1,
}


@dataclass(slots=True)
class FundamentalSnapshot:
    """Quality, trend and risk read for one instrument."""

    periods_used: int = 0
    period_type: str | None = None
    currency: str | None = None
    as_of: str | None = None

    revenue: float | None = None
    revenue_cagr: float | None = None
    revenue_growth_latest: float | None = None
    revenue_growth_series: list[float] = field(default_factory=list)

    net_income: float | None = None
    earnings_cagr: float | None = None
    eps: float | None = None

    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    margin_trend: float | None = None

    roe: float | None = None
    roce: float | None = None
    roe_avg: float | None = None

    total_debt: float | None = None
    net_debt: float | None = None
    net_debt_to_ebitda: float | None = None
    debt_to_equity: float | None = None
    interest_cover: float | None = None
    current_ratio: float | None = None

    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    fcf_margin: float | None = None
    cash_conversion: float | None = None

    dividend_per_share: float | None = None
    payout_ratio: float | None = None
    dividend_covered: bool | None = None

    shares_outstanding: float | None = None
    share_count_growth: float | None = None

    fundamentals_confidence: float = 0.0
    red_flags: list[str] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)

    #: Accounting-quality markers, each with the figures it was computed from.
    #: Not every marker applies to every company, and a marker whose inputs are
    #: missing is simply absent rather than zero.
    markers: list[Marker] = field(default_factory=list)

    def marker(self, name: str) -> Marker | None:
        for candidate in self.markers:
            if candidate.name == name:
                return candidate
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "periods_used": self.periods_used,
            "period_type": self.period_type,
            "currency": self.currency,
            "as_of": self.as_of,
            "revenue": self.revenue,
            "revenue_cagr": self.revenue_cagr,
            "revenue_growth_latest": self.revenue_growth_latest,
            "net_income": self.net_income,
            "earnings_cagr": self.earnings_cagr,
            "eps": self.eps,
            "gross_margin": self.gross_margin,
            "operating_margin": self.operating_margin,
            "net_margin": self.net_margin,
            "margin_trend": self.margin_trend,
            "roe": self.roe,
            "roce": self.roce,
            "roe_avg": self.roe_avg,
            "total_debt": self.total_debt,
            "net_debt": self.net_debt,
            "net_debt_to_ebitda": self.net_debt_to_ebitda,
            "debt_to_equity": self.debt_to_equity,
            "interest_cover": self.interest_cover,
            "free_cash_flow": self.free_cash_flow,
            "fcf_margin": self.fcf_margin,
            "cash_conversion": self.cash_conversion,
            "dividend_per_share": self.dividend_per_share,
            "payout_ratio": self.payout_ratio,
            "dividend_covered": self.dividend_covered,
            "shares_outstanding": self.shares_outstanding,
            "share_count_growth": self.share_count_growth,
            "fundamentals_confidence": self.fundamentals_confidence,
            "red_flags": self.red_flags,
            "positives": self.positives,
            "quality_markers": [marker.as_dict() for marker in self.markers],
        }


def _value(period: FundamentalPeriod, key: str) -> float | None:
    """One metric of one period, or ``None`` if it cannot be used."""
    return value_of(period.metrics, key)


def _dedupe_by_period(periods: list[FundamentalPeriod]) -> list[FundamentalPeriod]:
    """Keep one row per ``(period_end, period_type)``, preferring better sources."""
    best: dict[tuple[Any, str], FundamentalPeriod] = {}
    for period in periods:
        key = (period.period_end, period.period_type)
        current = best.get(key)
        if current is None:
            best[key] = period
            continue
        if SOURCE_PREFERENCE.get(period.source, 0) > SOURCE_PREFERENCE.get(current.source, 0):
            best[key] = period
    # Chronological, oldest first, so growth reads the right way round.
    return sorted(best.values(), key=lambda row: row.period_end)


def _cagr(first: float | None, last: float | None, years: int) -> float | None:
    """Compound growth rate. Requires positive endpoints and a real span.

    A sign change cannot be expressed as a CAGR, so it returns ``None`` instead of
    an imaginary number -- a growth rate computed across a move from loss to
    profit is meaningless and would dominate any screen that used it.
    """
    if first is None or last is None or years <= 0:
        return None
    if first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def build_snapshot(periods: list[FundamentalPeriod]) -> FundamentalSnapshot:
    """Assemble a snapshot from an instrument's stored periods."""
    snapshot = FundamentalSnapshot()
    if not periods:
        snapshot.red_flags.append("no accounts stored")
        return snapshot

    usable = [period for period in periods if period.metrics]
    if not usable:
        snapshot.red_flags.append("accounts stored but no metrics parsed")
        return snapshot

    # Prefer annuals; fall back to whatever series exists.
    annuals = [period for period in usable if period.period_type == "annual"]
    if len(annuals) >= 2:
        series = _dedupe_by_period(annuals)
        snapshot.period_type = "annual"
    else:
        by_type: dict[str, list[FundamentalPeriod]] = {}
        for period in usable:
            by_type.setdefault(period.period_type, []).append(period)
        chosen_type = max(by_type, key=lambda key: (len(by_type[key]), PERIOD_TYPE_ORDER.get(key, 0)))
        series = _dedupe_by_period(by_type[chosen_type])
        snapshot.period_type = chosen_type

    latest = series[-1]
    snapshot.periods_used = len(series)
    snapshot.currency = latest.currency
    snapshot.as_of = latest.period_end.isoformat()
    snapshot.fundamentals_confidence = min(
        1.0, 0.4 + 0.15 * len(series) + 0.2 * (latest.confidence or 0.0)
    )

    _fill_from_latest(snapshot, latest)
    _fill_growth(snapshot, series)
    _fill_trends(snapshot, series)
    _fill_quality(snapshot, series)
    snapshot.markers = analyse_accounting(series)
    _flag_markers(snapshot)
    _flag_risks(snapshot, series)

    return snapshot


def _fill_from_latest(snapshot: FundamentalSnapshot, latest: FundamentalPeriod) -> None:
    snapshot.revenue = _value(latest, "revenue")
    snapshot.net_income = _value(latest, "net_income")
    snapshot.eps = _value(latest, "eps_diluted")
    snapshot.gross_margin = _value(latest, "gross_margin")
    snapshot.operating_margin = _value(latest, "operating_margin")
    snapshot.net_margin = _value(latest, "net_margin")
    snapshot.roe = _value(latest, "roe")
    snapshot.roce = _value(latest, "roce")
    snapshot.total_debt = _value(latest, "total_debt")
    snapshot.net_debt = _value(latest, "net_debt")
    snapshot.debt_to_equity = _value(latest, "debt_to_equity")
    snapshot.interest_cover = _value(latest, "interest_cover")
    snapshot.current_ratio = _value(latest, "current_ratio")
    snapshot.operating_cash_flow = _value(latest, "operating_cash_flow")
    snapshot.free_cash_flow = _value(latest, "free_cash_flow")
    snapshot.dividend_per_share = _value(latest, "dividend_per_share")
    snapshot.payout_ratio = _value(latest, "payout_ratio")
    snapshot.shares_outstanding = _value(latest, "shares_outstanding")


def _fill_growth(snapshot: FundamentalSnapshot, series: list[FundamentalPeriod]) -> None:
    revenues = [_value(period, "revenue") for period in series]
    earnings = [_value(period, "net_income") for period in series]

    if len(series) >= 2:
        years = len(series) - 1
        snapshot.revenue_cagr = _cagr(revenues[0], revenues[-1], years)
        snapshot.earnings_cagr = _cagr(earnings[0], earnings[-1], years)

        if revenues[-1] and revenues[-2] and revenues[-2] > 0:
            snapshot.revenue_growth_latest = revenues[-1] / revenues[-2] - 1.0

        growth_series: list[float] = []
        for index in range(1, len(revenues)):
            previous, current = revenues[index - 1], revenues[index]
            if previous and current is not None and previous > 0:
                growth_series.append(current / previous - 1.0)
        snapshot.revenue_growth_series = growth_series


def _fill_trends(snapshot: FundamentalSnapshot, series: list[FundamentalPeriod]) -> None:
    """Compare recent margins with the earlier ones to get a direction."""
    margins = [_value(period, "operating_margin") for period in series]
    margins = [value for value in margins if value is not None]
    if len(margins) >= 3:
        midpoint = len(margins) // 2
        early = sum(margins[:midpoint]) / midpoint
        late = sum(margins[midpoint:]) / (len(margins) - midpoint)
        snapshot.margin_trend = late - early

    roes = [_value(period, "roe") for period in series]
    roes = [value for value in roes if value is not None]
    if roes:
        snapshot.roe_avg = sum(roes) / len(roes)

    if snapshot.revenue and snapshot.free_cash_flow is not None:
        snapshot.fcf_margin = snapshot.free_cash_flow / snapshot.revenue

    # Cash conversion: how much reported profit turned into operating cash.
    if snapshot.net_income and snapshot.net_income > 0 and snapshot.operating_cash_flow:
        snapshot.cash_conversion = snapshot.operating_cash_flow / snapshot.net_income

    if snapshot.net_debt is not None:
        ebitda = _value(series[-1], "ebitda")
        if ebitda and ebitda > 0:
            snapshot.net_debt_to_ebitda = snapshot.net_debt / ebitda

    eps = snapshot.eps
    if eps and eps > 0 and snapshot.dividend_per_share is not None:
        snapshot.payout_ratio = snapshot.dividend_per_share / eps
        snapshot.dividend_covered = snapshot.payout_ratio < 0.9

    if len(series) >= 2:
        first_shares = _value(series[0], "shares_outstanding")
        last_shares = _value(series[-1], "shares_outstanding")
        if first_shares and last_shares and first_shares > 0:
            snapshot.share_count_growth = last_shares / first_shares - 1.0


def _flag_markers(snapshot: FundamentalSnapshot) -> None:
    """Turn the accounting markers into named flags, and only where the evidence does.

    The thresholds that matter here are **not magnitudes**. The research note's
    claim for accruals is that a *persistently positive* accrual ratio is a reason
    to distrust the earnings number, and for cash conversion that it is
    *consistently below* 1.0 over several years. So these flags key off direction
    and persistence, and they stay silent for a single period -- one year's
    working-capital swing is noise, and flagging it would be the conventional
    one-period error this work exists to remove.
    """
    accruals = snapshot.marker("accrual_ratio")
    if accruals is not None:
        by_period = accruals.inputs.get("by_period") or {}
        positive = [value for value in by_period.values() if value > 0]
        if len(by_period) >= 2 and len(positive) == len(by_period):
            snapshot.red_flags.append(
                f"profit exceeded operating cash flow in every one of the last "
                f"{len(by_period)} periods, by {accruals.value:.1%} of assets on average"
            )
        elif len(by_period) >= MIN_PERIODS_FOR_TREND and len(positive) > len(by_period) / 2:
            snapshot.red_flags.append(
                f"profit has run ahead of operating cash flow in {len(positive)} of the "
                f"last {len(by_period)} periods"
            )

    conversion = snapshot.marker("cash_conversion")
    if conversion is not None:
        periods = int(conversion.inputs.get("periods") or 0)
        if periods >= MIN_PERIODS_FOR_TREND and conversion.value is not None:
            if conversion.value < 1.0:
                snapshot.red_flags.append(
                    f"only {conversion.value:.0%} of reported profit converted to cash "
                    f"on average over {periods} periods"
                )
            elif conversion.value >= 1.0:
                snapshot.positives.append(
                    f"profit converting to cash at {conversion.value:.0%} on average "
                    f"over {periods} periods"
                )


def _fill_quality(snapshot: FundamentalSnapshot, series: list[FundamentalPeriod]) -> None:
    """Record the things that are genuinely good, in plain language."""
    if snapshot.roce is not None and snapshot.roce > 0.15:
        snapshot.positives.append(f"returns on capital of {snapshot.roce:.1%}")
    if snapshot.cash_conversion is not None and snapshot.cash_conversion > 1.0:
        snapshot.positives.append(
            f"profit converting to cash at {snapshot.cash_conversion:.0%}"
        )
    if snapshot.revenue_cagr is not None and snapshot.revenue_cagr > 0.05:
        snapshot.positives.append(f"revenue compounding at {snapshot.revenue_cagr:.1%}")
    if snapshot.interest_cover is not None and snapshot.interest_cover > 8:
        snapshot.positives.append(f"interest covered {snapshot.interest_cover:.0f}x")
    if snapshot.net_debt is not None and snapshot.net_debt < 0:
        snapshot.positives.append("net cash on the balance sheet")
    if snapshot.net_margin is not None and snapshot.net_margin > 0.15:
        snapshot.positives.append(f"net margin of {snapshot.net_margin:.1%}")


def _flag_risks(snapshot: FundamentalSnapshot, series: list[FundamentalPeriod]) -> None:
    """Name each risk explicitly so it can be shown and argued with.

    Thresholds are conventional rather than fitted: an interest cover below 2x, a
    payout above earnings, or a shrinking margin are all things a reader can
    verify against the accounts themselves.
    """
    if snapshot.net_income is not None and snapshot.net_income < 0:
        snapshot.red_flags.append("loss-making in the latest period")

    if snapshot.interest_cover is not None and snapshot.interest_cover < 2:
        snapshot.red_flags.append(f"interest covered only {snapshot.interest_cover:.1f}x")

    if snapshot.net_debt_to_ebitda is not None and snapshot.net_debt_to_ebitda > 4:
        snapshot.red_flags.append(
            f"net debt is {snapshot.net_debt_to_ebitda:.1f}x EBITDA"
        )

    if snapshot.debt_to_equity is not None and snapshot.debt_to_equity > 2:
        snapshot.red_flags.append(f"liabilities are {snapshot.debt_to_equity:.1f}x equity")

    if snapshot.margin_trend is not None and snapshot.margin_trend < -0.02:
        snapshot.red_flags.append(
            f"operating margin fell {abs(snapshot.margin_trend):.1%} between periods"
        )

    if snapshot.share_count_growth is not None and snapshot.share_count_growth > 0.05:
        snapshot.red_flags.append(
            f"share count grew {snapshot.share_count_growth:.1%} (dilution)"
        )

    if snapshot.free_cash_flow is not None and snapshot.free_cash_flow < 0:
        snapshot.red_flags.append("negative free cash flow")

    if snapshot.cash_conversion is not None and snapshot.cash_conversion < 0.6:
        snapshot.red_flags.append(
            f"only {snapshot.cash_conversion:.0%} of profit converted to cash"
        )

    if snapshot.payout_ratio is not None and snapshot.payout_ratio > 1.0:
        snapshot.red_flags.append(
            f"dividend is {snapshot.payout_ratio:.0%} of earnings (uncovered)"
        )

    if snapshot.current_ratio is not None and snapshot.current_ratio < 1.0:
        snapshot.red_flags.append(f"current ratio of {snapshot.current_ratio:.2f}")

    # A materially negative equity position makes most ratios meaningless.
    latest = series[-1]
    equity = _value(latest, "total_equity")
    if equity is not None and equity < 0:
        snapshot.red_flags.append("negative shareholder equity")

    if len(series) < 3:
        snapshot.red_flags.append(
            f"only {len(series)} comparable period(s): trends are unreliable"
        )

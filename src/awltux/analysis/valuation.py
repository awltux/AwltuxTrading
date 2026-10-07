"""The deterministic valuation model.

This is where **every number that feeds a decision is produced**. The language
models upstream compress documents and the JEV model chooses a verdict, but no
model output is ever used as a valuation input -- it either cites a filed figure
or it does not get used.

Six independent methods are computed and blended:

===================  ==========================================================
DCF (FCFF)           Projected free cash flow discounted at WACC with a
                     growth fade and a capped terminal rate.
EPV                  Greenwald earnings power value: maintainable earnings
                     capitalised at the cost of capital, plus cash less debt.
Residual income      Book value plus the present value of returns above the
                     cost of equity, with ROE fading to the cost of equity.
Relative multiples   Sector-peer EV/EBITDA, P/E and P/B applied to this
                     company's own metrics.
Dividend discount    Gordon growth, for genuinely stable payers only.
Graham               ``sqrt(22.5 x EPS x BVPS)`` -- a bound, not a forecast.
===================  ==========================================================

Methods that are not applicable are dropped and the remaining weights
renormalised. If too few apply, the run refuses to produce a fair value rather
than emitting a number built on one fragile assumption.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.analysis import macro
from awltux.analysis.fundamental import FundamentalSnapshot, build_snapshot
from awltux.analysis.technical import TechnicalSnapshot, analyse
from awltux.config import Settings, get_settings
from awltux.db import FundamentalPeriod, Instrument, PriceBar, ValuationRun, utcnow
from awltux.db.session import release_write_lock
from awltux.ingest.prices import bar_currency

logger = logging.getLogger(__name__)

ENGINE_VERSION = "1.0.0"

#: Blended corporate tax rate used for the after-tax cost of debt. A single
#: default is used rather than per-jurisdiction rates, and it is recorded in the
#: run's inputs so a reviewer can see exactly what was assumed.
DEFAULT_TAX_RATE = 0.22
#: Fallback pre-tax cost of debt when a company's own interest expense is unusable.
DEFAULT_COST_OF_DEBT = 0.055

#: The rate shock the per-instrument sensitivity is measured over.
#:
#: One percentage point, because that is the unit a reader already thinks in and
#: the one central banks move in. It is a *measurement*, not a prediction: the
#: result says how much of a fair value rests on the discount rate, and says
#: nothing about where rates are going.
RATE_SHOCK = 0.01

METHOD_NAMES = {
    "dcf": "Discounted cash flow (FCFF)",
    "epv": "Earnings power value",
    "residual_income": "Residual income",
    "multiples": "Sector relative multiples",
    "dividend_discount": "Dividend discount (Gordon)",
    "graham": "Graham number (bound only)",
}


@dataclass(slots=True)
class MethodResult:
    """One method's output, with the inputs it used so it can be challenged."""

    name: str
    fair_value_per_share: float | None
    applicable: bool
    reason: str
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.name,
            "label": METHOD_NAMES.get(self.name, self.name),
            "fair_value_per_share": self.fair_value_per_share,
            "applicable": self.applicable,
            "reason": self.reason,
            "inputs": self.inputs,
        }


@dataclass(slots=True)
class PeerMultiples:
    """Sector median multiples, derived from our own universe rather than bought."""

    ev_ebitda: float | None = None
    pe: float | None = None
    pb: float | None = None
    sample_size: int = 0
    sector: str | None = None


@dataclass(slots=True)
class ValuationResult:
    status: str = "ok"
    price: float | None = None
    currency: str | None = None
    fair_value_base: float | None = None
    fair_value_low: float | None = None
    fair_value_high: float | None = None
    margin_of_safety: float | None = None
    valuation_confidence: float | None = None
    methods: list[MethodResult] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: Names of the methods that actually contributed weight to the fair value.
    #: Distinct from :attr:`methods_computed`, which includes methods that ran
    #: successfully but carry zero weight (Graham) and must not be presented as
    #: having influenced the result.
    contributing_methods: list[str] = field(default_factory=list)
    #: Percentage change in the blended fair value for a one-point *rise* in the
    #: risk-free rate, so a long-duration company reads as a large negative number.
    #:
    #: This is a sensitivity, not a forecast. It answers the one question a reader
    #: cannot get from the fair value itself: how much of this number is a bet on
    #: the discount rate rather than on the company. The discount rate is the only
    #: input the model takes from the market rather than from the filings.
    rate_sensitivity: float | None = None

    @property
    def methods_applied(self) -> list[str]:
        """Methods that contributed to the blended fair value."""
        return self.contributing_methods

    @property
    def methods_computed(self) -> list[str]:
        """Every method that produced a value, contributing or not."""
        return [
            method.name
            for method in self.methods
            if method.applicable and method.fair_value_per_share
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "price": self.price,
            "currency": self.currency,
            "fair_value_base": self.fair_value_base,
            "fair_value_low": self.fair_value_low,
            "fair_value_high": self.fair_value_high,
            "margin_of_safety": self.margin_of_safety,
            "valuation_confidence": self.valuation_confidence,
            "rate_sensitivity": self.rate_sensitivity,
            "methods": [method.as_dict() for method in self.methods],
            "methods_applied": self.methods_applied,
            "methods_computed": self.methods_computed,
            "inputs": self.inputs,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# discount rates
# --------------------------------------------------------------------------- #


def cost_of_equity(
    beta: float | None, settings: Settings, *, risk_free_rate: float | None = None
) -> float:
    """CAPM cost of equity: risk-free rate plus a beta-scaled equity premium.

    ``risk_free_rate`` overrides the configured constant. It is passed in rather
    than read from ``settings`` here so the *resolved* rate is visible at the call
    site; :mod:`awltux.analysis.macro` is the only place that decides between the
    observed market rate and the configured fallback.
    """
    config = settings.valuation
    rate = config.risk_free_rate if risk_free_rate is None else risk_free_rate
    effective_beta = beta if beta and beta > 0 else config.default_beta
    # Clamp beta: providers occasionally report absurd values for thin listings.
    effective_beta = min(max(effective_beta, 0.3), 3.0)
    return rate + effective_beta * config.equity_risk_premium


def wacc(
    *,
    cost_of_equity_value: float,
    market_cap: float | None,
    total_debt: float | None,
    interest_expense: float | None,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> tuple[float, dict[str, Any]]:
    """Weighted average cost of capital, with the weights recorded."""
    debt = total_debt or 0.0
    equity = market_cap or 0.0

    if debt <= 0 or equity <= 0:
        # All-equity financing, or we cannot see the split: use the cost of equity
        # rather than inventing a debt weight.
        return cost_of_equity_value, {
            "equity_weight": 1.0,
            "debt_weight": 0.0,
            "cost_of_equity": cost_of_equity_value,
            "cost_of_debt": None,
            "note": "no usable debt or market cap; treated as all-equity",
        }

    cost_of_debt = (
        interest_expense / debt
        if interest_expense and interest_expense > 0 and debt > 0
        else DEFAULT_COST_OF_DEBT
    )
    cost_of_debt = min(max(cost_of_debt, 0.01), 0.20)

    total = debt + equity
    equity_weight = equity / total
    debt_weight = debt / total
    rate = equity_weight * cost_of_equity_value + debt_weight * cost_of_debt * (1 - tax_rate)

    return rate, {
        "equity_weight": equity_weight,
        "debt_weight": debt_weight,
        "cost_of_equity": cost_of_equity_value,
        "cost_of_debt": cost_of_debt,
        "tax_rate": tax_rate,
    }


# --------------------------------------------------------------------------- #
# individual methods
# --------------------------------------------------------------------------- #


def _growth_estimate(snapshot: FundamentalSnapshot, settings: Settings) -> tuple[float, str]:
    """Best available growth rate for the explicit forecast period.

    Preference order is deliberate: realised revenue growth beats realised
    earnings growth (earnings are noisier), and both beat a guess. The result is
    always capped, because an uncapped extrapolation of a good year is the single
    fastest way to produce a nonsense valuation.
    """
    config = settings.valuation
    ceiling = 0.20

    for value, label in (
        (snapshot.revenue_cagr, "revenue CAGR"),
        (snapshot.revenue_growth_latest, "latest revenue growth"),
        (snapshot.earnings_cagr, "earnings CAGR"),
    ):
        if value is not None and value > -0.5:
            return min(max(value, -0.10), ceiling), label

    return config.terminal_growth_cap, "fallback: terminal growth (no usable history)"


def _fade_rate(
    start: float, end: float, year: int, years: int, *, enabled: bool
) -> float:
    """Linearly fade growth from ``start`` towards ``end`` across the horizon."""
    if not enabled or years <= 1:
        return end if enabled else start
    progress = (year - 1) / (years - 1)
    return start + (end - start) * progress


def dcf_fcff(
    *,
    snapshot: FundamentalSnapshot,
    market_cap: float | None,
    shares: float | None,
    beta: float | None,
    net_debt: float | None,
    settings: Settings,
    risk_free_rate: float | None = None,
) -> MethodResult:
    """Discounted free cash flow to the firm, per share."""
    inputs: dict[str, Any] = {}
    base_fcf = snapshot.free_cash_flow or snapshot.operating_cash_flow

    if base_fcf is None or base_fcf <= 0:
        return MethodResult(
            "dcf", None, False,
            "no positive free cash flow to discount", inputs,
        )
    if not shares or shares <= 0:
        return MethodResult("dcf", None, False, "share count unavailable", inputs)

    config = settings.valuation
    ke = cost_of_equity(beta, settings, risk_free_rate=risk_free_rate)
    discount_rate, wacc_inputs = wacc(
        cost_of_equity_value=ke,
        market_cap=market_cap,
        total_debt=snapshot.total_debt,
        interest_expense=None,
    )
    # A discount rate below the terminal rate produces a negative denominator and
    # an infinite value; refuse rather than return nonsense.
    min_rate = config.terminal_growth_cap + 0.02
    if discount_rate < min_rate:
        discount_rate = min_rate

    growth, growth_source = _growth_estimate(snapshot, settings)
    terminal = min(config.terminal_growth_cap, discount_rate - 0.02)

    inputs.update(
        {
            "base_free_cash_flow": base_fcf,
            "discount_rate": discount_rate,
            "terminal_growth": terminal,
            "forecast_years": config.forecast_years,
            "initial_growth": growth,
            "growth_source": growth_source,
            "growth_faded_to_terminal": config.growth_fade_to_terminal,
            "shares_outstanding": shares,
            "net_debt": net_debt,
            **wacc_inputs,
        }
    )

    present_value = 0.0
    cash_flow = base_fcf
    for year in range(1, config.forecast_years + 1):
        rate = _fade_rate(
            growth, terminal, year, config.forecast_years,
            enabled=config.growth_fade_to_terminal,
        )
        cash_flow *= 1.0 + rate
        present_value += cash_flow / ((1.0 + discount_rate) ** year)

    terminal_cash_flow = cash_flow * (1.0 + terminal)
    terminal_value = terminal_cash_flow / (discount_rate - terminal)
    present_value += terminal_value / ((1.0 + discount_rate) ** config.forecast_years)

    equity_value = present_value - (net_debt or 0.0)
    inputs["enterprise_value"] = present_value
    inputs["terminal_value_share"] = (
        (terminal_value / ((1.0 + discount_rate) ** config.forecast_years)) / present_value
        if present_value
        else None
    )

    if equity_value <= 0:
        return MethodResult(
            "dcf", None, False,
            "discounted cash flow does not cover net debt", inputs,
        )

    per_share = equity_value / shares
    # A terminal value dominating the result means the forecast, not the
    # business, is driving the answer.
    if (inputs.get("terminal_value_share") or 0) > 0.85:
        inputs["warning"] = "over 85% of value sits in the terminal value"

    return MethodResult("dcf", per_share, True, "projected FCFF discounted at WACC", inputs)


def earnings_power_value(
    *,
    snapshot: FundamentalSnapshot,
    periods: list[FundamentalPeriod],
    shares: float | None,
    beta: float | None,
    net_debt: float | None,
    settings: Settings,
    risk_free_rate: float | None = None,
) -> MethodResult:
    """Greenwald EPV: capitalise maintainable earnings, adjust for cash and debt."""
    inputs: dict[str, Any] = {}
    if not shares or shares <= 0:
        return MethodResult("epv", None, False, "share count unavailable", inputs)

    earnings_history: list[float] = []
    for period in periods[-5:]:
        value = (period.metrics or {}).get("net_income")
        if value is not None:
            try:
                earnings_history.append(float(value))
            except (TypeError, ValueError):
                continue

    if not earnings_history:
        return MethodResult("epv", None, False, "no earnings history", inputs)

    # Average rather than latest: EPV is explicitly a *maintainable* earnings
    # measure, and a single year can be exceptional in either direction.
    normalised = sum(earnings_history) / len(earnings_history)
    inputs["normalised_earnings"] = normalised
    inputs["years_averaged"] = len(earnings_history)

    if normalised <= 0:
        return MethodResult(
            "epv", None, False,
            "maintainable earnings are not positive, so EPV does not apply", inputs,
        )

    ke = cost_of_equity(beta, settings, risk_free_rate=risk_free_rate)
    inputs["cost_of_equity"] = ke
    value = normalised / ke

    # EPV assumes steady state, so no growth is added -- but balance-sheet
    # surplus and deficit belong to the equity holder.
    value -= net_debt or 0.0
    inputs["net_debt"] = net_debt

    if value <= 0:
        return MethodResult("epv", None, False, "earnings do not cover net debt", inputs)
    return MethodResult("epv", value / shares, True, "maintainable earnings capitalised at the cost of equity", inputs)


def residual_income(
    *,
    snapshot: FundamentalSnapshot,
    shares: float | None,
    beta: float | None,
    book_value: float | None,
    settings: Settings,
    risk_free_rate: float | None = None,
) -> MethodResult:
    """Book value plus the present value of returns above the cost of equity."""
    inputs: dict[str, Any] = {}
    if not shares or shares <= 0:
        return MethodResult("residual_income", None, False, "share count unavailable", inputs)
    if book_value is None or book_value <= 0:
        return MethodResult(
            "residual_income", None, False,
            "no positive book value (the model needs an equity base)", inputs,
        )

    roe = snapshot.roe if snapshot.roe is not None else snapshot.roe_avg
    if roe is None:
        return MethodResult("residual_income", None, False, "no return on equity available", inputs)

    ke = cost_of_equity(beta, settings, risk_free_rate=risk_free_rate)
    inputs.update(
        {
            "book_value": book_value,
            "starting_roe": roe,
            "cost_of_equity": ke,
            "horizon_years": 10,
            "note": "ROE fades linearly to the cost of equity, after which excess return is nil",
        }
    )

    # Beyond the fade horizon ROE equals the cost of equity, so residual income
    # is exactly zero and no terminal value term is needed.
    horizon = 10
    book = book_value
    value = book_value
    for year in range(1, horizon + 1):
        progress = (year - 1) / (horizon - 1) if horizon > 1 else 1.0
        year_roe = roe + (ke - roe) * progress
        residual = (year_roe - ke) * book
        value += residual / ((1.0 + ke) ** year)
        book *= 1.0 + residual / book_value if book_value else 1.0

    if value <= 0:
        return MethodResult("residual_income", None, False, "model produced a non-positive value", inputs)
    return MethodResult("residual_income", value / shares, True, "equity base plus discounted excess returns", inputs)


def relative_multiples(
    *,
    snapshot: FundamentalSnapshot,
    price: float | None,
    book_value: float | None,
    net_debt: float | None,
    shares: float | None,
    peers: PeerMultiples,
    settings: Settings,
) -> MethodResult:
    """Apply sector-peer multiples to this company's own metrics."""
    inputs: dict[str, Any] = {}
    min_sample = settings.valuation.peer_group_min_size

    if peers.sample_size < min_sample:
        return MethodResult(
            "multiples", None, False,
            f"only {peers.sample_size} peer(s) with usable multiples, "
            f"need {min_sample}",
            inputs,
        )
    if not shares or shares <= 0:
        return MethodResult("multiples", None, False, "share count unavailable", inputs)

    inputs.update(
        {
            "peer_sector": peers.sector,
            "peer_sample_size": peers.sample_size,
            "peer_ev_ebitda": peers.ev_ebitda,
            "peer_pe": peers.pe,
            "peer_pb": peers.pb,
        }
    )

    estimates: list[float] = []
    ebitda = (snapshot.as_dict().get("ebitda")) or None

    if peers.ev_ebitda and ebitda and ebitda > 0:
        equity_value = peers.ev_ebitda * ebitda - (net_debt or 0.0)
        if equity_value > 0:
            estimates.append(equity_value / shares)
            inputs["via_ev_ebitda"] = estimates[-1]

    if peers.pe and snapshot.eps and snapshot.eps > 0:
        estimates.append(peers.pe * snapshot.eps)
        inputs["via_pe"] = estimates[-1]

    if peers.pb and book_value and book_value > 0:
        estimates.append(peers.pb * (book_value / shares))
        inputs["via_pb"] = estimates[-1]

    if not estimates:
        return MethodResult(
            "multiples", None, False,
            "no combination of peer multiple and company metric was usable", inputs,
        )

    return MethodResult(
        "multiples", median(estimates), True,
        f"median of {len(estimates)} peer-multiple estimate(s)", inputs,
    )


def dividend_discount(
    *,
    snapshot: FundamentalSnapshot,
    beta: float | None,
    settings: Settings,
    risk_free_rate: float | None = None,
) -> MethodResult:
    """Gordon growth, restricted to genuinely stable dividend payers.

    Deliberately hard to qualify: a company with an uncovered dividend, negative
    free cash flow, or a high payout is excluded, because applying a perpetual
    growth formula to an unsustainable dividend produces a confidently wrong
    number rather than an obviously wrong one.
    """
    inputs: dict[str, Any] = {}
    dps = snapshot.dividend_per_share
    if not dps or dps <= 0:
        return MethodResult("dividend_discount", None, False, "no dividend", inputs)
    if snapshot.payout_ratio is not None and snapshot.payout_ratio > 0.9:
        return MethodResult(
            "dividend_discount", None, False,
            f"dividend is {snapshot.payout_ratio:.0%} of earnings, too high to extrapolate",
            inputs,
        )
    if snapshot.free_cash_flow is not None and snapshot.free_cash_flow <= 0:
        return MethodResult(
            "dividend_discount", None, False,
            "negative free cash flow: the dividend is not covered by cash generation",
            inputs,
        )

    config = settings.valuation
    ke = cost_of_equity(beta, settings, risk_free_rate=risk_free_rate)
    growth = min(
        config.terminal_growth_cap,
        max(snapshot.revenue_cagr or 0.0, 0.0),
    )
    # Gordon breaks down as growth approaches the discount rate.
    if ke - growth < 0.02:
        growth = ke - 0.02

    inputs.update(
        {"dividend_per_share": dps, "cost_of_equity": ke, "growth": growth,
         "payout_ratio": snapshot.payout_ratio}
    )
    if ke <= growth:
        return MethodResult("dividend_discount", None, False, "growth exceeds discount rate", inputs)

    return MethodResult(
        "dividend_discount", dps * (1.0 + growth) / (ke - growth), True,
        "Gordon growth on a covered dividend", inputs,
    )


def graham_number(*, snapshot: FundamentalSnapshot, book_value: float | None, shares: float | None) -> MethodResult:
    """``sqrt(22.5 x EPS x BVPS)``. Reported as a bound, never blended in."""
    inputs: dict[str, Any] = {}
    eps = snapshot.eps
    if not eps or eps <= 0 or not book_value or book_value <= 0 or not shares or shares <= 0:
        return MethodResult(
            "graham", None, False,
            "needs positive earnings and book value", inputs,
        )
    bvps = book_value / shares
    inputs.update({"eps": eps, "book_value_per_share": bvps})
    return MethodResult(
        "graham", math.sqrt(22.5 * eps * bvps), True,
        "Graham number: a defensive bound, excluded from the blended value",
        inputs,
    )


# --------------------------------------------------------------------------- #
# blending
# --------------------------------------------------------------------------- #


def blend(
    methods: list[MethodResult], *, price: float | None, settings: Settings
) -> tuple[float | None, float, float, float, list[str], list[str]]:
    """Weight the applicable methods into a base value and a band.

    Graham is excluded from the blend by a zero configured weight: it is a bound
    for a very different kind of investor, not an estimate of fair value. It is
    still reported, but as a computed value that did **not** contribute.

    Returns ``(base, low, high, band, contributing_names, notes)``.
    """
    config = settings.valuation
    weights = config.method_weights
    notes: list[str] = []

    applicable = [
        method
        for method in methods
        if method.applicable and method.fair_value_per_share and method.fair_value_per_share > 0
    ]
    contributing = [m for m in applicable if weights.get(m.name, 0.0) > 0]

    if len(contributing) < config.min_applicable_methods:
        return None, 0.0, 0.0, 0.0, [], [
            f"only {len(contributing)} weighted method(s) applied; "
            f"{config.min_applicable_methods} required"
        ]

    total_weight = sum(weights.get(method.name, 0.0) for method in contributing)
    base = sum(
        method.fair_value_per_share * weights.get(method.name, 0.0)  # type: ignore[operator]
        for method in contributing
    ) / total_weight

    values = [m.fair_value_per_share for m in contributing]
    spread = (max(values) - min(values)) / base if base else 1.0  # type: ignore[arg-type]
    band = max(config.scenario_spread, min(spread / 2.0, 0.6))

    low = base * (1.0 - band)
    high = base * (1.0 + band)

    zero_weight = [
        m.name for m in applicable if weights.get(m.name, 0.0) <= 0
    ]
    if zero_weight:
        notes.append(
            "computed but excluded from the blended value: " + ", ".join(zero_weight)
        )

    if spread > config.max_method_dispersion:
        notes.append(
            f"methods disagree widely (spread {spread:.0%} of the base value), "
            "so the range is wide and confidence is reduced"
        )
    if len(contributing) < 3:
        notes.append(f"only {len(contributing)} methods contributed to the blend")

    return base, low, high, band, [m.name for m in contributing], notes


def _confidence(
    methods: list[MethodResult],
    contributing: list[str],
    snapshot: FundamentalSnapshot,
    spread: float,
    settings: Settings,
) -> float:
    """Confidence in the *valuation*, which is not the same as in the decision.

    Driven by how many independent methods agreed, how much history backed them,
    and how dispersed they were.
    """
    config = settings.valuation
    if not contributing:
        return 0.0

    method_score = min(len(contributing) / 4.0, 1.0)
    data_score = min(snapshot.fundamentals_confidence, 1.0)
    agreement_score = max(0.0, 1.0 - min(spread / config.max_method_dispersion, 1.0))

    confidence = 0.4 * method_score + 0.3 * data_score + 0.3 * agreement_score
    return round(min(max(confidence, 0.0), 1.0), 4)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #


def sector_multiples(session: Session, *, min_peers: int = 4) -> dict[str, PeerMultiples]:
    """Derive sector median multiples from our own universe.

    Computed from stored data rather than bought, which keeps the app free but
    means the peer set is the universe in the database, not a licensed
    classification. That limitation is surfaced in the UI.
    """
    instruments = session.execute(
        select(Instrument).where(Instrument.in_universe.is_(True))
    ).scalars().all()

    buckets: dict[str, dict[str, list[float]]] = {}
    for instrument in instruments:
        if not instrument.sector:
            continue
        periods = session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == instrument.t212_ticker)
            .order_by(FundamentalPeriod.period_end.desc())
            .limit(1)
        ).scalars().all()
        if not periods:
            continue
        metrics = periods[0].metrics or {}
        market_cap = instrument.market_cap
        if not market_cap:
            continue

        bucket = buckets.setdefault(instrument.sector, {"pe": [], "pb": [], "ev_ebitda": []})

        net_income = metrics.get("net_income")
        if net_income and net_income > 0:
            bucket["pe"].append(market_cap / net_income)

        equity = metrics.get("total_equity")
        if equity and equity > 0:
            bucket["pb"].append(market_cap / equity)

        ebitda = metrics.get("ebitda")
        if ebitda and ebitda > 0:
            net_debt = metrics.get("net_debt") or 0.0
            bucket["ev_ebitda"].append((market_cap + net_debt) / ebitda)

    out: dict[str, PeerMultiples] = {}
    for sector, values in buckets.items():
        # Trim the extremes: a single distressed or speculative peer should not
        # move the sector median that every other name is valued against.
        pe = _trimmed_median(values["pe"])
        pb = _trimmed_median(values["pb"])
        ev_ebitda = _trimmed_median(values["ev_ebitda"])
        sample = max(len(values["pe"]), len(values["pb"]), len(values["ev_ebitda"]))
        out[sector] = PeerMultiples(
            ev_ebitda=ev_ebitda, pe=pe, pb=pb, sample_size=sample, sector=sector
        )
    return out


def _trimmed_median(values: list[float], *, keep: float = 0.8) -> float | None:
    """Median after dropping the outer 10% on each side."""
    clean = sorted(value for value in values if value and value > 0 and math.isfinite(value))
    if not clean:
        return None
    if len(clean) < 5:
        return median(clean)
    trim = int(len(clean) * (1 - keep) / 2)
    trimmed = clean[trim : len(clean) - trim] if trim else clean
    return median(trimmed or clean)


def value_instrument(
    *,
    price: float | None,
    currency: str | None,
    periods: list[FundamentalPeriod],
    closes: list[float],
    volumes: list[float],
    market_cap: float | None,
    beta: float | None,
    peers: PeerMultiples,
    settings: Settings,
    extra_inputs: dict[str, Any] | None = None,
    risk_free_rate: float | None = None,
    risk_free_rate_note: str | None = None,
    risk_free_rate_source: str | None = None,
) -> ValuationResult:
    """Run every method and blend them. Pure function of its inputs.

    ``risk_free_rate`` is the rate resolved by :mod:`awltux.analysis.macro` -- the
    observed market yield when there is one, otherwise the configured constant. It
    is passed in rather than read here so the model stays a function of its
    arguments, and it is *recorded* below with its provenance, because a fair value
    whose discount rate cannot be traced is not reproducible.
    """
    snapshot = build_snapshot(periods)
    result = ValuationResult(price=price, currency=currency)

    if price is None or price <= 0:
        result.status = "insufficient_data"
        result.notes.append("no usable price")
        return result

    latest_metrics = (periods[-1].metrics if periods else {}) or {}
    shares = _number(latest_metrics.get("shares_outstanding"))
    book_value = _number(latest_metrics.get("total_equity"))
    net_debt = _number(latest_metrics.get("net_debt"))

    if not shares or shares <= 0:
        result.status = "insufficient_data"
        result.notes.append(
            "share count unavailable, so no per-share value can be computed"
        )
        return result

    result.inputs = {
        "price": price,
        "currency": currency,
        "shares_outstanding": shares,
        "book_value": book_value,
        "net_debt": net_debt,
        "market_cap": market_cap,
        "beta": beta,
        "periods_used": len(periods),
        "fundamentals": snapshot.as_dict(),
        "peer_multiples": {
            "sector": peers.sector,
            "sample_size": peers.sample_size,
            "ev_ebitda": peers.ev_ebitda,
            "pe": peers.pe,
            "pb": peers.pb,
        },
        "assumptions": {
            "tax_rate": DEFAULT_TAX_RATE,
            "default_cost_of_debt": DEFAULT_COST_OF_DEBT,
            "risk_free_rate": (
                settings.valuation.risk_free_rate
                if risk_free_rate is None
                else risk_free_rate
            ),
            "risk_free_rate_source": risk_free_rate_source
            or ("config" if risk_free_rate is None else "supplied"),
            "risk_free_rate_note": risk_free_rate_note,
            "risk_free_rate_fallback": settings.valuation.risk_free_rate,
            "equity_risk_premium": settings.valuation.equity_risk_premium,
        },
        **(extra_inputs or {}),
    }

    snapshot_with_ebitda = snapshot

    def methods_at(rate: float | None) -> list[MethodResult]:
        """Every method, discounted at one risk-free rate.

        A function of the rate because the sensitivity below re-runs the whole set
        at a shocked one. The rate is the only input that differs between the two
        runs, which is what makes the difference attributable to it rather than to
        noise elsewhere in the model.
        """
        return [
            dcf_fcff(
                snapshot=snapshot,
                market_cap=market_cap,
                shares=shares,
                beta=beta,
                net_debt=net_debt,
                settings=settings,
                risk_free_rate=rate,
            ),
            earnings_power_value(
                snapshot=snapshot,
                periods=periods,
                shares=shares,
                beta=beta,
                net_debt=net_debt,
                settings=settings,
                risk_free_rate=rate,
            ),
            residual_income(
                snapshot=snapshot,
                shares=shares,
                beta=beta,
                book_value=book_value,
                settings=settings,
                risk_free_rate=rate,
            ),
            relative_multiples(
                snapshot=snapshot_with_ebitda,
                price=price,
                book_value=book_value,
                net_debt=net_debt,
                shares=shares,
                peers=peers,
                settings=settings,
            ),
            dividend_discount(
                snapshot=snapshot,
                beta=beta,
                settings=settings,
                risk_free_rate=rate,
            ),
            graham_number(snapshot=snapshot, book_value=book_value, shares=shares),
        ]

    methods = methods_at(risk_free_rate)
    result.methods = methods

    base, low, high, band, contributing, notes = blend(methods, price=price, settings=settings)
    result.notes.extend(notes)
    result.inputs["scenario_band"] = band
    result.contributing_methods = contributing

    # How much of this fair value is a bet on the discount rate.
    #
    # `relative_multiples` and `graham_number` ignore the rate, so a company valued
    # mostly on peers barely moves and one valued on a long forecast moves a lot --
    # which is exactly the distinction a reader needs and cannot see in a single
    # number. Measured on one percentage point because that is the unit rates are
    # discussed in.
    effective_rate = (
        settings.valuation.risk_free_rate if risk_free_rate is None else risk_free_rate
    )
    shocked_base, *_ = blend(
        methods_at(effective_rate + RATE_SHOCK), price=price, settings=settings
    )
    if base and shocked_base:
        change = (shocked_base / base - 1.0) * 100.0
        result.rate_sensitivity = round(change, 2)
        result.inputs["rate_sensitivity"] = {
            "shock": RATE_SHOCK,
            "fair_value_change_pct": result.rate_sensitivity,
            "note": (
                f"a {RATE_SHOCK:.0%} rise in the risk-free rate moves the blended "
                f"fair value by {change:+.1f}%; it is the share of this valuation "
                "that rests on the discount rate rather than on the company"
            ),
        }

    if base is None:
        result.status = "insufficient_data"
        result.fair_value_base = None
    else:
        spread = (high - low) / base if base else 0.0
        result.fair_value_base = base
        result.fair_value_low = low
        result.fair_value_high = high
        result.margin_of_safety = (base - price) / base
        result.valuation_confidence = _confidence(
            methods, contributing, snapshot, spread, settings
        )
        if (price and base and price > base * 3) or (base > price * 3 if price else False):
            result.notes.append(
                "price and model value differ by more than 3x; check the inputs "
                "before trusting either"
            )

    return result


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def run_valuations(
    session: Session,
    *,
    tickers: list[str] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Recompute valuations for the universe and store a run per instrument."""
    settings = settings or get_settings()

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    else:
        # A sweep skips instruments a scoped refresh holds; the refresh will write the
        # valuation for its own instrument at the end of its own sequence.
        from awltux.ingest.lease import exclude_locked

        statement = exclude_locked(statement, session)
    instruments = session.execute(statement).scalars().all()

    peers_by_sector = sector_multiples(session)

    # Resolved per currency, and cached, because a discount rate has to match the
    # currency of the cash flows it discounts. This universe is roughly three
    # quarters dollars and one quarter sterling -- the LSE alone is 118 of the 500 --
    # and one rate cannot serve both without embedding a cross-currency view.
    rates: dict[str, macro.RiskFreeRate] = {}

    def rate_for(currency: str | None) -> macro.RiskFreeRate:
        code = macro.normalise_currency(currency)
        if code not in rates:
            rates[code] = macro.resolve_risk_free_rate(session, settings, code)
        return rates[code]

    stats = {
        "attempted": 0,
        "valued": 0,
        "insufficient_data": 0,
        "no_peers": 0,
        "risk_free_rates": {},
    }
    for instrument in instruments:
        stats["attempted"] += 1

        bars = session.execute(
            select(PriceBar)
            .where(PriceBar.instrument_t212_ticker == instrument.t212_ticker)
            .order_by(PriceBar.date.asc())
        ).scalars().all()
        if not bars:
            stats["insufficient_data"] += 1
            continue

        periods = list(
            session.execute(
                select(FundamentalPeriod)
                .where(FundamentalPeriod.instrument_t212_ticker == instrument.t212_ticker)
                .order_by(FundamentalPeriod.period_end.asc())
            ).scalars().all()
        )

        peers = peers_by_sector.get(instrument.sector or "", PeerMultiples())
        if peers.sample_size < settings.valuation.peer_group_min_size:
            stats["no_peers"] += 1

        closes = [bar.close for bar in bars if bar.close]
        volumes = [bar.volume or 0.0 for bar in bars]

        # The currency the cash flows and the price are both in, which is the
        # currency the discount rate has to be quoted in.
        currency = bar_currency(session, instrument.t212_ticker)
        risk_free = rate_for(currency)

        result = value_instrument(
            price=closes[-1] if closes else None,
            currency=currency,
            periods=periods,
            closes=closes,
            volumes=volumes,
            market_cap=instrument.market_cap,
            beta=None,  # beta is currently only available from the profile payload
            peers=peers,
            settings=settings,
            risk_free_rate=risk_free.value,
            risk_free_rate_note=risk_free.note,
            risk_free_rate_source=risk_free.source,
        )

        session.add(
            ValuationRun(
                instrument_t212_ticker=instrument.t212_ticker,
                as_of=utcnow(),
                price=result.price,
                currency=result.currency,
                inputs=result.inputs,
                model_outputs=result.as_dict(),
                fair_value_low=result.fair_value_low,
                fair_value_base=result.fair_value_base,
                fair_value_high=result.fair_value_high,
                margin_of_safety=result.margin_of_safety,
                valuation_confidence=result.valuation_confidence,
                methods_applied=result.methods_applied,
                status=result.status,
                notes="; ".join(result.notes) or None,
                engine_version=ENGINE_VERSION,
            )
        )

        if result.status == "ok":
            stats["valued"] += 1
        else:
            stats["insufficient_data"] += 1

        # Release the write lock between instruments: a full sweep otherwise holds
        # one transaction for the whole universe and starves every other writer.
        release_write_lock(session)

    session.flush()
    # Which rate applied to which currency, so a sweep can be read back without
    # inferring it. A run that silently priced sterling off a dollar curve would look
    # identical in every other counter here.
    stats["risk_free_rates"] = {
        code: {
            "value": rate.value,
            "source": rate.source,
            "as_of": rate.as_of,
            "tenor": rate.tenor,
            "note": rate.note,
        }
        for code, rate in sorted(rates.items())
    }
    logger.info("valuation run: %s", stats)
    return stats


def analyse_price_history(closes: list[float], volumes: list[float]) -> TechnicalSnapshot:
    """Convenience wrapper so callers do not need to import two modules."""
    return analyse(closes, volumes)

"""The one macro input the valuation model actually depends on.

The risk-free rate anchors the CAPM cost of equity, which anchors every discount
rate, which decides every discounted fair value. It was a constant in
``config.yaml`` -- honest on the day it was typed, and silently wrong afterwards.
On 2026-10-05 the ten-year Treasury yielded 5.31% against a configured 4.2%, and
this model's own DCF gives up about **14%** of its fair value across that gap.

**It is per currency, and that is not a refinement.** A discount rate has to be
denominated in the currency of the cash flows it discounts. This universe is
roughly 385 USD and 115 GBP instruments -- the London Stock Exchange alone is 118 of
the 500 -- so applying one country's curve to all of them does not merely add noise:
it embeds a view on the cross-currency basis that the model does not claim to have.
On 2026-10-02 the ten-year gilt yielded 5.334% against the Treasury's 5.31%, about
2 basis points, which is a coincidence of that week rather than a property of the
pair; at the ~47bp long-end spread seen within the same month, a GBP instrument's
fair value is out by roughly 6%.

**A currency with no curve falls back and says so.** Substituting the dollar rate
for a currency nobody has wired up would recreate exactly the bug this module was
written to fix, so an unmapped currency uses the configured constant and the reason
names the currency.

Three further rules:

* **Observed beats configured.** A published rate is used whenever one is
  available, because it is the rate the market is actually charging.
* **An unobserved rate is not a failure.** Falling back and *saying so* beats
  refusing to value the universe because one HTTP request failed.
* **A plausible-looking wrong number is worse than no number.** Every observation
  is range-checked before it is stored or used. A mis-parsed quote -- an index
  level, or a percentage left as ``5.31`` instead of ``0.0531`` -- would move every
  fair value in the database while looking entirely normal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from awltux.config import Settings
from awltux.db import AppSetting, utcnow
from awltux.providers.yields import DEFAULT_TENOR, YieldCurve

logger = logging.getLogger(__name__)

#: ``app_setting`` key holding the most recent observation per currency.
SETTING_KEY = "risk_free_rate"

#: Which sovereign publishes which currency's curve.
#:
#: Structural rather than tunable: it records which country issues debt in which
#: currency, and that is not a deployment preference. Adding a currency means adding
#: a provider that can read its curve, so the map is the honest place for the
#: coupling to be visible.
CURRENCY_CURVES: dict[str, str] = {
    "USD": "treasury",
    "GBP": "gilt",
}

#: Units that are not currencies. LSE shares are *quoted* in pence, but the money is
#: pounds and prices are normalised to GBP before they are stored, so the units
#: cancel and the rate that applies is the sterling one.
CURRENCY_ALIASES: dict[str, str] = {"GBX": "GBP", "GBP\u00b0": "GBP"}

#: Bounds outside which an observation is a parse error rather than a market.
#:
#: The lower bound is deliberately above the ``fraction()`` unit slip: a curve
#: already expressed as decimals, divided by 100 a second time, lands at ~0.05% --
#: inside a naive 0-25% band, and it would quietly discount every company in the
#: universe at close to zero. 0.1% still sits comfortably below the lowest US
#: 10-year yield on record (0.52%, August 2020) and below any plausible gilt yield,
#: so a genuine low is never refused.
MIN_PLAUSIBLE_RATE = 0.001
MAX_PLAUSIBLE_RATE = 0.25


@dataclass(frozen=True, slots=True)
class RiskFreeRate:
    """The rate the model will use, and where it came from."""

    value: float
    #: "market" (a published curve) or "config" (the configured constant).
    source: str
    #: Currency the rate is denominated in. A USD rate must not discount GBP flows.
    currency: str = "USD"
    #: ISO date of the observation, when there is one.
    as_of: str | None = None
    #: Curve tenor the rate was read from, when it came from the market.
    tenor: str | None = None
    #: One sentence explaining the choice, for the valuation inputs and the UI.
    note: str = ""

    @property
    def is_market(self) -> bool:
        return self.source == "market"

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "source": self.source,
            "currency": self.currency,
            "as_of": self.as_of,
            "tenor": self.tenor,
            "note": self.note,
        }


def normalise_currency(currency: str | None) -> str:
    """The currency a rate should be quoted in, or ``""`` when it is unknown.

    An unknown currency is **not** dollars. Defaulting it to USD is the same silent
    substitution this module exists to remove, one level further down: an instrument
    whose currency could not be read would be discounted at the American rate and
    nothing would say so.
    """
    if not currency:
        return ""
    code = currency.strip().upper()
    return CURRENCY_ALIASES.get(code, code)


def curve_for(currency: str | None) -> str | None:
    """The provider publishing this currency's curve, or ``None`` if none is wired up."""
    return CURRENCY_CURVES.get(normalise_currency(currency))


def is_plausible(rate: float | None) -> bool:
    """Whether a rate could be a real long-term government yield."""
    if rate is None:
        return False
    return MIN_PLAUSIBLE_RATE <= rate <= MAX_PLAUSIBLE_RATE


def _config_rate(settings: Settings, *, currency: str, note: str) -> RiskFreeRate:
    return RiskFreeRate(
        value=settings.valuation.risk_free_rate,
        source="config",
        currency=normalise_currency(currency),
        note=note,
    )


def _entries(row: AppSetting | None) -> dict[str, dict]:
    """The currency-keyed observations in a stored row.

    A row written before this was currency-aware holds a single flat observation.
    It is ignored rather than migrated: this is a cache of a published number that
    the next job run republishes, and reading a shape that no longer exists is how
    a stale value gets used years later.
    """
    if row is None or not isinstance(row.value, dict):
        return {}
    return {
        key: value
        for key, value in row.value.items()
        if isinstance(value, dict) and "value" in value
    }


def store_observation(
    session: Session,
    curve: YieldCurve,
    *,
    currency: str = "USD",
    tenor: str = DEFAULT_TENOR,
) -> RiskFreeRate | None:
    """Persist the rate for ``tenor`` from a published curve, under its currency.

    Returns ``None`` when the curve has no usable value for that tenor, so the
    caller can record a real failure instead of storing a blank.
    """
    currency = normalise_currency(currency)
    rate = curve.fraction(tenor)
    if not is_plausible(rate):
        logger.warning(
            "refusing to store an implausible %s risk-free rate for %s: %r",
            currency,
            tenor,
            rate,
        )
        return None
    assert rate is not None  # is_plausible ruled out None

    observation = RiskFreeRate(
        value=rate,
        source="market",
        currency=currency,
        as_of=curve.as_of.isoformat(),
        tenor=tenor,
        note=(
            f"{tenor} {currency} sovereign par yield, published {curve.as_of.isoformat()} "
            f"({rate:.2%})"
        ),
    )

    row = session.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        session.add(row)

    entries = _entries(row)
    entries[currency] = {
        **observation.as_dict(),
        "observed_at": utcnow().isoformat(),
        "curve": curve.as_dict(),
    }
    row.value = entries
    # One sentence covering every currency, because the column holds one string and
    # a per-currency note would silently overwrite the others.
    row.note = "; ".join(
        f"{code} {entry['value']:.2%} ({entry.get('tenor')}, {entry.get('as_of')})"
        for code, entry in sorted(entries.items())
    )
    session.flush()
    return observation


def read_observation(session: Session, currency: str = "USD") -> RiskFreeRate | None:
    """The stored observation for a currency, or ``None`` if there is none.

    An observation that fails the plausibility check is treated as absent rather
    than used: whatever wrote it was wrong, and falling back to the configured rate
    is the safer of the two available answers.
    """
    entry = _entries(session.get(AppSetting, SETTING_KEY)).get(normalise_currency(currency))
    if entry is None:
        return None

    try:
        rate = float(entry["value"])
    except (TypeError, ValueError, KeyError):
        return None
    if not is_plausible(rate):
        return None

    as_of = entry.get("as_of")
    tenor = entry.get("tenor")
    return RiskFreeRate(
        value=rate,
        source="market",
        currency=normalise_currency(currency),
        as_of=as_of if isinstance(as_of, str) else None,
        tenor=tenor if isinstance(tenor, str) else None,
        note=str(entry.get("note") or f"observed market rate ({rate:.2%})"),
    )


def stored_curve(session: Session, currency: str = "USD") -> dict[str, float]:
    """Every tenor from the last observation for a currency, as percentages.

    The whole curve is stored with each observation, not just the anchoring tenor,
    so a reader can see the *shape* of the market rather than one point on it.
    """
    entry = _entries(session.get(AppSetting, SETTING_KEY)).get(normalise_currency(currency))
    if entry is None:
        return {}
    raw = entry.get("curve")
    if not isinstance(raw, dict):
        return {}

    curve: dict[str, float] = {}
    for tenor, value in raw.items():
        try:
            curve[str(tenor)] = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return curve


def resolve_risk_free_rate(
    session: Session, settings: Settings, currency: str = "USD"
) -> RiskFreeRate:
    """The rate to value with: the market's for this currency, else the constant.

    This is the only place the choice is made, so ``value_instrument`` can stay a
    function of its arguments and a reviewer can see the decision in one place.
    """
    code = normalise_currency(currency)

    if not code:
        return _config_rate(
            settings,
            currency="",
            note=(
                "this instrument has no recorded currency, so no sovereign curve can "
                "be chosen for it; the configured rate is standing in rather than "
                "another currency's, which would be a guess"
            ),
        )

    if curve_for(code) is None:
        return _config_rate(
            settings,
            currency=code,
            note=(
                f"no sovereign yield curve is wired up for {code}, so the configured "
                "rate is standing in for it; using another currency's rate would "
                "embed a cross-currency view this model does not hold"
            ),
        )

    if settings.valuation.risk_free_rate_source == "config":
        return _config_rate(
            settings,
            currency=code,
            note="using the configured rate (market observation disabled)",
        )

    observation = read_observation(session, code)
    if observation is not None:
        return observation

    return _config_rate(
        settings,
        currency=code,
        note=(
            f"no {code} market rate has been observed yet, so the configured rate is "
            "standing in for it; run the macro_rates job"
        ),
    )

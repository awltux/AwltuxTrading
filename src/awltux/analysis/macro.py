"""The one macro input the valuation model actually depends on.

The risk-free rate anchors the CAPM cost of equity, which anchors every discount
rate, which decides every discounted fair value. It was a constant in
``config.yaml`` -- honest on the day it was typed, and silently wrong afterwards.
On 2026-10-05 the 10-year Treasury yielded 5.31% against a configured 4.2%, and
this model's own DCF gives up about **14%** of its fair value across that gap. A
valuation anchored to a stale rate is neither conservative nor aggressive; it is
anchored to a number that stopped being true.

Three rules, and the third is the one that matters most:

* **Observed beats configured.** A published rate is used whenever one is
  available, because it is the rate the market is actually charging.
* **An unobserved rate is not a failure.** Falling back to the configured value
  and *saying so* beats refusing to value the universe because one HTTP request
  failed. The fallback is recorded, never silent.
* **A plausible-looking wrong number is worse than no number.** Every observation
  is range-checked before it is stored or used. A mis-parsed quote -- an index
  level, or a percentage left as ``5.31`` instead of ``0.0531`` -- would move every
  fair value in the database while looking entirely normal. The bounds below are
  deliberately wider than any real policy rate has been, so they catch unit and
  parse errors without second-guessing a genuine regime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from awltux.config import Settings
from awltux.db import AppSetting, utcnow
from awltux.providers.treasury import DEFAULT_TENOR, YieldCurve

logger = logging.getLogger(__name__)

#: ``app_setting`` key holding the most recent observation.
SETTING_KEY = "risk_free_rate"

#: Bounds outside which an observation is a parse error rather than a market.
#:
#: The lower bound is deliberately above the ``fraction()`` unit slip: a curve
#: already expressed as decimals, divided by 100 a second time, lands at ~0.05% --
#: inside a naive 0-25% band, and it would quietly discount every company in the
#: universe at close to zero. 0.1% still sits comfortably below the lowest US
#: 10-year yield on record (0.52%, August 2020), so a genuine low is never refused.
#: The upper bound catches the opposite slip, a percentage used as a fraction.
MIN_PLAUSIBLE_RATE = 0.001
MAX_PLAUSIBLE_RATE = 0.25


@dataclass(frozen=True, slots=True)
class RiskFreeRate:
    """The rate the model will use, and where it came from."""

    value: float
    #: "market" (a published curve) or "config" (the configured constant).
    source: str
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
            "as_of": self.as_of,
            "tenor": self.tenor,
            "note": self.note,
        }


def is_plausible(rate: float | None) -> bool:
    """Whether a rate could be a real long-term government yield."""
    if rate is None:
        return False
    return MIN_PLAUSIBLE_RATE <= rate <= MAX_PLAUSIBLE_RATE


def _config_rate(settings: Settings, *, note: str) -> RiskFreeRate:
    return RiskFreeRate(
        value=settings.valuation.risk_free_rate,
        source="config",
        note=note,
    )


def store_observation(
    session: Session,
    curve: YieldCurve,
    *,
    tenor: str = DEFAULT_TENOR,
) -> RiskFreeRate | None:
    """Persist the rate for ``tenor`` from a published curve.

    Returns ``None`` when the curve has no usable value for that tenor, so the
    caller can record a real failure instead of storing a blank.
    """
    rate = curve.fraction(tenor)
    if not is_plausible(rate):
        logger.warning(
            "refusing to store an implausible risk-free rate for %s: %r", tenor, rate
        )
        return None
    assert rate is not None  # is_plausible ruled out None

    observation = RiskFreeRate(
        value=rate,
        source="market",
        as_of=curve.as_of.isoformat(),
        tenor=tenor,
        note=(
            f"{tenor} US Treasury par yield, published {curve.as_of.isoformat()} "
            f"({rate:.2%})"
        ),
    )

    row = session.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        session.add(row)
    row.value = {
        **observation.as_dict(),
        "observed_at": utcnow().isoformat(),
        "curve": curve.as_dict(),
    }
    row.note = observation.note
    session.flush()
    return observation


def read_observation(session: Session) -> RiskFreeRate | None:
    """The stored observation, or ``None`` if there is none worth trusting.

    An observation that fails the plausibility check is treated as absent rather
    than used: whatever wrote it was wrong, and falling back to the configured rate
    is the safer of the two available answers.
    """
    row = session.get(AppSetting, SETTING_KEY)
    if row is None or not isinstance(row.value, dict):
        return None

    raw = row.value.get("value")
    try:
        rate = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not is_plausible(rate):
        return None

    as_of = row.value.get("as_of")
    tenor = row.value.get("tenor")
    return RiskFreeRate(
        value=rate,
        source="market",
        as_of=as_of if isinstance(as_of, str) else None,
        tenor=tenor if isinstance(tenor, str) else None,
        note=row.note or f"observed market rate ({rate:.2%})",
    )


def stored_curve(session: Session) -> dict[str, float]:
    """Every tenor from the last observation, as percentages.

    The whole curve is stored with each observation, not just the anchoring tenor,
    so a reader can see the *shape* of the market rather than one point on it: a
    long end that has moved away from the short end is the thing worth noticing,
    and a single rate cannot show it.
    """
    row = session.get(AppSetting, SETTING_KEY)
    if row is None or not isinstance(row.value, dict):
        return {}
    raw = row.value.get("curve")
    if not isinstance(raw, dict):
        return {}

    curve: dict[str, float] = {}
    for tenor, value in raw.items():
        try:
            curve[str(tenor)] = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return curve


def resolve_risk_free_rate(session: Session, settings: Settings) -> RiskFreeRate:
    """The rate to value with: the market's if we have one, otherwise the constant.

    This is the only place the choice is made, so ``value_instrument`` can stay a
    function of its arguments and a reviewer can see the decision in one place.
    """
    if settings.valuation.risk_free_rate_source == "config":
        return _config_rate(
            settings, note="using the configured rate (market observation disabled)"
        )

    observation = read_observation(session)
    if observation is not None:
        return observation

    return _config_rate(
        settings,
        note=(
            "no market rate has been observed yet, so the configured rate is "
            "standing in for it; run the macro_rates job"
        ),
    )

"""Forward-return tracking and calibration reporting, per horizon.

A decision is scored by what the price subsequently did, not by whether it matched
some internal target. Two things are recorded for each outcome: the raw forward
return of the instrument, and whether the *direction* the decision implied was
correct.

**The two horizons are scored on different timescales, and must be.** A tactical
call is a claim about the next few weeks; a long-term call is a claim about the
next year or two. Scoring both over the same 90-day window would make the tactical
record meaningless -- most of its signal would have decayed long before the
measurement window closed, and its hit rate would drift towards a coin flip for
reasons that have nothing to do with skill.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.db import DecisionOutcome, DecisionRun, Instrument, PriceBar, utcnow

logger = logging.getLogger(__name__)

#: Horizons tracked, per verdict. Tactical on days, long-term on months.
HORIZON_WINDOWS: dict[str, tuple[int, ...]] = {
    "long_term": (30, 90, 180),
    "short_term": (5, 10, 20),
}

#: Backwards-compatible alias for the long-term windows.
HORIZONS = HORIZON_WINDOWS["long_term"]

#: The decision column carrying each horizon's verdict.
ACTION_COLUMN = {
    "long_term": "long_term_action",
    "short_term": "short_term_action",
}

#: Whether an action implies the price should rise (+1), fall (-1), or does not
#: imply a direction (0). An unmapped action scores 0 and is excluded from the
#: directional hit rate, rather than being counted as correct.
ACTION_DIRECTION: dict[str, int] = {
    "strong_buy": 1,
    "buy": 1,
    "hold": 0,
    "reduce": -1,
    "sell": -1,
    "avoid": -1,
}

#: Actions that constitute an actionable call at all.
ACTIONABLE = frozenset({"strong_buy", "buy", "reduce", "sell", "avoid"})

#: Price movement smaller than this counts as flat rather than a hit or a miss.
#: Wider for the tactical horizon, where ordinary daily noise would otherwise be
#: scored as a directional success.
FLAT_BAND_PCT = {"long_term": 1.0, "short_term": 0.5}


@dataclass(slots=True)
class BucketStats:
    count: int = 0
    hits: int = 0
    misses: int = 0
    flats: int = 0
    returns: list[float] = field(default_factory=list)

    def add(self, return_pct: float, verdict: str | None) -> None:
        self.count += 1
        self.returns.append(return_pct)
        if verdict == "direction_correct":
            self.hits += 1
        elif verdict == "direction_wrong":
            self.misses += 1
        else:
            self.flats += 1

    @property
    def directional_count(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float | None:
        if self.directional_count == 0:
            return None
        return self.hits / self.directional_count

    @property
    def avg_return_pct(self) -> float | None:
        if not self.returns:
            return None
        return sum(self.returns) / len(self.returns)

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "hits": self.hits,
            "misses": self.misses,
            "flats": self.flats,
            "hit_rate": self.hit_rate,
            "avg_return_pct": self.avg_return_pct,
        }


def _price_on_or_after(session: Session, ticker: str, target: dt.date) -> PriceBar | None:
    """First stored bar at or after ``target``.

    Using "at or after" rather than "on" means a weekend or holiday target still
    finds the next trading day instead of silently producing no outcome.
    """
    return session.execute(
        select(PriceBar)
        .where(PriceBar.instrument_t212_ticker == ticker)
        .where(PriceBar.date >= target)
        .order_by(PriceBar.date.asc())
        .limit(1)
    ).scalar_one_or_none()


def _price_on_or_before(session: Session, ticker: str, target: dt.date) -> PriceBar | None:
    return session.execute(
        select(PriceBar)
        .where(PriceBar.instrument_t212_ticker == ticker)
        .where(PriceBar.date <= target)
        .order_by(PriceBar.date.desc())
        .limit(1)
    ).scalar_one_or_none()


def _verdict(horizon: str, direction: int, return_pct: float) -> str:
    if direction == 0:
        return "no_direction"
    band = FLAT_BAND_PCT.get(horizon, 1.0)
    if abs(return_pct) < band:
        return "flat"
    return "direction_correct" if (return_pct > 0) == (direction > 0) else "direction_wrong"


def score_pending_decisions(session: Session, *, limit: int = 2000) -> dict[str, int]:
    """Compute any outstanding forward returns, for both horizons. Idempotent.

    A decision is only scored once the horizon has actually elapsed and a bar
    exists at or after it, so no outcome is ever computed from a partial window.
    """
    today = dt.date.today()
    scored = 0
    skipped_no_price = 0

    decisions = session.execute(
        select(DecisionRun)
        .where(
            (DecisionRun.long_term_action.is_not(None))
            | (DecisionRun.short_term_action.is_not(None))
        )
        .order_by(DecisionRun.created_at.desc())
        .limit(limit)
    ).scalars().all()

    existing: set[tuple[int, str, int]] = {
        (row.decision_run_id, row.horizon, row.horizon_days)
        for row in session.execute(select(DecisionOutcome)).scalars().all()
    }

    for decision in decisions:
        created = decision.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.UTC)
        base_date = created.date()

        start_bar = _price_on_or_before(session, decision.instrument_t212_ticker, base_date)
        if start_bar is None or not start_bar.close:
            skipped_no_price += 1
            continue

        for horizon, windows in HORIZON_WINDOWS.items():
            action = getattr(decision, ACTION_COLUMN[horizon], None)
            if action is None:
                continue
            direction = ACTION_DIRECTION.get(action, 0)

            for horizon_days in windows:
                if (decision.id, horizon, horizon_days) in existing:
                    continue
                target = base_date + dt.timedelta(days=horizon_days)
                if target > today:
                    continue  # horizon has not elapsed yet

                end_bar = _price_on_or_after(
                    session, decision.instrument_t212_ticker, target
                )
                if end_bar is None or not end_bar.close:
                    skipped_no_price += 1
                    continue

                return_pct = (end_bar.close - start_bar.close) / start_bar.close * 100.0
                session.add(
                    DecisionOutcome(
                        decision_run_id=decision.id,
                        horizon=horizon,
                        horizon_days=horizon_days,
                        price_at_decision=start_bar.close,
                        price_at_horizon=end_bar.close,
                        return_pct=return_pct,
                        verdict=_verdict(horizon, direction, return_pct),
                        computed_at=utcnow(),
                    )
                )
                scored += 1

    session.flush()
    result = {"scored": scored, "skipped_no_price": skipped_no_price}
    logger.info("calibration scoring: %s", result)
    return result


def _confidence_bucket(confidence: float | None) -> str:
    if confidence is None:
        return "unknown"
    lower = int(confidence * 10) / 10
    lower = min(max(lower, 0.0), 0.9)
    return f"{lower:.1f}-{lower + 0.1:.1f}"


def calibration_report(
    session: Session,
    *,
    horizon: str = "long_term",
    horizon_days: int | None = None,
) -> dict[str, Any]:
    """Hit rate and average return for one horizon, sliced several ways.

    Only actionable calls contribute to the hit rate: HOLD has no directional
    claim, so counting it either way would flatter or penalise the model for
    something it did not assert.
    """
    windows = HORIZON_WINDOWS.get(horizon, HORIZON_WINDOWS["long_term"])
    chosen_window = horizon_days or windows[1]

    rows = session.execute(
        select(DecisionOutcome, DecisionRun, Instrument)
        .join(DecisionRun, DecisionRun.id == DecisionOutcome.decision_run_id)
        .join(Instrument, Instrument.t212_ticker == DecisionRun.instrument_t212_ticker)
        .where(DecisionOutcome.horizon == horizon)
        .where(DecisionOutcome.horizon_days == chosen_window)
    ).all()

    overall = BucketStats()
    by_confidence: dict[str, BucketStats] = {}
    by_engine: dict[str, BucketStats] = {}
    by_action: dict[str, BucketStats] = {}
    unexpected: list[dict[str, Any]] = []

    for outcome, decision, instrument in rows:
        if outcome.return_pct is None:
            continue
        action = getattr(decision, ACTION_COLUMN[horizon], None)
        if (action or "") not in ACTIONABLE:
            continue

        confidence = (
            decision.short_term_confidence
            if horizon == "short_term"
            else decision.confidence
        )

        overall.add(outcome.return_pct, outcome.verdict)
        by_confidence.setdefault(_confidence_bucket(confidence), BucketStats()).add(
            outcome.return_pct, outcome.verdict
        )
        by_engine.setdefault(decision.engine or "unknown", BucketStats()).add(
            outcome.return_pct, outcome.verdict
        )
        by_action.setdefault(action or "unknown", BucketStats()).add(
            outcome.return_pct, outcome.verdict
        )

        # A high-confidence miss is the most informative row in the report.
        if (
            confidence is not None
            and confidence >= 0.8
            and outcome.verdict == "direction_wrong"
        ):
            unexpected.append(
                {
                    "ticker": instrument.t212_ticker,
                    "name": instrument.display_name,
                    "action": action,
                    "confidence": confidence,
                    "engine": decision.engine,
                    "return_pct": outcome.return_pct,
                    "decided_at": decision.created_at.isoformat(),
                    "decision_id": decision.id,
                }
            )

    # A calibration curve only means something if the slices are consistent: a
    # higher-confidence bucket should hit more often. Surface any inversion.
    curve = {bucket: stats.as_dict() for bucket, stats in sorted(by_confidence.items())}
    inversions: list[str] = []
    ordered = [
        (bucket, stats.hit_rate)
        for bucket, stats in sorted(by_confidence.items())
        if stats.directional_count >= 5
    ]
    for (lower_bucket, lower_rate), (upper_bucket, upper_rate) in zip(
        ordered, ordered[1:], strict=False
    ):
        if lower_rate is not None and upper_rate is not None and upper_rate < lower_rate:
            inversions.append(
                f"{upper_bucket} hit rate ({upper_rate:.0%}) is below "
                f"{lower_bucket} ({lower_rate:.0%})"
            )

    unexpected.sort(key=lambda item: item["return_pct"])

    return {
        "horizon": horizon,
        "horizon_days": chosen_window,
        "horizons_available": list(windows),
        "all_horizons": HORIZON_WINDOWS,
        "scored_outcomes": len(rows),
        "overall": overall.as_dict(),
        "by_confidence": curve,
        "by_engine": {name: stats.as_dict() for name, stats in by_engine.items()},
        "by_action": {name: stats.as_dict() for name, stats in by_action.items()},
        "calibration_inversions": inversions,
        "unexpected": unexpected[:25],
        "computed_at": utcnow().isoformat(),
    }


def report_both_horizons(session: Session) -> dict[str, Any]:
    """Both horizons' reports in one call, for the dashboard."""
    return {
        horizon: calibration_report(session, horizon=horizon)
        for horizon in HORIZON_WINDOWS
    }

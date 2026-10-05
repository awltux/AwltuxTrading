"""The deterministic offline decision engine.

This is the honest fallback. It makes no claim to be a model: it applies explicit
thresholds to the same evidence the other engines see, and labels its output as
uncalibrated with no probabilities at all.

It exists for three reasons:

* **The app works with no API keys.** A fresh install produces real, explainable
  verdicts rather than an empty dashboard.
* **It is the replay engine.** Re-running a stored state through fixed rules
  distinguishes "the model changed its mind" from "the inputs changed".
* **It is the control.** A disagreement between the offline rules and JEV is
  informative -- it usually means the rules are missing context the model used,
  or the model is reading something into the state that is not there.

It produces **both horizons independently**, from the input each horizon is
supposed to use: value and durability for the long term, measured momentum and
news for the tactical view. A stock can be unattractive for years and well set up
this month; this engine will say so.

Every threshold is named in the output, so a verdict can be traced to the single
comparison that produced it.
"""

from __future__ import annotations

import logging
from typing import Any

from awltux.decision.engine import (
    ENGINE_OFFLINE,
    Answer,
    DecisionEngine,
    DecisionResponse,
)

logger = logging.getLogger(__name__)

#: Long-term thresholds. Plain round numbers rather than fitted values: this
#: engine is a fallback, and a fallback quietly tuned to look good is worse than
#: one whose reasoning is obvious.
MARGIN_STRONG_BUY = 0.40
MARGIN_BUY = 0.20
MARGIN_REDUCE = -0.15
MARGIN_SELL = -0.35

#: Balance-sheet risk score at or above this blocks a long-term buy.
RISK_SCORE_BLOCKING = 3

#: Tactical thresholds, on the 0-4 setup and drawdown scales.
SETUP_STRONG = 4
SETUP_GOOD = 3
SETUP_WEAK = 1
DRAWDOWN_BLOCKING = 3

#: Confidence assigned per evidence quality. Not calibrated, and labelled so.
CONFIDENCE_FULL = 0.65
CONFIDENCE_PARTIAL = 0.45
CONFIDENCE_THIN = 0.25


def _get(payload: dict[str, Any], *path: str, default: Any = None) -> Any:
    """Walk a nested dict, returning ``default`` at the first missing step."""
    node: Any = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


class OfflineEngine(DecisionEngine):
    """Threshold rules over the assembled state. No model, no probabilities."""

    name = ENGINE_OFFLINE

    @property
    def available(self) -> bool:
        return True

    def decide(
        self,
        *,
        state: dict[str, Any],
        state_text: str,
        questions: dict[str, Any],
    ) -> DecisionResponse:
        valuation = state.get("valuation") or {}
        accounts = state.get("accounts") or {}
        technical = state.get("price_and_trend") or {}
        sentiment = state.get("sentiment") or {}
        instrument = state.get("instrument") or {}
        news = state.get("recent_news") or []

        is_held = bool(instrument.get("is_held"))
        mos = _as_float(valuation.get("margin_of_safety"))
        confidence_in_valuation = _as_float(valuation.get("valuation_confidence")) or 0.0
        methods = valuation.get("methods_applied") or []
        status = valuation.get("status")

        red_flags: list[str] = list(accounts.get("red_flags") or [])
        positives: list[str] = list(accounts.get("positives") or [])
        instrument_sentiment = _as_float(sentiment.get("instrument_score"))
        sector_sentiment = _as_float(sentiment.get("sector_score"))

        answers: dict[str, Answer] = {}
        reasons: list[str] = []

        going_concern = _going_concern_evidence(red_flags, accounts)
        risk = _risk_score(accounts)
        quality = _quality_score(positives, red_flags, accounts)

        # ================= shared context questions =========================
        verdict = _valuation_verdict(mos, status, reasons)
        answers["valuation_verdict"] = Answer("valuation_verdict", "choice", verdict)
        answers["margin_of_safety"] = Answer("margin_of_safety", "score", float(_margin_score(mos)))
        answers["business_quality"] = Answer("business_quality", "score", float(quality))
        answers["balance_sheet_risk"] = Answer("balance_sheet_risk", "score", float(risk))
        answers["earnings_trend"] = Answer(
            "earnings_trend", "choice", _earnings_trend(accounts, technical)
        )
        answers["news_materiality"] = Answer(
            "news_materiality", "choice", _news_verdict(news)
        )
        answers["sentiment_regime"] = Answer(
            "sentiment_regime",
            "choice",
            _sentiment_regime(instrument_sentiment, sector_sentiment, technical),
        )
        answers["going_concern"] = Answer("going_concern", "noul", going_concern)
        answers["dilution_risk"] = Answer(
            "dilution_risk", "noul", any("dilution" in f.lower() for f in red_flags)
        )
        answers["accounting_red_flags"] = Answer(
            "accounting_red_flags",
            "noul",
            any(
                keyword in " ".join(red_flags).lower()
                for keyword in ("cash", "convert", "red flag", "aggressive")
            ),
        )

        # ================= long-term verdict ================================
        long_action, long_reasons = _choose_long_term_action(
            mos=mos,
            risk=risk,
            quality=quality,
            going_concern=going_concern,
            status=status,
        )
        reasons.extend(long_reasons)

        # ================= tactical verdict =================================
        setup = _setup_score(technical, instrument_sentiment, news)
        drawdown = _drawdown_risk(technical)
        short_action, short_reasons = _choose_short_term_action(
            setup=setup,
            drawdown=drawdown,
            going_concern=going_concern,
            news=_news_verdict(news),
            sentiment=_sentiment_regime(instrument_sentiment, sector_sentiment, technical),
            is_held=is_held,
        )
        reasons.extend(short_reasons)

        answers["short_term_setup"] = Answer("short_term_setup", "score", float(setup))
        answers["short_term_drawdown_risk"] = Answer(
            "short_term_drawdown_risk", "score", float(drawdown)
        )

        # The confidence describes the *evidence*, not the chance of being right.
        # It has to be on the action answers, because that is where the risk gate
        # looks -- leaving it off made this engine unable to ever suggest anything.
        long_confidence = _evidence_confidence(
            status=status,
            methods_used=len(methods),
            confidence_in_valuation=confidence_in_valuation,
            periods=int(accounts.get("periods_used") or 0),
            inputs_present=int(status == "ok") + int(bool(technical)) + int(bool(accounts)),
        )
        short_confidence = _tactical_confidence(technical, state.get("recent_news") or [])

        answers["long_term_action"] = Answer(
            "long_term_action", "choice", long_action, confidence=long_confidence
        )
        answers["short_term_action"] = Answer(
            "short_term_action", "choice", short_action, confidence=short_confidence
        )

        horizon = _horizon_fit(
            long_action=long_action,
            mos=mos,
            quality=quality,
            risk=risk,
            setup=setup,
            drawdown=drawdown,
            going_concern=going_concern,
        )
        answers["horizon_fit"] = Answer("horizon_fit", "choice", horizon)

        return DecisionResponse(
            answers=answers,
            engine=ENGINE_OFFLINE,
            model_id="offline-rules-1",
            raw={"rules_fired": reasons},
            notes=[
                "Deterministic rule engine: these are not calibrated probabilities, "
                "and no probabilities are reported at all.",
                "The short-term view is a days-to-weeks swing read on daily bars. "
                "It is not intraday and cannot support day trading.",
                *reasons,
            ],
        )


# --------------------------------------------------------------------------- #
# shared context
# --------------------------------------------------------------------------- #


def _valuation_verdict(mos: float | None, status: str | None, reasons: list[str]) -> str:
    if mos is None or status != "ok":
        reasons.append(
            "no usable valuation, so no view on value is expressed"
            if status != "ok"
            else "margin of safety unavailable"
        )
        return "fairly_valued"
    if mos >= MARGIN_STRONG_BUY:
        reasons.append(f"margin of safety {mos:.0%} exceeds {MARGIN_STRONG_BUY:.0%}")
        return "deeply_undervalued"
    if mos >= MARGIN_BUY:
        reasons.append(f"margin of safety {mos:.0%} exceeds {MARGIN_BUY:.0%}")
        return "undervalued"
    if mos <= MARGIN_SELL:
        reasons.append(f"price is {-mos:.0%} above the blended fair value")
        return "deeply_overvalued"
    if mos <= MARGIN_REDUCE:
        reasons.append(f"price is {-mos:.0%} above the blended fair value")
        return "overvalued"
    reasons.append(f"margin of safety {mos:.0%} is within the fair-value band")
    return "fairly_valued"


def _margin_score(mos: float | None) -> int:
    if mos is None:
        return 0
    if mos >= 0.40:
        return 4
    if mos >= 0.25:
        return 3
    if mos >= 0.10:
        return 2
    if mos > -0.05:
        return 1
    return 0


def _quality_score(
    positives: list[str], red_flags: list[str], accounts: dict[str, Any]
) -> int:
    """Combine stated strengths against stated weaknesses."""
    score = 2  # start neutral
    score += min(len(positives), 3)
    score -= min(len(red_flags), 3)

    roce = _as_float(accounts.get("roce"))
    if roce is not None:
        if roce >= 0.20:
            score += 1
        elif roce < 0.05:
            score -= 1

    return max(0, min(4, score))


def _risk_score(accounts: dict[str, Any]) -> int:
    """0 = minimal balance-sheet risk, 4 = severe."""
    score = 0
    net_debt_to_ebitda = _as_float(accounts.get("net_debt_to_ebitda"))
    interest_cover = _as_float(accounts.get("interest_cover"))
    debt_to_equity = _as_float(accounts.get("debt_to_equity"))
    net_debt = _as_float(accounts.get("net_debt"))

    if net_debt is not None and net_debt < 0:
        return 0  # net cash

    if net_debt_to_ebitda is not None:
        if net_debt_to_ebitda > 5:
            score += 3
        elif net_debt_to_ebitda > 4:
            score += 2
        elif net_debt_to_ebitda > 2.5:
            score += 1

    if interest_cover is not None:
        if interest_cover < 1.5:
            score += 3
        elif interest_cover < 3:
            score += 1

    if debt_to_equity is not None:
        if debt_to_equity > 3:
            score += 2
        elif debt_to_equity > 1.5:
            score += 1

    return max(0, min(4, score))


def _earnings_trend(accounts: dict[str, Any], technical: dict[str, Any]) -> str:
    margin_trend = _as_float(accounts.get("margin_trend"))
    growth = _as_float(accounts.get("revenue_growth_latest"))
    annual_vol = _as_float(technical.get("volatility_annual"))

    if margin_trend is not None and margin_trend < -0.02:
        return "deteriorating"
    if growth is not None and growth < -0.05:
        return "deteriorating"
    if margin_trend is not None and margin_trend > 0.01 and (growth or 0) > 0.05:
        return "improving"
    if annual_vol is not None and annual_vol > 0.6:
        return "volatile"
    return "stable"


def _news_verdict(news: list[dict[str, Any]]) -> str:
    """Sum the materiality-weighted direction of recent headlines."""
    weights = {"critical": 3.0, "material": 2.0, "moderate": 1.0, "mild": 0.5, "none": 0.0}
    total = 0.0
    for item in news:
        if not isinstance(item, dict):
            continue
        weight = weights.get(str(item.get("materiality") or "none"), 0.0)
        if weight == 0:
            continue
        direction = str(item.get("direction") or "neutral")
        sentiment = _as_float(item.get("sentiment"))
        if direction == "positive":
            total += weight
        elif direction == "negative":
            total -= weight
        elif sentiment is not None:
            total += weight * sentiment

    if total >= 2.5:
        return "material_positive"
    if total > 0.5:
        return "mild_positive"
    if total <= -2.5:
        return "material_negative"
    if total < -0.5:
        return "mild_negative"
    return "neutral"


def _sentiment_regime(
    instrument_score: float | None, sector_score: float | None, technical: dict[str, Any]
) -> str:
    combined = instrument_score
    if combined is None:
        combined = sector_score
    elif sector_score is not None:
        combined = (instrument_score * 0.7) + (sector_score * 0.3)

    if combined is None:
        # Fall back to price position within the 52-week range, which is a crude
        # but honest proxy for crowd positioning.
        position = _as_float(technical.get("position_in_52w_range"))
        if position is None:
            return "neutral"
        combined = (position - 0.5) * 2.0

    if combined >= 0.6:
        return "euphoric"
    if combined >= 0.15:
        return "positive"
    if combined <= -0.6:
        return "fearful"
    if combined <= -0.15:
        return "negative"
    return "neutral"


def _going_concern_evidence(red_flags: list[str], accounts: dict[str, Any]) -> bool:
    if any("going concern" in flag.lower() for flag in red_flags):
        return True
    net_income = _as_float(accounts.get("net_income"))
    if net_income is not None and net_income < 0:
        cover = _as_float(accounts.get("interest_cover"))
        if cover is not None and cover < 1.0:
            return True
    return False


# --------------------------------------------------------------------------- #
# long-term verdict
# --------------------------------------------------------------------------- #


def _choose_long_term_action(
    *,
    mos: float | None,
    risk: int,
    quality: int,
    going_concern: bool,
    status: str | None,
) -> tuple[str, list[str]]:
    """Pick a long-term action, naming the rule that decided it.

    Risk gates come before value: a large discount into a company that may not
    survive is not a bargain, and the action should say so rather than averaging
    the two signals into a mild "hold".
    """
    reasons: list[str] = []

    if going_concern:
        reasons.append("rule (long): going-concern evidence -> avoid")
        return "avoid", reasons

    if status != "ok" or mos is None:
        reasons.append("rule (long): no usable valuation -> hold")
        return "hold", reasons

    if risk >= RISK_SCORE_BLOCKING and mos > 0:
        reasons.append(
            f"rule (long): balance-sheet risk {risk}/4 blocks a purchase despite the discount"
        )
        return "hold", reasons

    if mos >= MARGIN_STRONG_BUY and quality >= 2 and risk <= 2:
        reasons.append(
            f"rule (long): margin of safety {mos:.0%} and quality {quality}/4 -> strong_buy"
        )
        return "strong_buy", reasons

    if mos >= MARGIN_BUY and risk <= 3:
        reasons.append(f"rule (long): margin of safety {mos:.0%} -> buy")
        return "buy", reasons

    if mos <= MARGIN_SELL:
        reasons.append(f"rule (long): price {-mos:.0%} above fair value -> sell")
        return "sell", reasons

    if mos <= MARGIN_REDUCE:
        reasons.append(f"rule (long): price {-mos:.0%} above fair value -> reduce")
        return "reduce", reasons

    reasons.append("rule (long): no threshold crossed -> hold")
    return "hold", reasons


# --------------------------------------------------------------------------- #
# tactical verdict
# --------------------------------------------------------------------------- #


def _setup_score(
    technical: dict[str, Any], sentiment: float | None, news: list[dict[str, Any]]
) -> int:
    """How clean is the tactical setup, 0 (poor) to 4 (excellent).

    **Technical evidence leads.** The score is built from measured quantities --
    trend, momentum, range position, volume confirmation -- and sentiment and news
    can only *modulate* it, by at most one point, and only once a technical picture
    actually exists.

    That asymmetry is deliberate. Treating sentiment as an equal contributor lets a
    mildly upbeat mood push an otherwise featureless chart to "Good", which is not
    a setup anyone should trade. A tactical view with no technical support is not a
    tactical view.
    """
    # --- technical component -------------------------------------------------
    technical_score = 2  # neutral start

    trend = str(technical.get("trend") or "unknown")
    if trend == "uptrend":
        technical_score += 1
    elif trend == "downtrend":
        technical_score -= 2

    momentum = _as_float(technical.get("return_3m"))
    if momentum is not None:
        if momentum > 0.05:
            technical_score += 1
        elif momentum < -0.05:
            technical_score -= 1

    position = _as_float(technical.get("position_in_52w_range"))
    if position is not None:
        if position > 0.7:
            technical_score += 1  # pushing the top of the range
        elif position < 0.3:
            technical_score -= 1

    volume_trend = _as_float(technical.get("volume_trend"))
    if volume_trend is not None and volume_trend > 0.2:
        # Confirmation: the move is being participated in rather than drifting.
        technical_score += 1

    technical_score = max(0, min(4, technical_score))

    # --- context can only modulate, never create, a setup --------------------
    news_verdict = _news_verdict(news)
    context_positive = (sentiment is not None and sentiment > 0.15) or news_verdict in (
        "material_positive",
        "mild_positive",
    )
    context_negative = (sentiment is not None and sentiment < -0.15) or news_verdict in (
        "material_negative",
        "mild_negative",
    )

    if context_negative and not context_positive:
        # Bad news can undermine any setup, including a merely neutral chart.
        technical_score -= 1
    elif context_positive and not context_negative and technical_score >= 3:
        # Good news can confirm a setup that already exists -- but a neutral or
        # poor chart stays exactly as it is. Otherwise a mildly upbeat mood would
        # be enough to call a featureless chart "Good", which is not a setup.
        technical_score += 1

    return max(0, min(4, technical_score))


def _drawdown_risk(technical: dict[str, Any]) -> int:
    """Risk of an adverse move over the next few weeks, 0 (minimal) to 4 (severe).

    Deliberately measures *extension* rather than direction: a stock that has run
    hard is more vulnerable to giving some back, whatever the trend.
    """
    score = 0

    position = _as_float(technical.get("position_in_52w_range"))
    if position is not None:
        if position > 0.97:
            score += 2
        elif position > 0.9:
            score += 1

    rsi = _as_float(technical.get("rsi_14"))
    if rsi is not None:
        if rsi > 78:
            score += 2
        elif rsi > 70:
            score += 1

    annual_vol = _as_float(technical.get("volatility_annual"))
    if annual_vol is not None:
        if annual_vol > 0.7:
            score += 2
        elif annual_vol > 0.4:
            score += 1

    run = _as_float(technical.get("return_1m"))
    if run is not None and run > 0.25:
        score += 1

    return max(0, min(4, score))


def _choose_short_term_action(
    *,
    setup: int,
    drawdown: int,
    going_concern: bool,
    news: str,
    sentiment: str,
    is_held: bool,
) -> tuple[str, list[str]]:
    """Pick a tactical action, naming the rule that decided it.

    ``is_held`` matters here in a way it does not for the long-term view: a weak
    setup on a name you own is a reason to trim, while the same setup on a name you
    do not own is simply a reason not to buy. Collapsing those into one word would
    make the tactical verdict misleading for half its readers.
    """
    reasons: list[str] = []

    if going_concern:
        reasons.append("rule (short): going-concern evidence -> avoid")
        return "avoid", reasons

    if drawdown >= DRAWDOWN_BLOCKING:
        reasons.append(
            f"rule (short): drawdown risk {drawdown}/4 too high to initiate -> hold"
        )
        return "hold", reasons

    if setup >= SETUP_STRONG and drawdown <= 1:
        reasons.append(f"rule (short): setup {setup}/4 with low risk -> strong_buy")
        return "strong_buy", reasons

    if setup >= SETUP_GOOD and drawdown <= 2:
        reasons.append(f"rule (short): setup {setup}/4 -> buy")
        return "buy", reasons

    if setup <= SETUP_WEAK:
        if is_held:
            reasons.append(
                f"rule (short): setup {setup}/4 and already held -> reduce"
            )
            return "reduce", reasons
        reasons.append(f"rule (short): setup {setup}/4 -> avoid initiating")
        return "avoid", reasons

    if sentiment in ("negative", "fearful") and news in (
        "material_negative",
        "mild_negative",
    ):
        # Weak setup in neither bucket, but both sentiment and news have turned.
        if is_held:
            reasons.append("rule (short): negative sentiment and news -> reduce")
            return "reduce", reasons
        reasons.append("rule (short): negative sentiment and news -> avoid")
        return "avoid", reasons

    reasons.append(f"rule (short): setup {setup}/4 is neutral -> hold")
    return "hold", reasons


def _horizon_fit(
    *,
    long_action: str,
    mos: float | None,
    quality: int,
    risk: int,
    setup: int,
    drawdown: int,
    going_concern: bool,
) -> str:
    """State plainly which horizon, if either, offers something worth acting on."""
    if going_concern:
        return "neither"

    long_ok = (
        long_action in ("strong_buy", "buy")
        and mos is not None
        and quality >= 2
        and risk <= 3
    )
    short_ok = setup >= SETUP_GOOD and drawdown <= 2

    if long_ok and short_ok:
        return "both"
    if long_ok:
        return "long_term"
    if short_ok:
        return "short_term"
    return "neither"


def _evidence_confidence(
    *,
    status: str | None,
    methods_used: int,
    confidence_in_valuation: float,
    periods: int,
    inputs_present: int = 0,
) -> float:
    """A crude evidence-quality score, explicitly not a probability of success."""
    if status != "ok":
        return CONFIDENCE_THIN
    if methods_used >= 3 and periods >= 3:
        return round(min(CONFIDENCE_FULL, 0.4 + confidence_in_valuation * 0.5), 4)
    if methods_used >= 2 and periods >= 2:
        return round(min(CONFIDENCE_PARTIAL, 0.3 + confidence_in_valuation * 0.4), 4)
    return CONFIDENCE_THIN


def _tactical_confidence(technical: dict[str, Any], news: list[dict[str, Any]]) -> float:
    """Evidence quality for the tactical view.

    Priced off how much of the technical picture is actually present. A tactical
    call resting on two of six inputs should not look as solid as one resting on
    all of them.
    """
    inputs = (
        "sma_50",
        "sma_200",
        "rsi_14",
        "return_3m",
        "position_in_52w_range",
        "volume_trend",
    )
    present = sum(1 for key in inputs if _as_float(technical.get(key)) is not None)
    coverage = present / len(inputs)

    # Confidence rises with coverage; news adds a little context but cannot
    # substitute for a missing technical picture.
    base = CONFIDENCE_THIN + coverage * (CONFIDENCE_FULL - CONFIDENCE_THIN)
    if news:
        base = min(base + 0.05, CONFIDENCE_FULL)
    return round(base, 4)

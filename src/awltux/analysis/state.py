"""Build the canonical state that the decision model evaluates.

The state is the entire evidence base for one decision, and building it well is
most of the work of getting a good decision. Three properties are engineered
here:

**It fits.** JEV accepts a 64k-token request but caps the state at 32k tokens, so
a full annual report cannot be sent. DeepSeek compresses filings into cited
facts first and this module assembles the compact result. A state that overflows
is truncated *deliberately and visibly*, never silently.

**It is canonical.** The same inputs always serialise to the same bytes, so the
SHA-256 recorded with a decision identifies exactly what the model saw. Without
this, "replay the decision" would be a claim rather than a check.

**It is source-tagged.** Every figure carries where it came from and when. A
model asked to judge a company should be able to see that a number came from a
filed statement rather than a scraped snapshot.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from awltux.analysis.fundamental import FundamentalSnapshot
from awltux.analysis.technical import TechnicalSnapshot
from awltux.analysis.valuation import ValuationResult
from awltux.db import Instrument, NewsItem

#: Rough characters-per-token for the estimator. Deliberately conservative:
#: JSON with numbers tokenises worse than prose, so under-estimating here would
#: cause 400s from the API.
CHARS_PER_TOKEN = 3.4

#: Headlines included in the state. Beyond this the marginal information is tiny
#: while the token cost is linear.
MAX_NEWS_ITEMS = 12


@dataclass(slots=True)
class DecisionState:
    """A built state plus the bookkeeping needed to store and audit it."""

    payload: dict[str, Any]
    text: str
    sha256: str
    token_estimate: int
    truncated: bool = False
    dropped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "payload": self.payload,
            "sha256": self.sha256,
            "token_estimate": self.token_estimate,
            "truncated": self.truncated,
            "dropped": self.dropped,
        }


def canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, no incidental whitespace.

    ``default=str`` keeps a stray ``date`` or ``Decimal`` from raising, and the
    sort means dict construction order can never change the hash.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def state_hash(payload: Any) -> str:
    """Canonical hash of a state.

    Pruning is applied here as well as in :func:`build_state` so that the hash is
    stable no matter which call site produced the payload. That matters for the
    ledger's integrity check, which re-hashes a stored state months later and must
    reproduce the recorded digest exactly. ``_prune`` is idempotent, so applying
    it to an already-pruned state is a no-op.
    """
    return hashlib.sha256(canonical_json(_prune(payload)).encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Cheap token estimate, adequate for enforcing a hard context cap."""
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


def _round(value: Any, digits: int = 4) -> Any:
    """Trim float noise so trivial precision differences do not change the hash."""
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, digits)
    return value


def _prune(payload: Any) -> Any:
    """Recursively round floats and drop ``None`` values.

    Dropping nulls matters for hashing: adding a field that is always absent must
    not change the state hash for every instrument.
    """
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            pruned = _prune(value)
            if pruned is None or pruned == {} or pruned == []:
                continue
            out[key] = pruned
        return out
    if isinstance(payload, list):
        return [_prune(item) for item in payload]
    return _round(payload)


def _freshness(when: dt.datetime | None) -> str | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    days = (dt.datetime.now(dt.UTC) - when).total_seconds() / 86400.0
    if days < 0.05:
        return "minutes"
    if days < 1:
        return f"{days * 24:.0f} hours"
    if days < 45:
        return f"{days:.0f} days"
    return f"{days / 30:.0f} months"


def _news_payload(items: list[NewsItem]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items[:MAX_NEWS_ITEMS]:
        entry: dict[str, Any] = {"headline": item.title}
        if item.materiality:
            entry["materiality"] = item.materiality
        if item.direction:
            entry["direction"] = item.direction
        if item.horizon:
            entry["horizon"] = item.horizon
        score = item.provider_sentiment if item.provider_sentiment is not None else item.sentiment_score
        if score is not None:
            entry["sentiment"] = _round(score)
        entry["source"] = item.source
        entry["age"] = _freshness(item.published_at)
        out.append(entry)
    return out


def build_state(
    *,
    instrument: Instrument,
    valuation: ValuationResult | None,
    technical: TechnicalSnapshot | None,
    fundamentals: FundamentalSnapshot | None,
    sentiment_score: float | None,
    news: list[NewsItem],
    sector_sentiment: float | None = None,
    extracted_facts: dict[str, Any] | None = None,
    filing_summary: str | None = None,
    deep_research: dict[str, Any] | None = None,
    max_tokens: int = 28_000,
    as_of: dt.datetime | None = None,
) -> DecisionState:
    """Assemble, prune, hash and size-check the decision state.

    Truncation is progressive and recorded: narrative context goes first, then the deep-dive,
    then headlines, then extracted filing facts. Quantities and the valuation itself are never
    dropped, because a decision made without them is not a decision this app should be making.

    **The deep-dive is dropped second, after the filing summary.** Both are narrative, and the
    prose a reader paid for is worth less to a *decision* than the figures and the headlines --
    which is why they outlive it. It is not dropped first either: a deep-dive that read the
    three annual reports is a better summary of them than the filing summariser's one-document
    read, and it is the newest evidence on the page.
    """
    as_of = as_of or dt.datetime.now(dt.UTC)
    dropped: list[str] = []

    payload: dict[str, Any] = {
        "task": (
            "Judge whether this share is under- or over-valued, and what action a "
            "long-only private investor should take. Weigh the deterministic "
            "valuation, the quality and trend of the accounts, the balance sheet, "
            "recent news and market sentiment. Say when the evidence is thin."
        ),
        "as_of": as_of.date().isoformat(),
        "instrument": _instrument_payload(instrument),
        "valuation": _valuation_payload(valuation),
        "accounts": fundamentals.as_dict() if fundamentals else None,
        "price_and_trend": technical.as_dict() if technical else None,
        "sentiment": _sentiment_payload(sentiment_score, sector_sentiment),
        "recent_news": _news_payload(news),
        "filed_facts": extracted_facts,
        "filing_summary": filing_summary,
        "deep_research": deep_research,
    }

    pruned = _prune(payload)

    def sized(candidate: dict[str, Any]) -> tuple[str, int]:
        text = canonical_json(candidate)
        return text, estimate_tokens(text)

    text, tokens = sized(pruned)
    truncated = False

    # Progressive degradation, cheapest information first.
    for key, label in (
        ("filing_summary", "filing summary"),
        ("deep_research", "deep-dive research"),
        ("recent_news", "older headlines"),
        ("filed_facts", "extracted filing detail"),
    ):
        if tokens <= max_tokens:
            break
        if key == "recent_news" and isinstance(pruned.get(key), list):
            current = pruned[key]
            while len(current) > 3 and tokens > max_tokens:
                current.pop()
                dropped.append("oldest headline")
                text, tokens = sized(pruned)
            truncated = True
            continue
        if key in pruned:
            pruned.pop(key)
            dropped.append(label)
            truncated = True
            text, tokens = sized(pruned)

    if tokens > max_tokens:
        # Nothing safe left to remove. Record the overrun rather than lying about
        # the size, so the caller can refuse or chunk explicitly.
        dropped.append(
            f"state still {tokens} tokens after progressive truncation "
            f"(cap {max_tokens}); send anyway and let the API decide"
        )

    return DecisionState(
        payload=pruned,
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        token_estimate=tokens,
        truncated=truncated,
        dropped=dropped,
    )


def _instrument_payload(instrument: Instrument) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": instrument.name,
        "ticker": instrument.t212_ticker,
        "exchange": instrument.exchange_name,
        "currency": instrument.currency_code,
        # Whether the position is already held changes what the right answer is,
        # especially on the tactical horizon: a weak setup on a name you own is a
        # reason to trim, while the same setup on a name you do not own is simply a
        # reason not to buy.
        "is_held": bool(instrument.is_held),
    }
    if instrument.isin:
        payload["isin"] = instrument.isin
    if instrument.sector:
        payload["sector"] = instrument.sector
    if instrument.industry:
        payload["industry"] = instrument.industry
    if instrument.market_cap:
        payload["market_cap"] = instrument.market_cap
    if instrument.median_daily_turnover_gbp:
        payload["median_daily_turnover_gbp"] = instrument.median_daily_turnover_gbp
    return payload


def _valuation_payload(valuation: ValuationResult | None) -> dict[str, Any] | None:
    if valuation is None:
        return None
    payload: dict[str, Any] = {
        "status": valuation.status,
        "price": valuation.price,
        "fair_value_low": valuation.fair_value_low,
        "fair_value_base": valuation.fair_value_base,
        "fair_value_high": valuation.fair_value_high,
        "margin_of_safety": valuation.margin_of_safety,
        "valuation_confidence": valuation.valuation_confidence,
        "methods_applied": valuation.methods_applied,
    }
    # Per-method values matter to the judgement: agreement between methods is
    # evidence, and so is the absence of it.
    methods = [
        {
            "method": method.name,
            "value_per_share": method.fair_value_per_share,
            "applicable": method.applicable,
            "why_not": None if method.applicable else method.reason,
        }
        for method in (valuation.methods or [])
    ]
    if methods:
        payload["methods"] = methods
    if valuation.notes:
        payload["analyst_notes"] = valuation.notes
    return payload


def _sentiment_payload(
    instrument_score: float | None, sector_score: float | None
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if instrument_score is not None:
        payload["instrument_score"] = instrument_score
        payload["instrument_score_meaning"] = "−1 very negative, 0 neutral, +1 very positive"
    if sector_score is not None:
        payload["sector_score"] = sector_score
    return payload or None


def state_summary(state: DecisionState) -> str:
    """One-line description for logs and the run history."""
    instrument = state.payload.get("instrument", {})
    valuation = state.payload.get("valuation") or {}
    mos = valuation.get("margin_of_safety")
    mos_text = f"{mos:+.1%}" if isinstance(mos, (int, float)) else "n/a"
    return (
        f"{instrument.get('ticker', '?')} "
        f"tokens={state.token_estimate} mos={mos_text} "
        f"truncated={state.truncated}"
    )

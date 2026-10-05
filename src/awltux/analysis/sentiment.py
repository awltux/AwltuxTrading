"""Sentiment aggregation: news and market behaviour into one score per scope.

The score is a weighted blend rather than an average, because an untagged
headline and a directly relevant one should not count the same:

* **Relevance** -- our classifier's judgement of how much the article concerns
  the instrument, which is what stops Yahoo's loose per-symbol matching from
  polluting the signal.
* **Recency** -- an exponential decay, because sentiment is a statement about now.
* **Materiality** -- how likely the article is to move a price at all.

Market behaviour is included alongside news, separately weighted and separately
recorded, so a sentiment reading can always be decomposed into "what was said"
and "what the price did".
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.analysis.technical import volatility
from awltux.config import Settings, get_settings
from awltux.db import Instrument, NewsItem, PriceBar, SentimentSeries, utcnow
from awltux.db.session import release_write_lock

logger = logging.getLogger(__name__)

#: Half-life of a headline's contribution, in days. Roughly a trading week.
NEWS_HALF_LIFE_DAYS = 5.0

#: How much each classified materiality level counts.
MATERIALITY_WEIGHT = {
    "critical": 1.0,
    "material": 0.75,
    "moderate": 0.5,
    "mild": 0.25,
    "none": 0.1,
    None: 0.3,  # unclassified: present but discounted
}

#: Component weights in the final blend. News dominates because it is the
#: forward-looking signal; price action confirms or contradicts it.
COMPONENT_WEIGHTS = {
    "news": 0.55,
    "momentum": 0.25,
    "volume": 0.10,
    "trend": 0.10,
}

SCORE_MIN, SCORE_MAX = -1.0, 1.0


@dataclass(slots=True)
class SentimentComponents:
    news_raw: float | None = None
    news_weight: float = 0.0
    article_count: int = 0
    momentum: float | None = None
    volume: float | None = None
    trend: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "news_raw": self.news_raw,
            "news_weight": self.news_weight,
            "article_count": self.article_count,
            "momentum": self.momentum,
            "volume": self.volume,
            "trend": self.trend,
            "weights": COMPONENT_WEIGHTS,
            "notes": self.notes,
        }


def _clamp(value: float | None) -> float | None:
    if value is None:
        return None
    return max(SCORE_MIN, min(SCORE_MAX, value))


def _decay(age_days: float, half_life: float = NEWS_HALF_LIFE_DAYS) -> float:
    """Exponential recency weight, 1.0 at age zero."""
    if age_days < 0:
        return 1.0
    return 0.5 ** (age_days / half_life)


def news_sentiment(
    items: list[NewsItem], *, as_of: dt.datetime | None = None
) -> tuple[float | None, float, int]:
    """Weighted average sentiment across articles.

    Returns ``(score, total_weight, article_count)``. Provider-supplied and
    self-classified scores are used together, with the provider value preferred
    when both exist because it is measured rather than inferred.
    """
    as_of = as_of or utcnow()
    numerator = 0.0
    denominator = 0.0
    count = 0

    for item in items:
        score = item.provider_sentiment if item.provider_sentiment is not None else item.sentiment_score
        if score is None:
            continue
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue

        published = item.published_at
        if published is None:
            age_days = 7.0  # undated: treat as old rather than as breaking news
        else:
            if published.tzinfo is None:
                published = published.replace(tzinfo=dt.UTC)
            age_days = (as_of - published).total_seconds() / 86400.0

        relevance = item.relevance if item.relevance is not None else 0.5
        weight = (
            _decay(age_days)
            * MATERIALITY_WEIGHT.get(item.materiality, MATERIALITY_WEIGHT[None])
            * max(0.0, min(float(relevance), 1.0))
        )
        if weight <= 0:
            continue

        numerator += score * weight
        denominator += weight
        count += 1

    if denominator <= 0:
        return None, 0.0, count
    return _clamp(numerator / denominator), denominator, count


def momentum_component(closes: list[float]) -> tuple[float | None, float | None]:
    """Risk-adjusted recent momentum plus a volume-agnostic volatility read.

    Raw return is normalised by realised volatility so a sleepy utility and a
    volatile small cap can share a scale. Without this, the score would mostly
    measure volatility rather than direction.
    """
    if len(closes) < 30:
        return None, None

    window = closes[-63:] if len(closes) >= 63 else closes
    if window[0] <= 0:
        return None, None
    raw_return = (window[-1] - window[0]) / window[0]

    vol = volatility(closes)
    # Scale so a 1-sigma move maps to roughly 0.5 on the -1..1 scale. Without
    # this, a sleepy utility and a volatile small cap cannot share a scale.
    scaled = raw_return / (vol * 0.5) if vol and vol > 0.05 else raw_return * 3.0

    return _clamp(scaled), vol


def volume_component(bars: list[PriceBar]) -> float | None:
    """Recent volume relative to its own baseline.

    Rising volume on its own is directionless, so this is deliberately reported
    as a small, low-weight component rather than being given a sign.
    """
    volumes = [bar.volume for bar in bars if bar.volume]
    if len(volumes) < 40:
        return None
    recent = sum(volumes[-10:]) / 10
    baseline = sum(volumes[-40:-10]) / 30
    if baseline <= 0:
        return None
    ratio = recent / baseline
    # Map 1x -> 0, 2x -> 0.4, 0.5x -> -0.2, then clamp.
    return _clamp((ratio - 1.0) * 0.4)


def compute_instrument_sentiment(
    *,
    items: list[NewsItem],
    bars: list[PriceBar],
    as_of: dt.datetime | None = None,
) -> tuple[float | None, SentimentComponents]:
    """Blend the components into one score for an instrument."""
    components = SentimentComponents()

    score, weight, count = news_sentiment(items, as_of=as_of)
    components.news_raw = score
    components.news_weight = weight
    components.article_count = count

    closes = [bar.close for bar in bars if bar.close]
    momentum, vol = momentum_component(closes)
    components.momentum = momentum
    if vol is not None:
        components.notes.append(f"realised volatility {vol:.0%}")

    components.volume = volume_component(bars)

    if len(closes) >= 200:
        sma_200 = sum(closes[-200:]) / 200
        components.trend = _clamp((closes[-1] - sma_200) / sma_200 * 3.0) if sma_200 else None

    # Only blend components that exist, renormalising the weights across them.
    available: dict[str, float] = {}
    if components.news_raw is not None:
        available["news"] = components.news_raw
    if components.momentum is not None:
        available["momentum"] = components.momentum
    if components.volume is not None:
        available["volume"] = components.volume
    if components.trend is not None:
        available["trend"] = components.trend

    if not available:
        components.notes.append("no sentiment inputs available")
        return None, components

    total_weight = sum(COMPONENT_WEIGHTS[key] for key in available)
    blended = sum(available[key] * COMPONENT_WEIGHTS[key] for key in available) / total_weight
    return _clamp(blended), components


def _recent_items(session: Session, ticker: str, *, days: int = 30) -> list[NewsItem]:
    cutoff = utcnow() - dt.timedelta(days=days)
    rows = session.execute(
        select(NewsItem).where(NewsItem.published_at >= cutoff).order_by(NewsItem.published_at.desc())
    ).scalars().all()
    # Membership test in Python: the tickers column is JSON, and the portable
    # SQL differs between SQLite and Postgres.
    return [row for row in rows if ticker in (row.tickers or [])]


def aggregate_all(
    session: Session, *, settings: Settings | None = None, days: int = 30
) -> dict[str, Any]:
    """Recompute today's sentiment series for every instrument and sector."""
    settings = settings or get_settings()
    today = dt.date.today()
    now = utcnow()

    instruments = session.execute(
        select(Instrument).where(Instrument.in_universe.is_(True))
    ).scalars().all()

    stats = {"instruments_seen": 0, "rows_written": 0, "skipped_no_data": 0}
    sector_accumulator: dict[str, list[float]] = {}
    sector_articles: dict[str, int] = {}

    for instrument in instruments:
        stats["instruments_seen"] += 1

        bars = list(
            session.execute(
                select(PriceBar)
                .where(PriceBar.instrument_t212_ticker == instrument.t212_ticker)
                .order_by(PriceBar.date.asc())
            ).scalars().all()
        )
        items = _recent_items(session, instrument.t212_ticker, days=days)

        score, components = compute_instrument_sentiment(items=items, bars=bars, as_of=now)
        if score is None:
            stats["skipped_no_data"] += 1
            continue

        _upsert_series(
            session,
            scope_type="instrument",
            scope_id=instrument.t212_ticker,
            date=today,
            score=score,
            article_count=components.article_count,
            components=components.as_dict(),
        )
        stats["rows_written"] += 1

        if instrument.sector:
            sector_accumulator.setdefault(instrument.sector, []).append(score)
            sector_articles[instrument.sector] = (
                sector_articles.get(instrument.sector, 0) + components.article_count
            )

        # Release the write lock between instruments. This loop runs over the whole
        # universe and holds a transaction the entire time, which starves every
        # other writer for as long as it takes.
        release_write_lock(session)

    # Sector score is the mean of its constituents' scores: a breadth-weighted
    # read, so one very negative name cannot define a whole sector.
    for sector, scores in sector_accumulator.items():
        if not scores:
            continue
        _upsert_series(
            session,
            scope_type="sector",
            scope_id=sector,
            date=today,
            score=sum(scores) / len(scores),
            article_count=sector_articles.get(sector, 0),
            components={"constituents": len(scores)},
        )
        stats["rows_written"] += 1

    session.flush()
    logger.info("sentiment aggregation: %s", stats)
    return stats


def _upsert_series(
    session: Session,
    *,
    scope_type: str,
    scope_id: str,
    date: dt.date,
    score: float,
    article_count: int,
    components: dict[str, Any],
) -> None:
    row = session.get(SentimentSeries, (scope_type, scope_id, date))
    if row is None:
        row = SentimentSeries(
            scope_type=scope_type,
            scope_id=scope_id,
            date=date,
            score=score,
        )
        session.add(row)
    row.score = score
    row.article_count = article_count
    row.components = components
    row.computed_at = utcnow()


def latest_sentiment(session: Session, ticker: str) -> float | None:
    row = session.execute(
        select(SentimentSeries)
        .where(SentimentSeries.scope_type == "instrument")
        .where(SentimentSeries.scope_id == ticker)
        .order_by(SentimentSeries.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row.score if row else None


def sector_sentiment_latest(session: Session) -> dict[str, float]:
    rows = session.execute(
        select(SentimentSeries)
        .where(SentimentSeries.scope_type == "sector")
        .order_by(SentimentSeries.date.desc())
    ).scalars().all()
    out: dict[str, float] = {}
    for row in rows:
        out.setdefault(row.scope_id, row.score)
    return out

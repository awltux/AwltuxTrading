"""News ingest: gather, canonicalise, dedupe, persist.

The shape of this pipeline is driven by the free tiers it sits on: hundreds of
loosely-matched headlines arrive from RSS, a small number of precisely-tagged and
sentiment-scored articles arrive from Marketaux, and only a handful are material.
So the work is staged to spend the expensive step (LLM classification) on as few
items as possible:

1. **Gather** from every configured source, swallowing per-source failures.
2. **Prefilter** cheaply -- drop obvious non-news, and require the subject to be
   mentioned at all.
3. **Dedupe** on a canonical URL, because the same story arrives via Google News,
   Yahoo and Finnhub with different tracking parameters.
4. **Classify** (optional, injected) to fill in materiality and direction.

Classification is a callback rather than a direct dependency so this module stays
testable without an LLM and so the pipeline still runs when no API key is set.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import Instrument, NewsItem, utcnow
from awltux.db.session import release_write_lock
from awltux.providers.news_rss import (
    FinnhubNewsProvider,
    GdeltProvider,
    MarketauxNewsProvider,
    RawNewsItem,
    RssNewsProvider,
    company_query,
)

logger = logging.getLogger(__name__)

#: Signature of an injected classifier: item -> updates, or None to leave as-is.
Classifier = Callable[[RawNewsItem, Instrument | None], dict[str, Any] | None]


@dataclass(slots=True)
class NewsIngestReport:
    fetched: int = 0
    prefiltered_out: int = 0
    duplicates: int = 0
    written: int = 0
    classified: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "prefiltered_out": self.prefiltered_out,
            "duplicates": self.duplicates,
            "written": self.written,
            "classified": self.classified,
            "by_source": self.by_source,
            "errors": self.errors[:10],
        }


class Prefilter:
    """Cheap rejection rules applied before anything expensive runs.

    Rules are deliberately conservative: rejecting a real headline is worse than
    passing a dull one, because the dull one only costs a classification call
    while the rejected one is invisible forever.
    """

    def __init__(self, settings: Settings) -> None:
        config = settings.news.prefilter
        self.min_title_chars = config.min_title_chars
        self.require_ticker_mention = config.require_any_ticker_mention
        self.drop_patterns = [re.compile(p) for p in config.drop_patterns]

    def keep(self, item: RawNewsItem, instrument: Instrument | None = None) -> bool:
        title = item.title.strip()
        if len(title) < self.min_title_chars:
            return False
        for pattern in self.drop_patterns:
            if pattern.search(title):
                return False
        if self.require_ticker_mention and instrument is not None:
            # Require the company name or a distinctive word of it to appear.
            words = [
                word
                for word in re.split(r"[^A-Za-z0-9]+", instrument.name)
                if len(word) > 3
            ]
            haystack = f"{title} {item.summary or ''}".lower()
            if words and not any(word.lower() in haystack for word in words):
                return False
        return True


def gather_for_instrument(
    instrument: Instrument,
    *,
    settings: Settings,
    rss: RssNewsProvider,
    finnhub: FinnhubNewsProvider | None = None,
    marketaux: MarketauxNewsProvider | None = None,
) -> list[RawNewsItem]:
    """Collect headlines for one instrument from every configured source.

    Google News gets both a UK and a US edition for UK listings, since UK
    coverage often surfaces only in one of them.
    """
    items: list[RawNewsItem] = []
    query = company_query(instrument.name, instrument.t212_ticker)

    regions = [("GB", "en")] if _is_uk(instrument) else [("US", "en")]
    for region, language in regions:
        items.extend(
            rss.fetch_feed(rss.google_news_url(query, region=region, language=language))
        )
        for item in items[-_FEED_SIZE:]:
            item.tickers = [instrument.t212_ticker]

    if instrument.yahoo_symbol:
        symbol = instrument.yahoo_symbol
        region = "GB" if symbol.upper().endswith(".L") else "US"
        lang = "en-GB" if region == "GB" else "en-US"
        yahoo_items = rss.fetch_feed(rss.yahoo_news_url(symbol, region=region, language=lang))
        for item in yahoo_items:
            item.tickers = [instrument.t212_ticker]
        items.extend(yahoo_items)

    if finnhub is not None and finnhub.configured and instrument.yahoo_symbol:
        # Finnhub takes the bare symbol, without the exchange suffix.
        bare = instrument.yahoo_symbol.split(".")[0]
        items.extend(finnhub.company_news(bare))

    if marketaux is not None and marketaux.configured and instrument.yahoo_symbol:
        bare = instrument.yahoo_symbol.split(".")[0]
        items.extend(marketaux.news([bare]))

    for item in items:
        if not item.tickers:
            item.tickers = [instrument.t212_ticker]
    return items


_FEED_SIZE = 50


def _is_uk(instrument: Instrument) -> bool:
    from awltux.ingest.symbols import is_uk_listing

    return is_uk_listing(instrument.exchange_name, instrument.yahoo_symbol)


def persist_items(
    session: Session,
    items: Iterable[RawNewsItem],
    *,
    classifier: Classifier | None = None,
    report: NewsIngestReport | None = None,
    instrument: Instrument | None = None,
) -> NewsIngestReport:
    """Insert new items, skipping ones already stored. Returns a report."""
    report = report or NewsIngestReport()

    for item in items:
        report.fetched += 1
        report.by_source[item.source] = report.by_source.get(item.source, 0) + 1

        url_hash = item.url_hash
        exists = session.execute(
            select(NewsItem.id).where(NewsItem.url_hash == url_hash).limit(1)
        ).scalar_one_or_none()
        if exists is not None:
            report.duplicates += 1
            continue

        row = NewsItem(
            source=item.source,
            url=item.url,
            url_hash=url_hash,
            title=item.title[:768],
            summary=item.summary,
            published_at=item.published_at,
            tickers=list(item.tickers),
            sectors=list(item.sectors),
            provider_sentiment=item.provider_sentiment,
            raw=item.raw,
            created_at=utcnow(),
        )

        if classifier is not None:
            try:
                updates = classifier(item, instrument)
            except Exception as exc:
                # A classifier failure must not lose the headline.
                logger.warning("classification failed for %r: %s", item.title[:80], exc)
                updates = None
            if updates:
                report.classified += 1
                row.materiality = updates.get("materiality")
                row.direction = updates.get("direction")
                row.horizon = updates.get("horizon")
                row.sentiment_score = updates.get("sentiment_score")
                row.relevance = updates.get("relevance")
                row.engine = updates.get("engine")
                if updates.get("tickers"):
                    row.tickers = list({*row.tickers, *updates["tickers"]})
                if updates.get("sectors"):
                    row.sectors = list({*row.sectors, *updates["sectors"]})

        session.add(row)
        report.written += 1

        # Flush inside the loop so the dedupe lookup sees rows added in this same
        # batch; without it, two copies of one story in a single feed both insert.
        session.flush()

    return report


def ingest_rss_news(
    session: Session,
    *,
    settings: Settings | None = None,
    tickers: list[str] | None = None,
    classifier: Classifier | None = None,
    limit_instruments: int | None = None,
) -> NewsIngestReport:
    """Poll RSS (and optional Finnhub/Marketaux) for the universe."""
    settings = settings or get_settings()
    report = NewsIngestReport()
    prefilter = Prefilter(settings)

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    instruments = list(session.execute(statement).scalars().all())
    if limit_instruments:
        # Prioritise held names when the poll is rationed.
        instruments.sort(key=lambda row: (not row.is_held, row.t212_ticker))
        instruments = instruments[:limit_instruments]

    rss = RssNewsProvider(settings)
    finnhub = FinnhubNewsProvider(settings)
    marketaux = MarketauxNewsProvider(settings)

    try:
        for instrument in instruments:
            try:
                gathered = gather_for_instrument(
                    instrument,
                    settings=settings,
                    rss=rss,
                    finnhub=finnhub,
                    marketaux=marketaux,
                )
            except Exception as exc:
                report.errors.append(f"{instrument.t212_ticker}: {exc}")
                continue

            kept = []
            for item in gathered:
                if prefilter.keep(item, instrument):
                    kept.append(item)
                else:
                    report.prefiltered_out += 1

            persist_items(
                session,
                kept[: settings.news.max_items_per_feed_poll],
                classifier=classifier,
                report=report,
                instrument=instrument,
            )

            # Release SQLite's write lock between instruments. This loop makes
            # roughly a thousand HTTP requests for a 500-instrument universe, and
            # holding one transaction across all of them locked every other writer
            # out for minutes.
            release_write_lock(session)
    finally:
        rss.close()
        finnhub.close()
        marketaux.close()

    logger.info("news ingest: %s", report.as_dict())
    return report


def ingest_sector_sentiment(
    session: Session,
    *,
    settings: Settings | None = None,
    sectors: list[str] | None = None,
) -> dict[str, Any]:
    """Sample GDELT tone per sector. Keyless, so this runs without any quota cost.

    GDELT has no ticker mapping, which is exactly why it is used here rather than
    for per-stock signals: it measures the mood around a *topic*.
    """
    settings = settings or get_settings()
    gdelt = GdeltProvider(settings)
    results: dict[str, Any] = {}

    targets = sectors or sorted(
        {
            row.sector
            for row in session.execute(
                select(Instrument).where(Instrument.in_universe.is_(True))
            ).scalars().all()
            if row.sector
        }
    )

    try:
        for sector in targets[:25]:
            tone = gdelt.article_tone(f'"{sector}" stock market')
            if tone is None:
                continue
            results[sector] = {"tone": tone, "source": "gdelt"}
    finally:
        gdelt.close()
    return results

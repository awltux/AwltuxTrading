"""News and sentiment providers.

Chosen from what is actually usable on a free tier. Notably **excluded** because
they are not:

* X/Twitter (pay-per-use only), StockTwits (Cloudflare-blocked),
* NewsAPI free (24-hour article delay, dev/test licence only),
* Polygon/Massive news (refreshed hourly, so useless for a flash ticker),
* Tiingo free (no news at all),
* and any real-time UK RNS feed, which is a paid LSEG licence (~£22k/yr).

What remains: RSS (keyless, broad UK+US coverage, loose matching), Finnhub for
real-time US company news, Marketaux for genuine per-entity sentiment scores on a
small budget, and GDELT for free sector-level mood.

Every source here is licensed for **personal, non-commercial** use. The app
stores headlines locally for private research and links back to the publisher
rather than republishing content.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus, urlparse, urlunparse

from awltux.config import Settings, get_settings
from awltux.providers.http import HttpClient, ProviderError

logger = logging.getLogger(__name__)

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"
YAHOO_FEED_BASE = "https://feeds.finance.yahoo.com/rss/2.0/headline"
FINNHUB_BASE = "https://finnhub.io/api/v1"
MARKETAUX_BASE = "https://api.marketaux.com/v1"
GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


@dataclass(slots=True)
class RawNewsItem:
    """A headline in source-neutral form, before classification writes to it."""

    title: str
    url: str | None
    source: str
    published_at: dt.datetime | None = None
    summary: str | None = None
    tickers: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    provider_sentiment: float | None = None
    raw: dict[str, Any] | None = None

    @property
    def url_hash(self) -> str:
        """Stable dedupe key.

        Google News wraps links in redirect URLs whose tracking parameters change
        between polls, so query strings and fragments are stripped and the host
        is lowercased. When there is no usable URL, the normalised title is
        hashed instead -- the same story from two feeds must collapse to one row.
        """
        basis = self.canonical_url or _normalise_title(self.title)
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    @property
    def canonical_url(self) -> str | None:
        return canonicalise_url(self.url)


def canonicalise_url(url: str | None) -> str | None:
    """Strip tracking noise so the same article has one stable identity."""
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip() or None
    if not parsed.scheme or not parsed.netloc:
        return url.strip() or None

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    # Drop the query entirely: news query strings are almost always tracking or
    # a Google News redirect payload, never part of the article's identity.
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", "", ""))


def _normalise_title(title: str) -> str:
    lowered = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    return re.sub(r"\s+", " ", lowered).strip()


def _parse_time(value: Any) -> dt.datetime | None:
    """Parse the several timestamp shapes these feeds use."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(float(value), tz=dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# RSS
# --------------------------------------------------------------------------- #


class RssNewsProvider:
    """Keyless RSS: Google News and per-ticker Yahoo Finance feeds.

    Coverage is the best free option for UK+US, but **matching is loose** -- a
    ``LLOY.L`` query happily returns HSBC and Barclays stories. Relevance is
    therefore confirmed by the classification layer, not assumed here.
    """

    SOURCE = "rss"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = HttpClient(
            "rss",
            settings=self.settings,
            headers={"Accept": "application/rss+xml, application/xml, text/xml"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RssNewsProvider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def google_news_url(
        self, query: str, *, region: str = "GB", language: str = "en"
    ) -> str:
        return (
            f"{GOOGLE_NEWS_BASE}?q={quote_plus(query)}"
            f"&hl={language}-{region}&gl={region}&ceid={region}:{language}"
        )

    def yahoo_news_url(self, symbol: str, *, region: str = "US", language: str = "en-US") -> str:
        return f"{YAHOO_FEED_BASE}?s={quote_plus(symbol)}&region={region}&lang={language}"

    def fetch_feed(
        self, url: str, *, ticker: str | None = None, cache_ttl: float = 300.0
    ) -> list[RawNewsItem]:
        """Fetch and parse one feed. Returns an empty list rather than raising.

        A single dead feed among hundreds must not fail the whole poll, so parse
        and transport failures are logged and swallowed here.
        """
        try:
            result = self._client.get(url, cache_ttl=cache_ttl, expect_json=False)
        except ProviderError as exc:
            logger.debug("feed fetch failed (%s): %s", url, exc)
            return []

        try:
            import feedparser

            parsed = feedparser.parse(result.body)
        except Exception as exc:
            logger.debug("feed parse failed (%s): %s", url, exc)
            return []

        items: list[RawNewsItem] = []
        for entry in parsed.entries or []:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            link = entry.get("link")
            published = _parse_time(
                entry.get("published") or entry.get("updated") or entry.get("published_parsed")
            )
            items.append(
                RawNewsItem(
                    title=title,
                    url=link,
                    source=self._source_name(url, entry),
                    published_at=published,
                    summary=_strip_html(entry.get("summary")),
                    tickers=[ticker] if ticker else [],
                    raw={"feed_url": url, "feed_title": parsed.feed.get("title")},
                )
            )
        return items

    @staticmethod
    def _source_name(feed_url: str, entry: Any) -> str:
        if "news.google.com" in feed_url:
            return "google_news"
        if "finance.yahoo.com" in feed_url:
            return "yahoo_rss"
        source = entry.get("source")
        if isinstance(source, dict) and source.get("title"):
            return f"rss:{str(source['title'])[:24]}"
        return "rss"


def _strip_html(value: Any) -> str | None:
    if not value:
        return None
    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000] or None


# --------------------------------------------------------------------------- #
# Finnhub
# --------------------------------------------------------------------------- #


class FinnhubNewsProvider:
    """Real-time US company news. Free tier is 60 requests/minute, 30/second cap.

    Sentiment endpoints (``/news-sentiment``, ``/social-sentiment``) are premium,
    so this source supplies headlines and timeliness only.
    """

    SOURCE = "finnhub"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = HttpClient(self.SOURCE, settings=self.settings, base_url=FINNHUB_BASE)

    @property
    def configured(self) -> bool:
        return bool(self.settings.env.finnhub_api_key)

    def close(self) -> None:
        self._client.close()

    def company_news(
        self, symbol: str, *, days_back: int = 3, cache_ttl: float = 900.0
    ) -> list[RawNewsItem]:
        if not self.configured:
            return []
        token = self.settings.env.require("Finnhub", "finnhub_api_key")
        today = dt.date.today()
        try:
            payload = self._client.get_json(
                "/company-news",
                params={
                    "symbol": symbol,
                    "from": (today - dt.timedelta(days=days_back)).isoformat(),
                    "to": today.isoformat(),
                    "token": token,
                },
                cache_ttl=cache_ttl,
            )
        except ProviderError as exc:
            logger.debug("finnhub news failed for %s: %s", symbol, exc)
            return []

        items: list[RawNewsItem] = []
        for entry in payload if isinstance(payload, list) else []:
            title = (entry.get("headline") or "").strip()
            if not title:
                continue
            items.append(
                RawNewsItem(
                    title=title,
                    url=entry.get("url"),
                    source=self.SOURCE,
                    published_at=_parse_time(entry.get("datetime")),
                    summary=_strip_html(entry.get("summary")),
                    tickers=[symbol],
                    raw={"id": entry.get("id"), "category": entry.get("category")},
                )
            )
        return items


# --------------------------------------------------------------------------- #
# Marketaux
# --------------------------------------------------------------------------- #


class MarketauxNewsProvider:
    """Sentiment-scored, ticker-tagged news. Free tier: 100 requests/day.

    The best free source of an actual per-entity sentiment score, and the budget
    is the binding constraint -- 100 requests returning 3 articles each is about
    300 articles a day, so calls are batched across symbols and rationed by the
    provider budget guard.
    """

    SOURCE = "marketaux"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = HttpClient(self.SOURCE, settings=self.settings, base_url=MARKETAUX_BASE)

    @property
    def configured(self) -> bool:
        return bool(self.settings.env.marketaux_api_key)

    def close(self) -> None:
        self._client.close()

    def news(
        self,
        symbols: list[str],
        *,
        limit: int = 3,
        published_after: dt.datetime | None = None,
        cache_ttl: float = 1800.0,
    ) -> list[RawNewsItem]:
        """Fetch news for a batch of symbols, with entity sentiment attached.

        ``filter_entities=true`` is what makes the per-symbol ``sentiment_score``
        and ``match_score`` available; without it the response only carries a
        document-level score.
        """
        if not self.configured or not symbols:
            return []
        token = self.settings.env.require("Marketaux", "marketaux_api_key")
        params: dict[str, Any] = {
            "symbols": ",".join(symbols[:50]),
            "filter_entities": "true",
            "limit": limit,
            "api_token": token,
        }
        if published_after is not None:
            params["published_after"] = published_after.strftime("%Y-%m-%dT%H:%M")

        try:
            payload = self._client.get_json("/news/all", params=params, cache_ttl=cache_ttl)
        except ProviderError as exc:
            logger.debug("marketaux fetch failed: %s", exc)
            return []

        items: list[RawNewsItem] = []
        for entry in (payload or {}).get("data") or []:
            title = (entry.get("title") or "").strip()
            if not title:
                continue

            entities = entry.get("entities") or []
            tickers: list[str] = []
            industries: list[str] = []
            sentiment: float | None = None
            for entity in entities:
                if entity.get("symbol"):
                    tickers.append(str(entity["symbol"]).upper())
                if entity.get("industry"):
                    industries.append(str(entity["industry"]))
                score = entity.get("sentiment_score")
                if score is not None and (
                    sentiment is None or abs(float(score)) > abs(sentiment)
                ):
                    # Keep the strongest-magnitude signal for this article.
                    sentiment = float(score)

            items.append(
                RawNewsItem(
                    title=title,
                    url=entry.get("url"),
                    source=self.SOURCE,
                    published_at=_parse_time(entry.get("published_at")),
                    summary=_strip_html(entry.get("description") or entry.get("snippet")),
                    tickers=tickers,
                    sectors=industries,
                    provider_sentiment=sentiment,
                    raw={"uuid": entry.get("uuid"), "source": entry.get("source")},
                )
            )
        return items


# --------------------------------------------------------------------------- #
# GDELT
# --------------------------------------------------------------------------- #


class GdeltProvider:
    """GDELT DOC 2.0: keyless, and the free way to measure *sector* mood.

    It has no ticker mapping -- queries are keyword based -- so it is used for
    market and sector tone via ``timelinetone``, not for per-stock signals.
    """

    SOURCE = "gdelt"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = HttpClient(self.SOURCE, settings=self.settings, base_url=GDELT_BASE)

    def close(self) -> None:
        self._client.close()

    def timeline_tone(
        self, query: str, *, days: int = 7, cache_ttl: float = 1800.0
    ) -> list[dict[str, Any]]:
        """Tone over time for a keyword query. Returns ``[{date, tone}]``.

        Only the last three months are queryable, and windows shorter than 72
        hours give about 15-minute granularity.
        """
        start = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).strftime("%Y%m%d%H%M%S")
        try:
            payload = self._client.get_json(
                "",
                params={
                    "query": query,
                    "mode": "timelinetone",
                    "format": "json",
                    "startdatetime": start,
                },
                cache_ttl=cache_ttl,
            )
        except ProviderError as exc:
            logger.debug("gdelt timeline failed for %r: %s", query, exc)
            return []

        series = ((payload or {}).get("timeline") or [{}])[0].get("data") or []
        out: list[dict[str, Any]] = []
        for point in series:
            date = point.get("date")
            tone = point.get("value")
            if date is None or tone is None:
                continue
            out.append({"date": date, "tone": float(tone)})
        return out

    def article_tone(self, query: str, *, limit: int = 50, cache_ttl: float = 900.0) -> float | None:
        """Average tone across recent matching articles."""
        try:
            payload = self._client.get_json(
                "",
                params={"query": query, "mode": "artlist", "format": "json", "maxrecords": limit},
                cache_ttl=cache_ttl,
            )
        except ProviderError:
            return None
        articles = (payload or {}).get("articles") or []
        tones = [float(a["tone"]) for a in articles if a.get("tone") is not None]
        if not tones:
            return None
        return sum(tones) / len(tones)


#: Query built from an instrument's display name, used for Google News and GDELT.
def company_query(name: str, ticker: str, *, extra: str = "stock") -> str:
    """Build a news query from a company name.

    Quotes the name so multi-word companies stay one phrase, and appends a
    disambiguating term: a bare company name collides with unrelated news far
    more often than one with "stock" or "shares" attached.
    """
    cleaned = re.sub(r"\s+", " ", name).strip()
    # Strip legal-form noise that hurts exact matching.
    cleaned = re.sub(
        r"\b(plc|PLC|p\.l\.c\.|Ltd|Limited|Inc\.?|Corp\.?|Corporation|Holdings?|Group)\b",
        "",
        cleaned,
    ).strip(" ,.")
    if not cleaned:
        cleaned = ticker
    return f'"{cleaned}" {extra}'.strip()

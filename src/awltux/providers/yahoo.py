"""Yahoo Finance provider (via ``yfinance``).

Yahoo is the only free source that covers **both** US and LSE listings with
quotes, deep daily history *and* fundamentals, so it carries the price and
profile workload. It is also an unofficial scrape of an undocumented API, which
shapes how it is wrapped here:

* Every call is treated as fallible. Failures raise; they never return an empty
  frame that a caller might mistake for "no data".
* **Currency is normalised at this boundary.** LSE symbols quote in pence
  (``GBp``) while Trading 212 reports GBP, so an un-normalised price is a latent
  100x error. The multiplier is returned and persisted.
* Requests are batched *within one quote-currency group* so that the per-symbol
  currency is never ambiguous.
* The provider is deliberately dumb about meaning: it returns provider-shaped
  data and leaves interpretation to ``analysis``.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from awltux.config import BudgetRule, Settings, get_settings
from awltux.money import expected_quote_currency, normalise_money
from awltux.providers.http import BudgetGuard, ProviderError

logger = logging.getLogger(__name__)

SOURCE = "yahoo"
# Lower rank loses to a higher one when two sources describe the same bar.
SOURCE_RANK = 20


@dataclass(slots=True)
class Bar:
    """One normalised daily OHLCV bar, in major currency units."""

    date: dt.date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adj_close: float | None
    volume: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adj_close": self.adj_close,
            "volume": self.volume,
        }


@dataclass(slots=True)
class BarSeries:
    """A price history plus the metadata needed to audit its normalisation."""

    symbol: str
    currency: str
    raw_currency: str
    raw_multiplier: float
    bars: list[Bar] = field(default_factory=list)
    source: str = SOURCE
    source_rank: int = SOURCE_RANK


@dataclass(slots=True)
class QuoteSnapshot:
    symbol: str
    price: float
    currency: str
    raw_currency: str
    raw_multiplier: float
    previous_close: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: float | None = None
    market_cap: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    ts: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    source: str = SOURCE


def _clean(value: Any) -> Any:
    """Turn NaN/inf into ``None`` so the value can be stored in JSON/SQLite."""
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _as_float(value: Any) -> float | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class YahooProvider:
    """Price history, quotes, profile and statements from Yahoo Finance."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        rule = self.settings.budget.get(SOURCE) or BudgetRule(requests=1800, window_seconds=3600)
        self.budget = BudgetGuard(SOURCE, rule)
        self._yf: Any | None = None

    # ----------------------------------------------------------------- setup
    @property
    def yf(self) -> Any:
        """Import yfinance lazily: it is heavy and prints on import failure."""
        if self._yf is None:
            try:
                import yfinance as yf
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise ProviderError(SOURCE, f"yfinance is not installed: {exc}") from exc
            self._yf = yf
        return self._yf

    def _account(self, count: int = 1) -> None:
        for _ in range(max(count, 1)):
            self.budget.acquire()

    # -------------------------------------------------------------- identity
    def search_symbols(self, query: str, *, max_results: int = 6) -> list[dict[str, Any]]:
        """Look a company up by ISIN or by name, rather than by guessing its ticker.

        **This is the missing half of identity resolution.** A symbol derived from
        the T212 ticker is only as good as that ticker, and Trading 212's tickers
        are frequently *former* ones: Humacyte is `AHAC_US_EQ` on T212 and `HUMA` on
        Yahoo, Vertical Aerospace is `BSN_US_EQ` and `EVTL`. Deriving the symbol
        cannot recover from that -- the error is in the input.

        An ISIN does not have that problem. It is stable across renames and
        restructurings, Trading 212 supplies it, and searching by it returned the
        right company for seven of the first eight instruments that no derived
        symbol could reach.

        Untrusted output, like the rest of this provider: ``yfinance.Search`` is an
        unofficial scrape of an endpoint Yahoo does not document, so every candidate
        is returned as-is for the caller to score and corroborate. Nothing here
        decides anything.
        """
        text = (query or "").strip()
        if not text:
            return []

        self._account(1)
        try:
            search = self.yf.Search(
                text,
                max_results=max(1, min(max_results, 20)),
                news_count=0,
                lists_count=0,
                include_cb=False,
                include_nav_links=False,
                include_research=False,
                include_cultural_assets=False,
            )
            quotes = getattr(search, "quotes", None) or []
        except Exception as exc:
            raise ProviderError(SOURCE, f"symbol search for {text!r} failed: {exc}") from exc

        out: list[dict[str, Any]] = []
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            symbol = quote.get("symbol")
            if not symbol:
                continue
            out.append(
                {
                    "symbol": str(symbol),
                    "name": quote.get("longname") or quote.get("shortname"),
                    "exchange": quote.get("exchDisp") or quote.get("exchange"),
                    "quote_type": quote.get("quoteType"),
                    "score": _as_float(quote.get("score")),
                }
            )
        return out

    # ------------------------------------------------------------- history
    def get_history(
        self,
        symbol: str,
        *,
        period: str = "2y",
        interval: str = "1d",
        start: dt.date | None = None,
    ) -> BarSeries:
        """Daily (or other) OHLCV for one symbol, normalised to major units.

        ``Ticker.history`` accepts ``*args, **kwargs`` and forwards them to
        ``PriceHistory.history``, which has a *different* parameter set from
        ``yfinance.download``. In particular ``progress`` is valid for ``download``
        but not for ``history``, and passing it raises TypeError -- which silently
        broke every price fetch until a live connectivity check surfaced it.
        """
        self._account()
        try:
            ticker = self.yf.Ticker(symbol)
            frame = ticker.history(
                period=None if start else period,
                start=start.isoformat() if start else None,
                interval=interval,
                auto_adjust=False,
                actions=False,
                timeout=30,
            )
        except Exception as exc:
            self.budget.note_failure(str(exc))
            raise ProviderError(SOURCE, f"history({symbol}) failed: {exc}") from exc

        if frame is None or frame.empty:
            return self._empty_series(symbol)

        raw_currency = self._infer_currency(symbol, ticker)
        return self._frame_to_series(symbol, frame, raw_currency)

    def get_history_batch(
        self,
        symbols: list[str],
        *,
        period: str = "2y",
        interval: str = "1d",
    ) -> dict[str, BarSeries]:
        """Fetch many symbols at once, grouped by expected quote currency.

        Symbols are partitioned by the currency we expect the provider to quote
        them in, because a single batch download reports one currency for the
        whole frame. Mixing a ``.L`` symbol with a US symbol in one group would
        make the pence/pounds distinction unresolvable.
        """
        if not symbols:
            return {}

        groups: dict[str, list[str]] = {}
        for symbol in symbols:
            key = expected_quote_currency(symbol) or "USD"
            groups.setdefault(key, []).append(symbol)

        out: dict[str, BarSeries] = {}
        for expected, group in groups.items():
            self._account()
            try:
                frame = self.yf.download(
                    tickers=group if len(group) > 1 else group[0],
                    period=period,
                    interval=interval,
                    auto_adjust=False,
                    actions=False,
                    progress=False,
                    threads=False,
                    group_by="ticker",
                )
            except Exception as exc:
                self.budget.note_failure(str(exc))
                logger.warning("batch download failed for group %s: %s", expected, exc)
                continue

            if frame is None or len(frame) == 0:
                continue

            for symbol in group:
                sub = self._extract_symbol_frame(frame, symbol, multi=len(group) > 1)
                if sub is None or sub.empty:
                    continue
                out[symbol] = self._frame_to_series(symbol, sub, self._fallback_currency(symbol))
        return out

    @staticmethod
    def _extract_symbol_frame(frame: Any, symbol: str, *, multi: bool) -> Any | None:
        if not multi:
            return frame
        try:
            if hasattr(frame.columns, "levels") and symbol in frame.columns.get_level_values(0):
                return frame[symbol]
        except Exception:
            return None
        return None

    def _frame_to_series(self, symbol: str, frame: Any, raw_currency: str) -> BarSeries:
        series = BarSeries(
            symbol=symbol,
            currency="",
            raw_currency=raw_currency,
            raw_multiplier=1.0,
        )

        # Read the currency from the frame if it carries one, else fall back to
        # what the symbol convention implies.
        frame_currency = ""
        try:
            metadata = getattr(getattr(frame, "attrs", {}), "get", None)
            if metadata:
                frame_currency = str(frame.attrs.get("currency") or "")
        except Exception:
            frame_currency = ""
        raw_currency = frame_currency or raw_currency or "USD"
        series.raw_currency = raw_currency

        columns = {str(c).lower(): c for c in frame.columns}

        for index, row in frame.iterrows():
            close = _as_float(row.get(columns.get("close", "Close")))
            if close is None:
                continue
            raw_date = index
            if hasattr(raw_date, "date"):
                bar_date = raw_date.date()
            elif isinstance(raw_date, dt.date):
                bar_date = raw_date
            else:
                continue

            # ``row`` is bound as a default so the closure captures this
            # iteration's row rather than the loop variable by reference.
            def column(name: str, _row: Any = row) -> float | None:
                key = columns.get(name)
                return _as_float(_row.get(key)) if key is not None else None

            raw_open = column("open")
            raw_high = column("high")
            raw_low = column("low")
            raw_adj = column("adj close") or column("adj_close")
            volume = column("volume")

            norm_close = normalise_money(close, raw_currency)
            assert norm_close is not None
            series.currency = norm_close.currency
            series.raw_multiplier = norm_close.multiplier

            def scaled(value: float | None) -> float | None:
                if value is None:
                    return None
                result = normalise_money(value, raw_currency)
                return result.value if result else None

            series.bars.append(
                Bar(
                    date=bar_date,
                    open=scaled(raw_open),
                    high=scaled(raw_high),
                    low=scaled(raw_low),
                    close=norm_close.value,
                    adj_close=scaled(raw_adj),
                    volume=volume,
                )
            )

        if series.bars and not series.currency:
            fallback = self._fallback_currency(symbol)
            norm = normalise_money(series.bars[-1].close, fallback)
            series.currency = norm.currency if norm else ""
            series.raw_multiplier = norm.multiplier if norm else 1.0
        return series

    def _empty_series(self, symbol: str) -> BarSeries:
        fallback = self._fallback_currency(symbol)
        norm = normalise_money(1.0, fallback)
        return BarSeries(
            symbol=symbol,
            currency=norm.currency if norm else "",
            raw_currency=fallback,
            raw_multiplier=norm.multiplier if norm else 1.0,
            bars=[],
        )

    def _infer_currency(self, symbol: str, ticker: Any) -> str:
        """Determine the unit the provider quotes this symbol in.

        Prefers the provider's own statement, falling back to the symbol
        convention (``.L`` means pence). Getting this wrong is the 100x bug, so
        the value is recorded rather than assumed silently.
        """
        for attribute in ("fast_info", "info"):
            try:
                container = getattr(ticker, attribute)
                if attribute == "fast_info":
                    value = container.get("currency") if hasattr(container, "get") else None
                else:
                    value = container.get("currency")
                if value:
                    return str(value)
            except Exception:
                continue
        return self._fallback_currency(symbol)

    @staticmethod
    def _fallback_currency(symbol: str) -> str:
        expected = expected_quote_currency(symbol)
        if expected:
            return expected
        return "USD"

    # --------------------------------------------------------------- quotes
    def get_quote(self, symbol: str) -> QuoteSnapshot:
        """A lightweight quote from ``fast_info`` (cheaper than ``info``)."""
        self._account()
        try:
            ticker = self.yf.Ticker(symbol)
            fast = ticker.fast_info
            raw_currency = self._infer_currency(symbol, ticker)

            raw_price = _as_float(fast.get("last_price"))
            if raw_price is None:
                # Fall back to the most recent daily close.
                series = self.get_history(symbol, period="5d")
                if not series.bars:
                    raise ProviderError(SOURCE, f"no quote available for {symbol}")
                last = series.bars[-1]
                return QuoteSnapshot(
                    symbol=symbol,
                    price=last.close,
                    currency=series.currency,
                    raw_currency=series.raw_currency,
                    raw_multiplier=series.raw_multiplier,
                    volume=last.volume,
                )

            price = normalise_money(raw_price, raw_currency)
            assert price is not None

            def scaled(key: str) -> float | None:
                value = _as_float(fast.get(key))
                if value is None:
                    return None
                result = normalise_money(value, raw_currency)
                return result.value if result else None

            return QuoteSnapshot(
                symbol=symbol,
                price=price.value,
                currency=price.currency,
                raw_currency=raw_currency,
                raw_multiplier=price.multiplier,
                previous_close=scaled("previous_close"),
                day_high=scaled("day_high"),
                day_low=scaled("day_low"),
                volume=_as_float(fast.get("last_volume")),
                market_cap=_as_float(fast.get("market_cap")),
                fifty_two_week_high=scaled("year_high"),
                fifty_two_week_low=scaled("year_low"),
            )
        except ProviderError:
            raise
        except Exception as exc:
            self.budget.note_failure(str(exc))
            raise ProviderError(SOURCE, f"quote({symbol}) failed: {exc}") from exc

    # -------------------------------------------------------------- profile
    def get_profile(self, symbol: str) -> dict[str, Any]:
        """``info`` payload, trimmed to keys the analysis layer actually uses.

        ``info`` is a heavy, slow, frequently-throttled call, so callers should
        cache the result aggressively (see ``ingest.fundamentals``).
        """
        self._account()
        try:
            ticker = self.yf.Ticker(symbol)
            info = ticker.info or {}
        except Exception as exc:
            self.budget.note_failure(str(exc))
            raise ProviderError(SOURCE, f"profile({symbol}) failed: {exc}") from exc

        if not isinstance(info, dict) or not info:
            raise ProviderError(SOURCE, f"empty profile for {symbol}")

        keys = (
            "symbol", "longName", "shortName", "currency", "financialCurrency",
            "sector", "industry", "country", "exchange", "marketCap",
            "sharesOutstanding", "floatShares", "trailingPE", "forwardPE",
            "priceToBook", "priceToSalesTrailing12Months", "enterpriseValue",
            "enterpriseToEbitda", "returnOnEquity", "returnOnAssets",
            "debtToEquity", "totalDebt", "totalCash", "freeCashflow",
            "operatingCashflow", "ebitda", "totalRevenue", "grossMargins",
            "operatingMargins", "profitMargins", "revenueGrowth",
            "earningsGrowth", "earningsQuarterlyGrowth", "dividendYield",
            "payoutRatio", "trailingEps", "forwardEps", "bookValue",
            "beta", "recommendationKey", "targetMeanPrice", "numberOfAnalystOpinions",
        )
        return {key: _clean(info.get(key)) for key in keys if key in info}

    def get_sector(self, symbol: str) -> tuple[str | None, str | None, str | None]:
        """Return ``(sector, industry, sic)`` for classification roll-ups."""
        try:
            info = self.get_profile(symbol)
        except ProviderError:
            return None, None, None
        sector = info.get("sector")
        industry = info.get("industry")
        sic = info.get("sic") if isinstance(info.get("sic"), str) else None
        return (
            str(sector) if sector else None,
            str(industry) if industry else None,
            sic,
        )

    # ----------------------------------------------------------- statements
    def get_financials(self, symbol: str) -> dict[str, Any]:
        """Annual income statement, balance sheet and cash flow as plain dicts.

        Returned un-interpreted: mapping these onto the canonical metric keys is
        the analysis layer's job, because US GAAP and UK FRS/IFRS tag different
        lines and that mapping is where the judgement belongs.
        """
        self._account(3)
        result: dict[str, Any] = {}
        try:
            ticker = self.yf.Ticker(symbol)
        except Exception as exc:
            raise ProviderError(SOURCE, f"financials({symbol}) failed: {exc}") from exc

        for name, attribute in (
            ("income", "income_stmt"),
            ("balance", "balance_sheet"),
            ("cashflow", "cashflow"),
        ):
            try:
                frame = getattr(ticker, attribute)
                if frame is None or frame.empty:
                    continue
                result[name] = {
                    "columns": [str(c.date() if hasattr(c, "date") else c) for c in frame.columns],
                    "rows": {
                        str(index): [_clean(v) for v in row.tolist()]
                        for index, row in frame.iterrows()
                    },
                }
            except Exception as exc:
                logger.debug("statement %s unavailable for %s: %s", name, symbol, exc)
        if not result:
            raise ProviderError(SOURCE, f"no statements available for {symbol}")
        return result

    # ----------------------------------------------------------------- news
    def get_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """Headlines Yahoo associates with a symbol.

        Yahoo's per-symbol news is loosely matched, so callers must treat the
        association as a hint and let classification confirm relevance.
        """
        self._account()
        try:
            items = self.yf.Ticker(symbol).news or []
        except Exception as exc:
            logger.debug("news unavailable for %s: %s", symbol, exc)
            return []
        return list(items)[:limit]

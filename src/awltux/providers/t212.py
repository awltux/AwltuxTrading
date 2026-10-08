"""Trading 212 public API client.

Scope of what this API can do, confirmed against the official OpenAPI bundle:

* It exposes **no quote and no candle endpoint**. The only price fields anywhere
  are ``currentPrice`` on your own positions and the fill price of your own past
  orders. Market data therefore comes from other providers; Trading 212 supplies
  the *instrument universe* and your *account state*, which is exactly the part
  nothing else can supply.
* Authentication is HTTP Basic with the **API key as the username and the API
  secret as the password**. Keys are per-environment: a demo key returns 401
  against the live base and vice versa.
* Rate limits are per-endpoint and per-account. They are modelled here as
  separate budget scopes so a slow metadata limit cannot be spent by position
  polling.
* The API is server-side only and the platform is Invest + Stocks ISA only.

Ticker formats are **never constructed by hand**. UK listings look like
``VODl_EQ`` (lowercase ``l``, no underscore) while US listings look like
``AAPL_US_EQ``, and Trading 212's own guidance is to look tickers up rather than
build them. The exchange for an instrument comes from ``workingScheduleId``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from awltux.config import Settings, get_settings
from awltux.providers.http import HttpClient, ProviderError, ProviderNotConfigured

logger = logging.getLogger(__name__)

# Budget scopes mirror Trading 212's per-endpoint limits.
SCOPE_INSTRUMENTS = "t212_instruments"  # 1 req / 50s
SCOPE_EXCHANGES = "t212_exchanges"  # 1 req / 30s
SCOPE_ACCOUNT = "t212_account"  # 1 req / 5s
SCOPE_POSITIONS = "t212_positions"  # 1 req / 1s
SCOPE_ORDERS = "t212_orders"  # 1 req / 2s
SCOPE_HISTORY = "t212_history"  # 20 req / 60s

# Endpoints that place or cancel orders. Used by the live-trading guard.
_ORDER_METHODS = frozenset({"place_market_order", "place_limit_order", "cancel_order"})


class LiveOrderRefused(ProviderError):
    """Raised when order placement is attempted without explicit permission."""


class ScopeUnavailable(ProviderError):
    """The API key lacks the scope this endpoint needs.

    Trading 212 issues keys with scopes, and a common configuration is a
    ``metadata``-only key -- enough to read the instrument universe, but not to
    read your positions or account. That distinction matters downstream: without
    the ``portfolio`` scope the risk gate cannot see your holdings and therefore
    cannot enforce its concentration limits. Callers must know that, rather than
    treating an empty portfolio as a real one.
    """

    def __init__(self, endpoint: str, scope: str) -> None:
        super().__init__(
            "t212",
            f"{endpoint} needs the '{scope}' scope, which this API key does not have",
            status=403,
        )
        self.endpoint = endpoint
        self.scope = scope


#: Which scope each endpoint group requires.
_ENDPOINT_SCOPES = {
    "positions": "portfolio",
    "account": "portfolio",
    "instruments": "metadata",
    "exchanges": "metadata",
    "orders": "equity",
    "history": "history",
}


class T212Provider:
    """Typed access to the Trading 212 public API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._clients: dict[str, HttpClient] = {}

    # ----------------------------------------------------------------- config
    @property
    def configured(self) -> bool:
        return self.settings.env.t212_configured

    @property
    def is_live(self) -> bool:
        return self.settings.env.t212_env == "live"

    def _auth(self) -> httpx.BasicAuth:
        if not self.configured:
            raise ProviderNotConfigured("Trading 212", "t212_api_key")
        return httpx.BasicAuth(
            self.settings.env.require("Trading 212", "t212_api_key"),
            self.settings.env.require("Trading 212", "t212_api_secret"),
        )

    def client(self, scope: str) -> HttpClient:
        """One client per budget scope, sharing auth and base URL."""
        if scope not in self._clients:
            self._clients[scope] = HttpClient(
                scope,
                settings=self.settings,
                base_url=self.settings.env.t212_base_url,
                auth=self._auth(),
                headers={"Accept": "application/json"},
            )
        return self._clients[scope]

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def __enter__(self) -> T212Provider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- reference
    def probe_capabilities(self) -> dict[str, Any]:
        """Which scopes this key actually has, by trying the cheap reads.

        Used by the health endpoint and the dashboard so a metadata-only key is
        visible as a limitation rather than as an empty portfolio. Results are not
        cached here: callers cache, because this makes real requests.
        """
        capabilities: dict[str, Any] = {
            "metadata": False,
            "portfolio": False,
            "errors": {},
        }

        try:
            self.get_instruments()
            capabilities["metadata"] = True
        except Exception as exc:
            capabilities["errors"]["metadata"] = str(exc)[:200]

        try:
            self.get_positions()
            capabilities["portfolio"] = True
        except ScopeUnavailable as exc:
            capabilities["errors"]["portfolio"] = f"missing '{exc.scope}' scope"
        except Exception as exc:
            capabilities["errors"]["portfolio"] = str(exc)[:200]

        return capabilities

    def get_instruments(self) -> list[dict[str, Any]]:
        """Every accessible instrument. Refreshed by T212 every 10 minutes.

        Returns the documented 10-field shape: ``addedOn``, ``currencyCode``,
        ``extendedHours``, ``isin``, ``maxOpenQuantity``, ``name``,
        ``shortName``, ``ticker``, ``type``, ``workingScheduleId``.
        """
        payload = self.client(SCOPE_INSTRUMENTS).get_json(
            "/equity/metadata/instruments",
            cache_ttl=3600.0,
            archive_as="instruments.json",
        )
        if not isinstance(payload, list):
            raise ProviderError("t212", "expected a list of instruments")
        return payload

    def get_exchanges(self) -> list[dict[str, Any]]:
        """Exchanges and their working schedules (open/close windows)."""
        payload = self.client(SCOPE_EXCHANGES).get_json(
            "/equity/metadata/exchanges",
            cache_ttl=3600.0,
            archive_as="exchanges.json",
        )
        if not isinstance(payload, list):
            raise ProviderError("t212", "expected a list of exchanges")
        return payload

    # --------------------------------------------------------------- account
    @staticmethod
    def _named_scope(endpoint: str, call):
        """Run ``call``, converting a 403 into a :class:`ScopeUnavailable`.

        A bare 403 is ambiguous -- wrong key, wrong environment and a missing
        scope all look alike. The required scope is known per endpoint, so naming
        it is what makes the error actionable.
        """
        try:
            return call()
        except ProviderError as exc:
            if getattr(exc, "status", None) == 403:
                raise ScopeUnavailable(endpoint, _ENDPOINT_SCOPES[endpoint]) from exc
            raise

    def get_account_summary(self) -> dict[str, Any]:
        """Cash and investment metrics in the primary account currency."""
        payload = self._named_scope(
            "account",
            lambda: self.client(SCOPE_ACCOUNT).get_json("/equity/account/summary"),
        )
        if not isinstance(payload, dict):
            raise ProviderError("t212", "expected an account summary object")
        return payload

    def get_positions(self, ticker: str | None = None) -> list[dict[str, Any]]:
        """Open positions. ``currentPrice`` here is held-names-only, not a feed.

        Requires the ``portfolio`` scope. Without it Trading 212 returns 403 and
        this raises :class:`ScopeUnavailable`, which callers must not treat as an
        empty portfolio.
        """
        params = {"ticker": ticker} if ticker else None
        payload = self._named_scope(
            "positions",
            lambda: self.client(SCOPE_POSITIONS).get_json("/equity/positions", params=params),
        )
        if not isinstance(payload, list):
            raise ProviderError("t212", "expected a list of positions")
        return payload

    def get_pending_orders(self) -> list[dict[str, Any]]:
        payload = self.client(SCOPE_ORDERS).get_json("/equity/orders")
        if not isinstance(payload, list):
            raise ProviderError("t212", "expected a list of orders")
        return payload

    # --------------------------------------------------------------- history
    def get_order_history(
        self, limit: int = 50, *, since_order_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Executed orders, newest first, stopping at an order already stored.

        ``since_order_id`` makes a repeat run cheap: it walks until it meets an id it has
        seen and stops there, rather than re-reading the whole account history every hour.
        """
        return self._paginate(
            "/equity/history/orders",
            limit,
            id_of=lambda item: (item.get("order") or {}).get("id"),
            stop_at_id=since_order_id,
        )

    def get_dividends(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._paginate("/equity/history/dividends", limit)

    def _paginate(
        self,
        path: str,
        limit: int,
        *,
        id_of: Callable[[dict[str, Any]], int | None] | None = None,
        stop_at_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Walk ``nextPagePath`` until exhausted, with a hard safety cap.

        ``stop_at_id`` ends the walk at the first item at or below that id, so an
        incremental run asks only for what is new. T212 returns history newest-first, but
        this does not *depend* on that: the caller upserts by id, so a page that arrived
        out of order would still be correct -- merely slower.

        **The cursor is not unique, so pages overlap and the same order arrives again.**
        `nextPagePath` carries a millisecond timestamp, and several fills share one, so the
        boundary bucket is served in full on both sides of it. Measured 2026-10-08 with
        `get_order_history(limit=200)`: 200 items, **148 distinct ids** -- 28 of them
        repeated up to six times, and the id sequence not strictly descending. Without the
        `seen` set those repeats both consume the caller's `limit` and hand the ingest the
        same order twice, which is a `UNIQUE constraint failed: t212_order.order_id` and a
        whole batch lost, because the session it writes on does not autoflush (`db/session.py`)
        and so cannot see a row it added a moment ago.
        """
        items: list[dict[str, Any]] = []
        seen: set[int] = set()
        next_path: str | None = path
        pages = 0
        client = self.client(SCOPE_HISTORY)
        while next_path and pages < 40:
            url, params = self._page_request(next_path, first_page=pages == 0, limit=limit)
            payload = client.get_json(url, params=params)
            if not isinstance(payload, dict):
                break
            page = payload.get("items") or []
            finished = False
            for item in page:
                item_id = id_of(item) if id_of is not None else None
                if isinstance(item_id, int):
                    if stop_at_id is not None and item_id <= stop_at_id:
                        finished = True
                        break
                    if item_id in seen:
                        continue
                    seen.add(item_id)
                items.append(item)
                if len(items) >= limit:
                    finished = True
                    break
            next_path = payload.get("nextPagePath")
            pages += 1
            if finished:
                break
        return items

    def _page_request(
        self, path: str, *, first_page: bool, limit: int
    ) -> tuple[str, dict[str, int] | None]:
        """The address and query for one page of a history walk.

        **Page two is not addressed like page one.** The first page is a *relative*
        endpoint -- `/equity/history/orders` -- which `HttpClient` joins to a base URL
        that already ends in `/api/v0`. Every `nextPagePath` after it comes back absolute
        from the **host root** and already carries that prefix
        (`/api/v0/equity/history/orders?cursor=…&limit=50`), so joining it a second time
        asks for `/api/v0/api/v0/equity/...`, which the API answers with 404.

        Measured 2026-10-08: `get_order_history(limit=5)` returned its five items because
        it stops after one page, while `limit=200` hit the 404 on the *second*. No caller
        had asked for more than a page before, so the bug had never been exercised.
        """
        if first_page:
            return path, {"limit": min(limit, 50)}
        return f"{self._origin()}{path}", None

    def _origin(self) -> str:
        """Scheme and host of the configured API, without its ``/api/v0`` path.

        The base URL is what a *relative* endpoint is joined to; a cursor path from the
        provider is absolute from the host root, so it needs this instead.
        """
        parts = urlsplit(self.settings.env.t212_base_url)
        return f"{parts.scheme}://{parts.netloc}"

    # --------------------------------------------------------------- trading
    def _assert_orders_allowed(self, method: str) -> None:
        """Refuse order placement unless it was explicitly enabled.

        Two independent conditions, both required: the app must not be pointing
        at live money *unless* the operator opted in, and the environment must be
        a deliberate choice rather than a leftover default.
        """
        if method not in _ORDER_METHODS:
            return
        env = self.settings.env
        if env.t212_env == "live" and not env.allow_live_orders:
            raise LiveOrderRefused(
                "t212",
                "refusing to place a LIVE order: AWLTUX_ALLOW_LIVE_ORDERS is false. "
                "AwltuxTrading is advisory-only by default.",
            )
        if env.t212_env not in ("demo", "live"):
            raise LiveOrderRefused("t212", f"unrecognised T212 environment {env.t212_env!r}")

    def place_market_order(self, ticker: str, quantity: float) -> dict[str, Any]:
        """Place a market order. Positive quantity buys, negative sells.

        Selling is expressed as a **negative** quantity -- a core T212
        convention. Only usable against the demo environment unless live orders
        have been explicitly unlocked in configuration.
        """
        self._assert_orders_allowed("place_market_order")
        if quantity == 0:
            raise ValueError("quantity must be non-zero")
        logger.warning(
            "placing %s market order for %s x%s",
            "LIVE" if self.is_live else "demo",
            ticker,
            quantity,
        )
        payload = self.client(SCOPE_ORDERS).post(
            "/equity/orders/market", json_body={"ticker": ticker, "quantity": quantity}
        ).json()
        return payload if isinstance(payload, dict) else {"raw": payload}

    def cancel_order(self, order_id: int) -> dict[str, Any]:
        self._assert_orders_allowed("cancel_order")
        payload = self.client(SCOPE_ORDERS).request(
            "DELETE", f"/equity/orders/{order_id}", expect_json=False
        )
        return {"status": payload.status}


def classify_exchange_name(name: str) -> str:
    """Map a Trading 212 exchange name onto a stable short code.

    Kept deliberately narrow: only venues the app actually trades are named, and
    anything unrecognised is passed through rather than guessed at.
    """
    upper = name.upper()
    if "LONDON" in upper or upper in {"LSE", "LSEG", "XLON"}:
        return "LSE"
    if "NASDAQ" in upper:
        return "NASDAQ"
    if "NEW YORK" in upper or upper in {"NYSE", "XNYS"}:
        return "NYSE"
    if "AMSTERDAM" in upper:
        return "AMS"
    if "XETRA" in upper or "FRANKFURT" in upper:
        return "XETRA"
    return name[:64]

"""Shared HTTP client: rate-limit budgets, retries, conditional caching, archiving.

Every outbound request in the application goes through here. It exists because
the free data tiers this app depends on are unforgiving:

* They enforce undocumented quotas and answer with opaque 403/429s, so we keep
  our own persisted budget and never rely on being told.
* They break transiently, so retries back off with jitter and honour
  ``Retry-After``.
* Yahoo and Stooq rate-limit by IP, so a restart must not reset our accounting.
* The SEC rejects requests without a declared contact, so the User-Agent is
  mandatory rather than cosmetic.

Responses are cached conditionally (ETag / Last-Modified) and every raw payload
is archived under ``data/raw`` so a parsing bug can be fixed without re-fetching
-- which matters when the source is rate-limited to a few requests per minute.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from awltux.config import BudgetRule, Settings, get_settings
from awltux.db import ProviderBudget, release_before_network, session_scope, utcnow
from awltux.timezones import utc_today

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=10.0)
# Status codes worth retrying: transient server-side and explicit throttling.
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 522, 524})


class ProviderError(RuntimeError):
    """A provider call failed after exhausting retries."""

    def __init__(self, provider: str, message: str, *, status: int | None = None) -> None:
        self.provider = provider
        self.status = status
        super().__init__(f"[{provider}] {message}")


class BudgetExhausted(ProviderError):
    """The local rate-limit budget for this provider is spent."""


class ProviderNotConfigured(ProviderError):
    """A required credential is missing."""

    def __init__(self, provider: str, env_key: str) -> None:
        super().__init__(
            provider, f"not configured -- set AWLTUX_{env_key.upper()} in .env"
        )
        self.env_key = env_key


# --------------------------------------------------------------------------- #
# rate limiting
# --------------------------------------------------------------------------- #


@dataclass
class _BudgetState:
    """In-memory rate-limit state for one provider."""

    requests_used: int
    window_started_at: dt.datetime
    blocked_until: dt.datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    dirty: bool = False
    last_flushed: float = 0.0


#: Process-wide budget state, keyed by provider.
#:
#: **Why the counter lives in memory rather than in a row per request.** The HTTP
#: client is the hot path, and every provider call would otherwise read and write
#: ``provider_budget``. Those writes happen while the caller may already hold an
#: open transaction -- and the ingest jobs necessarily hold one across a provider
#: call, which lasts as long as a rate-limit wait. The inner write then deadlocked
#: against the outer's ``BEGIN IMMEDIATE`` write lock.
#:
#: The symptom was a job dying with "database is locked" after exactly
#: ``busy_timeout``, followed by a foreign-key error, because the rollback
#: discarded the rows the next insert referenced.
#:
#: Keeping the counters in memory removes the database from the request path
#: entirely. They are checkpointed periodically so a restart resumes the budget
#: rather than resetting it.
_budget_registry: dict[str, _BudgetState] = {}
_budget_registry_lock = threading.Lock()

#: How often dirty state is written back, in seconds.
BUDGET_FLUSH_INTERVAL = 30.0


class BudgetGuard:
    """Fixed-window request budget, held in memory and checkpointed to SQLite.

    A fixed window is deliberately chosen over a sliding one: it maps directly
    onto how these providers describe their limits ("N requests per M seconds"),
    and it is cheap to persist. The cost is a possible burst across a window
    boundary, so the configured limits are set slightly below the real ones.
    """

    def __init__(self, provider: str, rule: BudgetRule) -> None:
        self.provider = provider
        self.rule = rule

    # ------------------------------------------------------------- lifecycle
    def _state_locked(self) -> _BudgetState:
        """Get or lazily load this provider's state. Caller holds the lock."""
        state = _budget_registry.get(self.provider)
        if state is not None:
            return state

        state = _BudgetState(
            requests_used=0, window_started_at=dt.datetime.now(dt.UTC)
        )
        try:
            with session_scope() as session:
                row = session.get(ProviderBudget, self.provider)
                if row is not None:
                    state.requests_used = row.requests_used or 0
                    state.window_started_at = _as_utc(row.window_started_at)
                    state.blocked_until = (
                        _as_utc(row.blocked_until) if row.blocked_until else None
                    )
                    state.consecutive_failures = row.consecutive_failures or 0
                    state.last_error = row.last_error
        except Exception as exc:
            # A budget we cannot load is better than no budget at all.
            logger.warning(
                "%s: could not load the persisted rate-limit state (%s); "
                "starting a fresh window",
                self.provider,
                exc,
            )
        _budget_registry[self.provider] = state
        return state

    def _flush(self, state: _BudgetState, *, force: bool = False) -> None:
        """Write dirty state back. Caller holds the lock."""
        now = time.monotonic()
        if not state.dirty or (not force and now - state.last_flushed < BUDGET_FLUSH_INTERVAL):
            return
        try:
            with session_scope() as session:
                row = session.get(ProviderBudget, self.provider)
                if row is None:
                    row = ProviderBudget(provider=self.provider)
                    session.add(row)
                row.requests_used = state.requests_used
                row.window_started_at = state.window_started_at
                row.blocked_until = state.blocked_until
                row.consecutive_failures = state.consecutive_failures
                row.last_error = state.last_error
            state.dirty = False
            state.last_flushed = now
        except Exception as exc:
            # Checkpointing must never fail a request: the in-memory state is
            # authoritative for this process, the row is only a checkpoint.
            logger.debug("%s: could not checkpoint the rate-limit state: %s", self.provider, exc)

    # ---------------------------------------------------------------- budget
    def acquire(self, *, max_wait: float = 300.0) -> None:
        """Consume one request slot, sleeping if the window is not yet reset.

        Raises :class:`BudgetExhausted` if the wait would exceed ``max_wait``, so a
        saturated provider skips this cycle instead of stalling the job.

        The sleep happens while holding **no** database lock -- only the brief
        in-process lock used to update the counter -- so a rate-limited wait
        cannot block the dashboard.
        """
        deadline = time.monotonic() + max_wait

        while True:
            with _budget_registry_lock:
                state = self._state_locked()
                now = dt.datetime.now(dt.UTC)
                wait_for: float | None = None

                if state.blocked_until is not None and state.blocked_until > now:
                    wait_for = (state.blocked_until - now).total_seconds()
                else:
                    state.blocked_until = None
                    elapsed = (now - _as_utc(state.window_started_at)).total_seconds()

                    if elapsed >= self.rule.window_seconds:
                        state.requests_used = 1
                        state.window_started_at = now
                        state.consecutive_failures = 0
                        state.dirty = True
                    elif state.requests_used >= self.rule.requests:
                        wait_for = self.rule.window_seconds - elapsed
                    else:
                        state.requests_used += 1
                        state.dirty = True

                self._flush(state)

            if wait_for is None:
                return

            if wait_for > deadline - time.monotonic():
                raise BudgetExhausted(
                    self.provider,
                    f"budget spent ({self.rule.requests} per "
                    f"{self.rule.window_seconds:.0f}s); window resets in {wait_for:.0f}s",
                )
            logger.info(
                "%s: rate limit reached, waiting %.1fs for the window to reset",
                self.provider,
                wait_for,
            )
            time.sleep(wait_for + 0.05)

    def note_success(self) -> None:
        with _budget_registry_lock:
            state = self._state_locked()
            state.consecutive_failures = 0
            state.last_error = None
            state.dirty = True
            self._flush(state)

    def note_failure(self, error: str, *, block_seconds: float | None = None) -> None:
        """Record a failure, and optionally back the provider off."""
        with _budget_registry_lock:
            state = self._state_locked()
            state.consecutive_failures += 1
            state.last_error = error[:500]
            if block_seconds:
                state.blocked_until = dt.datetime.now(dt.UTC) + dt.timedelta(
                    seconds=block_seconds
                )
            state.dirty = True
            # A backoff decision matters immediately, so force it to disk.
            self._flush(state, force=block_seconds is not None)

    def flush(self) -> None:
        """Force a checkpoint for this provider."""
        with _budget_registry_lock:
            state = _budget_registry.get(self.provider)
            if state is not None:
                self._flush(state, force=True)

    @classmethod
    def flush_all(cls) -> None:
        """Checkpoint every provider. Called on shutdown."""
        with _budget_registry_lock:
            for provider, state in _budget_registry.items():
                if not state.dirty:
                    continue
                try:
                    with session_scope() as session:
                        row = session.get(ProviderBudget, provider)
                        if row is None:
                            row = ProviderBudget(provider=provider)
                            session.add(row)
                        row.requests_used = state.requests_used
                        row.window_started_at = state.window_started_at
                        row.blocked_until = state.blocked_until
                        row.consecutive_failures = state.consecutive_failures
                        row.last_error = state.last_error
                    state.dirty = False
                except Exception:
                    logger.debug("could not checkpoint %s on shutdown", provider)

    @classmethod
    def reset_cache(cls) -> None:
        """Drop in-memory state, so tests cannot leak budgets into each other."""
        with _budget_registry_lock:
            _budget_registry.clear()


def _as_utc(value: dt.datetime) -> dt.datetime:
    """SQLite round-trips can drop tzinfo; comparisons must not fail on that."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


# --------------------------------------------------------------------------- #
# on-disk cache
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class CachedResponse:
    url: str
    status: int
    body: bytes
    headers: dict[str, str]
    fetched_at: dt.datetime


class ResponseCache:
    """Conditional-GET cache with a raw payload archive.

    Two distinct stores, because they answer different questions:

    * ``cache`` -- "can I skip this request?" (ETag/Last-Modified, TTL)
    * ``raw``   -- "what exactly did the provider send me?" (evidence)
    """

    def __init__(self, root: Path, *, raw_root: Path | None = None) -> None:
        self.root = root
        self.raw_root = raw_root or root
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(provider: str, url: str) -> str:
        """A stable filename for a cached response.

        Returns the digest **only** -- the provider is already a directory level
        (see :meth:`_meta_path`). Returning ``provider/digest`` here as well
        produced ``cache/t212_exchanges/t212_exchanges/...``, and because
        :meth:`write` only created the first level, every cache write raised
        ``FileNotFoundError``. The provider is still folded into the hash, so two
        providers caching the same URL cannot collide.
        """
        digest = hashlib.sha256(f"{provider}\x1f{url}".encode()).hexdigest()[:32]
        return digest

    def _meta_path(self, provider: str, key: str) -> Path:
        return self.root / provider / f"{key}.json"

    def _body_path(self, provider: str, key: str) -> Path:
        return self.root / provider / f"{key}.body"

    def read(self, provider: str, key: str) -> CachedResponse | None:
        meta_path = self._meta_path(provider, key)
        body_path = self._body_path(provider, key)
        if not meta_path.exists() or not body_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return CachedResponse(
                url=meta["url"],
                status=int(meta["status"]),
                body=body_path.read_bytes(),
                headers=meta.get("headers", {}),
                fetched_at=dt.datetime.fromisoformat(meta["fetched_at"]),
            )
        except Exception:
            logger.warning("discarding unreadable cache entry %s/%s", provider, key)
            return None

    def write(self, provider: str, key: str, response: CachedResponse) -> None:
        directory = self.root / provider
        directory.mkdir(parents=True, exist_ok=True)
        self._body_path(provider, key).write_bytes(response.body)
        self._meta_path(provider, key).write_text(
            json.dumps(
                {
                    "url": response.url,
                    "status": response.status,
                    "headers": response.headers,
                    "fetched_at": response.fetched_at.isoformat(),
                },
                indent=None,
            ),
            encoding="utf-8",
        )

    def archive(
        self, provider: str, name: str, payload: bytes | str, *, day: dt.date | None = None
    ) -> Path:
        """Write a raw payload under ``raw/<provider>/<date>/<name>``.

        The name usually comes from a URL, so it is sanitised rather than trusted:
        every character outside a safe set becomes ``_``, and leading dots are
        stripped so a name of ``..`` cannot escape the dated directory.
        """
        day = day or utc_today()
        directory = self.raw_root / provider / day.isoformat()
        directory.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in name)[:120]
        safe = safe.lstrip(".") or "payload"
        path = directory / safe
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_bytes(payload)
        return path

    def is_fresh(self, cached: CachedResponse, ttl_seconds: float) -> bool:
        fetched = cached.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=dt.UTC)
        return (dt.datetime.now(dt.UTC) - fetched).total_seconds() < ttl_seconds


# --------------------------------------------------------------------------- #
# client
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class FetchResult:
    """A provider response plus how we got it -- useful in tests and dashboards."""

    status: int
    body: bytes
    from_cache: bool
    revalidated: bool
    url: str

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class HttpClient:
    """Per-provider HTTP client with budget, retries and caching."""

    def __init__(
        self,
        provider: str,
        *,
        settings: Settings | None = None,
        headers: dict[str, str] | None = None,
        base_url: str | None = None,
        auth: httpx.Auth | tuple[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider
        self.base_url = base_url
        rule = self.settings.budget.get(provider)
        self.budget = BudgetGuard(provider, rule) if rule else None
        self.cache = ResponseCache(self.settings.cache_dir, raw_root=self.settings.raw_dir)
        self._owns_client = client is None

        # Providers with IP-restricted API keys need a predictable source address.
        # A dual-stack host presents a different address per family, so pinning to
        # IPv4 is what makes an IP allowlist work at all.
        transport = None
        if self._owns_client and self.settings.env.force_ipv4:
            transport = httpx.HTTPTransport(local_address="0.0.0.0")

        self._client = client or httpx.Client(
            timeout=timeout or DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": self.settings.env.sec_user_agent, **(headers or {})},
            auth=auth,
            transport=transport,
        )
        if client is not None and headers:
            self._client.headers.update(headers)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ core
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
        cache_ttl: float = 0.0,
        conditional: bool = True,
        archive_as: str | None = None,
        retries: int | None = None,
        expect_json: bool = True,
    ) -> FetchResult:
        """Perform a request with budget, retry, cache and archive handling.

        ``cache_ttl`` > 0 serves a cached body without any network call.
        ``conditional`` adds ETag/Last-Modified validators when a cached entry
        exists, so an unchanged resource costs one 304 instead of a full body.
        """
        full_url = url if url.startswith("http") else f"{self.base_url}{url}"
        key = ResponseCache.key(self.provider, full_url)
        cached = self.cache.read(self.provider, key)

        if cached is not None and cache_ttl > 0 and self.cache.is_fresh(cached, cache_ttl):
            return FetchResult(
                status=cached.status,
                body=cached.body,
                from_cache=True,
                revalidated=False,
                url=full_url,
            )

        request_headers = dict(headers or {})
        if conditional and cached is not None:
            if etag := cached.headers.get("etag"):
                request_headers["If-None-Match"] = etag
            if last_modified := cached.headers.get("last-modified"):
                request_headers["If-Modified-Since"] = last_modified

        attempts = retries if retries is not None else self.settings.llm.max_retries
        last_error: Exception | None = None

        for attempt in range(attempts + 1):
            # Give up this thread's SQLite write lock before waiting on the rate
            # limiter and before the request itself. A throttled provider can sit
            # here for seconds, and a job holding the write lock across that
            # blocks every other writer until busy_timeout expires.
            release_before_network()
            if self.budget is not None:
                self.budget.acquire()
            try:
                response = self._client.request(
                    method,
                    full_url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=request_headers or None,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                self._backoff(attempt, attempts, self.provider, str(exc))
                continue

            if response.status_code == 304 and cached is not None:
                if self.budget is not None:
                    self.budget.note_success()
                # Refresh the cached entry's freshness stamp.
                self.cache.write(
                    self.provider,
                    key,
                    CachedResponse(
                        url=full_url,
                        status=cached.status,
                        body=cached.body,
                        headers=cached.headers,
                        fetched_at=utcnow(),
                    ),
                )
                return FetchResult(
                    status=cached.status,
                    body=cached.body,
                    from_cache=True,
                    revalidated=True,
                    url=full_url,
                )

            if response.status_code in RETRY_STATUS:
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
                body_snippet = response.text[:200]
                last_error = ProviderError(
                    self.provider,
                    f"HTTP {response.status_code}: {body_snippet}",
                    status=response.status_code,
                )
                if self.budget is not None and response.status_code == 429:
                    self.budget.note_failure(str(last_error), block_seconds=retry_after)
                self._backoff(attempt, attempts, self.provider, str(last_error), retry_after)
                continue

            if response.status_code == 403:
                # The SEC (and some vendors) answer 403 for undeclared clients.
                # Retrying a 403 is usually pointless, so fail loudly and once.
                raise ProviderError(
                    self.provider,
                    f"HTTP 403 (check the User-Agent / key scope): {response.text[:200]}",
                    status=403,
                )

            if response.status_code >= 400:
                raise ProviderError(
                    self.provider,
                    f"HTTP {response.status_code}: {response.text[:200]}",
                    status=response.status_code,
                )

            body = response.content
            if self.budget is not None:
                self.budget.note_success()
            self.cache.write(
                self.provider,
                key,
                CachedResponse(
                    url=full_url,
                    status=response.status_code,
                    body=body,
                    headers=_selected_headers(response.headers),
                    fetched_at=utcnow(),
                ),
            )
            if archive_as:
                self.cache.archive(self.provider, archive_as, body)
            if expect_json and body and not _looks_like_json(response):
                raise ProviderError(
                    self.provider,
                    f"expected JSON but got {response.headers.get('content-type')!r}",
                    status=response.status_code,
                )
            return FetchResult(
                status=response.status_code,
                body=body,
                from_cache=False,
                revalidated=False,
                url=full_url,
            )

        raise ProviderError(
            self.provider,
            f"exhausted {attempts + 1} attempts: {last_error}",
            status=getattr(last_error, "status", None),
        )

    def get(self, url: str, **kwargs: Any) -> FetchResult:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FetchResult:
        # POSTs are never served from cache; they mutate or query live state.
        kwargs.setdefault("cache_ttl", 0.0)
        kwargs.setdefault("conditional", False)
        return self.request("POST", url, **kwargs)

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _backoff(
        attempt: int,
        attempts: int,
        provider: str,
        reason: str,
        retry_after: float | None = None,
    ) -> None:
        if attempt >= attempts:
            return
        if retry_after is not None:
            delay = retry_after
        else:
            delay = min(2.0**attempt, 30.0) * (0.5 + random.random())
        logger.warning(
            "%s: attempt %d/%d failed (%s); retrying in %.1fs",
            provider,
            attempt + 1,
            attempts + 1,
            reason[:180],
            delay,
        )
        time.sleep(delay)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        # Retry-After may be an HTTP date.
        try:
            from email.utils import parsedate_to_datetime

            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.UTC)
            return max((when - dt.datetime.now(dt.UTC)).total_seconds(), 0.0)
        except Exception:
            return None


def _selected_headers(headers: httpx.Headers) -> dict[str, str]:
    """Keep only the headers useful for revalidation and diagnostics."""
    keep = {
        "etag",
        "last-modified",
        "content-type",
        "cache-control",
        "date",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-used",
        "x-ratelimit-period",
    }
    return {k.lower(): v for k, v in headers.items() if k.lower() in keep}


def _looks_like_json(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return True
    stripped = response.content.lstrip()[:1]
    return stripped in (b"{", b"[")

"""External data providers.

Each provider is a thin, typed wrapper over one upstream API. They are the only
place in the application that talks to the network, so that a provider breaking
is a single-module fix rather than a hunt through the codebase.

Conventions every provider follows:

* Returns plain dicts/lists in the upstream's own shape, or a small typed
  structure -- never ORM objects.
* Raises :class:`~awltux.providers.http.ProviderError` (or a subclass) on
  failure; never returns a sentinel that looks like real data.
* Declares its credential requirement up front, so a missing key disables the
  provider instead of failing it on every cycle.
"""

from awltux.providers.http import (
    BudgetExhausted,
    CachedResponse,
    FetchResult,
    HttpClient,
    ProviderError,
    ProviderNotConfigured,
    ResponseCache,
)

__all__ = [
    "BudgetExhausted",
    "CachedResponse",
    "FetchResult",
    "HttpClient",
    "ProviderError",
    "ProviderNotConfigured",
    "ResponseCache",
]

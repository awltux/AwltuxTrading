"""Resolve Trading 212 instruments onto external provider identifiers.

This is the weakest link in the whole pipeline and is treated as such. Trading 212
supplies an ISIN and a ticker, and nothing else that joins cleanly to a market
data or filings provider. Two facts make naive parsing dangerous:

* **Ticker suffixes are not a documented public format.** US listings look like
  ``AAPL_US_EQ``, but UK listings append a lowercase venue letter with no
  separator -- ``VODl_EQ``, ``BPl_EQ``. Trading 212's own guidance is never to
  construct these by hand.
* **One ISIN can map to several T212 tickers** (dual listings), so an ISIN is not
  a key on this side of the join.

So the strategy is: parse conservatively, cross-check every guess against the
declared exchange, record the confidence and the method, and let anything
uncertain be confirmed by a real price fetch or by a human before it is allowed
to influence a decision.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Instrument-type suffixes Trading 212 appends to its internal tickers.
_TYPE_SUFFIXES = ("_EQ", "_CFD", "_ETF", "_FUND")

#: Single-letter venue codes appended directly to the symbol (no separator).
#: Derived from observed T212 tickers; ``l`` is London.
VENUE_LETTER_TO_EXCHANGE = {
    "l": "LSE",
    "a": "AMS",
    "p": "PAR",
    "d": "XETRA",
    "m": "MIL",
    "s": "SIX",
    "b": "BRU",
    "i": "DUB",
    "h": "HEL",
    "c": "CPH",
    "o": "OSL",
}

#: Yahoo Finance exchange suffixes for the venues we care about.
EXCHANGE_TO_YAHOO_SUFFIX = {
    "LSE": ".L",
    "AMS": ".AS",
    "PAR": ".PA",
    "XETRA": ".DE",
    "MIL": ".MI",
    "SIX": ".SW",
    "BRU": ".BR",
    "DUB": ".IR",
    "HEL": ".HE",
    "CPH": ".CO",
    "OSL": ".OL",
}

#: Confidence levels are coarse on purpose; a caller only ever needs to know
#: whether a mapping is trustworthy, plausible, or a guess.
CONFIDENCE_CONFIRMED = 1.0
CONFIDENCE_STRONG = 0.9
CONFIDENCE_PLAUSIBLE = 0.65
CONFIDENCE_GUESS = 0.35

_TICKER_SAFE = re.compile(r"^[A-Za-z0-9.\-^=]{1,24}$")


@dataclass(frozen=True, slots=True)
class SymbolMapping:
    """A proposed provider symbol plus how it was derived."""

    t212_ticker: str
    base_symbol: str
    venue: str | None
    yahoo_symbol: str | None
    confidence: float
    method: str
    note: str | None = None

    @property
    def usable(self) -> bool:
        return bool(self.yahoo_symbol)


def parse_t212_ticker(t212_ticker: str) -> tuple[str, str | None]:
    """Split a T212 ticker into ``(base_symbol, venue_code)``.

    Understands both documented shapes and makes no attempt to invent one it does
    not recognise -- an unrecognised ticker returns itself with ``venue=None``
    rather than a silently wrong base symbol.
    """
    raw = (t212_ticker or "").strip()
    for suffix in _TYPE_SUFFIXES:
        if raw.upper().endswith(suffix):
            raw = raw[: -len(suffix)]
            break

    if not raw:
        return "", None

    # Documented shape: SYMBOL_VENUE (e.g. AAPL_US, VOD_LSE).
    if "_" in raw:
        base, _, venue = raw.rpartition("_")
        if base and venue:
            venue_upper = venue.upper()
            if venue_upper in {"US", "USA"}:
                return base.upper(), "US"
            if venue_upper in EXCHANGE_TO_YAHOO_SUFFIX or venue_upper in {
                "NASDAQ", "NYSE", "LSE", "LSEG"
            }:
                return base.upper(), venue_upper
            # An unknown venue token: keep the base, admit we do not know it.
            return base.upper(), venue.upper()

    # Observed UK shape: SYMBOLl (lowercase venue letter glued on).
    last = raw[-1]
    if last.islower() and last in VENUE_LETTER_TO_EXCHANGE:
        base = raw[:-1]
        if base:
            return base.upper(), VENUE_LETTER_TO_EXCHANGE[last]

    # Bare symbol. Assume it is a US listing: T212 always qualifies non-US ones.
    return raw.upper(), None


def derive_yahoo_symbol(
    t212_ticker: str,
    *,
    exchange_name: str | None = None,
    currency_code: str | None = None,
) -> SymbolMapping:
    """Best-effort Yahoo symbol for a Trading 212 instrument.

    Resolution is deliberately conservative. When the ticker's venue token and
    the declared exchange disagree, or when the exchange is one we do not have a
    suffix for, the instrument is left **unresolved** rather than guessed at. An
    unresolved symbol costs analysis for that name; a wrong one silently attaches
    another company's prices to it.
    """
    base, venue = parse_t212_ticker(t212_ticker)

    if not base or not _TICKER_SAFE.match(base):
        return SymbolMapping(
            t212_ticker=t212_ticker,
            base_symbol=base,
            venue=venue,
            yahoo_symbol=None,
            confidence=0.0,
            method="unparseable",
            note="symbol does not match the expected shape",
        )

    unknown_venue_letter = _trailing_unknown_venue_letter(t212_ticker)

    exchange_code = _normalise_exchange(exchange_name) if exchange_name else None
    # A name was supplied but we did not recognise it: we cannot assume US.
    exchange_unrecognised = bool(exchange_name) and exchange_code is None

    # Cross-check the two sources. A disagreement means at least one is stale, and
    # there is no safe way to pick between them automatically.
    venue_market = _market_of(venue)
    exchange_market = _market_of(exchange_code)
    if venue_market and exchange_market and venue_market != exchange_market:
        return SymbolMapping(
            t212_ticker=t212_ticker,
            base_symbol=base,
            venue=venue,
            yahoo_symbol=None,
            confidence=0.0,
            method="conflict",
            note=(
                f"ticker implies {venue_market} but the exchange is "
                f"{exchange_name!r} ({exchange_market}); needs confirmation"
            ),
        )

    effective = venue or exchange_code

    if effective is None:
        if exchange_unrecognised:
            return SymbolMapping(
                t212_ticker=t212_ticker,
                base_symbol=base,
                venue=None,
                yahoo_symbol=None,
                confidence=0.0,
                method="unknown_exchange",
                note=(
                    f"exchange {exchange_name!r} is not one we can map to a "
                    "provider suffix, and the ticker carries no venue token"
                ),
            )
        if unknown_venue_letter:
            # The ticker ends in a lowercase letter we do not recognise. That
            # indicates a non-US venue, so assuming a US listing would be a guess
            # in the face of contrary evidence.
            return SymbolMapping(
                t212_ticker=t212_ticker,
                base_symbol=base,
                venue=None,
                yahoo_symbol=None,
                confidence=0.0,
                method="unsupported_venue",
                note=(
                    f"ticker ends in venue letter {unknown_venue_letter!r}, which is "
                    "not one this app can map to a provider suffix"
                ),
            )
        # No venue information at all. T212 qualifies non-US listings, so a bare
        # symbol is most likely a US listing -- plausible, not certain.
        return SymbolMapping(
            t212_ticker=t212_ticker,
            base_symbol=base,
            venue="US",
            yahoo_symbol=base,
            confidence=CONFIDENCE_PLAUSIBLE,
            method="us_bare",
        )

    if effective == "LSE":
        return SymbolMapping(
            t212_ticker=t212_ticker,
            base_symbol=base,
            venue="LSE",
            yahoo_symbol=f"{base}.L",
            # Strong only when the ticker itself said so; otherwise it is an
            # inference from the exchange name alone.
            confidence=CONFIDENCE_STRONG if venue == "LSE" else CONFIDENCE_PLAUSIBLE,
            method="lse_suffix",
        )

    if effective in ("US", "NASDAQ", "NYSE"):
        return SymbolMapping(
            t212_ticker=t212_ticker,
            base_symbol=base,
            venue=effective,
            yahoo_symbol=base,
            confidence=CONFIDENCE_STRONG if venue else CONFIDENCE_PLAUSIBLE,
            method="us_bare",
        )

    yahoo_suffix = EXCHANGE_TO_YAHOO_SUFFIX.get(effective)
    if yahoo_suffix:
        return SymbolMapping(
            t212_ticker=t212_ticker,
            base_symbol=base,
            venue=effective,
            yahoo_symbol=f"{base}{yahoo_suffix}",
            confidence=CONFIDENCE_PLAUSIBLE,
            method="venue_suffix",
        )

    # A venue we do not have a Yahoo suffix for: better unresolved than wrong.
    return SymbolMapping(
        t212_ticker=t212_ticker,
        base_symbol=base,
        venue=effective,
        yahoo_symbol=None,
        confidence=0.0,
        method="unsupported_venue",
        note=f"no Yahoo suffix known for venue {effective!r}",
    )


def _trailing_unknown_venue_letter(t212_ticker: str) -> str | None:
    """Return a trailing lowercase venue letter we cannot map, if there is one.

    Trading 212 glues a venue letter onto non-US tickers (``VODl_EQ``). A letter
    we do not recognise is evidence of a venue we cannot handle, which is the
    opposite of evidence for a US listing.
    """
    raw = (t212_ticker or "").strip()
    for suffix in _TYPE_SUFFIXES:
        if raw.upper().endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    if not raw or "_" in raw:
        return None
    last = raw[-1]
    if last.islower() and last.isalpha() and last not in VENUE_LETTER_TO_EXCHANGE:
        return last
    return None


def _market_of(code: str | None) -> str | None:
    """Reduce a venue code to the market it belongs to, for conflict detection."""
    if not code:
        return None
    if code == "LSE":
        return "LSE"
    if code in {"US", "NASDAQ", "NYSE", "USA"}:
        return "US"
    return code


def _normalise_exchange(exchange_name: str) -> str | None:
    upper = exchange_name.strip().upper()
    if "LONDON" in upper or upper in {"LSE", "LSEG", "XLON"}:
        return "LSE"
    if "NASDAQ" in upper:
        return "NASDAQ"
    if "NEW YORK" in upper or upper in {"NYSE", "XNYS"}:
        return "NYSE"
    for code in EXCHANGE_TO_YAHOO_SUFFIX:
        if code in upper:
            return code
    return None


def is_uk_listing(exchange_name: str | None, yahoo_symbol: str | None) -> bool:
    """Whether an instrument is a UK listing, used to pick the filings source."""
    if yahoo_symbol and yahoo_symbol.upper().endswith(".L"):
        return True
    return bool(exchange_name and _normalise_exchange(exchange_name) == "LSE")

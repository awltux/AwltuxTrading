"""Foreign-exchange rates, cached with their timestamp.

Needed for two things: expressing liquidity in a single currency (so a US and a
UK name can be compared in the risk gate), and valuing an instrument whose
reporting currency differs from its trading currency.

Rates are stored with the time they were observed and are never interpolated
silently. A stale rate is reported as stale, and callers refuse it rather than
guessing -- a silent 1:1 default would quietly corrupt every comparison that
depends on it.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from awltux.db import AppSetting, session_scope, utcnow
from awltux.providers.http import ProviderError

logger = logging.getLogger(__name__)

SETTING_KEY = "fx_rates"
#: Rates older than this are flagged rather than used silently.
STALE_AFTER_SECONDS = 48 * 3600

#: ``(base, quote) -> (yahoo_symbol, invert)``.
#:
#: Yahoo quotes ``GBPUSD=X`` as USD per GBP, so converting USD->GBP means
#: fetching that symbol and inverting. Every pair is written out explicitly
#: rather than derived, because getting the direction backwards here is silent
#: and would flip the sign of every foreign-currency comparison.
YAHOO_SYMBOLS: dict[tuple[str, str], tuple[str, bool]] = {
    ("GBP", "USD"): ("GBPUSD=X", False),
    ("USD", "GBP"): ("GBPUSD=X", True),
    ("EUR", "GBP"): ("EURGBP=X", False),
    ("GBP", "EUR"): ("EURGBP=X", True),
    ("EUR", "USD"): ("EURUSD=X", False),
    ("USD", "EUR"): ("EURUSD=X", True),
    ("GBP", "JPY"): ("GBPJPY=X", False),
    ("JPY", "GBP"): ("GBPJPY=X", True),
    ("USD", "JPY"): ("USDJPY=X", False),
    ("JPY", "USD"): ("USDJPY=X", True),
    ("GBP", "CHF"): ("GBPCHF=X", False),
    ("CHF", "GBP"): ("GBPCHF=X", True),
    ("USD", "CHF"): ("USDCHF=X", False),
    ("CHF", "USD"): ("USDCHF=X", True),
    ("GBP", "CAD"): ("GBPCAD=X", False),
    ("CAD", "GBP"): ("GBPCAD=X", True),
    ("USD", "CAD"): ("USDCAD=X", False),
    ("CAD", "USD"): ("USDCAD=X", True),
    ("GBP", "AUD"): ("GBPAUD=X", False),
    ("AUD", "GBP"): ("GBPAUD=X", True),
    ("USD", "AUD"): ("USDAUD=X", False),
    ("AUD", "USD"): ("USDAUD=X", True),
    ("GBP", "SEK"): ("GBPSEK=X", False),
    ("SEK", "GBP"): ("GBPSEK=X", True),
    ("GBP", "NOK"): ("GBPNOK=X", False),
    ("NOK", "GBP"): ("GBPNOK=X", True),
    ("GBP", "DKK"): ("GBPDKK=X", False),
    ("DKK", "GBP"): ("GBPDKK=X", True),
    ("GBP", "HKD"): ("GBPHKD=X", False),
    ("HKD", "GBP"): ("GBPHKD=X", True),
    ("GBP", "SGD"): ("GBPSGD=X", False),
    ("SGD", "GBP"): ("GBPSGD=X", True),
    ("GBP", "PLN"): ("GBPPLN=X", False),
    ("PLN", "GBP"): ("GBPPLN=X", True),
}


@dataclass(frozen=True, slots=True)
class FxRate:
    base: str
    quote: str
    rate: float
    as_of: dt.datetime
    source: str

    @property
    def age_seconds(self) -> float:
        when = self.as_of if self.as_of.tzinfo else self.as_of.replace(tzinfo=dt.UTC)
        return (dt.datetime.now(dt.UTC) - when).total_seconds()

    @property
    def stale(self) -> bool:
        return self.age_seconds > STALE_AFTER_SECONDS

    def convert(self, amount: float) -> float:
        return amount * self.rate


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #


def load_rates() -> dict[str, dict[str, object]]:
    """Read the persisted rate table, keyed ``"BASE:QUOTE"``."""
    with session_scope() as session:
        row = session.get(AppSetting, SETTING_KEY)
        if row is None or not isinstance(row.value, dict):
            return {}
        inner = row.value.get("rates")
        return inner if isinstance(inner, dict) else {}


def _store_rate(rate: FxRate) -> None:
    """Persist one rate, accumulating into whatever is already stored.

    Two things this gets right that a naive read-modify-write does not:

    * **It reads the row inside the same transaction that writes it.** Reading via
      a separate ``load_rates()`` call returns the last *committed* value, so three
      rates cached in one pass each wrote a dictionary containing only themselves
      -- silently keeping one rate and discarding the other two.
    * **It flushes after inserting.** ``session.get`` does not see a pending object
      that has not been flushed, so the second and third calls each believed the
      row was missing and inserted it again, colliding on the primary key.
    """
    key = f"{rate.base}:{rate.quote}"
    with session_scope() as session:
        row = session.get(AppSetting, SETTING_KEY)
        if row is None:
            row = AppSetting(
                key=SETTING_KEY,
                value={"rates": {}},
                note="Cached FX rates",
            )
            session.add(row)

        existing = row.value if isinstance(row.value, dict) else {}
        rates = dict(existing.get("rates") or {})
        rates[key] = {
            "rate": rate.rate,
            "as_of": rate.as_of.isoformat(),
            "source": rate.source,
        }
        row.value = {"rates": rates, "updated_at": utcnow().isoformat()}
        # So a subsequent get in this same transaction finds this row rather than
        # inserting a duplicate.
        session.flush()


def _read_cached(base: str, quote: str) -> FxRate | None:
    rates = load_rates()
    for from_ccy, to_ccy, invert in ((base, quote, False), (quote, base, True)):
        entry = rates.get(f"{from_ccy}:{to_ccy}")
        if not isinstance(entry, dict):
            continue
        raw = entry.get("rate")
        if not raw:
            continue
        rate = float(raw)
        if invert:
            if rate <= 0:
                continue
            rate = 1.0 / rate
        try:
            as_of = dt.datetime.fromisoformat(str(entry.get("as_of")))
        except (TypeError, ValueError):
            as_of = utcnow()
        return FxRate(
            base=base,
            quote=quote,
            rate=rate,
            as_of=as_of,
            source=str(entry.get("source") or "cache"),
        )
    return None


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


def get_rate(base: str, quote: str, *, refresh: bool = False) -> FxRate | None:
    """Return the rate for ``base -> quote``, fetching it when absent or stale.

    Returns ``None`` rather than a default of 1.0 when the pair is unknown. A
    stale cached rate is still returned when a refresh fails, but carries
    ``stale=True`` so the caller can refuse it explicitly.
    """
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return FxRate(base=base, quote=quote, rate=1.0, as_of=utcnow(), source="identity")

    cached = _read_cached(base, quote)
    if cached is not None and not refresh and not cached.stale:
        return cached

    fetched = _fetch_rate(base, quote)
    if fetched is not None:
        _store_rate(fetched)
        return fetched
    return cached


def to_gbp(amount: float | None, currency: str | None) -> float | None:
    """Convert an amount in a major currency to GBP.

    Returns ``None`` when no usable rate exists, so an unconvertible figure is
    visibly absent rather than silently wrong.
    """
    if amount is None:
        return None
    if not currency:
        return None
    key = currency.upper()
    if key == "GBP":
        return amount
    rate = get_rate(key, "GBP")
    if rate is None or rate.stale:
        return None
    return rate.convert(amount)


def quote_to_gbp(amount: float | None, quote_currency: str | None) -> float | None:
    """Convert a *quoted* price to GBP, honouring the pence convention.

    ``GBp`` is pence, so it needs the 100x normalisation and no FX; ``USD`` needs
    FX but no scaling. Mixing the two up is the classic UK equity bug, so the
    two paths are kept visibly separate.
    """
    from awltux.money import canonical_currency, normalise

    if amount is None:
        return None
    key = canonical_currency(quote_currency)
    if key == "GBP":
        return amount
    if key == "GBX":
        return normalise(amount, "GBX")
    normalised = normalise(amount, key)
    if normalised is None:
        return None
    return to_gbp(normalised, key)


def refresh_common_rates() -> dict[str, float]:
    """Warm the cache for the majors. Called by the scheduler once a day.

    Deliberately stores all three rates in one transaction, which is also the
    regression test for the accumulate-and-flush behaviour in
    :func:`_store_rate`.
    """
    out: dict[str, float] = {}
    for base, quote in (("USD", "GBP"), ("EUR", "GBP"), ("GBP", "USD")):
        rate = get_rate(base, quote, refresh=True)
        if rate is not None:
            out[f"{base}:{quote}"] = rate.rate
    return out


def _fetch_rate(base: str, quote: str) -> FxRate | None:
    entry = YAHOO_SYMBOLS.get((base, quote))
    if entry is None:
        logger.debug("no FX symbol known for %s->%s", base, quote)
        return None
    symbol, invert = entry

    try:
        from awltux.providers.yahoo import YahooProvider

        fetched = YahooProvider().get_quote(symbol)
    except (ProviderError, Exception) as exc:
        logger.warning("FX fetch failed for %s->%s: %s", base, quote, exc)
        return None

    raw = fetched.price
    if not raw or raw <= 0:
        return None
    rate = (1.0 / raw) if invert else raw
    return FxRate(base=base, quote=quote, rate=rate, as_of=utcnow(), source=f"yahoo:{symbol}")

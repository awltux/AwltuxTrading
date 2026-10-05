"""Currency handling, focused on the single most common UK equity bug.

LSE-listed shares are quoted in **pence (GBp/GBX)**, not pounds, by most market
data providers including Yahoo Finance. Trading 212 reports positions in GBP.
Mixing the two silently inflates or deflates a valuation by 100x, and because
the result is still a plausible-looking number it tends to survive review.

So the rule enforced here: **money never crosses a layer boundary un-normalised.**
Every conversion returns the multiplier it applied, and that multiplier is
persisted next to the value (see ``PriceBar.raw_multiplier``) so the original
figure can always be reconstructed.
"""

from __future__ import annotations

from dataclasses import dataclass

# Currencies that are a minor unit of another ISO 4217 currency, and the factor
# that converts them to the major unit.
_MINOR_UNITS: dict[str, tuple[str, float]] = {
    "GBP": ("GBP", 1.0),
    "GBX": ("GBP", 0.01),
    "GBP\u00b0": ("GBP", 0.01),  # rare GBp rendering
    "ZAR": ("ZAR", 1.0),
    "ZAC": ("ZAR", 0.01),
    "ILS": ("ILS", 1.0),
    "ILA": ("ILS", 0.01),
    "CHF": ("CHF", 1.0),
    "USD": ("USD", 1.0),
    "EUR": ("EUR", 1.0),
    "JPY": ("JPY", 1.0),
    "CAD": ("CAD", 1.0),
    "AUD": ("AUD", 1.0),
    "SEK": ("SEK", 1.0),
    "NOK": ("NOK", 1.0),
    "DKK": ("DKK", 1.0),
    "HKD": ("HKD", 1.0),
    "SGD": ("SGD", 1.0),
    "PLN": ("PLN", 1.0),
    "TRY": ("TRY", 1.0),
    # Minor units of the majors, kept distinct so the multiplier is explicit.
    "USX": ("USD", 0.01),
    "EUX": ("EUR", 0.01),
}

# Display aliases seen in the wild -> lookup key. Applied AFTER the
# case-sensitive table below, so it can never collapse "GBp" (pence) into
# "GBP" (pounds).
_ALIASES: dict[str, str] = {
    "GBP[CENTS]": "GBX",
    "GBX[CENTS]": "GBX",
    "PENCE": "GBX",
    "PENNIES": "GBX",
    "USX": "UXX",
    "USC": "UXX",
    "EUC": "EUX",
}

# Spellings that differ only by CASE but mean different units. "GBp" is pence and
# "GBP" is pounds -- a 100x difference -- so these must be matched exactly, before
# any uppercasing happens. Uppercasing first is precisely the bug this module
# exists to prevent.
_EXACT_TOKENS: dict[str, str] = {
    "GBP": "GBP",
    "GBp": "GBX",
    "GBX": "GBX",
    "GBx": "GBX",
    "gbx": "GBX",
    "ZAR": "ZAR",
    "ZAc": "ZAC",
    "ZAC": "ZAC",
    "ILS": "ILS",
    "ILA": "ILA",
    "CHF": "CHF",
    "JPY": "JPY",
}


class CurrencyMismatchError(ValueError):
    """Raised when two amounts in different currencies are combined."""


@dataclass(frozen=True, slots=True)
class NormalisedMoney:
    """A value plus the provenance needed to undo its normalisation."""

    value: float
    currency: str
    multiplier: float
    raw_currency: str

    @property
    def was_minor_unit(self) -> bool:
        return self.multiplier != 1.0


def canonical_currency(currency: str | None) -> str:
    """Map a provider currency label onto a canonical unit key.

    Case matters: ``GBp`` and ``GBX`` are pence, ``GBP`` is pounds. The exact
    spelling is therefore checked first and only then is an uppercase lookup
    attempted, so the two can never be conflated.
    """
    if not currency:
        return ""
    raw = currency.strip()
    if not raw:
        return ""

    # 1. Exact, case-sensitive spellings that carry a unit distinction.
    if raw in _EXACT_TOKENS:
        return _EXACT_TOKENS[raw]

    key = raw.upper()

    # 2. Uppercase spellings that are unambiguous once case is discarded.
    if key in _MINOR_UNITS:
        # "GBP" upper here means pounds, because the pence spellings were
        # captured by the exact table above. "GBX" upper is still pence.
        return key
    if key in _ALIASES:
        return _ALIASES[key]

    # 3. Unknown: report it as-is rather than guessing a conversion.
    return key


def multiplier_for(currency: str | None) -> float:
    """Factor converting ``currency`` to its major unit (1.0 if already major)."""
    return _MINOR_UNITS.get(canonical_currency(currency), (None, 1.0))[1]  # type: ignore[index]


def normalise(value: float | None, currency: str | None) -> float | None:
    """Convert a quoted amount into its major currency unit.

    ``normalise(1250, "GBp") -> 12.50``. Unknown currencies pass through
    unchanged, because inventing a conversion is worse than admitting ignorance.
    """
    if value is None:
        return None
    return value * multiplier_for(currency)


def normalise_money(value: float | None, currency: str | None) -> NormalisedMoney | None:
    """Like :func:`normalise`, but keeps the multiplier for the audit trail."""
    if value is None:
        return None
    raw = currency or ""
    key = canonical_currency(raw)
    major, factor = _MINOR_UNITS.get(key, (key or None, 1.0))  # type: ignore[assignment]
    return NormalisedMoney(
        value=value * factor,
        currency=(major or ""),
        multiplier=factor,
        raw_currency=raw,
    )


def to_major_currency(value: float, currency_code: str | None) -> tuple[float, str]:
    """Convenience wrapper returning ``(value, iso_currency)``.

    Also used to interpret Trading 212 instrument metadata, whose
    ``currencyCode`` is already a major unit (GBP/USD).
    """
    key = canonical_currency(currency_code)
    major, factor = _MINOR_UNITS.get(key, (key or "GBP", 1.0))  # type: ignore[assignment]
    return value * factor, major or "GBP"


def convert(amount: float, rate: float) -> float:
    """Convert between major units using an explicit rate.

    Rates are always passed in explicitly rather than looked up here, so that a
    valuation run can record exactly which rate it used.
    """
    if rate <= 0:
        raise ValueError(f"exchange rate must be positive, got {rate!r}")
    return amount * rate


def is_lse_symbol(yahoo_symbol: str | None) -> bool:
    """True for LSE-listed Yahoo symbols, which quote in pence."""
    return bool(yahoo_symbol) and yahoo_symbol.upper().endswith(".L")


def expected_quote_currency(yahoo_symbol: str | None) -> str | None:
    """Best-effort expectation of the unit a provider will quote a symbol in.

    Used to *verify* provider output rather than to convert it: if Yahoo returns
    ``GBP`` for a ``.L`` symbol, the 100x trap is live and we want to notice.
    """
    if is_lse_symbol(yahoo_symbol):
        return "GBX"
    return None

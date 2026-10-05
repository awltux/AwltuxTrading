"""Resolve an instrument's provider symbol by looking it up, not by guessing it.

Every price, account and news item joins on a provider symbol, and until now that
symbol was *derived* from the Trading 212 ticker. That works until the ticker is
stale, and Trading 212's tickers are frequently former ones: Humacyte is
``AHAC_US_EQ`` there and ``HUMA`` on Yahoo; Vertical Aerospace is ``BSN_US_EQ`` and
``EVTL``; Smiths News is ``CNCTl_EQ`` and ``SNWS.L``. Deriving cannot recover from
that -- the error is in the input -- and the result was 92 of 500 instruments
failing every price run forever, invisibly.

**The ISIN is the fix.** It is stable across renames and restructurings and Trading
212 supplies it. Measured against the first eight instruments no derived symbol
could reach, an ISIN search returned the right company for seven of them, each
corroborated by a name match. The eighth is a SPAC that appears to have no listing
left at all, which is the honest answer rather than a failure.

**This module decides; the provider only proposes.** Everything here is a pure
function of candidates and an instrument, so the scoring can be tested against real
provider output without a network call, and so a wrong answer is a wrong *rule*
rather than a wrong request.

**A weak match is recorded, not applied.** The alias table keeps the candidate and
its confidence either way -- a human overriding it needs to see what was considered
-- but ``yahoo_symbol`` is only changed when the match clears
:data:`APPLY_FLOOR`. This mirrors ``match_company`` for Companies House: attaching
the wrong company's prices to a ticker produces confident, completely wrong
analysis, which is worse than an instrument that is visibly unresolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Confidence at or above which a resolution is written onto the instrument.
#:
#: Below it the candidate is still stored on the alias, with its reason, so the
#: instrument shows up as needing review instead of silently resolving to the wrong
#: company.
APPLY_FLOOR = 0.70

#: Normalised name comparison results, as confidences.
_EXACT_NAME = 0.95
_CONTAINED_NAME = 0.80
_PARTIAL_NAME = 0.60

#: A candidate whose instrument type disagrees with ours is almost never right.
_TYPE_PENALTY = 0.25

#: A candidate on a *known-different* venue.
#:
#: Found by reading the first real run rather than its count: 79 of 92 resolved, and
#: two of them were cross-listings -- ``DOOO_US_EQ`` (a Nasdaq instrument) came back
#: as ``DOO.TO`` in Toronto, and ``EVTCY_US_EQ`` as ``EVTA.F`` in Frankfurt. An ISIN
#: identifies the *company*, and a company can be listed in several places; the
#: venue decides the price, the currency and the liquidity. A Toronto price attached
#: to a Nasdaq instrument is a plausible number that is simply not the right one.
#:
#: Large enough to drop an otherwise-exact ISIN match below the apply floor, so the
#: instrument stays visibly unresolved and asks for a human instead. That is the
#: right trade: a wrong-venue price is worse than a visible gap.
_VENUE_PENALTY = 0.45

#: Venue families, matched on substrings because providers spell exchanges
#: differently ("NASDAQ", "NasdaqGS", "NMS"; "LSE", "London"; "TOR", "Toronto").
_VENUE_FAMILIES: dict[str, tuple[str, ...]] = {
    "us": ("nasdaq", "nms", "ngm", "ncm", "nyse", "nyq", "new york", "nysearca", "pcx"),
    "uk": ("lse", "london", "lon"),
    "de": ("fra", "frankfurt", "stu", "stuttgart", "ham", "hamburg", "mun", "munich",
           "ber", "berlin", "dus", "dusseldorf", "xetra", "ger"),
    "ca": ("tor", "toronto", "tsx", "cve", "van", "vancouver"),
    "au": ("asx", "sydney"),
}

#: Suffixes that mark a listing away from the company's home market.
_FOREIGN_SUFFIX = re.compile(r"\.(F|SG|TO|V|BE|DU|HM|MU|XC|XA|IL|ST|CO|HE|PA|AS|MI|BR)$")

#: Suffixes and words that mark a derivative rather than the share itself. A name
#: search for Kodiak AI returns ``KDKRW`` "Kodiak AI, Inc. Warrants" second, and a
#: warrant has its own price series that would look plausible and be wrong.
_DERIVATIVE_WORDS = re.compile(
    r"\b(warrants?|rights?|units?|notes?|preferred|debentures?|when issued)\b",
    re.IGNORECASE,
)
_DERIVATIVE_SUFFIX = re.compile(r"(?:\.(?:WS|WT|RT|U)|(?:WS|WT|RT|UN))$", re.IGNORECASE)

#: Yahoo's placeholder for a company with no live listing.
#:
#: ``DUMY0001134`` came back for BioKey, whose name matched well enough to apply.
#: A placeholder carries no price series, so "resolving" to one just moves the
#: failure one step later and makes it look like success in the meantime.
_PLACEHOLDER_SYMBOL = re.compile(r"^DUMY", re.IGNORECASE)


@dataclass(slots=True)
class SymbolCandidate:
    """One possible provider symbol for an instrument, and why it scored what it did."""

    symbol: str
    name: str | None = None
    exchange: str | None = None
    quote_type: str | None = None
    confidence: float = 0.0
    method: str = "search"
    reasons: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.symbol) and self.confidence > APPLY_FLOOR

    @property
    def worth_recording(self) -> bool:
        """Any scored candidate is worth storing, even a rejected one."""
        return bool(self.symbol) and self.confidence > 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "reasons": list(self.reasons),
        }


def _normalise(name: str | None) -> str:
    """Reduce a company name to something comparable across providers."""
    if not name:
        return ""
    text = name.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(
        r"\b(plc|p l c|ltd|limited|inc|incorporated|corp|corporation|company|co|"
        r"holdings?|group|the|nv|sa|ag|ordin ary|ord|new|class [a-z])\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def _is_derivative(candidate: SymbolCandidate) -> bool:
    if _DERIVATIVE_SUFFIX.search(candidate.symbol or ""):
        return True
    return bool(candidate.name and _DERIVATIVE_WORDS.search(candidate.name))


def _is_placeholder(candidate: SymbolCandidate) -> bool:
    """Yahoo's ``DUMY...`` stand-in for a company with no live listing."""
    return bool(_PLACEHOLDER_SYMBOL.match(candidate.symbol or ""))


def _venue_family(exchange: str | None, symbol: str | None = None) -> str | None:
    """Which market a candidate trades on, as far as can be told.

    The symbol suffix is consulted as well as the venue name, because a provider
    can return a venue string this does not know while the suffix still says
    plainly that it is a foreign listing.
    """
    for text in (exchange or "", symbol or ""):
        lowered = text.lower()
        if not lowered:
            continue
        for family, spellings in _VENUE_FAMILIES.items():
            if any(spelling in lowered for spelling in spellings):
                return family
    if symbol and _FOREIGN_SUFFIX.search(symbol):
        return "other"
    return None


def _exchange_agrees(candidate_exchange: str | None, instrument_exchange: str | None) -> bool:
    """Whether the venue in the search result matches where we think it trades.

    Corroboration, not identification: an ISIN match on the wrong venue is still
    the right company, so disagreement lowers confidence rather than vetoing.
    """
    if not candidate_exchange or not instrument_exchange:
        return False
    left = candidate_exchange.lower()
    right = instrument_exchange.lower()
    if left == right:
        return True
    ours = _venue_family(instrument_exchange)
    theirs = _venue_family(candidate_exchange)
    return bool(ours and ours == theirs)


def _venue_disagrees(candidate: SymbolCandidate, instrument_exchange: str | None) -> bool:
    """Whether we can tell the candidate is on a *different* market to ours.

    Only a positive disagreement counts. An unrecognised venue is not evidence of a
    mismatch, and penalising it would drop correct resolutions for every exchange
    this has never heard of.
    """
    ours = _venue_family(instrument_exchange)
    theirs = _venue_family(candidate.exchange, candidate.symbol)
    if ours is None or theirs is None:
        return False
    return ours != theirs


def score_candidate(
    candidate: SymbolCandidate,
    *,
    instrument_name: str | None,
    instrument_exchange: str | None = None,
    instrument_type: str | None = None,
    queried_by_isin: bool,
) -> SymbolCandidate:
    """Fill in a candidate's confidence from what can be checked about it."""
    reasons: list[str] = []
    target = _normalise(instrument_name)
    found = _normalise(candidate.name)

    if not target or not found:
        candidate.confidence = 0.0
        candidate.reasons = ["no comparable name on either side"]
        return candidate

    if found == target:
        confidence = _EXACT_NAME
        reasons.append("name matches exactly")
    elif found in target or target in found:
        confidence = _CONTAINED_NAME
        reasons.append("name is contained in the other")
    else:
        left, right = set(target.split()), set(found.split())
        overlap = len(left & right) / max(len(left | right), 1)
        if overlap >= 0.6:
            confidence = _PARTIAL_NAME
            reasons.append(f"names share {overlap:.0%} of their words")
        else:
            # Returned before any corroboration is applied. Agreement on type and
            # venue corroborates a match; it cannot substitute for one, or every
            # equity on the right exchange would score as a weak candidate for
            # every instrument and the alias table would fill with noise.
            candidate.confidence = 0.0
            candidate.reasons = ["name does not resemble the instrument's"]
            return candidate

    # An ISIN is an identity, so a name match on top of one is corroboration.
    # Without it, a name match is the only evidence there is.
    if queried_by_isin:
        confidence = min(1.0, confidence * 1.05)
        reasons.append("found by ISIN, which survives a rename")
    else:
        confidence *= 0.85
        reasons.append("found by name only, which does not survive a rename")

    if instrument_type and candidate.quote_type:
        ours = instrument_type.upper()
        theirs = candidate.quote_type.upper()
        agrees = (ours == "ETF" and theirs in ("ETF", "MUTUALFUND")) or (
            ours == "STOCK" and theirs in ("EQUITY", "STOCK")
        )
        if agrees:
            confidence = min(1.0, confidence + 0.05)
            reasons.append("instrument type agrees")
        else:
            confidence = max(0.0, confidence - _TYPE_PENALTY)
            reasons.append(f"instrument type disagrees ({theirs} against {ours})")

    if _exchange_agrees(candidate.exchange, instrument_exchange):
        confidence = min(1.0, confidence + 0.05)
        reasons.append("exchange agrees")
    elif _venue_disagrees(candidate, instrument_exchange):
        confidence = max(0.0, confidence - _VENUE_PENALTY)
        reasons.append(
            f"listed on a different market ({candidate.exchange or candidate.symbol}); "
            "the price, currency and liquidity would be another venue's"
        )

    if _is_derivative(candidate):
        # A warrant or a right has its own plausible-looking price series.
        confidence = 0.0
        reasons.append("this is a warrant, right or unit, not the share")
    elif _is_placeholder(candidate):
        # Resolving to a placeholder just moves the failure one step later, and
        # makes it look like success in the meantime.
        confidence = 0.0
        reasons.append("this is a provider placeholder for a company with no listing")

    candidate.confidence = round(confidence, 4)
    candidate.reasons = reasons
    return candidate


def choose_symbol(
    candidates: list[dict[str, Any]],
    *,
    instrument_name: str | None,
    instrument_exchange: str | None = None,
    instrument_type: str | None = None,
    queried_by_isin: bool = False,
) -> SymbolCandidate | None:
    """The best candidate, or ``None`` when none is worth recording.

    A tie is broken by the provider's own relevance score, then by symbol, so the
    same inputs always produce the same answer.
    """
    scored: list[SymbolCandidate] = []
    for raw in candidates or []:
        if not isinstance(raw, dict) or not raw.get("symbol"):
            continue
        scored.append(
            score_candidate(
                SymbolCandidate(
                    symbol=str(raw["symbol"]),
                    name=raw.get("name"),
                    exchange=raw.get("exchange"),
                    quote_type=raw.get("quote_type"),
                    method="isin" if queried_by_isin else "name",
                ),
                instrument_name=instrument_name,
                instrument_exchange=instrument_exchange,
                instrument_type=instrument_type,
                queried_by_isin=queried_by_isin,
            )
        )

    usable = [candidate for candidate in scored if candidate.worth_recording]
    if not usable:
        return None
    usable.sort(
        key=lambda candidate: (
            -candidate.confidence,
            -next(
                (
                    float(raw["score"])
                    for raw in candidates
                    if isinstance(raw, dict)
                    and str(raw.get("symbol")) == candidate.symbol
                    and raw.get("score") is not None
                ),
                0.0,
            ),
            candidate.symbol,
        )
    )
    return usable[0]


def describe(resolution: SymbolCandidate | None, *, instrument_name: str | None = None) -> str:
    """A sentence for the alias note, so a reviewer can see why this symbol.

    Written whether or not the match cleared the floor. An alias that says "below
    the 0.70 floor, not applied, names share 40% of their words" is a request for a
    human; one that says nothing is an instrument that quietly never resolves.
    """
    if resolution is None:
        return "no candidate resembled the instrument closely enough; needs a human"
    why = "; ".join(resolution.reasons) or "scored on defaults"
    verdict = (
        "applied"
        if resolution.usable
        else f"below the {APPLY_FLOOR:.2f} floor, recorded but not applied"
    )
    return f"{resolution.method} lookup for {instrument_name or '?'}: {why} ({verdict})"

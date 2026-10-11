"""What Trading 212's own metadata says about one instrument, for the business panel.

Asked for directly: *"Use the Trading 212 API to populate an instrument's basic 'about'
data during initial population and refresh jobs. The Research job can replace or extend
this data."*

**This is the whole of what that API knows about a company.** ``/equity/metadata/instruments``
returns ten fields -- ``ticker``, ``type``, ``workingScheduleId``, ``isin``, ``currencyCode``,
``name``, ``shortName``, ``maxOpenQuantity``, ``extendedHours``, ``addedOn`` -- confirmed
against the official bundle and against the 18,479-row payload the live sync archived. There
is no description, no sector and no company profile, and there is **no per-instrument
endpoint at all**: the list is one call, rate-limited to one request per 50 seconds, and
:func:`awltux.ingest.universe.synchronize_instruments` is what reads it. So the jobs that
"populate" this are the ones that already do, and the sentence below is *derived* from the
row they write rather than stored in a record of its own -- a second copy would be a second
source of truth for fields that already have one, and would go stale the moment the daily
sync rewrote them.

What the *scoped* refresh contributes is the classification: its filings and statements
steps are what fill in a sector for an instrument that had none, and the panel shows it as
soon as they have.

**Why this is not in ``queries.py``.** It runs no SQL. ``web/queries.py`` is the module that
owns SQL and the read models that need a session; this module owns one panel's presentation
and is a pure function of a row. It sits beside ``templating.py`` rather than inside it
because ``templating.py`` is the generic formatting layer -- "how a number is shown" --
while the wording here is about one provider's listing.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from awltux.db import Instrument

#: The instrument types Trading 212 publishes, in the words a reader is shown. Anything absent
#: prints as the raw value rather than being guessed at: Trading 212 can add a type, and a page
#: that said "a stock" about a warrant would be worse than one that said "WARRANT".
#:
#: Each value is a complete noun phrase, article included, because the words are read after a
#: verb -- "Stantec **is** a stock", "Trading 212 lists it **as** an exchange-traded fund" -- and
#: an article chosen from the first letter would be wrong on the first exception ("a utility").
INSTRUMENT_TYPE_WORDS: dict[str, str] = {
    "STOCK": "a stock",
    "ETF": "an exchange-traded fund",
    "WARRANT": "a warrant",
}

#: What an instrument whose type is absent, or is one Trading 212 has never published before, is
#: called in the sentence. A noun phrase is not optional: ``as_listed`` is read after "is" and
#: after "lists it as", so dropping the clause left the sentence starting with a preposition --
#: the panel read "Stantec is on NYSE traded in USD" and, under a deep-dive, "Trading 212 lists
#: it as on NYSE traded in USD". A generic noun says nothing false and the raw type is still
#: named in the identifiers line, so this is not a guess at what the type means.
GENERIC_INSTRUMENT_WORD = "an instrument"


@dataclass(frozen=True, slots=True)
class ListingAbout:
    """What Trading 212's metadata says about one instrument, ready to print.

    A record rather than a dict because the template reads five fields by name and a typo in
    one of them should fail a test rather than render an empty line -- which is exactly how
    the untyped version behaved, since Jinja's default undefined is falsy rather than an error.

    Every field is a string and may be empty except :attr:`summary` and :attr:`as_listed`,
    which are the two the panel always has something to say with:

    :attr:`summary`
        The whole sentence, name included: ``"Stantec is a stock on NYSE traded in USD."``
        The panel's lead when there is no deep-dive.
    :attr:`as_listed`
        The same clause without the name: ``"a stock on NYSE traded in USD"``. It is a
        noun-phrase *complement*, read only after a verb -- "Stantec **is** ...", "Trading 212
        lists it **as** ..." -- so it is never empty and never starts with a preposition.
    :attr:`identifiers`
        The ISIN, Trading 212's short name, and its raw type when that type is one it has no
        words for.
    :attr:`note`
        When the listing was added, and whether it trades extended hours.
    :attr:`classification`
        The industry the filings gave it, with the source that gave it.
    """

    summary: str
    as_listed: str
    identifiers: str
    note: str
    classification: str


def listing_about(instrument: Instrument) -> ListingAbout | None:
    """Trading 212's metadata about ``instrument``, or ``None`` for a row that knows nothing.

    ``None`` only when the row carries nothing but its ticker -- no name, type, exchange,
    currency, ISIN or short name -- so the panel can say "nothing here yet" rather than print
    a sentence with holes in it.
    """
    name = _text(instrument.name)
    kind = _text(instrument.instrument_type)
    exchange = _text(instrument.exchange_name)
    currency = _text(instrument.currency_code)
    known = (name, kind, exchange, currency, _text(instrument.isin), _text(instrument.short_name))
    if not any(known):
        return None

    as_listed = _as_listed(kind, exchange, currency)
    return ListingAbout(
        summary=f"{name or instrument.t212_ticker} is {as_listed}.",
        as_listed=as_listed,
        identifiers=_identifiers(instrument, name=name, kind=kind),
        note=_carried(instrument),
        classification=_classification(instrument),
    )


def _text(value: Any) -> str:
    """A nullable column as a stripped string. ``None`` and whitespace are the same absence."""
    return str(value or "").strip()


def _as_listed(kind: str, exchange: str, currency: str) -> str:
    """The listing as a noun-phrase complement: ``"a stock on NYSE traded in USD"``.

    The noun phrase is unconditional. An unmapped or absent type falls back to a generic noun
    rather than being omitted, which is what used to leave the clause list starting with "on"
    and the sentence reading as a typo -- see :data:`GENERIC_INSTRUMENT_WORD`.
    """
    clauses = [INSTRUMENT_TYPE_WORDS.get(kind, GENERIC_INSTRUMENT_WORD)]
    if exchange:
        clauses.append(f"on {exchange}")
    if currency:
        clauses.append(f"traded in {currency}")
    return " ".join(clauses)


def _identifiers(instrument: Instrument, *, name: str, kind: str) -> str:
    """The disambiguating facts: ISIN, Trading 212's short name, and its raw type if unmapped."""
    isin = _text(instrument.isin)
    short = _text(instrument.short_name)
    parts = []
    if isin:
        parts.append(f"ISIN {isin}")
    if short and short not in (name, instrument.t212_ticker):
        # A "short name" the reader already has in front of them is noise, not information.
        parts.append(f"Trading 212's short name for it is {short}")
    if kind and kind not in INSTRUMENT_TYPE_WORDS:
        # Named rather than guessed at, and here rather than in the sentence: an unmapped type
        # read as "Stantec is CFD on NYSE", which reads as a typo. Lower-casing it would be a
        # second guess on top of the first.
        parts.append(f"Trading 212's type for it is {kind}")
    return " · ".join(parts)


def _carried(instrument: Instrument) -> str:
    """When Trading 212 first listed it and whether it trades extended hours, or ``""``."""
    parts = []
    since = _added_on(instrument.added_on)
    if since:
        parts.append(f"Trading 212 has carried it since {since}")
    if instrument.extended_hours:
        parts.append("it trades outside normal hours there")
    if not parts:
        return ""
    # Upper-cased by its first character rather than with `str.capitalize`, which would
    # lower-case the rest of the sentence and quietly mangle any acronym in it.
    sentence = " and ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def _classification(instrument: Instrument) -> str:
    """The industry from the filings, with its source, or ``""`` when nothing has classified it."""
    sector = _text(instrument.sector)
    group = _text(instrument.sector_group)
    if not (sector or group):
        return ""
    text = " — ".join(part for part in (group, sector) if part)
    if instrument.sector_source:
        text += f", via {instrument.sector_source}"
    return text


def _added_on(value: str | None) -> str | None:
    """Trading 212's ``addedOn`` as a date, or ``None`` when it is absent or unparseable.

    Kept as the string the API sent (``String(32)`` on the row), so this is the one place that
    reads it. A value the parser refuses prints nothing rather than raising: it is one fact about
    the listing, and a missing one must not cost the reader the panel.
    """
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None

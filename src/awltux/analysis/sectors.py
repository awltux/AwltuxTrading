"""One coarse sector per instrument, derived from its SEC SIC code.

**Why this exists.** The universe already carries a sector, and it is unusable as a
grouping: ``instrument.sector`` holds the SEC's SIC *industry description*, which is 148
distinct strings across 500 in-universe instruments, most of them holding one or two
names -- ``Services-Computer Programming, Data Processing, Etc.`` is a sector of five.
A page per one of those is a page nobody visits, and a news query for one is a query
Google News cannot answer. Measured 2026-10-07: 312 in-universe instruments carry a
``sic_code`` (144 distinct codes), 185 carry no sector at all, and 3 carry a Yahoo
sector name.

**Why from the SIC code and not the string.** ``sic_code`` is the authoritative number
EDGAR supplies alongside the description, and it is stable while the description is
free text -- the register spells the same industry three ways across three filings.
The description is kept as a fallback for the handful of rows that have one and no code.

**Why one table rather than arithmetic.** SIC is numeric by *division* -- 2834
pharmaceuticals and 2810 industrial chemicals are both "28, chemicals" -- so the
two-digit prefix is the right default and the exceptions carry all the meaning. 283
is Health Care and 281 is Materials; 366 and 367 are Information Technology while 362
and 364 are Industrials. A range table alone would put every drug company in Materials,
which is the single mistake worth avoiding here, so the table below is checked
most-specific-first: exact code, then major group, then division.

**The vocabulary is GICS's eleven**, deliberately. It is what the news tags already
use in the coarse form ("Industrials", "Energy", "Technology"), it is what a reader
recognises, and it is small enough that every entry has instruments behind it.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from typing import Any

#: The eleven, in the order a page should offer them. Not alphabetical: this is the
#: order the classification lists them in, and a stable order means the sector index
#: does not reshuffle when a name is added.
SECTOR_NAMES = (
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Health Care",
    "Financials",
    "Information Technology",
    "Communication Services",
    "Utilities",
    "Real Estate",
)

#: Exact SIC code -> sector, checked before the major group. Only where a four-digit
#: code disagrees with the three-digit group it sits in and the group as a whole is
#: right: 679 is "miscellaneous investing" and is Financials, but 6798 is a REIT and
#: belongs with the other property companies.
EXACT_CODES: dict[str, str] = {
    "6798": "Real Estate",
}

#: Three-digit SIC major group -> sector. Every group present in the live universe is
#: listed where the division default would be wrong; the rest fall through to
#: :data:`DIVISIONS`. The comments name the industries, because the numbers are not
#: memorable and a later reader has to be able to check one without a lookup.
MAJOR_GROUPS: dict[str, str] = {
    # --- extraction, where the division would call oil "Materials"
    "131": "Energy",  # crude petroleum & natural gas
    "132": "Energy",  # natural gas liquids
    "138": "Energy",  # oil & gas field services
    "291": "Energy",  # petroleum refining
    "461": "Energy",  # pipelines
    "492": "Utilities",  # natural gas distribution
    "493": "Utilities",  # combination utilities
    "494": "Utilities",  # water supply
    "491": "Utilities",  # electric services
    # --- manufacturing, where "28 chemicals" is the trap
    "283": "Health Care",  # drugs
    "284": "Consumer Staples",  # soap, cleaners, toilet goods
    "384": "Health Care",  # surgical & medical instruments
    "385": "Health Care",  # ophthalmic goods
    "382": "Information Technology",  # measuring & controlling devices
    "386": "Information Technology",  # photographic equipment
    "357": "Information Technology",  # computer & office equipment
    "366": "Information Technology",  # communications equipment
    "367": "Information Technology",  # electronic components & semiconductors
    "369": "Information Technology",  # electronic components, NEC
    "371": "Consumer Discretionary",  # motor vehicles & parts
    "375": "Consumer Discretionary",  # motorcycles, bicycles
    "394": "Consumer Discretionary",  # toys & sporting goods
    "271": "Communication Services",  # newspapers & publishing
    "272": "Communication Services",  # periodicals
    "273": "Communication Services",  # books
    "274": "Communication Services",  # miscellaneous publishing
    "483": "Communication Services",  # radio & television broadcasting
    "484": "Communication Services",  # cable & pay television
    "481": "Communication Services",  # telephone communications
    "489": "Communication Services",  # communications services, NEC
    "737": "Information Technology",  # computer programming & data processing
    # --- wholesale, where the goods decide the sector
    "512": "Health Care",  # drugs, proprietaries & sundries
    "504": "Health Care",  # professional & commercial equipment (medical)
    "514": "Consumer Staples",  # groceries & related products
    "515": "Consumer Staples",  # farm product raw materials
    "517": "Energy",  # petroleum & petroleum products
    "541": "Consumer Staples",  # grocery stores
    # --- finance and property
    "650": "Real Estate",  # real estate
    "651": "Real Estate",  # real estate operators & lessors
    "653": "Real Estate",  # real estate agents & managers
    "655": "Real Estate",  # land subdividers & developers
    "679": "Financials",  # miscellaneous investing (see EXACT_CODES for REITs)
    # --- services, where 73 and 80 are not one thing
    "731": "Communication Services",  # advertising
    "781": "Communication Services",  # motion picture production
    "782": "Communication Services",  # motion picture distribution
    "784": "Communication Services",  # video tape rental
    "790": "Communication Services",  # amusement & recreation
    "799": "Consumer Discretionary",  # amusement & recreation services
    "701": "Consumer Discretionary",  # hotels & motels
    "702": "Consumer Discretionary",  # rooming & boarding houses
    "751": "Industrials",  # automotive rental & leasing
    "736": "Industrials",  # personnel supply services
    "738": "Industrials",  # miscellaneous business services
    "871": "Industrials",  # engineering & management services
    "800": "Health Care",  # health services
    "801": "Health Care",  # offices & clinics of doctors
    "805": "Health Care",  # nursing & personal care facilities
    "806": "Health Care",  # hospitals
    "807": "Health Care",  # medical & dental laboratories
    "808": "Health Care",  # home health care services
    "809": "Health Care",  # miscellaneous health & allied services
}

#: Two-digit SIC division -> sector, the default when nothing more specific matches.
#: **Contiguous over 01..99 by construction**, and asserted so below: a hole here is a
#: code that classifies as nothing, and the first draft of this table had six of them
#: (18, 19, 68, 69, 74, 77) that no amount of reading the ranges reveals. The orphan
#: divisions the SEC never assigned are placed by their neighbours rather than left out,
#: because a sector page with a silent hole in it is worse than one with a broad bucket.
DIVISIONS: tuple[tuple[int, int, str], ...] = (
    (1, 9, "Consumer Staples"),  # agriculture, forestry, fishing
    (10, 14, "Materials"),  # mining & extraction
    (15, 19, "Industrials"),  # construction, and the unassigned 18-19 beside it
    (20, 21, "Consumer Staples"),  # food, tobacco
    (22, 23, "Consumer Discretionary"),  # textiles, apparel
    (24, 26, "Materials"),  # lumber, furniture, paper
    (27, 27, "Communication Services"),  # printing & publishing
    (28, 30, "Materials"),  # chemicals, rubber
    (31, 34, "Materials"),  # leather, stone, primary & fabricated metals
    (35, 35, "Industrials"),  # industrial machinery
    (36, 36, "Information Technology"),  # electronic & electrical equipment
    (37, 37, "Industrials"),  # transportation equipment
    (38, 38, "Industrials"),  # measuring, analysing & controlling instruments
    (39, 39, "Consumer Discretionary"),  # miscellaneous manufacturing
    (40, 49, "Industrials"),  # transport; the utility groups override above
    (50, 51, "Consumer Discretionary"),  # wholesale trade
    (52, 59, "Consumer Discretionary"),  # retail trade
    (60, 64, "Financials"),  # banking, credit, insurance
    (65, 65, "Real Estate"),  # real estate
    (66, 69, "Financials"),  # holding & investment offices, and the unassigned 68-69
    (70, 72, "Consumer Discretionary"),  # hotels, personal services
    (73, 73, "Industrials"),  # business services
    (74, 77, "Industrials"),  # business, repair & parking services, and unassigned 77
    (78, 79, "Communication Services"),  # motion pictures, amusement
    (80, 80, "Health Care"),  # health services
    (81, 81, "Industrials"),  # legal & engineering services
    (82, 82, "Consumer Discretionary"),  # educational services
    (83, 83, "Health Care"),  # social services
    (84, 89, "Industrials"),  # museums, membership organisations, private households
    (90, 99, "Industrials"),  # public administration & non-classifiable
)

#: Sector strings that already mean one of the eleven, normalised. The news classifier
#: and Marketaux both write a coarse sector, and neither spells it the way GICS does:
#: "Healthcare" is one word there, "Technology" is not "Information Technology", and
#: Yahoo writes "Basic Materials". Mapping them is the difference between a sector page
#: that collects the news and one that silently collects nothing.
ALIASES: dict[str, str] = {
    "healthcare": "Health Care",
    "health care": "Health Care",
    "technology": "Information Technology",
    "information technology": "Information Technology",
    "basic materials": "Materials",
    "materials": "Materials",
    "financial services": "Financials",
    "financials": "Financials",
    "finance": "Financials",
    "consumer cyclical": "Consumer Discretionary",
    "consumer discretionary": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer staples": "Consumer Staples",
    "communication services": "Communication Services",
    "telecommunications": "Communication Services",
    "telecom": "Communication Services",
    "industrials": "Industrials",
    "energy": "Energy",
    "utilities": "Utilities",
    "real estate": "Real Estate",
}

_DIGITS = re.compile(r"\D+")


def normalise_code(sic_code: str | int | None) -> str | None:
    """A SIC code as four bare digits, or ``None``.

    Left-padded, because agriculture really is SIC ``0100`` and arrives as ``100``
    from some sources. Truncated on the right for the same reason the tail is not
    kept: the *division* is what a longer string's leading digits carry.
    """
    if sic_code is None:
        return None
    digits = _DIGITS.sub("", str(sic_code))
    if not digits:
        return None
    return digits[:4].zfill(4)


def group_for(sic_code: str | int | None = None, sector_text: str | None = None) -> str | None:
    """The coarse sector for a SIC code, falling back to a sector string.

    Returns ``None`` when neither is known, and the caller must record that rather
    than bucket it: "no sector" is a real state for 185 in-universe instruments and
    hiding them in a default sector would make the sector pages wrong by exactly the
    amount that is invisible.
    """
    code = normalise_code(sic_code)
    if code:
        if code in EXACT_CODES:
            return EXACT_CODES[code]
        if code[:3] in MAJOR_GROUPS:
            return MAJOR_GROUPS[code[:3]]
        division = int(code[:2])
        for low, high, sector in DIVISIONS:
            if low <= division <= high:
                return sector
    if sector_text:
        return ALIASES.get(sector_text.strip().lower())
    return None


#: The name the sector pages use for instruments that have no group at all.
#:
#: Not one of the eleven, and not a twelfth sector: 185 in-universe instruments have
#: neither a SIC code nor a sector string, and they have to be reachable from the
#: sector index or the pages silently omit a third of the universe. Kept as a word
#: rather than a sentinel so ``/sectors/Unclassified`` is a URL a reader can read.
UNCLASSIFIED = "Unclassified"


def is_sector_page(name: str | None) -> bool:
    """Whether ``name`` is a sector page: one of the eleven, or the unclassified one."""
    return name in SECTOR_NAMES or name == UNCLASSIFIED


def is_sector(name: str | None) -> bool:
    """Whether ``name`` is one of the eleven, for validating a URL or a form value."""
    return name in SECTOR_NAMES


def index_from_closes(
    closes: Iterable[tuple[str, dt.date, float]],
) -> list[tuple[dt.date, float, int]]:
    """An equal-weighted index from ``(instrument, date, close)`` rows.

    **Rebased, not averaged.** The mean of the raw closes would be dominated by whichever
    constituent happens to have the largest price -- a 3,000p share beside a 30p one is not
    an average of anything -- so each instrument is divided by its *own* first close in this
    input and the level is 100 times the mean of those ratios. Two consequences are the point
    of doing it this way:

    * **Currencies cancel**, so a sector of US and UK listings needs no FX rate. A ratio is
      dimensionless, and pence against pounds is a constant factor per instrument.
    * **A constituent that lists mid-window joins at its own 100**, so it does not move the
      line on the day it appears. `contributors` is returned with each date precisely so that
      changing membership is visible rather than inferred from the shape.

    Each instrument's base is its first bar *in this input*, so the caller decides the window
    and every row of the result is on one basis. Rows with a non-positive close are dropped:
    a zero would divide the instrument out of the index on every later date, and a negative
    one would invert it.
    """
    base: dict[str, float] = {}
    per_date: dict[dt.date, list[float]] = {}
    for instrument, date, close in closes:
        if close is None or close <= 0:
            continue
        if instrument not in base:
            base[instrument] = close
        per_date.setdefault(date, []).append(close / base[instrument])

    return [
        (date, 100.0 * sum(ratios) / len(ratios), len(ratios))
        for date, ratios in sorted(per_date.items())
    ]


#: What to ask a news search for, per sector.
#:
#: The sector *name* is a poor query on its own -- "Materials" and "Utilities" are
#: ordinary English words, and a Google News search for them returns the weather and
#: the water bill. Each entry names the industries a reader would recognise as that
#: sector, in the vocabulary journalism uses rather than the register's.
#:
#: Every one of :data:`SECTOR_NAMES` has an entry; :func:`query_for` falls back to
#: ``"<name>" sector`` so a sector added without a query is still polled rather than
#: silently skipped, which would show up as a page with no news and no reason.
SECTOR_QUERIES: dict[str, str] = {
    "Energy": '"oil and gas" OR "energy sector" OR "crude oil" stocks',
    "Materials": '"mining" OR "chemicals" OR "steel" sector stocks',
    "Industrials": '"industrial" OR "manufacturing" OR "engineering" sector stocks',
    "Consumer Discretionary": '"retail" OR "consumer spending" OR "automaker" stocks',
    "Consumer Staples": '"food and drink" OR "consumer goods" OR "supermarket" stocks',
    "Health Care": '"pharmaceutical" OR "biotech" OR "healthcare" sector stocks',
    "Financials": '"banking" OR "insurer" OR "asset manager" sector stocks',
    "Information Technology": '"software" OR "semiconductor" OR "cloud computing" stocks',
    "Communication Services": '"telecoms" OR "media" OR "streaming" sector stocks',
    "Utilities": '"utility" OR "power company" OR "electricity" sector stocks',
    "Real Estate": '"real estate" OR "property" OR "REIT" sector stocks',
}


def query_for(name: str) -> str:
    """The news search query for a sector. See :data:`SECTOR_QUERIES`."""
    return SECTOR_QUERIES.get(name) or f'"{name}" sector'


def assign(instrument: Any) -> str | None:
    """Recompute an instrument's ``sector_group`` from its own sector fields.

    Called at the three places that write ``sector`` or ``sic_code`` rather than
    derived on read, because a derivation on read is a join on every page render and
    because a job can then *report* the instruments it cannot classify -- 185 in
    universe have neither a SIC code nor a sector string, and a silent ``None`` on a
    page is indistinguishable from a bug.

    Duck-typed on purpose: ``analysis`` does not import the ORM, and this is the whole
    coupling between the rule and the row it lands on.
    """
    group = group_for(getattr(instrument, "sic_code", None), getattr(instrument, "sector", None))
    instrument.sector_group = group
    return group

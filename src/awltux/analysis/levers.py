"""The levers a business is exposed to, and which way they push it.

Asked for directly: *"an instrument should have a short description of what the company does
... its perceived moat and what the primary levers are that affect its performance. The levers
is a particularly interesting addition that could be used to analyse which instruments are
affected by a specific lever e.g. interest rates, exchange rates, inflation, resource costs,
technology."*

**Why a vocabulary rather than free text.** The whole value of the feature is the question
asked *across* instruments -- what moves if rates rise -- and that question cannot be put to
prose: 500 readers would write 500 spellings of "interest rates" and the join would find none
of them. So a lever is one of :data:`LEVERS`, and the page that answers the question is a
lookup on a column. The vocabulary is deliberately short and evenly sized -- fourteen levers
in four groups, each with a *channel* sentence saying how it reaches a business -- because a
long taxonomy is one nobody keeps to, and two readers recording the same exposure must land on
the same key.

**What a record says.** ``direction`` is which way the *business* moves when the lever
*rises*: that is the only framing in which one lever means the same thing across a bank, a
housebuilder and a utility, and it is what lets a list of what a lever touches be read without
opening a row. ``strength`` separates the levers that move the earnings on their own from the
ones that merely matter. ``reason`` is the evidence in the recorder's own words and is the
part a reader argues with; ``source`` says who recorded it.

**Nothing here is inferred.** A lever with no reason is recorded with
:data:`NO_REASON` rather than with a sentence invented on the reader's behalf, and an
unrecognised key is refused rather than mapped to the nearest lever -- the same rule
`ingest/identity.py` applies to a venue and `analysis/corrections.py` applies to a tag.

**The automatic path is deliberately not built yet.** Filling this from the model rides on the
deep-dive, which already reads the whole company, so it would spend output tokens on a call
that is made anyway rather than another call -- but the reader asked for the mechanism first.
``TODO.md`` carries the prompt block to add and the shape to read, and :func:`record` is the
seam it will write through.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, delete, func, select

from awltux.db import Instrument, InstrumentLever, utcnow

#: Why a lever carries no reason, when the recorder did not give one. Not an empty string:
#: the record is evidence, and "no reason given" is itself the honest answer.
NO_REASON = "no reason given"

#: The provenance for a lever a person recorded, named rather than left empty so a page can
#: mark it -- the same convention as ``analysis/corrections.py::MANUAL``.
MANUAL = "manual"

#: Which way the *business* moves when the lever rises. ``mixed`` is a real answer and not a
#: failure to decide: a bank's margin improves with rates while its credit losses worsen, and
#: forcing that into one direction would be the record lying.
POSITIVE = "positive"
NEGATIVE = "negative"
MIXED = "mixed"
UNKNOWN = "unknown"
DIRECTIONS: tuple[str, ...] = (POSITIVE, NEGATIVE, MIXED, UNKNOWN)

DIRECTION_LABELS: dict[str, str] = {
    POSITIVE: "Rises help",
    NEGATIVE: "Rises hurt",
    MIXED: "Cuts both ways",
    UNKNOWN: "Direction not established",
}

#: Whether the lever moves the earnings on its own or merely matters.
PRIMARY = "primary"
SECONDARY = "secondary"
STRENGTHS: tuple[str, ...] = (PRIMARY, SECONDARY)

STRENGTH_LABELS: dict[str, str] = {PRIMARY: "Primary", SECONDARY: "Secondary"}

#: The four groups, in the order a page shows them. Their labels are the headings; the notes
#: say what the group is for, which is what stops a reader filing "technology" under demand.
GROUP_ORDER: tuple[str, ...] = ("macro", "costs", "demand", "structural")

GROUP_LABELS: dict[str, str] = {
    "macro": "The economy",
    "costs": "What it buys",
    "demand": "Who buys",
    "structural": "How the game changes",
}

GROUP_NOTES: dict[str, str] = {
    "macro": (
        "Conditions that apply to every business at once, which is why they are worth "
        "asking across the whole universe."
    ),
    "costs": "What the business has to buy in order to trade.",
    "demand": "Whose spending it depends on.",
    "structural": (
        "Things that reshape the business itself: substitution, the rules it works under, "
        "who else can do what it does, and the physical conditions it works in."
    ),
}


@dataclass(frozen=True, slots=True)
class Lever:
    """One entry in the vocabulary.

    ``channel`` is how the lever reaches a business, in one sentence, and it is part of the
    vocabulary rather than page copy: it is what a reader is shown while deciding which lever
    they are looking at, and two people filing the same exposure need the same rule.
    """

    key: str
    label: str
    group: str
    channel: str


LEVERS: tuple[Lever, ...] = (
    Lever(
        "interest_rates",
        "Interest rates",
        "macro",
        "The price of money: policy rates and bond yields set what a business borrows at, "
        "the rate its future cash flows are discounted at, and what a saver earns for taking "
        "no risk at all.",
    ),
    Lever(
        "inflation",
        "Inflation",
        "macro",
        "The general level of prices: it decides whether rising costs can be passed on, and "
        "what a nominal figure is worth a year later.",
    ),
    Lever(
        "exchange_rates",
        "Exchange rates",
        "macro",
        "The value of the currencies it earns in against the ones it spends and reports in, "
        "which moves revenue and costs in opposite directions for an exporter and an importer.",
    ),
    Lever(
        "economic_growth",
        "Economic growth",
        "macro",
        "How fast the economies it sells into are growing, which is the tide under its "
        "volumes and the reason a cyclical business earns more at the top of a cycle.",
    ),
    Lever(
        "energy_costs",
        "Energy costs",
        "costs",
        "Electricity, gas and fuel: a cost in their own right, and an indirect one through "
        "everything that is made, grown, cooled or moved with them.",
    ),
    Lever(
        "raw_material_costs",
        "Raw material costs",
        "costs",
        "The commodities, components and packaging it consumes, and the freight that brings "
        "them -- the input whose price is quoted on an exchange somewhere.",
    ),
    Lever(
        "labour_costs",
        "Labour costs",
        "costs",
        "Wages, and the supply of the people it needs: a cost in a service business and a "
        "constraint on growth in skilled work.",
    ),
    Lever(
        "consumer_demand",
        "Consumer demand",
        "demand",
        "Household spending: how many people choose to buy its product, and whether they "
        "keep buying it when their own budgets tighten.",
    ),
    Lever(
        "corporate_spending",
        "Corporate spending",
        "demand",
        "Investment and procurement by other businesses, which is discretionary and among the "
        "first things cut when they turn cautious.",
    ),
    Lever(
        "government_spending",
        "Government spending",
        "demand",
        "Public budgets, procurement and subsidies, and the taxes and levies it pays -- the "
        "same lever pulling in both directions.",
    ),
    Lever(
        "technology_change",
        "Technology change",
        "structural",
        "Substitution, automation and new entrants: the product replaced, the cost removed, "
        "or the position itself made obsolete.",
    ),
    Lever(
        "regulation",
        "Regulation and trade policy",
        "structural",
        "Rules, tariffs, licensing and compliance: what it is allowed to do, what that costs, "
        "and what crossing a border costs.",
    ),
    Lever(
        "competition",
        "Competition",
        "structural",
        "How many others can do what it does and whether that lets it price. Capacity added "
        "by a rival is the usual way a moat drains.",
    ),
    Lever(
        "weather_and_climate",
        "Weather and climate",
        "structural",
        "Seasonal conditions, and the physical risk to its sites, its crops, its routes or "
        "its customers.",
    ),
)

BY_KEY: dict[str, Lever] = {lever.key: lever for lever in LEVERS}

#: Every way a reader might name a lever, mapped to its key: the key itself, the label, and
#: the label without its "and". Built rather than hand-listed so a new lever cannot be added to
#: :data:`LEVERS` and forgotten here -- the failure that would look like "the CLI refuses a
#: lever the page offers".
def _normalise(text: str) -> str:
    """A reader's word for a lever, reduced to one spelling.

    Whitespace is collapsed before the spaces become underscores: a doubled space between two
    words would otherwise produce a key with two underscores in it and resolve to nothing,
    which reads as "that lever does not exist" rather than as a typo in the spacing.
    """
    return "_".join((text or "").split()).lower()


_ALIASES: dict[str, str] = {}
for _lever in LEVERS:
    for _alias in (_lever.key, _lever.label, _lever.label.replace(" and ", " ")):
        _ALIASES[_normalise(_alias)] = _lever.key
del _lever, _alias


def is_lever(key: str) -> bool:
    return key in BY_KEY


def label_for(key: str) -> str:
    """The lever's label, or the key itself when it is not in the vocabulary.

    The fallback is the key rather than an em dash because this is called on **stored** rows:
    a key that is no longer in the vocabulary -- a lever retired between two versions -- should
    still print as itself, so the row is readable rather than blank.
    """
    lever = BY_KEY.get(key)
    return lever.label if lever else key


def channel_for(key: str) -> str:
    lever = BY_KEY.get(key)
    return lever.channel if lever else ""


def group_of(key: str) -> str:
    lever = BY_KEY.get(key)
    return lever.group if lever else ""


def resolve(text: str) -> str | None:
    """The vocabulary key a reader's word for a lever names, or ``None``.

    ``None`` rather than a nearest match: recording an exposure against the wrong lever is
    worse than refusing it, because the page it feeds is a claim about what moves a business
    and nothing downstream would show the mistake.
    """
    return _ALIASES.get(_normalise(text))


@dataclass(frozen=True, slots=True)
class Exposure:
    """One lever, one instrument, as recorded.

    ``reason`` and ``source`` are empty when the caller did not give one, rather than
    defaulted here: the call-level default and the "no reason given" placeholder belong to
    :func:`record`, which is the only thing that writes, so that a reader of this dataclass is
    never shown a reason nobody gave.
    """

    lever: str
    direction: str = UNKNOWN
    strength: str = PRIMARY
    reason: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "lever": self.lever,
            "direction": self.direction if self.direction in DIRECTIONS else UNKNOWN,
            "strength": self.strength if self.strength in STRENGTHS else PRIMARY,
            "reason": self.reason,
            "source": self.source or MANUAL,
        }


def parse(text: str) -> Exposure:
    """Read one ``key=direction[:strength]`` argument, as the CLI and a form take it.

    Raises :class:`ValueError` naming what was wrong, because the caller is a person at a
    command line or a future model reading a validation error, and "invalid" alone would make
    them guess which of the three parts was refused.
    """
    raw = (text or "").strip()
    name, _, rest = raw.partition("=")
    key = resolve(name)
    if key is None:
        raise ValueError(
            f"unknown lever {name.strip()!r}; known: {', '.join(lever.key for lever in LEVERS)}"
        )
    direction, _, strength = rest.partition(":")
    direction = direction.strip().lower()
    if direction not in DIRECTIONS:
        raise ValueError(
            f"{key}: direction must be one of {', '.join(DIRECTIONS)}, not {direction!r}"
        )
    strength = (strength or PRIMARY).strip().lower()
    if strength not in STRENGTHS:
        raise ValueError(
            f"{key}: strength must be one of {', '.join(STRENGTHS)}, not {strength!r}"
        )
    return Exposure(lever=key, direction=direction, strength=strength)


def describe(exposure: Exposure) -> dict[str, Any]:
    """An exposure with the vocabulary filled in, for a page to render.

    The label, the group and the channel are joined here rather than stored on the row,
    because they are properties of the *vocabulary*: storing them would freeze the wording of
    a lever at the moment it was recorded and let two rows disagree about what a lever means.
    """
    group = group_of(exposure.lever)
    return exposure.as_dict() | {
        "label": label_for(exposure.lever),
        "group": group,
        "group_label": GROUP_LABELS.get(group, group),
        "channel": channel_for(exposure.lever),
        "direction_label": DIRECTION_LABELS.get(exposure.direction, exposure.direction),
        "strength_label": STRENGTH_LABELS.get(exposure.strength, exposure.strength),
    }


def _row_exposure(row: InstrumentLever) -> Exposure:
    return Exposure(
        lever=row.lever,
        direction=row.direction,
        strength=row.strength,
        reason=row.reason or "",
        source=row.source or MANUAL,
    )


def record(
    session: Any,
    ticker: str,
    exposures: Iterable[Exposure],
    *,
    reason: str = "",
    source: str = MANUAL,
) -> list[InstrumentLever]:
    """Write an instrument's levers, replacing whatever was recorded for the same lever.

    Upserted on ``(ticker, lever)`` rather than appended, because what the page and the
    cross-instrument query want is the *current* judgement -- see
    :class:`~awltux.db.models.InstrumentLever`.

    ``reason`` and ``source`` are call-level defaults for exposures that did not carry their
    own: the CLI takes one reason for a whole list, and a caller with something per lever puts
    it on the exposure. A reason nobody gave is stored as :data:`NO_REASON` rather than
    invented.

    Returns the rows it wrote, so a command can print what changed rather than a count.
    """
    now = utcnow()
    written: list[InstrumentLever] = []
    for exposure in exposures:
        if not is_lever(exposure.lever):
            raise ValueError(f"unknown lever {exposure.lever!r}")
        row = session.execute(
            select(InstrumentLever)
            .where(InstrumentLever.instrument_t212_ticker == ticker)
            .where(InstrumentLever.lever == exposure.lever)
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            row = InstrumentLever(instrument_t212_ticker=ticker, lever=exposure.lever)
            session.add(row)
        row.direction = exposure.direction if exposure.direction in DIRECTIONS else UNKNOWN
        row.strength = exposure.strength if exposure.strength in STRENGTHS else PRIMARY
        row.reason = (exposure.reason or reason or NO_REASON).strip()
        row.source = exposure.source or source or MANUAL
        row.updated_at = now
        written.append(row)
    session.flush()
    return written


def forget(session: Any, ticker: str, lever: str | None = None) -> int:
    """Drop one lever, or every lever, from an instrument. Returns how many rows went.

    The count is returned rather than a boolean because the CLI prints it: "nothing to
    forget" and "one gone" are different answers to the same command, and an idempotent
    silence would hide a typo in the ticker.
    """
    statement = delete(InstrumentLever).where(
        InstrumentLever.instrument_t212_ticker == ticker
    )
    if lever is not None:
        statement = statement.where(InstrumentLever.lever == lever)
    result = session.execute(statement)
    session.flush()
    return int(result.rowcount or 0)


def stored(session: Any, ticker: str) -> list[Exposure]:
    """Every lever recorded for one instrument, primary first and then by the vocabulary."""
    rows = session.execute(
        select(InstrumentLever)
        .where(InstrumentLever.instrument_t212_ticker == ticker)
        .order_by(InstrumentLever.lever)
    ).scalars().all()
    order = {lever.key: index for index, lever in enumerate(LEVERS)}
    exposures = [_row_exposure(row) for row in rows]
    exposures.sort(
        key=lambda exposure: (
            0 if exposure.strength == PRIMARY else 1,
            order.get(exposure.lever, len(order)),
        )
    )
    return exposures


def _universe_filter() -> tuple[Any, Any]:
    return Instrument.in_universe.is_(True), Instrument.excluded.is_(False)


def totals(session: Any) -> dict[str, dict[str, int]]:
    """Per lever, how many in-universe instruments it is recorded against.

    Restricted to the universe for the same reason :func:`~awltux.web.queries.universe_size`
    is: an exposure recorded for an instrument that was later excluded would otherwise make a
    lever look better covered than the pages it links to can show.
    """
    left, right = _universe_filter()
    rows = session.execute(
        select(InstrumentLever.lever, InstrumentLever.strength, func.count())
        .join(Instrument, Instrument.t212_ticker == InstrumentLever.instrument_t212_ticker)
        .where(left)
        .where(right)
        .group_by(InstrumentLever.lever, InstrumentLever.strength)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for lever, strength, count in rows:
        # Grouped by strength rather than split into two named bands, so a strength this
        # version does not know is still counted -- and under its own name, not folded into
        # one of the two, because the band is a claim about what moves the earnings.
        bucket = counts.setdefault(lever, {})
        bucket["instruments"] = bucket.get("instruments", 0) + count
        bucket[strength] = bucket.get(strength, 0) + count
    return counts


def coverage(session: Any) -> dict[str, int]:
    """How much of the universe carries any recorded lever, and how much of what is held.

    Both numbers are wanted on the page: the universe says how much of the taxonomy has been
    filled in, and the held count says whether the gap is somewhere the reader has money.
    """
    left, right = _universe_filter()
    universe = session.execute(
        select(func.count()).select_from(Instrument).where(left).where(right)
    ).scalar_one()
    recorded = session.execute(
        select(func.count(func.distinct(InstrumentLever.instrument_t212_ticker)))
        .join(Instrument, Instrument.t212_ticker == InstrumentLever.instrument_t212_ticker)
        .where(left)
        .where(right)
    ).scalar_one()
    held = session.execute(
        select(func.count(func.distinct(InstrumentLever.instrument_t212_ticker)))
        .join(Instrument, Instrument.t212_ticker == InstrumentLever.instrument_t212_ticker)
        .where(left)
        .where(right)
        .where(Instrument.is_held.is_(True))
    ).scalar_one()
    return {"universe": universe, "recorded": recorded, "held": held}


def instruments_for(session: Any, lever: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """The in-universe instruments a lever is recorded against, its primary ones first.

    Ordered by strength band, then held instruments, then name -- and deliberately by no
    measure of size: nothing here claims the first row is the most affected, and ordering by a
    figure would invite that reading. The strength goes through an explicit ranking rather than
    sorting the word, because "primary" only happens to precede "secondary" alphabetically and
    a later third band would silently land in the wrong place.
    """
    left, right = _universe_filter()
    rows = session.execute(
        select(InstrumentLever, Instrument)
        .join(Instrument, Instrument.t212_ticker == InstrumentLever.instrument_t212_ticker)
        .where(left)
        .where(right)
        .where(InstrumentLever.lever == lever)
        .order_by(
            case((InstrumentLever.strength == PRIMARY, 0), else_=1),
            Instrument.is_held.desc(),
            Instrument.name,
        )
        .limit(limit)
    ).all()
    return [
        describe(_row_exposure(row)) | {
            "ticker": instrument.t212_ticker,
            "name": instrument.name,
            "sector_group": instrument.sector_group,
            "sector": instrument.sector,
            "is_held": bool(instrument.is_held),
            "in_universe": bool(instrument.in_universe),
            "updated_at": row.updated_at,
        }
        for row, instrument in rows
    ]

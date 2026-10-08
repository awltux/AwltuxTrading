"""The filer's own arithmetic: the XBRL calculation linkbase.

`companyfacts` gives us the filer's tagged facts, and `ingest/xbrl.py`'s ``TAG_MAP``
decides which tag supplies which canonical metric. Neither says which lines *sum* to
which subtotal -- so every check in ``analysis/ledger.py`` compares our figures
against *our own* assertion of how a balance sheet is built. The filer states it too,
machine-readably, in the calculation linkbase published beside the filing: for each
statement role, ``<link:calculationArc>`` elements declare

    parent = Σ weight × child        (weight is +1 or -1)

which is the issuer publishing its own double-entry arithmetic. Checking our subtotals
against that instead of against ourselves is what turns a plausible check into an
authoritative one.

**Reading is separate from deciding.** :func:`parse_calculation_linkbase` parses bytes
into arcs and nothing else, and it never sees a stored period; the fetch and the stored
copy live beside it here, and the reconciliation lives in ``analysis/linkbase.py``. So the
rules are testable against a captured linkbase with no network and no database.

**Tags are joined on ``taxonomy:Tag``.** A locator's ``xlink:href`` is a fragment like
``#us-gaap_Assets`` -- the taxonomy prefix and the tag name joined by an underscore --
while ``FundamentalPeriod.metric_sources`` records ``us-gaap:Assets``. The first
underscore is the prefix separator; anything after it is the tag, which may contain
underscores of its own.

**A custom tag is normal, not an error.** Filers extend the taxonomy freely (DFPH
declares ``toi_DerivativeWarrantLiabilitiesNoncurrent``), so an arc naming a tag we
have never seen is the expected case and must not be treated as a parse failure.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from lxml import etree

logger = logging.getLogger(__name__)

XLINK = "{http://www.w3.org/1999/xlink}"

#: The XBRL specification's linkbase namespace. A literal because it is the
#: specification's URI, not ours to change.
LINK_NS = "http://www.xbrl.org/2003/linkbase"

#: What the calculation linkbase is called, after the filer's own prefix and period label
#: (`dac-20251231_cal.xml`). The suffix is the only part that is the same on every filing.
CALCULATION_SUFFIX = "_cal.xml"

#: One `app_setting` row per filing. The linkbase is read whole for one accession and
#: joined on by nothing else, which is the shape `analysis/metric_fields` already stores
#: its discovered vocabulary in -- see the reasoning there.
SETTING_PREFIX = "linkbase:"


def setting_key(accession: str) -> str:
    return f"{SETTING_PREFIX}{accession.strip()}"


@dataclass(frozen=True, slots=True)
class Calculation:
    """One declared subtotal: ``parent`` is the weighted sum of ``children``.

    ``parent`` and the child tags are ``taxonomy:Tag``, which is the key
    ``FundamentalPeriod.metric_sources`` uses for the tag a figure came from.
    """

    role: str
    parent: str
    #: ``(tag, weight)`` in the filer's declared presentation order.
    children: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class Linkbase:
    """One filing's calculation linkbase, as far as it could be read."""

    calculations: tuple[Calculation, ...] = ()
    #: Arcs that named a locator with no usable href, or a weight that was not a
    #: number. Recorded rather than dropped silently: a linkbase is the filer's
    #: statement of its own arithmetic, and a reader has to be able to tell "the
    #: filer declared nothing here" from "we could not read what it declared".
    refused: tuple[str, ...] = ()
    #: Byte length of the document this was parsed from, which with the URL is the
    #: provenance a reader needs to go and look.
    bytes_read: int = 0

    @property
    def roles(self) -> tuple[str, ...]:
        """The statements the filer declared, in first-seen order."""
        seen: dict[str, None] = {}
        for calculation in self.calculations:
            seen.setdefault(calculation.role, None)
        return tuple(seen)

    def for_parent(self, *tags: str) -> tuple[Calculation, ...]:
        """Every declaration whose parent is one of ``tags``.

        More than one role may declare the same subtotal -- the same figure appears on
        the balance sheet and in a note -- so this returns all of them and the caller
        decides.
        """
        wanted = set(tags)
        return tuple(c for c in self.calculations if c.parent in wanted)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calculations": [
                {
                    "role": c.role,
                    "parent": c.parent,
                    "children": [[tag, weight] for tag, weight in c.children],
                }
                for c in self.calculations
            ],
            "refused": list(self.refused),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Linkbase:
        """The inverse of :meth:`as_dict`, for a cached linkbase.

        Written by us and read back by us, so a malformed payload is a bug rather
        than a provider surprise: an unreadable entry raises and the caller falls back
        to refetching instead of checking against a half-read document.
        """
        calculations = tuple(
            Calculation(
                role=str(entry["role"]),
                parent=str(entry["parent"]),
                children=tuple((str(tag), float(weight)) for tag, weight in entry["children"]),
            )
            for entry in payload.get("calculations") or []
        )
        return cls(
            calculations=calculations,
            refused=tuple(str(item) for item in payload.get("refused") or []),
        )


def qualification(href: str | None) -> str | None:
    """``taxonomy:Tag`` from a locator's ``xlink:href``.

    ``#us-gaap_Assets`` becomes ``us-gaap:Assets``; a custom extension's
    ``#toi_DerivativeWarrantLiabilitiesNoncurrent`` becomes
    ``toi:DerivativeWarrantLiabilitiesNoncurrent``. Returns ``None`` for a href with
    no fragment, because a locator that names no element names no tag and guessing one
    from its label is how a check ends up comparing two different things.
    """
    if not href or "#" not in href:
        return None
    fragment = href.rsplit("#", 1)[-1].strip()
    if not fragment:
        return None
    prefix, separator, tag = fragment.partition("_")
    if not separator or not prefix or not tag:
        # A fragment with no underscore is a tag in the default namespace. Kept as it
        # is rather than refused: it is a real locator, just an unusual one.
        return fragment
    return f"{prefix}:{tag}"


def _weight(value: str | None) -> float | None:
    """An arc's weight, or ``None`` if it is not a number.

    XBRL types this as ``xsd:decimal`` and every filed arc is ``1`` or ``-1``, but the
    attribute is optional in the schema in the sense that it may be absent -- absent
    means 1 by specification, an unparseable string means nothing -- so the two cases
    are told apart rather than both defaulting to 1.
    """
    if value is None or value.strip() == "":
        return 1.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _order(value: str | None) -> float:
    """An arc's declared position, for reading the children back in statement order."""
    if value is None:
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _role_name(role: str) -> str:
    """The filer's own name for a statement, from its role URI.

    A role is a URI whose last path segment is the filer's label for the statement --
    ``.../role/CONSOLIDATEDBALANCESHEETS``. The whole URI is kept on the calculation's
    ``role`` field only as this tail: nothing downstream matches on it, and the tail is
    what a reader recognises.
    """
    return role.rsplit("/", 1)[-1] or role


def _role_declarations(link: Any, refused: list[str]) -> list[Calculation]:
    """One ``calculationLink``'s declarations, in the filer's order.

    The filer writes one arc per child, so grouping the arcs by their parent's label
    rebuilds the subtotal. Grouping is on the label rather than the tag because a
    parent may appear more than once in the same role -- once per section -- and each
    occurrence adds children.

    An arc that cannot be read appends to ``refused`` and is skipped: the rest of the
    role is still the filer's arithmetic, and refusing the whole document over one
    unusable locator would lose far more than it protects.
    """
    role = _role_name(link.get(f"{XLINK}role") or "")
    locators: dict[str, str] = {}
    arcs: list[tuple[float, str, str, str | None]] = []

    for child in link:
        name = etree.QName(child).localname
        if name == "loc":
            href = child.get(f"{XLINK}href")
            label = child.get(f"{XLINK}label")
            if label and href:
                locators[label] = href
        elif name == "calculationArc":
            arcs.append(
                (
                    _order(child.get("order")),
                    child.get(f"{XLINK}from") or "",
                    child.get(f"{XLINK}to") or "",
                    child.get("weight"),
                )
            )

    grouped: dict[str, list[tuple[float, str, float]]] = {}
    for order, source, target, weight_text in arcs:
        weight = _weight(weight_text)
        if weight is None:
            refused.append(
                f"{role}: {source} has weight {weight_text!r}, which is not a number"
            )
            continue
        parent = qualification(locators.get(source))
        child_tag = qualification(locators.get(target))
        if parent is None or child_tag is None:
            refused.append(
                f"{role}: an arc from {source!r} to {target!r} names no element "
                "(no usable xlink:href on its locator)"
            )
            continue
        grouped.setdefault(parent, []).append((order, child_tag, weight))

    declarations: list[Calculation] = []
    for parent, children in grouped.items():
        children.sort(key=lambda item: item[0])
        declarations.append(
            Calculation(
                role=role,
                parent=parent,
                children=tuple((tag, weight) for _order_, tag, weight in children),
            )
        )
    return declarations


def parse_calculation_linkbase(document: bytes | str) -> Linkbase:
    """Parse a ``_cal.xml`` document into the subtotals it declares.

    Pure: bytes in, arcs out. Raises :class:`lxml.etree.XMLSyntaxError` on a document
    that is not XML, because a caller that asked for a specific artefact and got
    something else needs to know; a *malformed arc* inside a well-formed document is
    recorded in ``refused`` and the rest of the document is still read.
    """
    raw = document.encode("utf-8") if isinstance(document, str) else document
    root = etree.fromstring(raw)

    calculations: list[Calculation] = []
    refused: list[str] = []
    for link in root.iter(f"{{{LINK_NS}}}calculationLink"):
        calculations.extend(_role_declarations(link, refused))

    if refused:
        logger.warning("calculation linkbase: %d arc(s) could not be read", len(refused))
    return Linkbase(
        calculations=tuple(calculations), refused=tuple(refused), bytes_read=len(raw)
    )


def declared_tags(linkbase: Linkbase) -> set[str]:
    """Every tag the filer's arithmetic mentions, parents included."""
    tags: set[str] = set()
    for calculation in linkbase.calculations:
        tags.add(calculation.parent)
        tags.update(tag for tag, _weight_ in calculation.children)
    return tags


# --------------------------------------------------------------------------- #
# getting one, and remembering it
# --------------------------------------------------------------------------- #


def find_calculation(names: Iterable[str]) -> str | None:
    """The calculation linkbase among a filing's filenames, if it filed one.

    Filers are not required to publish one, and the ones that do call it whatever their
    filing agent chose, so this is a suffix test over the directory listing rather than a
    constructed name. ``None`` is an ordinary answer: the reconciliation then has nothing
    to check against and the page says so instead of showing an empty table.
    """
    for name in names:
        if name.lower().endswith(CALCULATION_SUFFIX):
            return name
    return None


def fetch(
    provider: Any,
    *,
    cik: str,
    accession: str,
    cache_ttl: float = 604_800.0,
) -> tuple[Linkbase | None, str]:
    """Fetch and parse one filing's calculation linkbase. No database, no session.

    Returns the linkbase (``None`` when the filing published none) and the filename it
    came from, which is what the page cites so a reader can open the document.

    **Deliberately sessionless**, so the caller can fetch between two database phases
    rather than holding SQLite's write lock across an EDGAR request -- the rule
    ``ingest/xbrl.py`` releases the lock for, applied here by not taking it.

    A filing that published no calculation linkbase is not an error: filers are not
    required to publish one, so ``None`` is an ordinary answer and the page says so
    instead of showing an empty table.
    """
    names = provider.get_filing_index(cik, accession, cache_ttl=cache_ttl)
    name = find_calculation(names)
    if name is None:
        logger.info("no calculation linkbase among %d file(s) for %s", len(names), accession)
        return None, ""

    document = provider.fetch_document(
        provider.document_url(cik, accession, name), cache_ttl=cache_ttl
    )
    return parse_calculation_linkbase(document.body), name


def stored(session: Any, accession: str) -> tuple[Linkbase, str] | None:
    """The remembered linkbase for one filing, with the filename it came from."""
    from awltux.db import AppSetting

    if not accession:
        return None
    row = session.get(AppSetting, setting_key(accession))
    payload = row.value if row is not None else None
    if not isinstance(payload, dict) or not payload.get("calculations"):
        return None
    # The filename comes out of the stored payload, not out of `note`: the note is prose
    # for a human and parsing it would make the citation depend on its wording.
    return Linkbase.from_dict(payload), str(payload.get("source") or "")


def save(session: Any, accession: str, linkbase: Linkbase, *, source: str, cik: str) -> None:
    """Remember one filing's declared arithmetic, replacing any earlier read of it."""
    from awltux.db import AppSetting

    payload = linkbase.as_dict()
    payload["cik"] = cik
    payload["source"] = source
    payload["read_at"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    row = session.get(AppSetting, setting_key(accession))
    if row is None:
        row = AppSetting(key=setting_key(accession))
        session.add(row)
    row.value = payload
    # The filename, because it is the provenance a reader needs to open the document --
    # kept in `note` so the row is legible on the settings page as well as in code.
    row.note = f"{len(linkbase.calculations)} declaration(s) from {source}"
    session.flush()


def forget(session: Any, accession: str) -> bool:
    """Drop one filing's stored linkbase, so a wrong read is not permanent."""
    from awltux.db import AppSetting

    row = session.get(AppSetting, setting_key(accession))
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


__all__ = [
    "Calculation",
    "Linkbase",
    "declared_tags",
    "fetch",
    "find_calculation",
    "forget",
    "parse_calculation_linkbase",
    "qualification",
    "save",
    "stored",
]

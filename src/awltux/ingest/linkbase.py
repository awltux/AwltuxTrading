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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
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

#: The other two linkbases this project reads. The presentation linkbase says which
#: statement a line is printed in and in what order; the label linkbase says what the
#: filer *calls* it -- `us-gaap:PrepaidExpenseCurrent` is "Prepaid expenses" on the page.
PRESENTATION_SUFFIX = "_pre.xml"
LABEL_SUFFIX = "_lab.xml"

#: The label roles this project keeps. `label` is the printed line; `totalLabel` is what a
#: subtotal is called where the filer gives it one ("Total current assets"); `terseLabel`
#: is the short form some filers use in the statement and print nothing else.
LABEL_ROLES = (
    "http://www.xbrl.org/2003/role/label",
    "http://www.xbrl.org/2003/role/totalLabel",
    "http://www.xbrl.org/2003/role/terseLabel",
)

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


@dataclass(frozen=True, slots=True)
class RoleOrder:
    """One statement's presentation tree: which lines it prints, in the filer's order.

    XBRL presentation arcs are parent/child with an ``order`` and no weight, so this is
    the same shape as a calculation tree without the arithmetic -- and it carries what the
    calculation linkbase does not: the *statement* a line is printed in and its position.
    """

    role: str
    parent: str
    children: tuple[str, ...] = ()

    def as_list(self) -> list[Any]:
        return [self.role, self.parent, list(self.children)]


@dataclass(frozen=True, slots=True)
class Presentation:
    """One filing's presentation linkbase, as far as it could be read."""

    roles: tuple[str, ...] = ()
    links: tuple[RoleOrder, ...] = ()

    def children(self, role: str, parent: str) -> tuple[str, ...]:
        for link in self.links:
            if link.role == role and link.parent == parent:
                return link.children
        return ()

    def position(self, role: str, tag: str) -> int | None:
        """Where in a statement the filer prints ``tag``, counting from one.

        Counted over the role's leaves in order, which is the order a reader sees them:
        the point of it is to answer "where is the line we are missing" with a place in
        the filing rather than a row in our own table.
        """
        seen: list[str] = []
        parents = {link.parent for link in self.links if link.role == role}
        for link in self.links:
            if link.role != role:
                continue
            for child in link.children:
                if child in parents:
                    continue
                seen.append(child)
        if tag not in seen:
            return None
        return seen.index(tag) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "roles": list(self.roles),
            "links": [link.as_list() for link in self.links],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> Presentation:
        raw = payload or {}
        return cls(
            roles=tuple(str(role) for role in raw.get("roles") or []),
            links=tuple(
                RoleOrder(
                    role=str(entry[0]),
                    parent=str(entry[1]),
                    children=tuple(str(child) for child in entry[2]),
                )
                for entry in raw.get("links") or []
            ),
        )


@dataclass(frozen=True, slots=True)
class Labels:
    """What the filer calls each concept, keyed the way ``metric_sources`` keys tags."""

    names: Mapping[str, str] = field(default_factory=dict)
    totals: Mapping[str, str] = field(default_factory=dict)

    def name(self, tag: str) -> str:
        """The filer's name for a concept, falling back to the tag itself.

        The fallback is the tag rather than an empty string because a missing label is
        not a missing line: a reader still needs to know which line the report means.
        """
        return self.names.get(tag) or tag

    def as_dict(self) -> dict[str, Any]:
        return {"names": dict(self.names), "totals": dict(self.totals)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> Labels:
        raw = payload or {}
        return cls(
            names={str(k): str(v) for k, v in (raw.get("names") or {}).items()},
            totals={str(k): str(v) for k, v in (raw.get("totals") or {}).items()},
        )


LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
TOTAL_LABEL_ROLE = "http://www.xbrl.org/2003/role/totalLabel"
TERSE_LABEL_ROLE = "http://www.xbrl.org/2003/role/terseLabel"


def parse_presentation_linkbase(
    document: bytes | str, *, roles: Iterable[str] | None = None
) -> Presentation:
    """Parse a ``_pre.xml`` document into statement order.

    ``roles`` keeps only the roles asked about -- the statements whose arithmetic is being
    checked. A filing's notes are most of the bytes in this document and none of the
    question, and the stored copy is one JSON column per accession.

    Pure: bytes in, order out. A malformed arc is skipped; a document that is not XML
    raises, because a caller that asked for a specific artefact needs to know it got
    something else.
    """
    raw = document.encode("utf-8") if isinstance(document, str) else document
    root = etree.fromstring(raw)
    wanted = set(roles) if roles is not None else None

    links: list[RoleOrder] = []
    seen_roles: dict[str, None] = {}
    for link in root.iter(f"{{{LINK_NS}}}presentationLink"):
        role = _role_name(link.get(f"{XLINK}role") or "")
        if wanted is not None and role not in wanted:
            continue
        seen_roles.setdefault(role, None)

        locators: dict[str, str] = {}
        arcs: list[tuple[float, str, str]] = []
        for child in link:
            name = etree.QName(child).localname
            if name == "loc":
                href, label = child.get(f"{XLINK}href"), child.get(f"{XLINK}label")
                if label and href:
                    locators[label] = href
            elif name == "presentationArc":
                arcs.append(
                    (
                        _order(child.get("order")),
                        child.get(f"{XLINK}from") or "",
                        child.get(f"{XLINK}to") or "",
                    )
                )

        grouped: dict[str, list[tuple[float, str]]] = {}
        for order, source, target in arcs:
            parent = qualification(locators.get(source))
            child_tag = qualification(locators.get(target))
            if parent is None or child_tag is None:
                continue
            grouped.setdefault(parent, []).append((order, child_tag))
        for parent, children in grouped.items():
            children.sort(key=lambda item: item[0])
            links.append(
                RoleOrder(
                    role=role,
                    parent=parent,
                    children=tuple(tag for _order_, tag in children),
                )
            )

    return Presentation(roles=tuple(seen_roles), links=tuple(links))


@dataclass(frozen=True, slots=True)
class _LabelParts:
    """A label linkbase's three pieces, before they are joined."""

    #: locator label -> the concept it names.
    concepts: Mapping[str, str] = field(default_factory=dict)
    #: resource label -> role -> the text. **The same resource label carries every role**,
    #: so keying by the label alone keeps only whichever role the document happened to
    #: write last -- measured on `DAC_US_EQ`, that was `verboseLabel`, which is why an
    #: earlier version reported "Contract with Customer, Liability, Current" as unnamed.
    texts: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    #: ``(locator label, resource label)`` for every ``labelArc``.
    joins: tuple[tuple[str, str], ...] = ()


def _label_parts(root: Any) -> _LabelParts:
    """Read a label linkbase's locators, label resources and arcs, without joining them."""
    concepts: dict[str, str] = {}
    texts: dict[str, dict[str, str]] = {}
    joins: list[tuple[str, str]] = []
    for link in root.iter(f"{{{LINK_NS}}}labelLink"):
        for child in link:
            name = etree.QName(child).localname
            if name == "loc":
                href, label = child.get(f"{XLINK}href"), child.get(f"{XLINK}label")
                concept = qualification(href) if href else None
                if label and concept:
                    concepts[label] = concept
            elif name == "label":
                resource = child.get(f"{XLINK}label")
                role = child.get(f"{XLINK}role") or ""
                if resource and role in LABEL_ROLES:
                    texts.setdefault(resource, {})[role] = (child.text or "").strip()
            elif name == "labelArc":
                joins.append(
                    (child.get(f"{XLINK}from") or "", child.get(f"{XLINK}to") or "")
                )
    return _LabelParts(concepts=concepts, texts=texts, joins=tuple(joins))


def _label_names(parts: _LabelParts, wanted: set[str] | None) -> Labels:
    """Join the arcs to the concepts, keeping the role a reader actually sees."""
    names: dict[str, str] = {}
    totals: dict[str, str] = {}
    for source, resource in parts.joins:
        concept = parts.concepts.get(source)
        available = {role: text for role, text in parts.texts.get(resource, {}).items() if text}
        if not concept or not available:
            continue
        if wanted is not None and concept not in wanted:
            continue
        totals.setdefault(concept, available.get(TOTAL_LABEL_ROLE, ""))
        #  The terse label wins, and that is the whole reason to read this document:
        #  measured on `DAC_US_EQ`, `us-gaap:ContractWithCustomerLiabilityCurrent` is
        #  printed as "Unearned revenue" while its standard label is "Contract with
        #  Customer, Liability, Current", and `DeferredCosts` is "Deferred charges, net"
        #  rather than "Deferred Costs, Noncurrent". The taxonomy's wording names the
        #  concept; the terse label is what a person reading the balance sheet sees.
        for role in (TERSE_LABEL_ROLE, LABEL_ROLE, TOTAL_LABEL_ROLE):
            if available.get(role):
                names.setdefault(concept, available[role])
                break
    return Labels(
        names=names,
        totals={concept: text for concept, text in totals.items() if text},
    )


def parse_label_linkbase(
    document: bytes | str, *, concepts: Iterable[str] | None = None
) -> Labels:
    """Parse a ``_lab.xml`` document into the filer's names for its concepts.

    ``concepts`` keeps only the labels for concepts something else already names -- in
    practice the tags in the calculation linkbase. The alternative is a megabyte of
    footnote labels for accounts this codebase never reads.

    **The label is addressed by an arc, not by proximity.** A ``label`` element carries a
    resource label and ``labelArc`` joins a concept's locator to it; several label roles
    exist per concept (the printed line, a total, a terse form), so the role decides which
    one is the line a reader sees. Matching labels to concepts by document order would put
    a footnote's wording on the balance sheet.
    """
    raw = document.encode("utf-8") if isinstance(document, str) else document
    return _label_names(
        _label_parts(etree.fromstring(raw)),
        set(concepts) if concepts is not None else None,
    )


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
    """The calculation linkbase among a filing's filenames."""
    return find_document(names, CALCULATION_SUFFIX)


def find_document(names: Iterable[str], suffix: str) -> str | None:
    """The linkbase with this suffix among a filing's filenames, if it filed one.

    Filers are not required to publish any of them, and the ones that do call them
    whatever their filing agent chose (`dac-20251231_cal.xml`), so this is a suffix test
    over the directory listing rather than a constructed name. ``None`` is an ordinary
    answer: the reconciliation then has nothing to check against and the page says so
    instead of showing an empty table.
    """
    for name in names:
        if name.lower().endswith(suffix):
            return name
    return None


@dataclass(frozen=True, slots=True)
class Read:
    """What one filing's linkbases said, and the filename each came from.

    One object rather than three returns, because they are read together and used
    together: the calculation tree is the arithmetic, the presentation tree is the order
    and the statement, and the labels are what the filer calls the lines -- and a page
    that showed one without the others would name a line "us-gaap:PrepaidExpenseCurrent".
    """

    calculation: Linkbase | None = None
    presentation: Presentation | None = None
    labels: Labels | None = None
    #: kind (`cal`/`pre`/`lab`) -> the filename it was read from.
    files: Mapping[str, str] = field(default_factory=dict)

    @property
    def source(self) -> str:
        """The calculation linkbase's filename, which is the one the page cites."""
        return self.files.get("cal", "")


def fetch(
    provider: Any,
    *,
    cik: str,
    accession: str,
    cache_ttl: float = 604_800.0,
) -> Read:
    """Fetch and parse one filing's calculation, presentation and label linkbases.

    No database and no session, so the caller can fetch between two database phases
    rather than holding SQLite's write lock across an EDGAR request -- the rule
    ``ingest/xbrl.py`` releases the lock for, applied here by not taking it.

    **The three are not equal, and the trimming is deliberate.** The calculation linkbase
    is kept whole: it *is* the reconciliation. The presentation tree is kept for the roles
    the calculation declares -- a filing's notes are most of that document's bytes and none
    of the question -- and the labels are kept for the concepts the calculation names, for
    the same reason: `DAC_US_EQ`'s label linkbase is 929 KB of footnote labels for accounts
    this codebase never reads.

    A filing that published no calculation linkbase is not an error: filers are not
    required to publish one, so ``Read.calculation is None`` is an ordinary answer and the
    page says so instead of showing an empty table.
    """
    names = provider.get_filing_index(cik, accession, cache_ttl=cache_ttl)
    name = find_document(names, CALCULATION_SUFFIX)
    if name is None:
        logger.info("no calculation linkbase among %d file(s) for %s", len(names), accession)
        return Read()

    def body(filename: str) -> bytes:
        return provider.fetch_document(
            provider.document_url(cik, accession, filename), cache_ttl=cache_ttl
        ).body

    calculation = parse_calculation_linkbase(body(name))
    files = {"cal": name}
    read = Read(calculation=calculation, files=files)

    presentation_name = find_document(names, PRESENTATION_SUFFIX)
    if presentation_name is not None:
        files["pre"] = presentation_name
        read = replace(
            read,
            presentation=parse_presentation_linkbase(
                body(presentation_name), roles=calculation.roles
            ),
        )

    label_name = find_document(names, LABEL_SUFFIX)
    if label_name is not None:
        files["lab"] = label_name
        read = replace(
            read,
            labels=parse_label_linkbase(
                body(label_name), concepts=declared_tags(calculation)
            ),
        )

    return read


@dataclass(frozen=True, slots=True)
class Stored:
    """A filing as we remembered it: its trees, its source, and its figures.

    The figures are the second half of the reconciliation and are not part of a linkbase
    at all -- they come from the companyfacts payload. They are kept together because they
    answer one question together: *what does the filer say this subtotal is made of, and
    what did it tag each piece at?* An unread line with no figure beside it tells a reader
    it is missing; with its own figure it tells them how much is missing, which is what
    decides whether to care -- and with the filer's *label* it tells them which line to
    look for in the filing, in the words the filing uses.
    """

    linkbase: Linkbase
    source: str = ""
    #: iso period end -> ``taxonomy:Tag`` -> the value the filer tagged at that date.
    values: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    presentation: Presentation = field(default_factory=Presentation)
    labels: Labels = field(default_factory=Labels)
    #: kind (`cal`/`pre`/`lab`) -> the filename that tree came from, for the citation.
    files: Mapping[str, str] = field(default_factory=dict)
    read_at: str = ""

    def value(self, period: str, tag: str) -> float | None:
        """The filer's own figure for one concept at one period end, if it tagged one."""
        return (self.values.get(period) or {}).get(tag)

    def name(self, tag: str) -> str:
        """What the filer calls this concept, or the tag when it published no label."""
        return self.labels.name(tag)


def declared_values(
    payload: Mapping[str, Any],
    concepts: Iterable[str],
    *,
    ends: Iterable[str] | None = None,
) -> dict[str, dict[str, float]]:
    """The filer's own figure for each declared concept, per period end.

    Pure, and separate from the fetch so it can be tested against a captured payload.

    **Only the period ends we already hold**, passed in as ``ends``. A companyfacts
    payload carries every date the filer has ever tagged an instant at, and a linkbase's
    children include concepts tagged at quarter ends too -- so without that filter the
    record would grow by four figures per line per year to answer a question about one
    balance-sheet date. Filtering on the dates we hold is also what stands in for
    ``xbrl._is_year_end``: a period end in our table is one a duration already
    established as a fiscal year, which is the same guarantee that function provides.
    """
    from awltux.ingest import xbrl

    facts = (payload or {}).get("facts") or {}
    wanted = set(ends) if ends is not None else None
    out: dict[str, dict[str, float]] = {}
    for concept in sorted(set(concepts)):
        taxonomy, _, tag = concept.partition(":")
        if not tag:
            continue
        chosen = xbrl._pick_per_period(
            xbrl._select(facts, tag, taxonomy, instant=True, kind=xbrl.MONETARY)
        )
        for end, fact in chosen.items():
            iso = end.isoformat()
            if wanted is not None and iso not in wanted:
                continue
            value = fact.get("val")
            if isinstance(value, int | float):
                out.setdefault(iso, {})[concept] = float(value)
    return out


def stored(session: Any, accession: str) -> Stored | None:
    """The remembered record for one filing, or ``None``."""
    from awltux.db import AppSetting

    if not accession:
        return None
    row = session.get(AppSetting, setting_key(accession))
    payload = row.value if row is not None else None
    if not isinstance(payload, dict) or not payload.get("calculations"):
        return None
    # The filename comes out of the stored payload, not out of `note`: the note is prose
    # for a human and parsing it would make the citation depend on its wording.
    return Stored(
        linkbase=Linkbase.from_dict(payload),
        source=str(payload.get("source") or ""),
        values={
            str(period): {str(tag): float(value) for tag, value in (figures or {}).items()}
            for period, figures in (payload.get("values") or {}).items()
        },
        presentation=Presentation.from_dict(payload.get("presentation")),
        labels=Labels.from_dict(payload.get("labels")),
        # A record written before the presentation and label linkbases were read has no
        # `files`, and the citation must not come back empty for it.
        files=(
            {str(kind): str(name) for kind, name in (payload.get("files") or {}).items()}
            or ({"cal": str(payload["source"])} if payload.get("source") else {})
        ),
        read_at=str(payload.get("read_at") or ""),
    )


def save(
    session: Any,
    accession: str,
    linkbase: Linkbase,
    *,
    source: str,
    cik: str,
    values: Mapping[str, Mapping[str, float]] | None = None,
    presentation: Presentation | None = None,
    labels: Labels | None = None,
    files: Mapping[str, str] | None = None,
) -> None:
    """Remember one filing's trees and figures, replacing any earlier read of it."""
    from awltux.db import AppSetting

    payload = linkbase.as_dict()
    payload["cik"] = cik
    payload["source"] = source
    payload["read_at"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["values"] = {
        period: dict(figures) for period, figures in (values or {}).items()
    }
    if presentation is not None:
        payload["presentation"] = presentation.as_dict()
    if labels is not None:
        payload["labels"] = labels.as_dict()
    #  Every filename, so a reader can open the document each tree came from rather than
    #  the calculation linkbase's alone. The calculation one is always known -- it is the
    #  caller's `source` -- so the citation is never empty.
    payload["files"] = dict(files) if files else {"cal": source}

    row = session.get(AppSetting, setting_key(accession))
    if row is None:
        row = AppSetting(key=setting_key(accession))
        session.add(row)
    row.value = payload
    # The filename, because it is the provenance a reader needs to open the document --
    # kept in `note` so the row is legible on the settings page as well as in code.
    figures = sum(len(period) for period in (values or {}).values())
    names = len((labels or Labels()).names)
    row.note = (
        f"{len(linkbase.calculations)} declaration(s) from {source}, "
        f"{figures} figure(s), {names} label(s)"
    )
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
    "Labels",
    "Linkbase",
    "Presentation",
    "Read",
    "RoleOrder",
    "Stored",
    "declared_tags",
    "declared_values",
    "fetch",
    "find_calculation",
    "find_document",
    "forget",
    "parse_calculation_linkbase",
    "parse_label_linkbase",
    "parse_presentation_linkbase",
    "qualification",
    "save",
    "stored",
]

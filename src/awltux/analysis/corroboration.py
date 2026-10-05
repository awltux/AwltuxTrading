"""How many sources does this story actually have?

"Multiple outlets are reporting it" is the most common defence of a story and one
of the weakest, because most financial news is one piece of copy travelling. A
single Reuters story appears on Reuters, Yahoo Finance, MSN, a dozen regional
sites, an aggregator app, and five outlets that rewrite the first paragraph. That
is **one source with fourteen carriers**, and a system that counts domains instead
of origins will report it as overwhelming corroboration.

So this module separates the two:

* **carriers** -- distinct domains that published the story.
* **independent sources** -- how many *origins* those carriers represent. Copied
  copy collapses to one.

The collapse is a heuristic and is labelled as one. Verbatim-identical headlines
are treated as copied, which is right far more often than it is wrong, and the
alternative -- believing every republication is a fresh confirmation -- is wrong
almost always. Where a wire credit can be found in the text ("Reuters", "(AP)"),
the origin is attributed to that wire rather than to whichever domain we happened
to read first.

Independent *agreement* still counts for something, and so does disagreement: two
outlets with their own reporters describing the same event differently is a signal
worth surfacing, not noise to average away.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from awltux.analysis.sources import Publisher, domain_of, lookup

#: Two headlines this similar (token overlap) are the same story.
NEAR_DUPLICATE_THRESHOLD = 0.72

#: Attributions that mark a piece of copy as originating somewhere else.
_WIRE_MENTIONS: dict[str, tuple[str, ...]] = {
    "reuters.com": ("reuters",),
    "apnews.com": ("associated press", "(ap)", " ap)"),
    "afp.com": ("agence france-presse", "afp",),
    "bloomberg.com": ("bloomberg",),
}

#: Words carrying no topical signal, dropped before comparing headlines.
_STOPWORDS = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those", "of", "for", "from", "with", "without", "to", "in", "on", "at", "by", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its", "it's", "has", "have", "had", "will", "would", "can", "could", "may", "might", "should", "do", "does", "did", "not", "no", "nor", "so", "up", "out", "over", "under", "after", "before", "about", "into", "onto", "his", "her", "their", "our", "your", "my", "we", "you", "they", "he", "she"]
)

_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    lowered = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", lowered)).strip()


def tokens(text: str) -> set[str]:
    return {word for word in _normalise(text).split() if word not in _STOPWORDS and len(word) > 1}


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of headline tokens.

    Deliberately crude. A better duplicate detector would embed the text, but this
    one is explainable in a sentence, has no model to drift, and the cases it needs
    to catch -- the same headline reprinted verbatim -- are the easy ones.
    """
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def detect_attributed_wire(*texts: str) -> str | None:
    """The wire a piece of copy credits, if it credits one.

    Checked before domain attribution because an outlet that says "Reuters
    contributed" is not the origin, however much of the paragraph it rewrote.
    """
    haystack = " ".join(text or "" for text in texts).lower()
    for domain, markers in _WIRE_MENTIONS.items():
        for marker in markers:
            if marker in haystack:
                return domain
    return None


@dataclass(slots=True)
class Carrier:
    """One publication of the story."""

    domain: str
    title: str
    url: str | None
    publisher: Publisher
    published_at: dt.datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "title": self.title,
            "url": self.url,
            "publisher": self.publisher.name,
            "kind": self.publisher.kind,
            "reliability": self.publisher.reliability,
            "independence": self.publisher.independence,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


@dataclass(slots=True)
class Corroboration:
    """What the surrounding coverage actually establishes."""

    #: Distinct domains carrying the story.
    carriers: list[Carrier] = field(default_factory=list)
    #: Independent origins after collapsing copies.
    origins: list[str] = field(default_factory=list)
    #: The wire or outlet the copy is credited to, when one can be identified.
    attributed_origin: str | None = None
    #: True when every carrier is a copy of one origin.
    syndicated: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def carrier_count(self) -> int:
        return len(self.carriers)

    @property
    def independent_count(self) -> int:
        return len(self.origins)

    @property
    def is_single_source(self) -> bool:
        return self.independent_count <= 1

    @property
    def best_publisher(self) -> Publisher | None:
        """The most reliable independent voice, or ``None`` when there is none.

        Deliberately not "the first one we saw": an aggregator republishing a wire
        must never stand in for the wire's own reliability.
        """
        candidates = [
            carrier.publisher
            for carrier in self.carriers
            if carrier.publisher.kind not in ("aggregator", "unknown")
        ]
        if not candidates:
            candidates = [carrier.publisher for carrier in self.carriers]
        if not candidates:
            return None
        return max(candidates, key=lambda publisher: publisher.reliability)

    def as_dict(self) -> dict[str, Any]:
        return {
            "carrier_count": self.carrier_count,
            "independent_count": self.independent_count,
            "origins": list(self.origins),
            "attributed_origin": self.attributed_origin,
            "syndicated": self.syndicated,
            "carriers": [carrier.as_dict() for carrier in self.carriers[:12]],
            "notes": list(self.notes),
            "method": (
                "Carriers are distinct domains; independent sources collapse "
                "near-identical headlines and wire attributions to one origin. "
                "This is a heuristic: rewriting defeats it."
            ),
        }


def _group_by_similarity(items: list[Carrier]) -> list[list[Carrier]]:
    """Cluster carriers whose headlines describe the same story."""
    groups: list[list[Carrier]] = []
    for carrier in items:
        for group in groups:
            if any(similarity(carrier.title, member.title) >= NEAR_DUPLICATE_THRESHOLD for member in group):
                group.append(carrier)
                break
        else:
            groups.append([carrier])
    return groups


def assess(
    subject: str,
    candidates: Iterable[Any],
    *,
    window_hours: int = 72,
    as_of: dt.datetime | None = None,
) -> Corroboration:
    """Work out how many independent sources back the story ``subject``.

    ``candidates`` is any iterable of objects with ``title`` and ``url`` (a
    :class:`~awltux.db.NewsItem` is the intended one). Everything near-identical to
    the subject headline inside the window is treated as the same story.
    """
    as_of = as_of or dt.datetime.now(dt.UTC)
    cutoff = as_of - dt.timedelta(hours=window_hours)

    carriers: list[Carrier] = []
    for row in candidates:
        title = getattr(row, "title", None)
        if not title:
            continue
        published = getattr(row, "published_at", None)
        if published is not None:
            # Undated items are kept: suppressing them would hide coverage.
            if published.tzinfo is None:
                published = published.replace(tzinfo=dt.UTC)
            if published < cutoff or published > as_of + dt.timedelta(hours=6):
                continue
        url = getattr(row, "url", None)
        domain = domain_of(url) or f"source:{getattr(row, 'source', 'unknown')}"
        carriers.append(
            Carrier(
                domain=domain,
                title=title,
                url=url,
                publisher=lookup(url) if url else lookup(None),
                published_at=published,
            )
        )

    result = Corroboration(carriers=carriers)
    if not carriers:
        result.notes.append("no surrounding coverage found to corroborate this")
        return result

    attributed = detect_attributed_wire(
        *(f"{carrier.title} {carrier.url or ''}" for carrier in carriers)
    )

    # Collapse to origins. Each cluster of near-identical headlines is one origin,
    # named after the wire it credits if it credits one, otherwise after the most
    # reliable domain carrying it.
    for group in _group_by_similarity(carriers):
        credited = detect_attributed_wire(*(c.title for c in group))
        if credited:
            result.origins.append(credited)
            continue
        independent = [
            carrier
            for carrier in group
            if carrier.publisher.kind not in ("aggregator", "press_release")
        ]
        if independent:
            best = max(independent, key=lambda c: c.publisher.reliability)
            result.origins.append(best.domain)
        else:
            # Only aggregators and distributors carry it, so the origin is not
            # visible from here -- which is not the same as there being none.
            result.origins.append(f"unnamed-origin:{group[0].domain}")

    # Deduplicate origins while preserving order.
    result.origins = list(dict.fromkeys(result.origins))
    result.attributed_origin = attributed

    if result.independent_count <= 1 and result.carrier_count > 1:
        result.syndicated = True
        result.notes.append(
            f"{result.carrier_count} domains are carrying this, but they trace to one "
            "origin: republication is not corroboration."
        )
    elif result.independent_count <= 1:
        result.notes.append("only one outlet is carrying this story")

    if any(carrier.publisher.kind == "press_release" for carrier in carriers) and (
        result.independent_count <= 1
    ):
        result.notes.append(
            "the only coverage is the company's own announcement, distributed "
            "verbatim -- which is a statement, not an independent report"
        )

    if result.attributed_origin:
        result.notes.append(
            f"copy is credited to {result.attributed_origin}, so other domains "
            "carrying it add no independent confirmation"
        )
    return result


def corroboration_factor(corroboration: Corroboration) -> float:
    """Multiplier for how much the coverage is worth, 0..1.

    Rises with genuine independence and falls away when the apparent breadth is
    republication. Deliberately *not* linear in carrier count: the tenth
    republication of a wire story adds nothing, so the curve saturates quickly.
    """
    if corroboration.is_single_source:
        return 0.35 if corroboration.carrier_count else 0.2
    independent = corroboration.independent_count
    # 2 -> 0.7, 3 -> 0.85, 4+ -> ~1.0
    return min(1.0, 0.55 + 0.15 * independent)

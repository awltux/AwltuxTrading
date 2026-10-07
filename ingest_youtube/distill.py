"""Offline: transcripts in, concept candidates out. No network, no model calls.

The output of this module is a short list of *passages that mention a technique*, one
per concept, for a human (or a later pass) to grade against the primary literature.

What it deliberately does not do is turn a transcript into a finding. A transcript is
machine-recognised: unpunctuated, no speaker labels, and the numbers are its least
reliable part -- "fifteen" and "50" are one mishearing apart. A figure taken from a
transcript must never reach `FINDINGS.md` as a fact. So this module's job is to say
*this idea is in this video, at this point, in these words*, and to stop there.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

#: The concept vocabulary, grouped the way `docs/investment-markers.md` groups it, so
#: a candidate arrives with a rough idea of where it would belong. Patterns are
#: matched case-insensitively against the transcript text.
CONCEPTS: tuple[tuple[str, str, str], ...] = (
    ("valuation", "discount rate / cost of capital",
     r"discount rate|cost of capital|hurdle rate|required return|wacc"),
    ("valuation", "terminal value",
     r"terminal value|perpetuity|continuing value|exit multiple"),
    ("valuation", "cash-flow definition",
     r"free cash flow|owner earnings|maintenance capital|maintenance capex"
     r"|reinvestment|capital expenditure|capex"),
    ("valuation", "growth and reinvestment",
     r"growth rate|reinvestment|return on invested capital|roic|return on capital"
     r"|excess return"),
    ("valuation", "margin of safety",
     r"margin of safety|intrinsic value|fair value|price to value"),
    ("valuation", "multiples and comparables",
     r"multiple|p/e|price to earnings|ev/ebitda|comparable|peer group"),
    ("accounting", "earnings quality",
     r"accrual|earnings quality|non-cash|one-off|exceptional item|non-recurring"),
    ("accounting", "revenue recognition and receivables",
     r"revenue recogni|receivable|days sales|dso|channel stuffing|bill and hold"),
    ("accounting", "leases and off-balance-sheet",
     r"ifrs 16|lease liabilit|operating lease|capital lease|off-balance"),
    ("accounting", "goodwill and impairments",
     r"goodwill|impairment|write-?down|write-?off"),
    ("accounting", "stock-based compensation",
     r"stock-based compensation|share-based|sbc|dilution from options|option expense"),
    ("quality", "returns on capital",
     r"return on equity|roe|return on assets|roa|roic|return on invested"),
    ("quality", "moat and durability",
     r"\bmoat\b|competitive advantage|pricing power|switching cost|network effect"),
    ("quality", "capital allocation",
     r"capital allocation|buyback|share repurchase|dividend polic|payout ratio"),
    ("risk", "leverage and solvency",
     r"leverage|net debt|interest coverage|solvency|bankrupt|insolven|altman"),
    ("risk", "cyclicality",
     r"cyclical|through the cycle|normalis|normaliz|peak earnings|trough"),
    ("meta", "a figure that would need a filing",
     r"\b\d+(?:\.\d+)?\s?%|\$\s?\d|\b\d+(?:\.\d+)?\s?(?:billion|million|bn|bn\.)\b"),
)

#: A video teaches a method when its text spans at least this many distinct concepts
#: across at least this many mentions.
#:
#: Measured on the thirteen transcripts this POC holds: the twelve earlier ones top
#: out at three distinct concepts and fail; Damodaran's DCF session carries eleven
#: concepts and 104 mentions of them. The bar is deliberately about *vocabulary
#: spread* rather than volume, because a 25-minute company analysis mentions cash flow
#: a dozen times without defining anything.
METHOD_MIN_DISTINCT = 4
METHOD_MIN_MENTIONS = 12

#: Sentences carrying one of these are almost never a method statement; the corpus
#: that motivated this module was wall-to-wall financial entertainment.
PROMO_MARKERS = (
    "link below", "description below", "free course", "sign up", "sponsor",
    "patreon", "subscribe", "click the", "my course", "discord", "affiliate",
    "membership", "giveaway", "not financial advice",
)

MIN_SENTENCE_CHARS = 60
MAX_CANDIDATES_PER_CONCEPT = 6

#: Bumped when the extraction rules change, so previously distilled transcripts become
#: outstanding again. The same idiom as a mapper version stamped on a metric row: the
#: only way to tell "never distilled" from "distilled by an older version of the rules"
#: without re-reading every transcript on every run.
EXTRACTOR_VERSION = 1

#: Words per excerpt when a block carries no sentence punctuation.
#:
#: Auto-captions are not sentences. Measured on Damodaran's DCF session: 15,433 words
#: with **31 full stops in the entire transcript**, so splitting on sentence enders
#: found one match and returned the whole lecture as a single 80,000-character
#: "sentence" -- which then became the excerpt for every concept it mentioned, all
#: eleven of them quoting the opening roll-call. Chunks of about this many words are
#: short enough to read and long enough to hold a claim.
CHUNK_WORDS = 40


@dataclass
class Candidate:
    """One passage that mentions one concept, with enough context to judge it."""

    concept: str
    group: str
    video_id: str
    title: str
    quote: str
    promo_flagged: bool

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "concept": self.concept,
            "video_id": self.video_id,
            "title": self.title,
            "promo_flagged": self.promo_flagged,
            "quote": self.quote,
        }


def sentences(text: str) -> list[str]:
    """Split a caption blob into readable units.

    Three passes, because captions are only sometimes punctuated: sentence enders
    where the transcript has them, the caption's own line breaks, and -- for the long
    unpunctuated stretches that are the norm -- fixed-width chunks of
    :data:`CHUNK_WORDS`. The last pass exists because the first one, on real input,
    returned a single 80,000-character unit and made every quote in the output come
    from the same opening seconds.
    """
    units: list[str] = []
    for block in re.split(r"\n+", text):
        block = " ".join(block.split())
        if not block:
            continue
        parts = [part for part in re.split(r"(?<=[.!?])\s+", block) if part.strip()]
        for part in parts or [block]:
            words = part.split()
            if len(words) <= CHUNK_WORDS * 1.5:
                units.append(" ".join(words))
            else:
                # A long unpunctuated stretch: cut it at word boundaries.
                for start in range(0, len(words), CHUNK_WORDS):
                    units.append(" ".join(words[start:start + CHUNK_WORDS]))
    return [unit for unit in units if len(unit) >= MIN_SENTENCE_CHARS]


def is_promo(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in PROMO_MARKERS)


def select_candidates(text: str, video_id: str, title: str) -> list[Candidate]:
    """Every concept mention in one transcript, capped per concept.

    Promo-flagged passages are kept rather than dropped: the task note says to expect
    promotional bias, and a reviewer needs to see that the concept arrived attached
    to a product recommendation rather than have the tool quietly hide it.
    """
    found: list[Candidate] = []
    per_concept: dict[str, int] = {}
    for sentence in sentences(text):
        for group, concept, pattern in CONCEPTS:
            if per_concept.get(concept, 0) >= MAX_CANDIDATES_PER_CONCEPT:
                continue
            if re.search(pattern, sentence, re.IGNORECASE):
                found.append(
                    Candidate(
                        concept=concept,
                        group=group,
                        video_id=video_id,
                        title=title,
                        quote=sentence[:400],
                        promo_flagged=is_promo(sentence),
                    )
                )
                per_concept[concept] = per_concept.get(concept, 0) + 1
    return found


def kind_of(text: str, title: str) -> str:
    """Rough genre of one transcript: `method`, `example`, `entertainment` or `mixed`.

    Not a classifier anyone should trust. It exists so a corpus of clickbait does not
    get read as if it were a syllabus: a video whose whole text is "the window is
    closing" and "link below" is not a valuation lecture, whatever its title says.

    The first version of this counted how many concept *patterns* appeared anywhere in
    the text and called it `entertainment` when the count was low. Measured on
    Damodaran's DCF session: 15,433 words, 61 mentions of discount rate or cost of
    capital, 16 of cash flow, 104 concept mentions in total across eight distinct
    concepts -- classified as entertainment, because eight patterns is not many and
    the *mentions* were never counted. Hence: distinct concepts carry the genre,
    mentions carry the weight, and the `meta` group ("a figure that would need a
    filing") is not evidence of method at all -- it fires on any number.
    """
    lowered = (text or "").lower()
    title_low = (title or "").lower()
    promo_hits = sum(lowered.count(marker) for marker in PROMO_MARKERS)

    mentions = 0
    distinct: set[str] = set()
    for group, concept, pattern in CONCEPTS:
        if group == "meta":
            continue
        hits = len(re.findall(pattern, lowered, re.IGNORECASE))
        if hits:
            distinct.add(concept)
            mentions += hits

    hype = re.search(
        r"window is closing|about to lose|you will be wiped out|millionaire"
        r"|life-changing|never be the same|biggest (?:wealth|opportunity)",
        lowered,
    )
    example = re.search(
        r"\bq[1-4] 20\d\d\b|\bearnings (?:call|report)\b|\bprice target\b|\bmy position\b",
        title_low,
    )
    # Genre is about *method*, so a thin concept vocabulary disqualifies a video
    # whatever else it does: a handful of mentions across fewer than four distinct
    # concepts is a video that keeps returning to one idea, or to none.
    lecture = len(distinct) >= METHOD_MIN_DISTINCT and mentions >= METHOD_MIN_MENTIONS
    if lecture and promo_hits < 4:
        return "method"
    if example and len(distinct) >= 3:
        return "example"
    if hype or not lecture:
        return "entertainment"
    return "mixed"


def transcript_digest(text: str) -> str:
    """A short, stable fingerprint of one transcript's **content**.

    Purpose: tell "this transcript is the one we already extracted" from "this
    transcript changed" without keeping a second copy of the text. A re-fetched
    transcript whose captions were revised changes its digest and is re-read, which a
    `done: true` flag could not notice -- and a local file that was truncated, edited or
    corrupted changes it too, which is the integrity half.

    Deliberately **not** folded together with :data:`EXTRACTOR_VERSION`. An earlier
    version hashed the version into this value, which conflated two unrelated events:
    "the rules changed" and "the text changed". They need different answers -- the first
    re-extracts, the second is a data-integrity problem -- and a reader cannot separate
    them from one digest.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def integrity_report(root: Path, previous: dict | None = None) -> dict:
    """Which stored transcripts still hash to what was extracted from them.

    The check the store could not answer before: a transcript can be present, counted
    as held, and be the wrong bytes. Reports a count and one example, so the answer to
    "is the local corpus intact?" is a sentence rather than an exercise.
    """
    previous = previous or {}
    stored = previous.get("digests") or {}
    store = root / "transcripts"
    mismatched: list[str] = []
    checked = 0
    for video_id, digest in sorted(stored.items()):
        path = store / f"{video_id}.txt"
        if not path.exists():
            mismatched.append(video_id)
            continue
        checked += 1
        if transcript_digest(path.read_text(encoding="utf-8")) != digest:
            mismatched.append(video_id)
    return {"checked": checked, "mismatched": mismatched}


def load_previous(path: Path) -> dict:
    """The last extraction, for its watermarks. Anything unreadable is not a watermark."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def distill_store(
    root: Path,
    previous: dict | None = None,
    *,
    only_outstanding: bool = True,
) -> dict:
    """Walk the transcript store and return a candidate payload plus a genre census.

    ``previous`` is the payload a prior run wrote, read for its per-transcript
    ``digests``. A transcript whose digest is unchanged is **skipped**, not re-extracted:
    the candidates are carried forward from the previous payload verbatim. Without that,
    every run re-did settled work -- measured as byte-identical output across two runs --
    which is a bug even when the result is correct.
    """
    store = root / "transcripts"
    index = {}
    index_path = store / "index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            index = {}

    previous = previous or {}
    old_digests = previous.get("digests") or {}
    old_version = previous.get("extractor_version")
    # Two separate reasons to re-read, reported separately because they call for
    # different responses: `changed` means the bytes are not the bytes we extracted
    # (a revised transcript, or a damaged file), `restated` means the rules moved on.
    changed: list[str] = []
    restated: list[str] = []
    carried: dict[str, list[dict]] = {}
    for entry in previous.get("candidates") or []:
        carried.setdefault(entry["video_id"], []).append(entry)

    candidates: list[Candidate] = []
    genres: dict[str, list[str]] = {}
    paths = sorted(store.glob("*.txt"))
    digests: dict[str, str] = {}
    done: list[str] = []
    outstanding: list[str] = []

    for path in paths:
        video_id = path.stem
        text = path.read_text(encoding="utf-8")
        digest = transcript_digest(text)
        digests[video_id] = digest
        title = (index.get(video_id) or {}).get("title") or ""

        settled = video_id in carried and old_digests.get(video_id) == digest
        current = old_version == EXTRACTOR_VERSION
        # `only_outstanding` guards the skip: without it, `--force` was a no-op that
        # still reported the text as already extracted.
        if only_outstanding and settled and current:
            done.append(video_id)
            genres.setdefault(
                (previous.get("genres_by_video") or {}).get(video_id, "unknown"), []
            ).append(video_id)
            candidates.extend(_from_dict(entry) for entry in carried[video_id])
            continue

        if only_outstanding:
            if video_id in carried and not current:
                restated.append(video_id)
            elif video_id in carried:
                changed.append(video_id)

        outstanding.append(video_id)
        genre = kind_of(text, title)
        genres.setdefault(genre, []).append(video_id)
        candidates.extend(select_candidates(text, video_id, title))

    by_concept: dict[str, int] = {}
    for candidate in candidates:
        by_concept[candidate.concept] = by_concept.get(candidate.concept, 0) + 1

    return {
        "transcripts": len(paths),
        "extracted_this_run": len(outstanding),
        "already_extracted": len(done),
        "outstanding": sorted(outstanding),
        "changed_since_extraction": sorted(changed),
        "restated_by_extractor": sorted(restated),
        "extractor_version": EXTRACTOR_VERSION,
        "digests": digests,
        "genres": {name: sorted(ids) for name, ids in genres.items()},
        "genres_by_video": {
            video_id: name for name, ids in genres.items() for video_id in ids
        },
        "by_concept": by_concept,
        "candidates": [candidate.as_dict() for candidate in candidates],
    }


def _from_dict(entry: dict) -> Candidate:
    """Rehydrate a candidate carried forward from a previous payload."""
    return Candidate(
        concept=entry["concept"],
        group=entry.get("group", ""),
        video_id=entry["video_id"],
        title=entry.get("title") or "",
        quote=entry.get("quote") or "",
        promo_flagged=bool(entry.get("promo_flagged")),
    )

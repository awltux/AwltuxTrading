"""Manipulation markers in news copy, found without a model.

Financial news is written to be read, and a great deal of it is written to make
you *feel* something: fear, urgency, excitement, certainty. Those techniques are
not subtle and they are not random -- they use a recognisable vocabulary, and a
recognisable set of structural tricks. This module finds them by pattern, which
matters for two reasons:

* **It cannot be talked out of it.** A language model asked "is this article
  manipulative?" can be persuaded by the article, which is exactly the input it is
  judging. A regular expression cannot.
* **It is cheap enough to run on everything.** The expensive model is then used
  only where it adds something a lexicon cannot: what the article actually claims,
  and what it leaves out.

The score is not a verdict on the article's truth. A tabloid shouting about a real
bank run is still shouting. It measures *presentation*, and the system treats a
high score as a reason to demand corroboration, not as evidence of falsehood --
conflating the two would be its own kind of lazy thinking.

Techniques are named after the classical informal-fallacy and propaganda
taxonomies, because those names are checkable and a claim that an article uses
"appeal to fear" can be pointed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Maximum contribution each technique can make to the 0..1 score, before the
#: overall clamp. Weighted by how strongly the technique signals manipulation
#: rather than merely vivid writing.
TECHNIQUE_WEIGHTS: dict[str, float] = {
    "appeal_to_fear": 0.22,
    "shock_language": 0.20,
    "false_urgency": 0.14,
    "vague_authority": 0.14,
    "anonymous_sourcing": 0.12,
    "absolute_language": 0.10,
    "loaded_language": 0.10,
    "bandwagon": 0.10,
    "unnamed_expert_consensus": 0.10,
    "clickbait_construction": 0.08,
}

#: Score at or above which the framing is worth acting on.
#:
#: One number rather than three: the flag on the report, the discount in the
#: grading rules and the threshold the pipeline uses to decide what to look at all
#: mean "this was written to provoke", and letting them drift apart would mean a
#: story could be damning enough to appraise but not damning enough to discount.
#:
#: 0.30 is roughly "one strong technique with evidence, or several weak ones". It
#: is a judgement, and it is deliberately low: this flag asks for corroboration
#: rather than declaring falsehood, so the cost of a false positive is a little
#: extra scrutiny.
SUSPICION_THRESHOLD = 0.30

#: Readable names for the UI, so a score can always be decomposed into reasons.
TECHNIQUE_LABELS: dict[str, str] = {
    "appeal_to_fear": "Appeal to fear",
    "shock_language": "Shock language",
    "false_urgency": "Manufactured urgency",
    "vague_authority": "Unnamed authority",
    "anonymous_sourcing": "Anonymous sourcing",
    "absolute_language": "Absolute claims",
    "loaded_language": "Loaded language",
    "bandwagon": "Bandwagon appeal",
    "unnamed_expert_consensus": "'Analysts say' consensus",
    "clickbait_construction": "Clickbait construction",
}

#: Each pattern is anchored where it matters and matched case-insensitively.
#: Phrases are chosen to be *characteristic* of the technique rather than merely
#: possible in it: "crash" appears in real reporting about real crashes, so the
#: fear lexicon takes the intensifiers ("wipeout", "bloodbath", "catastrophe")
#: and leaves the plain nouns alone.
PATTERNS: dict[str, tuple[str, ...]] = {
    "appeal_to_fear": (
        r"\b(wipeout|wipe out|bloodbath|blood bath|carnage|apocalypse|catastroph\w+|"
        r"meltdown|obliterat\w+|annihilat\w+|doom(?:ed)?|disaster|panic|"
        r"nightmare|horror show|crushed|slaughtered|devastat\w+)\b",
        r"\b(investors?\s+(?:are\s+)?(?:fleeing|panicking|dumping))\b",
        r"\b(wealth|savings|retirement|pension)s?\s+(?:destroyed|wiped out|obliterated)\b",
    ),
    "shock_language": (
        r"\b(stunning|shocking|explosive|bombshell|jaw[- ]dropping|breathtaking|"
        r"unbelievable|incredible|mind[- ]blowing|scary|terrifying|alarming)\b",
        r"\b(you won'?t believe|what happened next|this is huge|nobody saw)\b",
    ),
    "false_urgency": (
        r"\b(act now|act fast|before it'?s too late|time is running out|"
        r"urgent(?:ly)?|immediately|right now|don'?t wait|last chance|"
        r"window is closing|hurry)\b",
        r"\b(must act|critical moment|now or never|decide today)\b",
    ),
    "vague_authority": (
        r"\b(experts?|analysts?|observers?|commentators?|insiders?|sources?|"
        r"officials?|people familiar|those close to|industry figures?|"
        r"market participants?|some say|it is (?:said|understood|believed|thought)|"
        r"reportedly|rumou?rs? (?:say|suggest|circulat))\b",
    ),
    "anonymous_sourcing": (
        r"\b(unnamed|anonymous|unidentified)\s+(?:source|sources|official|officials|"
        r"person|people|insider|executive)\b",
        r"\b(sources? (?:said|told|say|claim|suggest|indicated)|"
        r"people familiar with the matter|speaking on condition of anonymity)\b",
        r"\b(a person (?:with )?(?:knowledge|familiar))\b",
    ),
    "absolute_language": (
        r"\b(always|never|everyone|no one|nobody|all of|none of|"
        r"guaranteed|certain(?:ly)?|undoubtedly|unquestionably|impossible|"
        r"definitely|proves?|proof that)\b",
    ),
    "loaded_language": (
        r"\b(regime|bureaucrat\w*|elites?|fat cat\w*|greedy|corrupt|"
        r"scam|fraudster|shill|propaganda|brainwash\w*|sleazy|disgraceful|"
        r"outrageous|despicable|pathetic|incompetent|clueless)\b",
    ),
    "bandwagon": (
        r"\b(everyone is|everybody is|no one is|nobody is|the whole market|"
        r"all investors|smart money is|the crowd is|consensus is now)\b",
    ),
    "unnamed_expert_consensus": (
        r"\b(analysts? (?:say|expect|believe|agree|warn|predict)|"
        r"experts? (?:say|agree|warn|believe|expect)|"
        r"widely (?:expected|believed|anticipated)|"
        r"market (?:expects|believes|fears)|consensus (?:expects|is))\b",
    ),
    "clickbait_construction": (
        r"(^|\s)(here'?s why|this is why|the reason why|what it means for)\b",
        r"\?$",
        r"\b(and it'?s not what you think|for good reason)\b",
    ),
}

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    name: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for name, patterns in PATTERNS.items()
}

#: Words that carry emotional charge without adding information. Counted as a
#: density: a long article using two intensifiers is not the same as a headline
#: made of them.
INTENSIFIERS = (
    "massive", "huge", "enormous", "staggering", "devastating", "dire",
    "brutal", "savage", "explosive", "unprecedented", "chaos", "turmoil",
    "plunge", "plummet", "tumble", "soar", "skyrocket", "surge", "slump",
    "collapse", "slam", "blast", "hammer", "demolish", "erupt",
)
_INTENSIFIER_RE = re.compile(r"\b(" + "|".join(INTENSIFIERS) + r")\b", re.IGNORECASE)

#: Headline openers characteristic of a story that is trying to sell itself.
_HEDGE_WORDS = re.compile(
    r"\b(may|could|might|reportedly|rumou?red|expected|likely|appears?|"
    r"said to|set to|poised to|on track to)\b",
    re.IGNORECASE,
)

#: Sentences that put a number in front of a reader without a comparison are worse
#: than useless -- "down 40%" is meaningless without "from what". This flags the
#: common shape of a bare percentage with no base. No trailing ``\b``: a word
#: boundary does not exist between ``%`` and the comma that usually follows it.
_BARE_PERCENTAGE = re.compile(r"\d+(?:\.\d+)?\s?(?:%|per cent|percent)", re.IGNORECASE)


@dataclass(slots=True)
class RhetoricFinding:
    """One detected technique, with the text that triggered it."""

    technique: str
    label: str
    evidence: tuple[str, ...]
    count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "technique": self.technique,
            "label": self.label,
            "evidence": list(self.evidence),
            "count": self.count,
        }


@dataclass(slots=True)
class RhetoricReport:
    """The full picture for one piece of copy."""

    score: float
    findings: list[RhetoricFinding] = field(default_factory=list)
    intensifier_density: float = 0.0
    hedged: bool = False
    bare_percentages: int = 0
    word_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_suspicious(self) -> bool:
        return self.score >= SUSPICION_THRESHOLD

    @property
    def techniques(self) -> list[str]:
        return [finding.technique for finding in self.findings]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "findings": [finding.as_dict() for finding in self.findings],
            "intensifier_density": round(self.intensifier_density, 4),
            "hedged": self.hedged,
            "bare_percentages": self.bare_percentages,
            "word_count": self.word_count,
            "notes": self.notes,
        }


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9%']+", text)


def analyse_text(text: str, *, headline: str | None = None) -> RhetoricReport:
    """Score one piece of copy for manipulation techniques.

    ``text`` is whatever we hold -- usually the summary or lede. ``headline`` is
    scored with a heavier hand, because headlines are where the technique is
    applied hardest and where it survives into the reader's memory even when the
    article contradicts it.
    """
    body = (text or "").strip()
    if not body and not headline:
        return RhetoricReport(score=0.0, notes=["no text to analyse"])

    combined = f"{headline or ''}\n{body}".strip()
    words = _words(combined)
    word_count = len(words)

    findings: list[RhetoricFinding] = []
    raw_score = 0.0

    for technique, patterns in _COMPILED.items():
        matched: list[str] = []
        for pattern in patterns:
            for match in pattern.finditer(combined):
                snippet = _snippet(combined, match.start(), match.end())
                if snippet and snippet not in matched:
                    matched.append(snippet)
                if len(matched) >= 3:
                    break
            if len(matched) >= 3:
                break
        if not matched:
            continue

        count = sum(len(pattern.findall(combined)) for pattern in patterns)
        weight = TECHNIQUE_WEIGHTS[technique]
        # The first occurrence is the signal; repetition adds a little, because
        # hammering one technique is itself a technique.
        raw_score += weight * (1.0 + 0.25 * (len(matched) - 1))
        findings.append(
            RhetoricFinding(
                technique=technique,
                label=TECHNIQUE_LABELS[technique],
                evidence=tuple(matched[:3]),
                count=count,
            )
        )

    intensifiers = _INTENSIFIER_RE.findall(combined)
    # Density per 100 words, normalised so 4% of words being intensifiers is
    # already a lot. Headlines are short, so they are scaled as if 12 words.
    density_basis = max(word_count, 12)
    dens = len(intensifiers) / density_basis * 100.0
    intensifier_density = dens

    score = raw_score + min(0.12, dens * 0.03)
    if intensifier_density >= 8.0 and "loaded_language" not in {
        finding.technique for finding in findings
    }:
        findings.append(
            RhetoricFinding(
                technique="loaded_language",
                label=TECHNIQUE_LABELS["loaded_language"],
                evidence=tuple(dict.fromkeys(intensifiers))[:3],
                count=len(intensifiers),
            )
        )

    notes: list[str] = []
    hedged = bool(_HEDGE_WORDS.search(combined))
    if hedged and score >= 0.3:
        # The classic combination: an alarming claim that is technically a
        # prediction, so it cannot be wrong. "Shares may be wiped out."
        notes.append(
            "Alarming language attached to a hedged claim: the headline asserts "
            "what the wording only speculates."
        )
        score *= 1.15

    bare = len(_BARE_PERCENTAGE.findall(body))
    if bare and not re.search(r"\b(from|versus|vs\.?|compared|than|prior|ago|year[- ]on[- ]year)\b",
                              body, re.IGNORECASE):
        notes.append(
            "Percentages with no base stated: a change is given without saying what "
            "it is a change from."
        )
        score += 0.05

    if headline and body:
        mismatch = _headline_mismatch(headline, body)
        if mismatch:
            notes.append(
                "Headline is more extreme than the text beneath it, which is where "
                "most readers stop."
            )
            score += 0.10

    return RhetoricReport(
        score=max(0.0, min(1.0, score)),
        findings=findings,
        intensifier_density=intensifier_density,
        hedged=hedged,
        bare_percentages=bare,
        word_count=word_count,
        notes=notes,
    )


def _headline_mismatch(headline: str, body: str) -> bool:
    """Whether the headline carries charge the body does not.

    Only compares technique density, not sentiment: a negative headline over a
    negative article is normal reporting. The failure is a headline that shouts
    while the copy explains.
    """
    headline_report = _score_only(headline)
    body_report = _score_only(body)
    return headline_report - body_report >= 0.15 and headline_report >= 0.2


def _score_only(text: str) -> float:
    score = 0.0
    for technique, patterns in _COMPILED.items():
        if any(pattern.search(text) for pattern in patterns):
            score += TECHNIQUE_WEIGHTS[technique]
    return score


def _snippet(text: str, start: int, end: int, *, radius: int = 40) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    excerpt = re.sub(r"\s+", " ", text[left:right]).strip()
    return excerpt[:160]


def identify_technique(name: str) -> str | None:
    """Whether a model-reported technique name is one we recognise.

    Used to validate model output against the closed taxonomy: an invented
    technique name is dropped rather than displayed, so the vocabulary the UI
    shows is one a reader can hold the article to.
    """
    cleaned = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return cleaned if cleaned in TECHNIQUE_LABELS else None

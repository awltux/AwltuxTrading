"""Critical-thinking arithmetic: how much should this story move anything?

Every other module here produces an observation -- who published it, what
techniques it uses, how many independent sources carry it, what it claims. This
one turns those observations into the only number that actually matters:
**how much weight this article gets when the sentiment score is computed.**

The arithmetic lives in code, not in a prompt, for the same reason the valuation
does. A model asked "how credible is this?" is judging its own input, and an
article that is confidently written tends to be judged confidently written. The
rules below are dull, explicit, and can be argued with:

1. Start from who is speaking: reliability, adjusted for whether the source has a
   stake and which way the story cuts for them.
2. Multiply by corroboration -- and republication is not corroboration.
3. Discount for presentation: fear appeals, unnamed authorities, urgency.
4. Discount hard when a material claim rests on nothing checkable.
5. **Ceiling.** A single-source story from an unrated publisher, written in
   shock language, cannot exceed a low weight however favourable everything else
   looks. A rule that composes multiplications will eventually let something
   through that every individual factor thought was tolerable, so there is an
   explicit cap as well.

An article judged weak is not deleted and not hidden. It keeps its sentiment
score, loses most of its influence, and carries the reasons why -- which is the
difference between scepticism and censorship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from awltux.analysis.corroboration import Corroboration, corroboration_factor
from awltux.analysis.rhetoric import RhetoricReport
from awltux.analysis.sources import Publisher, source_weight

#: Claim types, ordered by how much work they can do as evidence. A claim is
#: scored by *type* rather than by whether we happen to believe it.
CLAIM_TYPES: dict[str, str] = {
    "reported_fact": "something that happened, stated as fact",
    "attributed_statement": "someone said something (which may be true regardless)",
    "filed_record": "a fact recorded in a filing, register or court document",
    "inference": "the writer's conclusion, not stated by any source",
    "prediction": "a claim about the future, which cannot be checked now",
    "opinion": "a judgement or preference",
    "allegation": "a claim of wrongdoing that is unproven",
    "rumour": "an unattributed claim of something not yet public",
    "promotional": "a claim that serves the subject's interests",
}

#: Where the *ultimate* source of a claim would live, if one exists. Used to
#: answer "what would settle this?" -- and, when the answer is "nothing", to say
#: that instead of pretending a source exists.
PRIMARY_REGISTERS: dict[str, tuple[str, str]] = {
    # claim category -> (register name, where to look)
    "financial_result": (
        "Company filings",
        "SEC EDGAR for US filers; RNS announcements and Companies House accounts for UK",
    ),
    "guidance": (
        "Company statement",
        "The company's own announcement, filing or earnings call transcript",
    ),
    "regulatory_action": (
        "The regulator",
        "FCA or SEC enforcement pages, or the regulator's own press office",
    ),
    "legal_proceeding": (
        "Court records",
        "The court's own docket, not a report about the docket",
    ),
    "ownership_change": (
        "Regulatory disclosure",
        "SEC Schedule 13D/13G, or an RNS holding notification",
    ),
    "macro_statistic": (
        "Statistical agency",
        "ONS, BLS, Eurostat or the central bank that published the number",
    ),
    "market_data": ("Exchange data", "The exchange or its official data vendor"),
    "product_or_contract": (
        "Company announcement",
        "The company's own release or filing -- a distributor's copy is not additional evidence",
    ),
    "analyst_opinion": (
        "The analyst's own note",
        "Usually not public. Without it, a report of a rating change cannot be checked at all",
    ),
    "rumour_or_speculation": ("None exists", "By definition there is nothing to check against"),
}

#: Weight multiplier per claim type when deciding whether a story is *supported*.
CLAIM_TYPE_SUPPORT: dict[str, float] = {
    "filed_record": 1.0,
    "reported_fact": 0.8,
    "attributed_statement": 0.6,
    "promotional": 0.35,
    "inference": 0.3,
    "allegation": 0.3,
    "opinion": 0.2,
    "prediction": 0.2,
    "rumour": 0.1,
}

#: Attributions that let a claim be checked, and those that do not.
CHECKABLE_ATTRIBUTIONS = frozenset(
    {"filing", "regulator", "court", "company_statement", "named_source", "official_data"}
)
UNCHECKABLE_ATTRIBUTIONS = frozenset(
    {"unnamed_source", "market_rumour", "analyst_note", "journalist_inference", "none"}
)

#: No article scoring above this on the rhetoric scale can be treated as strong
#: evidence, whatever its source: presentation and precision are supposed to be
#: independent, and when the presentation is doing the work, it is doing the work.
RHETORIC_HARD_CEILING = 0.55

#: A single-source, unrated-publisher story tops out here.
UNCONFIRMED_CEILING = 0.25

#: Ordering for the headline grade shown to a reader.
GRADES = ("unsupported", "weak", "mixed", "moderate", "strong")


@dataclass(slots=True)
class Claim:
    """One assertion extracted from the article, and where it could be checked."""

    text: str
    claim_type: str
    attribution: str
    span: str | None = None
    primary_register: str | None = None
    where_to_check: str | None = None

    @property
    def checkable(self) -> bool:
        return self.attribution in CHECKABLE_ATTRIBUTIONS

    @property
    def support(self) -> float:
        base = CLAIM_TYPE_SUPPORT.get(self.claim_type, 0.2)
        if self.attribution in UNCHECKABLE_ATTRIBUTIONS:
            # An uncheckable attribution halves whatever the type was worth.
            base *= 0.5
        return base

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "claim_type": self.claim_type,
            "attribution": self.attribution,
            "span": self.span,
            "checkable": self.checkable,
            "primary_register": self.primary_register,
            "where_to_check": self.where_to_check,
            "support": round(self.support, 4),
        }


@dataclass(slots=True)
class NewsAssessment:
    """Everything the system concluded about one article's evidential value."""

    credibility: float
    grade: str
    source_reliability: float
    source_independence: float
    source_kind: str
    source_weight: float
    corroboration_factor: float
    rhetoric_score: float
    claim_support: float
    #: Human-readable reasons, in the order they were applied.
    warnings: list[str] = field(default_factory=list)
    #: Things a reader is entitled to know before believing any of it.
    caveats: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)

    @property
    def is_confirmed(self) -> bool:
        return "unconfirmed" not in self.flags

    def as_dict(self) -> dict[str, Any]:
        return {
            "credibility": round(self.credibility, 4),
            "grade": self.grade,
            "source_reliability": self.source_reliability,
            "source_independence": self.source_independence,
            "source_kind": self.source_kind,
            "source_weight": round(self.source_weight, 4),
            "corroboration_factor": round(self.corroboration_factor, 4),
            "rhetoric_score": round(self.rhetoric_score, 4),
            "claim_support": round(self.claim_support, 4),
            "warnings": list(self.warnings),
            "caveats": list(self.caveats),
            "flags": list(self.flags),
            "claims": [claim.as_dict() for claim in self.claims],
        }


def resolve_primary_source(category: str | None) -> tuple[str | None, str | None]:
    """Where the ultimate source of a claim would be found, if anywhere."""
    if not category:
        return None, None
    entry = PRIMARY_REGISTERS.get(category)
    if entry is None:
        return None, None
    return entry


# A flat list of independent observations, each appending its own sentence and flag.
# The order is the order a reader checks them in, and every block is self-contained;
# the branches are a decision table, which is shorter read whole than in five parts.
def grade(  # noqa: C901
    *,
    publisher: Publisher,
    rhetoric: RhetoricReport | None = None,
    corroboration: Corroboration | None = None,
    claims: list[Claim] | None = None,
    direction: str | None = None,
    materiality: str | None = None,
    source_category: str | None = None,
) -> NewsAssessment:
    """Turn the observations into a credibility weight and a stated grade.

    ``source_category`` lets a claim be routed to its register without a model
    having to name it: a story about results has a company filing behind it, and
    the caller may know that from the article's own event_type.
    """
    rhetoric = rhetoric or RhetoricReport(score=0.0)
    corroboration = corroboration or Corroboration()
    claims = claims or []

    warnings: list[str] = []
    caveats: list[str] = []
    flags: list[str] = []

    if not publisher.assessed:
        caveats.append(
            f"No assessment on file for {publisher.domain or 'this publisher'}. "
            "Unknown is not the same as disreputable, but nothing is known either way."
        )
        flags.append("unrated_source")

    weight = source_weight(publisher, direction=direction)
    if publisher.independence < 0.5:
        if direction == "positive":
            warnings.append(
                f"{publisher.name} has a direct interest in this being good news, so a "
                "positive claim from it is discounted."
            )
            flags.append("self_serving_positive")
        elif direction == "negative":
            caveats.append(
                f"{publisher.name} is speaking against its own interest, which makes the "
                "claim more credible than the same words from an outsider."
            )
            flags.append("against_interest")

    corr_factor = corroboration_factor(corroboration)
    if publisher.is_primary:
        # Corroboration is the wrong test for an authoritative record. A company's
        # filed accounts are not "single-sourced" because no newspaper repeated
        # them -- the filing *is* the fact, and demanding a second outlet would
        # penalise the best evidence in the system for being first-hand.
        corr_factor = 1.0
        caveats.append(
            "This is a primary record rather than a report about one, so being "
            "carried by only one outlet says nothing about it."
        )
    if corroboration.syndicated:
        warnings.append(
            f"Apparent breadth is an illusion: {corroboration.carrier_count} domains, "
            f"{corroboration.independent_count} origin."
        )
        flags.append("syndicated")
    elif corroboration.is_single_source:
        warnings.append("Only one independent source is carrying this.")
        flags.append("single_source")
    else:
        caveats.append(
            f"{corroboration.independent_count} independent origins are reporting this."
        )

    if corroboration.attributed_origin:
        caveats.append(
            f"The copy originates with {corroboration.attributed_origin}; the other "
            "carriers are republication."
        )

    if rhetoric.is_suspicious:
        labels = ", ".join(
            finding.label.lower() for finding in rhetoric.findings[:4]
        ) or "loaded framing"
        warnings.append(f"Written to provoke rather than inform: {labels}.")
        flags.append("manipulative_framing")
    for note in rhetoric.notes:
        caveats.append(note)

    checkable = [claim for claim in claims if claim.checkable]
    unsupported = [
        claim for claim in claims if claim.claim_type in ("rumour", "allegation", "prediction")
    ]
    claim_support = (
        sum(claim.support for claim in claims) / len(claims) if claims else 0.45
    )
    if claims and not checkable:
        warnings.append(
            "Nothing in this article can be checked against a primary source: every "
            "claim rests on an unnamed source, an inference, or a prediction."
        )
        flags.append("nothing_checkable")
    if unsupported:
        kinds = ", ".join(sorted({claim.claim_type for claim in unsupported}))
        warnings.append(f"Contains {kinds}, which cannot be verified as stated.")
        flags.append("unverifiable_claims")

    if claims and len(checkable) == len(claims) and all(
        claim.claim_type == "filed_record" for claim in claims
    ):
        caveats.append("Every claim here is recorded in a filing or register.")

    # --- the arithmetic -----------------------------------------------------
    credibility = weight * corr_factor * (1.0 - 0.6 * rhetoric.score) * (0.5 + 0.5 * claim_support)

    register, where = resolve_primary_source(source_category)
    # Speculation has no source to check against, whether or not the *topic* is one
    # that usually has a register. A rumour about earnings is still a rumour, and
    # routing it to the filings register because the subject is results would give
    # it the credibility of an audited account.
    speculation_only = bool(claims) and all(
        claim.claim_type in ("rumour", "prediction", "opinion", "inference", "allegation")
        for claim in claims
    )
    if register == "None exists" or speculation_only:
        caveats.append(
            "No primary source exists for what is being claimed -- there is nothing "
            "to check it against, which is not the same as it being false."
        )
        credibility = min(credibility, 0.3)
        flags.append("no_primary_source")
    elif register:
        caveats.append(f"Ultimate source, if it exists: {register} -- {where}")

    if materiality in ("material", "critical") and corroboration.is_single_source:
        flags.append("unconfirmed")
        warnings.append(
            "This is a material claim from a single source. Until something "
            "independent carries it, treat it as a lead, not a fact."
        )

    if rhetoric.score >= RHETORIC_HARD_CEILING:
        credibility = min(credibility, RHETORIC_HARD_CEILING)
        warnings.append(
            "Credibility capped: the presentation is doing so much of the work that the "
            "substance cannot be assessed on its own."
        )
        flags.append("capped_rhetoric")

    if (
        corroboration.is_single_source
        and not publisher.assessed
        and rhetoric.is_suspicious
    ) or (corroboration.is_single_source and corroboration.carrier_count <= 1 and not claims):
        credibility = min(credibility, UNCONFIRMED_CEILING)
        warnings.append(
            "Credibility capped: single-source, unrated publisher. This is the exact "
            "shape of a story that spreads because it is shocking, not because it is true."
        )
        flags.append("capped_unconfirmed")

    credibility = round(max(0.0, min(1.0, credibility)), 4)
    grade_name = _grade_for(credibility)

    if not corroboration.carrier_count and not publisher.assessed:
        caveats.append(
            "Nothing here has been checked against anything else. It is recorded "
            "because it was published, not because it is established."
        )

    return NewsAssessment(
        credibility=credibility,
        grade=grade_name,
        source_reliability=publisher.reliability,
        source_independence=publisher.independence,
        source_kind=publisher.kind,
        source_weight=weight,
        corroboration_factor=corr_factor,
        rhetoric_score=rhetoric.score,
        claim_support=claim_support,
        warnings=warnings,
        caveats=caveats,
        flags=list(dict.fromkeys(flags)),
        claims=claims,
    )


def _grade_for(credibility: float) -> str:
    if credibility >= 0.7:
        return "strong"
    if credibility >= 0.5:
        return "moderate"
    if credibility >= 0.35:
        return "mixed"
    if credibility >= 0.2:
        return "weak"
    return "unsupported"


def apply_to_sentiment(score: float | None, assessment: NewsAssessment | None) -> float | None:
    """Shrink a sentiment score by how much the article is worth.

    Shrinks towards zero rather than flipping sign: a weak article should stop
    moving the needle, not start pushing it the other way. That would be a
    different claim, and one we have no evidence for.
    """
    if score is None:
        return None
    if assessment is None:
        return score
    return max(-1.0, min(1.0, score * assessment.credibility))

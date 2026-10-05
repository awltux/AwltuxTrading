"""Adversarial news analysis via DeepSeek.

The classification step upstream asks a shallow question -- is this about the
company, how big is it, which way does it point. This step asks the hard one:
*what does this article actually establish?* It is the "investigation" half of the
brief, and it is deliberately separated from the scoring half.

What the model is trusted with:

* reading the item and restating its claims without the article's framing,
* naming the propaganda and informal-fallacy techniques it can see, from a closed
  taxonomy this module validates against,
* saying what a complete account would have included and what this left out,
* proposing the falsifier -- the checkable fact that would change the assessment,
* naming where the underlying fact would be *recorded*, if anywhere.

What it is not trusted with:

* any number that feeds a decision. Nothing here returns a credibility score; the
  arithmetic lives in :mod:`awltux.analysis.news_scepticism`, so a model that has
  been persuaded by the article cannot vote on how persuasive it was.

Every claim must carry a verbatim span from the supplied text. A claim without one
is dropped, which is the same discipline the filing extractor uses and for the same
reason: it makes fabrication useless rather than merely discouraged.
"""

from __future__ import annotations

import logging
from typing import Any

from awltux.analysis.news_scepticism import CLAIM_TYPES, PRIMARY_REGISTERS, Claim
from awltux.analysis.rhetoric import TECHNIQUE_LABELS, identify_technique
from awltux.config import Settings, get_settings
from awltux.llm.deepseek import (
    BudgetExceeded,
    DeepSeekClient,
    DeepSeekError,
    build_messages,
    model_for_purpose,
)
from awltux.llm.prompts import (
    NEWS_SCEPTIC_INSTRUCTION,
    NEWS_SCEPTIC_SYSTEM,
    prompt_fingerprint,
)

logger = logging.getLogger(__name__)

PURPOSE = "news_scepticism"

#: Attributions the model may return. Anything else is coerced to "none" rather
#: than stored, so an invented label cannot reach the credibility arithmetic.
VALID_ATTRIBUTIONS = frozenset(
    {
        "filing",
        "regulator",
        "court",
        "company_statement",
        "named_source",
        "official_data",
        "unnamed_source",
        "market_rumour",
        "analyst_note",
        "journalist_inference",
        "none",
    }
)

#: Maps the model's `checkable_against` onto the primary-source registers.
#: (``None exists`` is a legitimate answer: some claims have no source.)
CHECKABLE_MAP = {
    "financial_result": "financial_result",
    "guidance": "guidance",
    "regulatory_action": "regulatory_action",
    "legal_proceeding": "legal_proceeding",
    "ownership_change": "ownership_change",
    "macro_statistic": "macro_statistic",
    "market_data": "market_data",
    "product_or_contract": "product_or_contract",
    "analyst_opinion": "analyst_opinion",
    "rumour_or_speculation": "rumour_or_speculation",
    "none": None,
}

#: Above this many claims the schema is being padded rather than filled.
MAX_CLAIMS = 8


def _text(value: Any, limit: int = 600) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _span_in_document(span: str | None, document: str) -> bool:
    """Whether a quoted span really appears in what we sent.

    Compared on collapsed whitespace and case, because a model re-quoting a line
    may normalise spacing. Long spans are checked on their first eight words: a
    model that quotes a paragraph correctly but trims it should not be punished,
    while one that invents a sentence still fails.
    """
    if not span:
        return False
    haystack = " ".join(document.lower().split())
    needle = " ".join(span.lower().split())
    if needle in haystack:
        return True
    words = needle.split()
    if len(words) >= 8:
        return " ".join(words[:8]) in haystack
    return False


def normalise_claims(payload: Any, document: str) -> list[Claim]:
    """Validate model claims, dropping anything unquoted or malformed."""
    if not isinstance(payload, list):
        return []
    claims: list[Claim] = []
    seen: set[str] = set()

    for entry in payload[:MAX_CLAIMS]:
        if not isinstance(entry, dict):
            continue
        text = _text(entry.get("text"), 300)
        if not text:
            continue
        span = _text(entry.get("span"), 400)
        if not _span_in_document(span, document):
            # The claim is not in the item, or the quote was invented. Either way
            # it cannot be attributed to this article, so it is not counted.
            logger.debug("dropping claim with no verifiable span: %r", text[:80])
            continue

        claim_type = str(entry.get("claim_type") or "").strip().lower()
        if claim_type not in CLAIM_TYPES:
            claim_type = "reported_fact"

        attribution = str(entry.get("attribution") or "").strip().lower()
        if attribution not in VALID_ATTRIBUTIONS:
            attribution = "none"

        category = CHECKABLE_MAP.get(str(entry.get("checkable_against") or "").strip().lower())
        register, where = PRIMARY_REGISTERS.get(category, (None, None)) if category else (None, None)

        key = text.lower()
        if key in seen:
            continue
        seen.add(key)

        claims.append(
            Claim(
                text=text,
                claim_type=claim_type,
                attribution=attribution,
                span=span,
                primary_register=register,
                where_to_check=where,
            )
        )
    return claims


def normalise_techniques(payload: Any) -> list[dict[str, str]]:
    """Keep only techniques from the closed taxonomy, with their evidence."""
    if not isinstance(payload, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        name = identify_technique(str(entry.get("name") or ""))
        if name is None or name in seen:
            continue
        seen.add(name)
        out.append(
            {
                "technique": name,
                "label": TECHNIQUE_LABELS[name],
                "example": _text(entry.get("example"), 240) or "",
                "why": _text(entry.get("why"), 240) or "",
            }
        )
    return out


def normalise_analysis(payload: dict[str, Any], document: str) -> dict[str, Any] | None:
    """Coerce a model response into the stored shape."""
    if not isinstance(payload, dict):
        return None

    omissions = [
        text
        for text in (
            _text(item, 300) for item in (payload.get("omissions") or [])
        )
        if text
    ][:6]

    agenda = payload.get("agenda_hypothesis")
    if not isinstance(agenda, dict):
        agenda = {}

    headline_matches = payload.get("headline_matches_body")
    if not isinstance(headline_matches, bool):
        headline_matches = None

    return {
        "claims": normalise_claims(payload.get("claims"), document),
        "techniques": normalise_techniques(payload.get("techniques")),
        "headline_matches_body": headline_matches,
        "headline_overstates": _text(payload.get("headline_overstates")),
        "omissions": omissions,
        "who_benefits": _text(agenda.get("who_benefits_if_believed"), 240),
        "agenda_basis": _text(agenda.get("basis"), 300),
        "base_rate": _text(payload.get("base_rate"), 400),
        "what_would_change_my_mind": _text(payload.get("what_would_change_my_mind"), 400),
        "primary_source": _text(payload.get("primary_source"), 240),
        "scepticism_summary": _text(payload.get("scepticism_summary"), 900),
        "injection_suspected": bool(payload.get("injection_suspected")),
        "engine": None,
    }


def analyse_item(
    *,
    title: str,
    summary: str | None,
    source_name: str | None = None,
    publisher: dict[str, Any] | None = None,
    known_context: str | None = None,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Run the adversarial analysis on one item. ``None`` when it cannot run."""
    settings = settings or get_settings()
    client = client or DeepSeekClient(settings)
    if not client.configured:
        return None

    context = [f"Headline: {title}"]
    if summary:
        context.append(f"Text: {summary}")
    if source_name:
        context.append(f"Published by: {source_name}")
    if publisher:
        # The system's own assessment of the publisher is supplied as context, not
        # as a conclusion: the model is told what the reader would want to know.
        context.append(
            "Publisher assessment (the system's own, editorial judgement, not fact): "
            f"{publisher.get('name')} -- kind={publisher.get('kind')}, "
            f"biases={', '.join(publisher.get('biases') or []) or 'none recorded'}. "
            f"Basis: {publisher.get('basis')}"
        )
    if known_context:
        # Primary documents we already hold (a filing, an announcement).
        context.append(f"Primary documents held by the system:\n{known_context}")

    document = "\n".join(context)
    messages = build_messages(
        system=NEWS_SCEPTIC_SYSTEM,
        document=document,
        instruction=NEWS_SCEPTIC_INSTRUCTION,
    )

    try:
        completion = client.complete(
            purpose=PURPOSE,
            messages=messages,
            model=model_for_purpose(settings, PURPOSE),
            json_mode=True,
            max_tokens=2_500,
            prompt_hash=prompt_fingerprint(NEWS_SCEPTIC_SYSTEM),
        )
        payload = completion.json_object()
    except BudgetExceeded as exc:
        logger.warning("news scepticism paused: %s", exc)
        return None
    except DeepSeekError as exc:
        logger.debug("news scepticism failed for %r: %s", title[:70], exc)
        return None

    result = normalise_analysis(payload, document)
    if result is None:
        return None
    result["engine"] = f"deepseek:{completion.model}"
    result["llm_call_id"] = completion.llm_call_id
    return result


def build_analyser(settings: Settings | None = None):
    """Return an analyser callable, or ``None`` when unavailable.

    Matches :func:`awltux.llm.classify.build_classifier`: no key means the caller
    skips the step visibly rather than receiving a stub that always fails.
    """
    settings = settings or get_settings()
    client = DeepSeekClient(settings)
    if not client.configured:
        logger.info("DeepSeek is not configured, so news will not be sceptically analysed")
        return None
    return lambda **kwargs: analyse_item(client=client, settings=settings, **kwargs)

"""News classification via DeepSeek.

Turns a headline into the fields the sentiment model and the flash ticker need:
whether it concerns the company at all, how material it is, its direction, and a
sentiment score.

Design constraints this respects:

* **The classifier is optional.** :func:`build_classifier` returns ``None`` when
  no key is configured or the monthly budget is spent, and the callers treat that
  as "leave the item unclassified" rather than an error. An unclassified headline
  is still ingested and still visible; it simply carries less weight.
* **Conservative materiality.** Overstating importance is the main failure mode,
  so the prompt leans towards "mild" and the downstream ticker filters on the
  materiality level rather than showing everything.
* **Failures never lose the headline.** Any exception is swallowed into ``None``
  by the ingest layer, which keeps the article.
"""

from __future__ import annotations

import logging
from typing import Any

from awltux.config import Settings, get_settings
from awltux.llm.deepseek import (
    BudgetExceeded,
    DeepSeekClient,
    DeepSeekError,
    TruncatedResponse,
    build_messages,
    model_for_purpose,
)
from awltux.llm.prompts import (
    NEWS_CLASSIFICATION_INSTRUCTION,
    NEWS_CLASSIFICATION_SYSTEM,
    prompt_fingerprint,
)
from awltux.providers.news_rss import RawNewsItem

logger = logging.getLogger(__name__)

PURPOSE = "news_classification"

#: Materiality levels, ordered, for filtering and comparison.
MATERIALITY_ORDER = ["none", "mild", "moderate", "material", "critical"]

VALID_DIRECTIONS = {"positive", "negative", "neutral"}
VALID_HORIZONS = {"days", "weeks", "months", "years"}

#: Closed set of event types. These are not decoration: each one maps to the
#: register where the claim's primary source would be found, so an invented label
#: would silently break primary-source resolution.
VALID_EVENT_TYPES = {
    "earnings",
    "guidance",
    "m_and_a",
    "capital_raise",
    "regulatory",
    "legal",
    "management_change",
    "product",
    "macro",
    "analyst",
    "other",
}


def _clamp(value: Any, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return max(low, min(high, number))


def normalise_classification(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and coerce a model response into the stored fields.

    Anything unrecognised is dropped rather than stored, so a schema drift shows
    up as a missing field (visible, debuggable) instead of an invalid value
    silently reaching the risk gate.
    """
    if not isinstance(payload, dict):
        return None

    materiality = str(payload.get("materiality") or "").strip().lower()
    if materiality not in MATERIALITY_ORDER:
        materiality = "none"

    is_about = payload.get("is_about_this_company")
    if is_about is False:
        materiality = "none"

    relevance = _clamp(payload.get("relevance"), 0.0, 1.0)
    sentiment = _clamp(payload.get("sentiment_score"), -1.0, 1.0)

    direction = str(payload.get("direction") or "").strip().lower()
    if direction not in VALID_DIRECTIONS:
        direction = "neutral"

    horizon = str(payload.get("horizon") or "").strip().lower()
    if horizon not in VALID_HORIZONS:
        horizon = None  # type: ignore[assignment]

    event_type = str(payload.get("event_type") or "").strip().lower()
    if event_type not in VALID_EVENT_TYPES:
        event_type = "other"

    return {
        "materiality": materiality,
        "direction": direction,
        "horizon": horizon,
        "sentiment_score": sentiment,
        "relevance": relevance if relevance is not None else (0.2 if is_about is False else 0.5),
        "reasoning": payload.get("reasoning"),
        "event_type": event_type,
        # Kept, not just used to force materiality to "none". The ticker on a news
        # item usually comes from the feed it was fetched by rather than from the
        # article, so "this is not about that company" is what distinguishes a
        # connection from a passing mention -- see analysis/relevance.py.
        "is_about_this_company": is_about,
    }


def classify_headline(
    item: RawNewsItem,
    *,
    company_name: str,
    ticker: str,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Classify one headline. Returns ``None`` when it cannot be classified."""
    settings = settings or get_settings()
    client = client or DeepSeekClient(settings)
    if not client.configured:
        return None

    headline = item.title
    context = [
        f"Company: {company_name}",
        f"Ticker: {ticker}",
        f"Headline: {headline}",
    ]
    if item.summary:
        context.append(f"Summary: {item.summary[:800]}")
    if item.source:
        context.append(f"Source: {item.source}")
    if item.provider_sentiment is not None:
        context.append(f"Provider sentiment score: {item.provider_sentiment}")

    messages = build_messages(
        system=NEWS_CLASSIFICATION_SYSTEM,
        document="\n".join(context),
        instruction=NEWS_CLASSIFICATION_INSTRUCTION,
    )

    # Two budgets, and the first one has to cover more than the answer.
    #
    # Measured over 2,474 calls: the mean output was 235 tokens while the returned
    # *content* was about 120, and 165 of them (6.7%) spent the whole 500-token
    # budget and returned an empty body. The tokens went to reasoning that
    # `message.content` does not carry, so a budget sized to the JSON alone is
    # sized to the wrong thing -- which is why the log said "no content at all"
    # rather than "cut off mid-object".
    #
    # Raising it is close to free: `max_tokens` is a cap rather than a reservation,
    # so an ordinary call generates exactly what it did before. What it removes is
    # the second request for the 6.7% that ran out of room, and the handful that
    # ran out twice and were lost.
    budgets = list(
        dict.fromkeys(
            (
                settings.news.classify_max_tokens,
                settings.llm.max_output_tokens,
            )
        )
    )
    for attempt, budget in enumerate(budgets):
        try:
            completion = client.complete(
                purpose=PURPOSE,
                messages=messages,
                model=model_for_purpose(settings, PURPOSE),
                json_mode=True,
                max_tokens=budget,
                prompt_hash=prompt_fingerprint(NEWS_CLASSIFICATION_SYSTEM),
            )
            payload = completion.json_object()
        except BudgetExceeded as exc:
            # Expected and benign: stop classifying, keep ingesting.
            logger.warning("news classification paused: %s", exc)
            return None
        except TruncatedResponse as exc:
            logger.warning(
                "classification truncated for %r (attempt %d of %d at %d tokens): %s",
                headline[:70],
                attempt + 1,
                len(budgets),
                budget,
                exc,
            )
            if attempt == len(budgets) - 1:
                logger.warning("classification gave up on %r after a truncated retry", headline[:70])
                return None
            continue
        except DeepSeekError as exc:
            logger.debug("classification failed for %r: %s", headline[:70], exc)
            return None
        break

    result = normalise_classification(payload)
    if result is None:
        return None
    result["engine"] = f"deepseek:{completion.model}"
    result["llm_call_id"] = completion.llm_call_id
    return result


def build_classifier(settings: Settings | None = None):
    """Return a classifier callable for the ingest pipeline, or ``None``.

    Returning ``None`` (rather than a callable that always fails) lets the ingest
    layer skip the work entirely on an unconfigured install.
    """
    settings = settings or get_settings()
    client = DeepSeekClient(settings)
    if not client.configured:
        logger.info(
            "DeepSeek is not configured, so headlines will be stored unclassified"
        )
        return None

    def classifier(item: RawNewsItem, instrument: Any) -> dict[str, Any] | None:
        if instrument is None:
            return None
        return classify_headline(
            item,
            company_name=instrument.name,
            ticker=instrument.t212_ticker,
            client=client,
            settings=settings,
        )

    return classifier


def is_material_enough(materiality: str | None, *, threshold: str = "mild") -> bool:
    """Whether a headline clears the flash-ticker materiality threshold."""
    if materiality is None:
        return False
    try:
        return MATERIALITY_ORDER.index(materiality) >= MATERIALITY_ORDER.index(threshold)
    except ValueError:
        return False

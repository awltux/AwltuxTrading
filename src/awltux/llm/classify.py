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

from awltux.analysis.relevance import MATERIALITY_ORDER
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
    NEWS_BATCH_INSTRUCTION,
    NEWS_CLASSIFICATION_INSTRUCTION,
    NEWS_CLASSIFICATION_SYSTEM,
    NEWS_SECTOR_INSTRUCTION,
    prompt_fingerprint,
)
from awltux.numbers import as_finite_float
from awltux.providers.news_rss import RawNewsItem

logger = logging.getLogger(__name__)

PURPOSE = "news_classification"

#: A distinct purpose for the sector poll so its spend is separable in `llm_call` --
#: the two are the same task at the same price, but "how much of the news bill is
#: sector capture" is a question the operations page should be able to answer.
SECTOR_PURPOSE = "news_sector_classification"

#: Materiality levels, ordered, for filtering and comparison. Owned by
#: `analysis.relevance`, which is where the weights they compare against live -- this
#: module fills the field in, it does not decide what the levels are.

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

#: What a story's numbers are *of*. ``event_type`` says what kind of fact this is and
#: this says what the fact is about; they come apart on the pairs that broke the
#: same-event grouping, where one company's share moving and a broker changing its
#: target on it share an ``event_type``. Unlike ``VALID_EVENT_TYPES`` nothing routes a
#: claim by this, but the grouping compares it, so an invented label vetoes real joins.
#:
#: ``"none"`` is a stated answer -- the story is not about a number -- and is kept
#: distinct from an absent value, which means the field was never assessed.
VALID_METRICS = {
    "share_price",
    "price_target",
    "revenue",
    "earnings",
    "margin",
    "dividend",
    "valuation",
    "volume",
    "none",
}

#: Longest ``period`` or ``magnitude`` kept. Both are shown beside a headline rather
#: than parsed, so a value longer than a few words is the model writing a sentence
#: into a field that holds one -- and it would then be rendered as one.
_DETAIL_LIMIT = 32

#: What the model writes when it means "the story does not say". Treated as absent:
#: storing the literal string would put a fake value in a field the grouping compares,
#: where two stories would then agree on the word "unknown" and be joined by it.
_ABSENT = {"", "null", "none", "unknown", "n/a", "not stated", "unspecified"}


def _clamp(value: Any, low: float, high: float) -> float | None:
    number = as_finite_float(value)
    if number is None:
        return None
    return max(low, min(high, number))


def _short_text(value: Any) -> str | None:
    """A stated detail, or ``None``. Empty and "unknown" alike mean the story did not say."""
    text = str(value or "").strip()
    if text.lower() in _ABSENT:
        return None
    return text[:_DETAIL_LIMIT]


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

    metric = str(payload.get("metric") or "").strip().lower()
    if metric not in VALID_METRICS:
        metric = "none"

    return {
        "materiality": materiality,
        "direction": direction,
        "horizon": horizon,
        "sentiment_score": sentiment,
        "relevance": relevance if relevance is not None else (0.2 if is_about is False else 0.5),
        "reasoning": payload.get("reasoning"),
        "event_type": event_type,
        "metric": metric,
        "period": _short_text(payload.get("period")),
        "magnitude": _short_text(payload.get("magnitude")),
        # Kept, not just used to force materiality to "none". The ticker on a news
        # item usually comes from the feed it was fetched by rather than from the
        # article, so "this is not about that company" is what distinguishes a
        # connection from a passing mention -- see analysis/relevance.py.
        "is_about_this_company": is_about,
    }


def classify_headlines(
    items: list[RawNewsItem],
    *,
    company_name: str,
    ticker: str,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any] | None] | None:
    """Classify a batch of headlines in one call.

    Returns one entry per item, or **``None`` when the batch cannot be trusted** -- which
    is a different answer from a list of ``None``. The caller re-asks one at a time on
    ``None``, because the alternative is worse than the cost: a response that parses but
    is shorter than the list, or carries duplicate indices, pairs verdicts with the wrong
    headlines, and nothing downstream raises. `normalise_classification` drops keys it
    does not recognise, so an off-by-one batch is a perfectly valid-looking row with
    somebody else's judgement on it.
    """
    settings = settings or get_settings()
    client = client or DeepSeekClient(settings)
    if not client.configured:
        return None

    subject = f"Company: {company_name}\nTicker: {ticker}"
    lines = [subject, ""]
    for index, item in enumerate(items):
        lines.append(f"{index}. {item.title}")
        if item.summary:
            lines.append(f"   Summary: {item.summary[:400]}")
        if item.source:
            lines.append(f"   Source: {item.source}")
    document = "\n".join(lines)

    messages = build_messages(
        system=NEWS_CLASSIFICATION_SYSTEM,
        document=document,
        instruction=NEWS_BATCH_INSTRUCTION,
    )

    # Sized to the batch, because `max_tokens` is a cap rather than a reservation and the
    # single-headline budget would truncate an answer about twenty of them. Clamped to
    # the route's own ceiling so a large batch cannot ask for more than the model allows.
    per_item = settings.news.classify_max_tokens
    budget = min((len(items) + 1) * per_item, settings.llm.max_output_tokens)

    try:
        completion = client.complete(
            purpose=PURPOSE,
            messages=messages,
            model=model_for_purpose(settings, PURPOSE),
            json_mode=True,
            max_tokens=budget,
            prompt_hash=prompt_fingerprint(NEWS_CLASSIFICATION_SYSTEM + NEWS_BATCH_INSTRUCTION),
        )
        payload = completion.json_value()
    except BudgetExceeded as exc:
        logger.warning("news batch classification paused: %s", exc)
        return None
    except (TruncatedResponse, DeepSeekError) as exc:
        logger.warning("news batch classification of %d headlines failed: %s", len(items), exc)
        return None

    return _aligned_verdicts(payload, len(items), completion)


def _indexed_entries(payload: Any, expected: int) -> dict[int, Any] | None:
    """Key a batch response by the headline index each answer claims.

    ``None`` for anything that cannot be matched *totally* to the headlines: wrong
    length, an index that is not an integer, one out of range, one repeated, or a
    headline with no answer. Partial credit is not available here -- an unaligned batch
    is not half usable, it is unusable, because the answers that did arrive cannot be
    told apart from the ones that are merely misplaced.
    """
    if not isinstance(payload, list) or len(payload) != expected:
        logger.warning(
            "news batch returned %s entries for %d headlines; re-asking one at a time",
            len(payload) if isinstance(payload, list) else type(payload).__name__,
            expected,
        )
        return None

    by_index: dict[int, Any] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            return None
        index = entry.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        if not 0 <= index < expected or index in by_index:
            return None
        # `classification` when the model nested the answer, the entry itself when it
        # did not. `normalise_classification` ignores the keys it does not know, so the
        # un-nested form costs nothing but the `index`.
        by_index[index] = entry.get("classification", entry)

    if set(by_index) != set(range(expected)):
        return None
    return by_index


def _aligned_verdicts(payload: Any, expected: int, completion: Any) -> list[dict[str, Any] | None] | None:
    """Match a batch response to its headlines, or refuse it."""
    if isinstance(payload, dict):
        for key in ("classifications", "results", "items"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break

    by_index = _indexed_entries(payload, expected)
    if by_index is None:
        return None

    verdicts: list[dict[str, Any] | None] = []
    for index in range(expected):
        result = normalise_classification(by_index[index])
        if result is not None:
            result["engine"] = f"deepseek:{completion.model}"
            result["llm_call_id"] = completion.llm_call_id
        verdicts.append(result)
    return verdicts


def classify_headline(
    item: RawNewsItem,
    *,
    company_name: str,
    ticker: str,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Classify one headline for a company. ``None`` when it cannot be classified."""
    return _classify(
        item,
        subject=f"Company: {company_name}\nTicker: {ticker}",
        instruction=NEWS_CLASSIFICATION_INSTRUCTION,
        purpose=PURPOSE,
        client=client,
        settings=settings,
    )


def classify_for_sector(
    item: RawNewsItem,
    *,
    sector: str,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Classify one headline for an industry sector. ``None`` when it cannot be.

    A separate entry point rather than a flag on the one above, because the *subject
    line* is what the model answers against -- "Ticker: Energy" would be nonsense, and
    the sector is the only thing a sector feed's stories can be said to be about.
    """
    return _classify(
        item,
        subject=f"Industry sector: {sector}",
        instruction=NEWS_SECTOR_INSTRUCTION,
        purpose=SECTOR_PURPOSE,
        client=client,
        settings=settings,
    )


def _classify(
    item: RawNewsItem,
    *,
    subject: str,
    instruction: str,
    purpose: str,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Ask the model about one headline, and nothing else.

    The retry and budget handling lives here so the two subjects cannot drift: the
    500-token truncation that made 6.7% of calls return an empty body was fixed once,
    and a second copy of this loop is how that fix gets lost for half the calls.
    """
    settings = settings or get_settings()
    client = client or DeepSeekClient(settings)
    if not client.configured:
        return None

    headline = item.title
    context = [subject, f"Headline: {headline}"]
    if item.summary:
        context.append(f"Summary: {item.summary[:800]}")
    if item.source:
        context.append(f"Source: {item.source}")
    if item.provider_sentiment is not None:
        context.append(f"Provider sentiment score: {item.provider_sentiment}")

    messages = build_messages(
        system=NEWS_CLASSIFICATION_SYSTEM,
        document="\n".join(context),
        instruction=instruction,
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
                purpose=purpose,
                messages=messages,
                model=model_for_purpose(settings, purpose),
                json_mode=True,
                max_tokens=budget,
                # The instruction as well as the system: the two subjects share a system
                # prompt and differ only in the instruction, so hashing the system alone
                # would give a company call and a sector call the same cache key.
                prompt_hash=prompt_fingerprint(NEWS_CLASSIFICATION_SYSTEM + instruction),
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


class NewsBatchClassifier:
    """The ingest classifier, able to answer one headline or a batch of them.

    Callable, so every existing caller of the injected classifier keeps working: the
    batch is an extra capability (``many``) rather than a replacement signature. The
    ingest layer uses ``many`` when it is present and calls this per item when it is
    not, which is why the sector classifier needed no change at all.
    """

    #: Headlines per model call. The whole batch is one request, so this trades depth of
    #: attention for calls: measured, one call covering twenty headlines costs 1,988
    #: input tokens against 11,760 for twenty separate calls, for the same output volume.
    #: Twenty is where the input saving stops improving much (83% at 20, 84% at 40) and
    #: is small enough that a single misaligned answer loses twenty headlines rather
    #: than a hundred.
    BATCH = 20

    def __init__(self, settings: Settings, client: DeepSeekClient) -> None:
        self._settings = settings
        self._client = client

    def __call__(self, item: RawNewsItem, instrument: Any) -> dict[str, Any] | None:
        if instrument is None:
            return None
        return classify_headline(
            item,
            company_name=instrument.name,
            ticker=instrument.t212_ticker,
            client=self._client,
            settings=self._settings,
        )

    def many(
        self, items: list[RawNewsItem], instrument: Any
    ) -> list[dict[str, Any] | None]:
        """Verdicts for a run of headlines, one call per `BATCH` of them.

        **A batch that comes back unaligned is re-asked one at a time.** That is the
        whole safety property: `classify_headlines` refuses a response it cannot match
        to the headlines, and the fallback costs calls rather than filing a verdict
        against the wrong story. The cost is bounded -- at most one wasted batch call
        per `BATCH` headlines, on the rare occasion the model miscounts.
        """
        if instrument is None:
            return [None for _ in items]

        verdicts: list[dict[str, Any] | None] = []
        for start in range(0, len(items), self.BATCH):
            chunk = items[start : start + self.BATCH]
            if len(chunk) == 1:
                # Not worth a batch envelope, and the single form is the better-validated
                # of the two.
                verdicts.append(self(chunk[0], instrument))
                continue

            batch = classify_headlines(
                chunk,
                company_name=instrument.name,
                ticker=instrument.t212_ticker,
                client=self._client,
                settings=self._settings,
            )
            if batch is None:
                batch = [self(item, instrument) for item in chunk]
            verdicts.extend(batch)
        return verdicts


def build_classifier(settings: Settings | None = None) -> NewsBatchClassifier | None:
    """Return a classifier for the ingest pipeline, or ``None``.

    Returning ``None`` (rather than a callable that always fails) lets the ingest
    layer skip the work entirely on an unconfigured install.

    The returned object is callable for one headline and also carries ``many``, which is
    what lets `persist_items` ask about a batch at a time.
    """
    settings = settings or get_settings()
    client = DeepSeekClient(settings)
    if not client.configured:
        logger.info(
            "DeepSeek is not configured, so headlines will be stored unclassified"
        )
        return None

    return NewsBatchClassifier(settings, client)

def build_sector_classifier(settings: Settings | None = None):
    """A classifier for the sector poll, or ``None`` when there is no key.

    Its ``instrument`` argument is ignored: a sector feed's stories carry no ticker, so
    the subject comes off the item itself. The signature is the ingest layer's, which
    is why it is accepted and unused rather than the call site being special-cased.
    """
    settings = settings or get_settings()
    client = DeepSeekClient(settings)
    if not client.configured:
        logger.info(
            "DeepSeek is not configured, so sector headlines will be stored unclassified"
        )
        return None

    def classifier(item: RawNewsItem, _instrument: Any = None) -> dict[str, Any] | None:
        sector = (item.sectors or [None])[0]
        if not sector:
            return None
        return classify_for_sector(item, sector=sector, client=client, settings=settings)

    return classifier


def apply_classification(row: Any, updates: dict[str, Any] | None) -> bool:
    """Copy a classification onto a news row. Says whether there was one to copy.

    One place rather than one per caller. The ingest path and the relevance backfill
    each assigned these fields by hand, so a field added to
    :func:`normalise_classification` reached whichever of the two its author happened
    to be looking at -- and the backfill job exists precisely to fill in rows the
    ingest path missed, which is the worst pair of callers to let drift apart.

    ``relevance_reason`` is set only when the model supplied one. The backfill runs
    over rows that already carry a rule-derived reason, and overwriting that with
    ``None`` would trade an explanation for a blank.
    """
    if not updates:
        return False
    row.materiality = updates.get("materiality")
    row.direction = updates.get("direction")
    row.horizon = updates.get("horizon")
    row.sentiment_score = updates.get("sentiment_score")
    row.relevance = updates.get("relevance")
    row.engine = updates.get("engine")
    row.event_type = updates.get("event_type")
    row.metric = updates.get("metric")
    row.period = updates.get("period")
    row.magnitude = updates.get("magnitude")
    reasoning = updates.get("reasoning")
    if reasoning:
        row.relevance_reason = str(reasoning)[:1000]
    return True

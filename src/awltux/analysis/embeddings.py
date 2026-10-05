"""Embed headlines, and group the ones describing the same event.

The problem this solves is specific. A profit warning reaches this system five or
six times: the company's own release, a wire copy, two aggregator rewrites and a
broker note that repeats it. The existing corroboration layer counts *carriers* by
comparing word sets, which collapses syndication -- the same text pasted
everywhere -- and misses the commoner case, where the same event is reported in
genuinely different words. Word overlap says those are different stories. They are
not.

A vector compares meaning instead, so "Acme warns on profit" and "Acme cuts its
full-year outlook" land near each other while "Acme wins a contract" does not.

**Provider-agnostic by design.** Any OpenAI-compatible ``/embeddings`` endpoint
works, which covers a hosted service and a local Ollama alike. There is no key
requirement, because a local endpoint needs none -- so this is usable without
signing up for anything. Unset means the feature is off and the lexical comparison
is used, exactly as before, with no pretence that clustering happened.

**Thresholds are asymmetric on purpose.** Joining two different events tells a
reader one thing happened when two did. Missing a join shows two entries instead
of one. The second is a nuisance and the first is a lie, so ``same_event_threshold``
is set high, and every cluster carries its members so a wrong join is visible
rather than hidden.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from awltux.config import Settings, get_settings
from awltux.db import NewsEmbedding, NewsItem, session_scope
from awltux.providers.http import HttpClient, ProviderError

logger = logging.getLogger(__name__)

EMBEDDING_PROVIDER = "embeddings"


def embed_text(item: NewsItem) -> str:
    """The text a story is embedded from.

    Headline plus the feed's summary, truncated. The summary is what distinguishes
    "Acme wins a contract" from "Acme wins a contract worth 10m, sending the shares
    up 4%", so it carries real signal. The headline leads because it is the part
    every source writes for itself.
    """
    parts = [item.title or ""]
    if item.summary:
        parts.append(item.summary[:600])
    return "\n".join(part for part in parts if part).strip()


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class EmbeddingResult:
    vectors: list[list[float]] = field(default_factory=list)
    model: str = ""
    errors: list[str] = field(default_factory=list)


class EmbeddingClient:
    """Calls any OpenAI-compatible ``/embeddings`` endpoint."""

    def __init__(self, settings: Settings | None = None, *, http: HttpClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.config = self.settings.news.embeddings
        self._http = http

    @property
    def configured(self) -> bool:
        return self.config.configured

    def _client(self) -> HttpClient:
        if self._http is None:
            api_key = (
                self.config.api_key.get_secret_value() if self.config.api_key else None
            )
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
            self._http = HttpClient(
                EMBEDDING_PROVIDER,
                base_url=self.config.base_url.rstrip("/"),
                settings=self.settings,
                headers=headers,
            )
        return self._http

    def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed a batch. Returns what succeeded; failures are recorded, not raised.

        A batch the provider rejects does not lose the stories: the caller simply
        has no vector for them, which is the same state as before the job ran, and
        it retries next time.
        """
        result = EmbeddingResult(model=self.config.model)
        if not self.configured or not texts:
            return result

        try:
            response = self._client().request(
                "POST",
                "/embeddings",
                json_body={"model": self.config.model, "input": texts},
            )
            payload = response.json()
        except (ProviderError, ValueError) as exc:
            result.errors.append(str(exc))
            logger.warning("embedding request failed: %s", exc)
            return result

        rows = (payload or {}).get("data")
        if not isinstance(rows, list):
            result.errors.append("response contained no `data` array")
            return result

        # OpenAI returns objects with an `index`; sort by it rather than trusting
        # the order, because a mismatch would silently attach one story's vector to
        # another -- and the whole point is comparing the right things.
        ordered = sorted(rows, key=lambda row: row.get("index", 0))
        for row in ordered:
            vector = row.get("embedding")
            if isinstance(vector, list) and vector:
                result.vectors.append([float(value) for value in vector])
        if len(result.vectors) != len(texts):
            result.errors.append(
                f"asked for {len(texts)} vectors and got {len(result.vectors)}"
            )
            result.vectors = result.vectors[: len(texts)]
        return result

    def close(self) -> None:
        if self._http is not None:
            self._http.close()


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


def numpy():
    """numpy, imported lazily so the module is usable without the maths stack."""
    import numpy as np

    return np


def store_vectors(
    item_ids: list[int], texts: list[str], vectors: list[list[float]], model: str
) -> int:
    """Persist vectors for the stories they were produced for, in order.

    Takes ids rather than ORM rows: it opens its own session, and passing detached
    instances across a session boundary is how one thread's stale state silently
    overwrites another's.
    """
    from sqlalchemy import select

    if not vectors:
        return 0
    np = numpy()
    written = 0
    with session_scope() as session:
        for item_id, text, vector in zip(item_ids, texts, vectors, strict=False):
            array = np.asarray(vector, dtype=np.float32)
            row = session.execute(
                select(NewsEmbedding).where(NewsEmbedding.news_item_id == item_id)
            ).scalar_one_or_none()
            if row is None:
                row = NewsEmbedding(news_item_id=item_id)
                session.add(row)
            row.model = model
            row.dim = int(array.shape[0])
            row.vector = array.tobytes()
            row.text_hash = text_fingerprint(text)
            written += 1
    return written


def vectors_for(item_ids: list[int], model: str | None = None) -> dict[int, Any]:
    """Vectors for a set of stories, keyed by story id.

    Only rows carrying the requested model are returned. Comparing vectors from two
    different models produces a number that looks like a similarity and means
    nothing, which is worse than having no number at all.
    """
    from sqlalchemy import select

    if not item_ids:
        return {}
    np = numpy()
    with session_scope() as session:
        statement = select(NewsEmbedding).where(NewsEmbedding.news_item_id.in_(item_ids))
        if model:
            statement = statement.where(NewsEmbedding.model == model)
        rows = session.execute(statement).scalars().all()
        return {
            row.news_item_id: np.frombuffer(row.vector, dtype=np.float32) for row in rows
        }


# --------------------------------------------------------------------------- #
# clustering
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Event:
    """One happening, and the stories that reported it."""

    #: Story ids, best first. The first is the representative.
    members: list[int] = field(default_factory=list)
    #: Why these were grouped: the weakest similarity that holds the group together.
    similarity: float | None = None

    @property
    def size(self) -> int:
        return len(self.members)

    def as_dict(self) -> dict[str, Any]:
        return {"members": list(self.members), "size": self.size, "similarity": self.similarity}


def cluster(
    item_ids: list[int],
    vectors: dict[int, Any],
    *,
    threshold: float,
) -> list[Event]:
    """Group stories describing the same event, best-first order preserved.

    Greedy nearest-neighbour agglomeration: each story joins the first existing
    cluster whose representative it is close enough to, and starts its own if it is
    not close to any. That is ``O(n * k)`` in the number of clusters rather than
    ``O(n^2)`` pairwise, which matters because the window is hundreds of stories.

    Comparing against the **representative** rather than the cluster mean is
    deliberate: a mean drifts as members are added, so a cluster can slowly absorb
    stories that resemble its average and not each other. Anchoring on one story
    keeps membership explainable -- every member is one comparison away from
    something a reader can be shown.

    Order is preserved: callers pass stories best-first, so each cluster's first
    member is the best story in it.
    """
    np = numpy()
    events: list[Event] = []
    anchors: list[Any] = []

    for item_id in item_ids:
        vector = vectors.get(item_id)
        if vector is None:
            # No vector means no basis for comparison, so the story stands alone
            # rather than being merged on a guess.
            events.append(Event(members=[item_id]))
            anchors.append(None)
            continue

        best_index = -1
        best_score = 0.0
        for index, anchor in enumerate(anchors):
            if anchor is None:
                continue
            score = _cosine(np, vector, anchor)
            if score >= threshold and score > best_score:
                best_index, best_score = index, score

        if best_index >= 0:
            events[best_index].members.append(item_id)
            held = events[best_index].similarity
            events[best_index].similarity = (
                best_score if held is None else min(held, best_score)
            )
        else:
            events.append(Event(members=[item_id], similarity=None))
            anchors.append(vector)

    return events


def _cosine(np, left, right) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(left, right) / denominator)


def cluster_items(
    items: list[NewsItem], *, settings: Settings | None = None
) -> tuple[list[Event], str | None]:
    """Cluster stories that have vectors, and say whether it could be done.

    Returns the events and an optional note explaining why clustering did not
    happen. The note matters: "one entry per event" and "one entry per story" look
    identical in a UI, and only one of them means the feature is working.
    """
    settings = settings or get_settings()
    config = settings.news.embeddings
    if not config.configured:
        return [Event(members=[item.id]) for item in items], "embeddings are not configured"

    vectors = vectors_for([item.id for item in items], model=config.model)
    if not vectors:
        return (
            [Event(members=[item.id]) for item in items],
            "no stored vectors for these stories yet",
        )
    return (
        cluster([item.id for item in items], vectors, threshold=config.same_event_threshold),
        None,
    )

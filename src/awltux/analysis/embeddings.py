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

**Two questions, two tools.** "Is this the same kind of thing?" is exact: the story's
event type, direction and metric are stated by the classifier that already read it, and
:class:`Identity` compares them. "Is this the same instance of it?" is fuzzy: two wire
copies of one profit warning share no words, and only a vector can see that. The
similarity is therefore a tie-break inside a set the keys have already agreed on, not
the decision itself -- which is what it was when the threshold was the whole rule, and
what made 65% of its joins contradict the story's own stored direction or event type.

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
    #: Set when the failure cannot succeed on a retry -- a rejected credential, a
    #: model the account cannot use. Without it a run asks sixteen more times for
    #: something that will never work, against a rate-limited endpoint.
    fatal: bool = False


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
            headers = None
            # The scheme is configuration rather than an assumption. Fal.ai wants
            # `Authorization: Key <key>` and an OpenAI client whose own `api_key` is
            # a placeholder -- so a client that assumes `Bearer` gets a 401 against a
            # perfectly good key, which reads as "the key is wrong".
            credential = self.config.credential(self.settings.env)
            if credential:
                scheme = self.config.auth_scheme.strip()
                headers = {
                    "Authorization": f"{scheme} {credential}".strip() if scheme else credential
                }
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
        except ProviderError as exc:
            # A rejected credential is the likeliest first-run failure for a hosted
            # endpoint, and it is indistinguishable from a broken one unless the
            # message says which header was sent with which scheme. It never prints
            # the key.
            text = str(exc)
            if "401" in text or "403" in text:
                scheme = self.config.auth_scheme.strip() or "(none)"
                result.fatal = True
                result.errors.append(
                    f"the endpoint rejected our credential (sent as `Authorization: "
                    f"{scheme} ...`). Check the key, and that this account can use "
                    f"`{self.config.model}`. Upstream said: {text[:200]}"
                )
                # Fal's OpenRouter passthrough answers this sentence when the key is
                # fine but the organization behind it has no access to *that model*.
                # The wording matters and was wrong: it used to say that trying a
                # different model name could not change it, because "four model names,
                # including two that do not exist on OpenRouter, all return it
                # identically". Measured 2026-10-07 and both halves of that were false:
                # a name that does not exist returns `400 Model ... does not exist`, so
                # names *do* reach resolution, and every non-`openai/*` embedding model
                # answers `200` on the same URL with the same key. The refusal is a
                # per-model entitlement, so the model is exactly what to change -- and
                # the old sentence pointed the operator away from the fix.
                if "organization tied to the api key" in text.lower():
                    result.errors.append(
                        "the provider says the organization behind the key has no "
                        "access to this model. The key is accepted and then refused "
                        "upstream, so this is a per-model entitlement rather than a "
                        "request problem -- changing `news.embeddings.model` is the "
                        "fix, and the `openai/*` family is the one refused here."
                    )
            else:
                result.errors.append(text)
            logger.warning("embedding request failed: %s", str(exc)[:200])
            return result
        except ValueError as exc:
            result.errors.append(str(exc))
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


#: The fields :class:`Identity` compares. Named here so the dataclass and the
#: comparison cannot drift apart.
IDENTITY_FIELDS = ("event_type", "direction", "metric")


@dataclass(frozen=True, slots=True)
class Identity:
    """What a story says it is about, in the fields a comparison can be exact on.

    A vector measures how much two texts *resemble* each other, and on real stories
    that is not the same as describing one event. Measured 2026-10-07 over the 1,000
    embedded stories at the threshold then in force: of the 672 joins the similarity
    made, **439 (65%) disagreed with their group on the stored event type or the stored
    direction** -- "Canadian National Railway stock falls Wednesday" grouped with the
    same headline saying "rises", and one Claritev margin story grouped with an insider
    share sale, a buyback and a DOJ probe. A cosine cannot see any of that, because
    all four are the same company on the same day written in the same register.

    These fields can, and the model already fills them in on the call that classifies
    every story -- so the filter costs nothing to run and its decision is exact rather
    than a threshold.

    **An absent value is not a disagreement.** Rows classified before these fields
    existed carry ``None``, and the backfill is rationed, so reading "no metric
    recorded" as "a different metric" would veto every join until it caught up -- a
    worse failure than the one this exists to fix, and an invisible one.
    """

    event_type: str | None = None
    direction: str | None = None
    metric: str | None = None

    def conflicts(self, other: Identity) -> tuple[str, ...]:
        """The fields where both stories state a value and the values differ."""
        differing = []
        for name in IDENTITY_FIELDS:
            mine = getattr(self, name)
            theirs = getattr(other, name)
            if mine and theirs and mine != theirs:
                differing.append(name)
        return tuple(differing)

    def agrees(self, other: Identity) -> bool:
        return not self.conflicts(other)


def identity_of(item: Any) -> Identity:
    """The identity keys of a story row, or of anything shaped like one."""
    return Identity(
        event_type=getattr(item, "event_type", None),
        direction=getattr(item, "direction", None),
        metric=getattr(item, "metric", None),
    )


def cluster(
    item_ids: list[int],
    vectors: dict[int, Any],
    *,
    threshold: float,
    identities: dict[int, Identity] | None = None,
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

    ``identities`` adds the exact half of the comparison: a story may only join a
    cluster whose anchor it does not contradict on the keys it states. The similarity
    is then a tie-break inside a set the model has already agreed is the same kind of
    thing, which is the only question a cosine is equipped to answer. Passed as a
    mapping rather than read off rows so that the rule stays testable on its own.

    Order is preserved: callers pass stories best-first, so each cluster's first
    member is the best story in it.
    """
    np = numpy()
    identities = identities or {}
    events: list[Event] = []
    #: The anchor of each event, paired with the keys it stated. One list rather than
    #: two kept in step by hand: they are appended in the same two places, and a third
    #: place that appended only one of them would mis-attribute every event after it.
    anchors: list[tuple[Any, Identity] | None] = []

    for item_id in item_ids:
        vector = vectors.get(item_id)
        mine = identities.get(item_id) or Identity()
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
            anchored_vector, anchored_keys = anchor
            if not mine.agrees(anchored_keys):
                continue
            score = _cosine(np, vector, anchored_vector)
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
            anchors.append((vector, mine))

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
        cluster(
            [item.id for item in items],
            vectors,
            threshold=config.same_event_threshold,
            identities={item.id: identity_of(item) for item in items},
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class EventGroup:
    """One event as a *page* shows it: a lead story and the other reports of it.

    The clustering above speaks in story ids, which is right for the banner's JSON and
    wrong for a template that has to render a headline, a publisher and a grade. This
    is the same grouping with the rows attached, and it exists so the banner and the
    news list on an instrument page cannot disagree about what one event is.
    """

    lead: NewsItem
    others: tuple[NewsItem, ...] = ()
    #: The weakest similarity holding the group together, or ``None`` for a singleton.
    similarity: float | None = None

    @property
    def size(self) -> int:
        return 1 + len(self.others)

    @property
    def members(self) -> tuple[NewsItem, ...]:
        return (self.lead, *self.others)


def group_events(
    items: list[NewsItem], *, settings: Settings | None = None
) -> tuple[list[EventGroup], str | None]:
    """``items`` as one entry per event, in the order given.

    Order is the caller's, and the lead of each group is the first of its members, so a
    caller that passes stories best-first gets the best story leading each event --
    which is the same guarantee :func:`cluster` documents, moved up to rows.
    """
    events, note = cluster_items(items, settings=settings)
    by_id = {item.id: item for item in items}

    groups: list[EventGroup] = []
    for event in events:
        members = [by_id[item_id] for item_id in event.members if item_id in by_id]
        if not members:
            continue
        groups.append(
            EventGroup(lead=members[0], others=tuple(members[1:]), similarity=event.similarity)
        )
    return groups, note

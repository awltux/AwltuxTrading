"""News flash ticker: JSON, an HTML partial, and a Server-Sent Events stream.

SSE is implemented by polling the database rather than by an in-process pub/sub
bus. That is a deliberate choice: news rows are written by scheduler threads,
and a database cursor is the only handoff that is correct across threads,
survives a restart, and cannot deliver an event for a row that was rolled back.
At a few hundred rows a day the cost is negligible.

**The stream carries that cursor rather than the stories.** One function, `_events`,
decides what the ticker shows -- ranked, floored by `news.ticker_min_materiality`, and
grouped into events -- and the browser re-fetches its output when the stream says the
banner has gone stale. It used to push the stories themselves, which gave the client a
second renderer and a second answer to "what belongs in the ticker"; the live one showed
every relevant story, one entry per story, and displaced the curated entries.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import desc, func, select
from starlette.concurrency import run_in_threadpool

from awltux.analysis.relevance import (
    assess,
    materiality_floor_values,
    priority,
)
from awltux.config import Settings, get_settings
from awltux.db import NewsAnalysis, NewsItem, session_scope, utcnow
from awltux.timezones import format_moment

router = APIRouter(tags=["news"])

#: How often the stream looks for new rows.
POLL_SECONDS = 2.0
#: Stop a stream that nobody is reading, so a dead client cannot leak a task.
MAX_IDLE_SECONDS = 900.0

#: How many recent stories to score before taking the top ``limit``.
#:
#: Priority is computed in Python -- it mixes materiality, the scepticism weight
#: and an age decay -- so it cannot be an ``ORDER BY``. Scoring a bounded recent
#: window and sorting that is the honest alternative to loading the whole table;
#: the window is far larger than any banner needs, so nothing that could plausibly
#: rank is excluded.
RANKING_WINDOW = 600

#: Stories scanned when finding the other reports of one event. Smaller than the
#: ranking window because the question is only "who else covered this", and the
#: answer is always recent.
EVENT_WINDOW = 300


def _targets(item: NewsItem) -> list[dict[str, str]]:
    """Everything this story can be attached to, with the kind of each."""
    out: list[dict[str, str]] = []
    for ticker in item.tickers or []:
        out.append({"kind": "instrument", "id": str(ticker)})
    for sector in item.sectors or []:
        out.append({"kind": "sector", "id": str(sector)})
    return out


def _score(item: NewsItem, analysis: NewsAnalysis | None) -> tuple[float, dict[str, object]]:
    """Priority, and every input that produced it."""
    return priority(
        materiality=item.materiality,
        credibility=analysis.credibility if analysis else None,
        published_at=item.published_at,
    )


def _relevance(item: NewsItem) -> dict[str, object]:
    """The stored verdict, explained.

    The verdict is read from the row rather than recomputed, because one input
    cannot be recovered here: whether the classifier judged the article *about*
    the company. A ticker on an item normally comes from the feed it was fetched
    by, so recomputing without that fact would call a passing mention relevant --
    which is the opposite of what was stored.

    The structural rule is still evaluated, but only to explain a verdict whose
    reason is missing, and it says which half held rather than contradicting the
    stored answer. When the rule itself changes, rows keep their old verdicts until
    the ``news_relevance`` job re-assesses them -- which is what that job is for.
    """
    structural = assess(
        tickers=item.tickers,
        sectors=item.sectors,
        direction=item.direction,
        materiality=item.materiality,
    )
    return {
        "relevant": item.relevant,
        "has_target": structural.has_target,
        "directional": structural.directional,
        "reason": item.relevance_reason or structural.reason,
        "targets": structural.targets,
    }


def _serialise(item: NewsItem, analysis: NewsAnalysis | None = None) -> dict[str, object]:
    score, inputs = _score(item, analysis)
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        # The permanent, local page: everything above, plus which instruments this
        # concerns and why, without leaving the app or hitting a paywall.
        "local_url": f"/news/{item.id}",
        "source": item.source,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "tickers": item.tickers or [],
        "sectors": item.sectors or [],
        "targets": _targets(item),
        "materiality": item.materiality,
        "direction": item.direction,
        "horizon": item.horizon,
        "sentiment": item.sentiment_score,
        "engine": item.engine,
        "event_type": item.event_type,
        # Whether this is a claim about a share price at all, and the sentence
        # that says which half of the rule held. ``None`` is "not assessed".
        "relevant": item.relevant,
        "relevance": _relevance(item),
        "relevance_reason": item.relevance_reason,
        "priority": round(score, 6),
        "priority_inputs": inputs,
        # The sceptical read travels with the item so a consumer of the API cannot
        # take the headline without also being told what it is worth. Omitting it
        # would make the flash feed the one place a raw claim reached the UI.
        "scepticism": _serialise_analysis(analysis) if analysis else None,
    }


def _serialise_analysis(analysis: NewsAnalysis) -> dict[str, object]:
    return {
        "credibility": analysis.credibility,
        "grade": analysis.evidence_grade,
        "flags": analysis.flags or [],
        "source": analysis.source_name,
        "source_kind": analysis.source_kind,
        "source_biases": analysis.source_biases or [],
        "independent_sources": analysis.independent_sources,
        "carriers": analysis.carrier_count,
        "warnings": analysis.warnings or [],
        "summary": analysis.scepticism_summary,
    }


def format_sse(data: object, *, event: str | None = None, event_id: int | None = None) -> bytes:
    """Encode one Server-Sent Event frame.

    Extracted so the wire format is a pure function that can be tested without
    holding a streaming response open -- an SSE endpoint is otherwise awkward to
    cover, and the framing is exactly the part a browser depends on.
    """
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, default=str)}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def format_comment(text: str) -> bytes:
    """A comment frame, used for keepalives so proxies do not close the stream."""
    return f": {text}\n\n".encode()


def _primary(items: list[NewsItem]) -> dict[int, tuple[str, str]]:
    """Each story's primary subject, as ``(type, id)``. See `primary_subject`."""
    from awltux.analysis.news_analysis import primary_subject

    out: dict[int, tuple[str, str]] = {}
    for item in items:
        subject = primary_subject(item)
        if subject is not None:
            out[item.id] = (subject.type, subject.id)
    return out


def _pick(rows, wanted: dict[int, tuple[str, str]]) -> dict[int, NewsAnalysis]:
    """The row for each story's primary subject, from every subject's rows."""
    chosen: dict[int, NewsAnalysis] = {}
    for row in rows:
        if wanted.get(row.news_item_id) == (row.subject_type, row.subject_id):
            chosen[row.news_item_id] = row
    return chosen


def _analyses_in(session, items: list[NewsItem]) -> dict[int, NewsAnalysis]:
    """One appraisal per story: its primary subject's.

    The list pages key on the story and have no subject of their own, so they show the
    same appraisal the sentiment weighting uses. An instrument or sector page passes
    the subject it is about and gets that one -- see `queries.instrument_detail`.
    """
    if not items:
        return {}
    wanted = _primary(items)
    if not wanted:
        return {}
    rows = session.execute(
        select(NewsAnalysis).where(NewsAnalysis.news_item_id.in_(list(wanted)))
    ).scalars().all()
    return _pick(rows, wanted)


def _visible_to_the_banner(settings: Settings) -> tuple[object, ...]:
    """The conditions a story must meet to be shown by the ticker.

    One definition with three callers: the ranking that picks the entries, the stream's
    refresh check, and the sibling window on the news page -- which promises to agree with
    the banner about what one event is, so it has to draw from the same population. A story
    that can never be displayed must not wake every open tab, and a story the banner shows
    must not be missing from its own event.

    **Assessed only.** ``relevant IS NULL`` means nothing has judged the story: it is not
    known to be a claim about a price, and it carries no materiality to clear the floor
    with either. Showing it would be the banner guessing, and the classification output is
    the thing this ticker exists to curate with.

    **Not dismissed.** No filter can know which of four `critical` write-ups of one
    acquisition the reader has already read, so the reader says so (see `dismiss_news_item`).
    """
    return (
        NewsItem.relevant.is_(True),
        NewsItem.dismissed_at.is_(None),
        NewsItem.materiality.in_(
            materiality_floor_values(settings.news.ticker_min_materiality)
        ),
    )


def _ranked(
    session, *, window: int, limit: int, settings: Settings | None = None
) -> list[tuple[NewsItem, NewsAnalysis | None]]:
    """Recent stories a reader should see, best first.

    Eligibility is `_visible_to_the_banner`: assessed, and at or above
    ``news.ticker_min_materiality``. Most of the corpus fails the second test -- measured
    2026-10-08, 12,125 of 26,301 stored stories are classified ``none`` -- and until this
    was wired the banner had no floor at all, despite its own label reading
    "materiality-filtered headlines likely to move a price".

    Then two things order and thin what is left:

    * **Priority**, the product of materiality, credibility and recency.
    * **A repeated headline collapses to its best copy.** A wire story carried by two
      outlets is two rows with two URLs, so ``url_hash`` cannot see it; ``title_key`` can.
      The embedding grouping in `_events` catches the semantic case afterwards, but it needs
      a stored vector and most stories do not have one yet.
    """
    settings = settings or get_settings()
    rows = list(
        session.execute(
            select(NewsItem)
            .where(*_visible_to_the_banner(settings))
            .order_by(desc(NewsItem.id))
            .limit(window)
        ).scalars().all()
    )
    analyses = _analyses_in(session, list(rows))

    def sort_key(row: NewsItem) -> tuple[float, int]:
        score, _ = _score(row, analyses.get(row.id))
        return (score, row.id or 0)

    rows.sort(key=sort_key, reverse=True)

    # Collapse by headline, keeping the first -- which, after the sort, is the best copy of
    # it. Rows written before migration `0018` carry no key and pass through uncollapsed:
    # they cannot be matched, and inventing a key here would be a second answer to "is this
    # the same story" when the database already keeps one.
    seen: set[str] = set()
    kept: list[NewsItem] = []
    for row in rows:
        if row.title_key:
            if row.title_key in seen:
                continue
            seen.add(row.title_key)
        kept.append(row)
    return [(row, analyses.get(row.id)) for row in kept[:limit]]


def _events(
    session, *, window: int, limit: int
) -> tuple[list[dict[str, object]], str | None]:
    """The banner's entries: one per event, best first.

    Ranking happens per *story*, then stories describing the same event collapse
    into one entry led by the best of them. Doing it in that order matters: the
    alternative -- cluster first, rank the clusters -- would let a well-covered
    minor event outrank a poorly-covered important one, which is exactly backwards.

    Where embeddings are not configured nothing collapses and ``note`` says so.
    "One entry per event" and "one entry per story" look identical on screen, and
    only one of them means the feature works.
    """
    from awltux.analysis.embeddings import cluster_items

    ranked = _ranked(session, window=window, limit=limit)
    items = [row for row, _ in ranked]
    analyses = {row.id: analysis for row, analysis in ranked if analysis}

    events, note = cluster_items(items)
    by_id = {row.id: row for row in items}

    payload: list[dict[str, object]] = []
    for event in events:
        members = [by_id[mid] for mid in event.members if mid in by_id]
        if not members:
            continue
        lead = members[0]
        entry = _serialise(lead, analyses.get(lead.id))
        entry["event"] = {
            "size": event.size,
            "similarity": event.similarity,
            "members": [
                {
                    "id": member.id,
                    "title": member.title,
                    "source": member.source,
                    "url": member.url,
                    "local_url": f"/news/{member.id}",
                    "published_at": (
                        member.published_at.isoformat() if member.published_at else None
                    ),
                }
                for member in members[1:]
            ],
        }
        payload.append(entry)
    return payload, note


def _refresh_due(cursor: int, settings: Settings | None = None) -> int | None:
    """The newest story that could change the banner, or ``None`` if none could.

    **A cursor, not a payload.** This used to return the stories themselves, which left
    the client to decide what the banner should show -- and it decided differently: every
    relevant story, in id order, one entry per story, up to forty of them displacing the
    fifteen the server had curated. Saying only *that* something changed lets `_events`
    render the update exactly as it renders the first paint.

    The same materiality floor `_ranked` applies is applied here, so a story that could
    never be displayed does not wake every open tab to re-render identical HTML.
    """
    settings = settings or get_settings()
    with session_scope() as session:
        return session.execute(
            select(func.max(NewsItem.id))
            .where(NewsItem.id > cursor)
            .where(*_visible_to_the_banner(settings))
        ).scalar()


@router.get("/api/news", summary="Recent news items")
def recent_news(
    limit: int = Query(100, ge=1, le=1000),
    ticker: str | None = None,
    materiality: str | None = None,
) -> dict[str, object]:
    from awltux.web import queries

    with session_scope() as session:
        if ticker is None and materiality is None:
            # The default feed is the flash banner: one entry per event, best first.
            items, clustering = _events(session, window=RANKING_WINDOW, limit=limit)
        else:
            rows = queries.recent_news(
                session, limit=limit, min_materiality=materiality, ticker=ticker
            )
            analyses = _analyses_in(session, list(rows))
            items = [_serialise(row, analyses.get(row.id)) for row in rows]
            clustering = "filtered view: one entry per story"
        return {
            "items": items,
            "count": len(items),
            "ordered_by": "priority" if ticker is None and materiality is None else "recency",
            "clustering": clustering,
        }


@router.get("/partials/news-ticker", response_class=HTMLResponse, include_in_schema=False)
def news_ticker_partial(request: Request, limit: int = Query(15, ge=1, le=50)) -> HTMLResponse:
    """HTMX-friendly fragment, used as the no-JS fallback for the ticker."""
    from awltux.web.templating import templates

    with session_scope() as session:
        entries, clustering = _events(session, window=RANKING_WINDOW, limit=limit)
    return templates.TemplateResponse(
        request,
        "partials/news_ticker.html",
        {"entries": entries, "clustering": clustering},
    )


@router.post("/api/news/{item_id}/dismiss", summary="Stop showing a story in the ticker")
def dismiss_news_item(item_id: int) -> dict[str, object]:
    """Hide one story from the flash ticker.

    **Global rather than per-browser.** This dashboard has no login and one reader, so a
    dismissal kept in the browser would come back in a second browser or after clearing
    site data -- not what "dismiss" means to the person clicking it.

    **A timestamp, not a delete.** The row stays; it is still a headline that was ingested
    and classified, and it still carries one event for the grouping and the scepticism work
    to use. This records only that the reader does not want it in the banner. Dismissing is
    therefore reversible by clearing the column, and nothing has to be re-ingested.
    """
    with session_scope() as session:
        item = session.get(NewsItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="no such news item")
        item.dismissed_at = utcnow()
    return {"dismissed": True, "id": item_id}


@router.get("/news/{item_id}", response_class=HTMLResponse, include_in_schema=False)
def news_item_page(request: Request, item_id: int) -> HTMLResponse:
    """One story, on a page of our own.

    The flash banner links here rather than straight out to the publisher, because
    the published article is the *input* to an assessment, not the assessment. What
    a reader needs is what the system concluded and why: which instruments this
    concerns, which way it points, what the scepticism layer made of the source,
    and where the original is.
    """
    from awltux.web.templating import templates

    with session_scope() as session:
        item = session.get(NewsItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="no such news item")
        # The story's *primary* subject, not `.limit(1)`. That worked only while an
        # item had exactly one appraisal; a story naming two instruments now has two,
        # and an unordered LIMIT 1 would show a different one run to run.
        analysis = _analyses_in(session, [item]).get(item.id)
        payload = _serialise(item, analysis)

        # The instruments named by this story, resolved to their stored rows so the
        # page can link to them and show what they are. An unknown ticker is shown
        # as unknown rather than hidden: it is still what the story was attached to.
        from awltux.db import Instrument

        wanted = list(item.tickers or [])
        instruments = (
            {
                row.t212_ticker: row
                for row in session.execute(
                    select(Instrument).where(Instrument.t212_ticker.in_(wanted))
                ).scalars().all()
            }
            if wanted
            else {}
        )

        # Which other stories cover the same event. Drawn from the same population the
        # banner draws from, so the page and the banner agree about what the event is -- a
        # page that said "3 stories" while the banner showed the entry alone would be worse
        # than either.
        from awltux.analysis.embeddings import cluster_items

        window_rows = list(
            session.execute(
                select(NewsItem)
                .where(*_visible_to_the_banner(get_settings()))
                .order_by(desc(NewsItem.id))
                .limit(EVENT_WINDOW)
            ).scalars().all()
        )
        events, clustering_note = cluster_items(window_rows)
        siblings: list[NewsItem] = []
        for event in events:
            if item_id in event.members:
                by_id_local = {row.id: row for row in window_rows}
                siblings = [
                    by_id_local[mid]
                    for mid in event.members
                    if mid != item_id and mid in by_id_local
                ]
                break

    return templates.TemplateResponse(
        request,
        "news_item.html",
        {
            "item": item,
            "analysis": analysis,
            "payload": payload,
            "instruments": instruments,
            "published": format_moment(item.published_at) if item.published_at else None,
            "siblings": siblings,
            "clustering_note": clustering_note,
        },
    )


@router.get("/api/news/stream", summary="Live news stream (Server-Sent Events)")
async def news_stream(
    request: Request,
    last_event_id: int = Query(0, ge=0, alias="last_id"),
) -> StreamingResponse:
    """Tell the ticker when the banner it is already showing has gone stale.

    **It carries a cursor, not the stories.** The ticker is rendered by :func:`_events`;
    sending stories here would mean a second renderer and a second answer to "what belongs
    in the ticker", which is exactly what went wrong -- the live path appended every
    relevant story, one entry per story, and pushed the curated entries off the end of the
    track. The client now re-fetches the fragment, so what it shows cannot disagree with
    what the server would have sent on first paint.

    Honours ``Last-Event-ID`` so a reconnecting client neither replays a refresh it has
    already applied nor misses one: a refresh is idempotent, and the cursor is the id of
    the newest story considered.
    """
    header_cursor = request.headers.get("last-event-id")
    if header_cursor and header_cursor.isdigit():
        last_event_id = max(last_event_id, int(header_cursor))

    async def event_source() -> AsyncIterator[bytes]:
        cursor = last_event_id

        # Tell proxies not to buffer, then keep the connection warm. The first paint is
        # already in the DOM, so there is no history to replay.
        yield format_comment("connected")

        idle = 0.0
        while idle < MAX_IDLE_SECONDS:
            if await request.is_disconnected():
                break
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS

            try:
                newest = await run_in_threadpool(_refresh_due, cursor)
            except Exception as exc:  # pragma: no cover - transient DB error
                yield format_sse(
                    {"error": str(exc), "at": dt.datetime.now(dt.UTC).isoformat()},
                    event="error",
                )
                continue

            if newest is not None and newest > cursor:
                idle = 0.0
                cursor = newest
                yield format_sse({"latest_id": newest}, event="refresh", event_id=newest)
            else:
                # A comment frame keeps intermediaries from closing the stream.
                yield format_comment("keepalive")

        yield format_sse({}, event="close")

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

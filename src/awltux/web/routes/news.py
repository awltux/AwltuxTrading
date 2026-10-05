"""News flash ticker: JSON, an HTML partial, and a Server-Sent Events stream.

SSE is implemented by polling the database rather than by an in-process pub/sub
bus. That is a deliberate choice: news rows are written by scheduler threads,
and a database cursor is the only handoff that is correct across threads,
survives a restart, and cannot deliver an event for a row that was rolled back.
At a few hundred rows a day the cost is negligible.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import desc, select
from starlette.concurrency import run_in_threadpool

from awltux.db import NewsItem, session_scope

router = APIRouter(tags=["news"])

#: How often the stream looks for new rows.
POLL_SECONDS = 2.0
#: Stop a stream that nobody is reading, so a dead client cannot leak a task.
MAX_IDLE_SECONDS = 900.0


def _serialise(item: NewsItem) -> dict[str, object]:
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "tickers": item.tickers or [],
        "sectors": item.sectors or [],
        "materiality": item.materiality,
        "direction": item.direction,
        "horizon": item.horizon,
        "sentiment": item.sentiment_score,
        "engine": item.engine,
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


def _fetch_since(item_id: int, limit: int) -> list[dict[str, object]]:
    with session_scope() as session:
        rows = session.execute(
            select(NewsItem)
            .where(NewsItem.id > item_id)
            .order_by(NewsItem.id)
            .limit(limit)
        ).scalars().all()
        return [_serialise(row) for row in rows]


def _fetch_latest(limit: int) -> list[dict[str, object]]:
    with session_scope() as session:
        rows = session.execute(
            select(NewsItem).order_by(desc(NewsItem.id)).limit(limit)
        ).scalars().all()
        return [_serialise(row) for row in reversed(rows)]


@router.get("/api/news", summary="Recent news items")
def recent_news(
    limit: int = Query(100, ge=1, le=1000),
    ticker: str | None = None,
    materiality: str | None = None,
) -> dict[str, object]:
    from awltux.web import queries

    with session_scope() as session:
        items = queries.recent_news(
            session, limit=limit, min_materiality=materiality, ticker=ticker
        )
    return {"items": [_serialise(item) for item in items], "count": len(items)}


@router.get("/partials/news-ticker", response_class=HTMLResponse, include_in_schema=False)
def news_ticker_partial(request: Request, limit: int = Query(15, ge=1, le=50)) -> HTMLResponse:
    """HTMX-friendly fragment, used as the no-JS fallback for the ticker."""
    from awltux.web.templating import templates

    with session_scope() as session:
        items = (
            session.execute(select(NewsItem).order_by(desc(NewsItem.id)).limit(limit))
            .scalars()
            .all()
        )
    return templates.TemplateResponse(
        request, "partials/news_ticker.html", {"items": items}
    )


@router.get("/api/news/stream", summary="Live news stream (Server-Sent Events)")
async def news_stream(
    request: Request,
    last_event_id: int = Query(0, ge=0, alias="last_id"),
    replay: int = Query(20, ge=0, le=200),
) -> StreamingResponse:
    """Push new material news items as they are ingested.

    Honours ``Last-Event-ID`` so a reconnecting client resumes without gaps or
    duplicates.
    """
    header_cursor = request.headers.get("last-event-id")
    if header_cursor and header_cursor.isdigit():
        last_event_id = max(last_event_id, int(header_cursor))

    async def event_source() -> AsyncIterator[bytes]:
        cursor = last_event_id

        # Prime the client with recent history so the ticker is never empty.
        if cursor == 0 and replay:
            history = await run_in_threadpool(_fetch_latest, replay)
            for item in history:
                cursor = max(cursor, int(item["id"]))  # type: ignore[arg-type]
                yield format_sse(item, event="news", event_id=int(item["id"]))  # type: ignore[arg-type]

        # Tell proxies not to buffer, then keep the connection warm.
        yield format_comment("connected")

        idle = 0.0
        while idle < MAX_IDLE_SECONDS:
            if await request.is_disconnected():
                break
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS

            try:
                items = await run_in_threadpool(_fetch_since, cursor, 50)
            except Exception as exc:  # pragma: no cover - transient DB error
                yield format_sse(
                    {"error": str(exc), "at": dt.datetime.now(dt.UTC).isoformat()},
                    event="error",
                )
                continue

            if items:
                idle = 0.0
                for item in items:
                    cursor = max(cursor, int(item["id"]))  # type: ignore[arg-type]
                    yield format_sse(item, event="news", event_id=int(item["id"]))  # type: ignore[arg-type]
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

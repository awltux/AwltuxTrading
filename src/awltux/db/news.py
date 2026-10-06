"""Reading news by instrument, in SQL rather than in Python.

**The bug this module exists to fix.** Three places asked "what news does this
instrument have?" the same wrong way: take the newest N rows *across the whole
universe*, then filter them by ticker in Python. The limit is applied before the
filter, so the window is global and the filter only ever sees a slice of it.

Measured on the live database, with 6,555 stored items:

| caller | window | result |
|---|---|---|
| the instrument page | newest 40 globally | **131 of 153** instruments with news showed nothing |
| the decision engine | newest 400 of 1,470 in-window | **47 of 135** tickers it saw no news for at all |

The engine one is the serious one. `news_materiality` and the sentiment answers were
being computed as though those instruments had no news, because the news never
reached the window. It also degrades in the direction opposite to the obvious one:
as more news is ingested, each instrument's *share* of a fixed global window falls,
so the per-instrument view empties out rather than growing.

**Why the filter is in SQL.** The tickers are a JSON array column, so membership is
`json_each` on SQLite. That is not portable to Postgres, and the old comment worried
about exactly that -- but `Settings.database_url` is `sqlite+pysqlite:///` by
construction, so the portability was never real and the correctness was. If the
database ever moves, this is the one function to rewrite
(`jsonb_array_elements_text(tickers) ? :ticker`).

**No index will help.** `json_each` cannot use one, so this is a scan of `news_item`.
At 6.5k rows that is sub-millisecond; the fix if it ever matters is a join table
(`news_item_ticker`), not an index. Recorded in ``TODO.md``.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import Select, func, literal, select
from sqlalchemy.orm import Session

from awltux.db.models import NewsItem


def mentions_ticker(ticker: str):
    """SQL predicate: this news item names the given instrument.

    Exposed because callers compose it into their own statements -- an ordering, an
    extra filter -- and duplicating the subquery is how the three wrong copies
    started.
    """
    tagged = func.json_each(NewsItem.tickers).table_valued("value")
    return (
        select(literal(1))
        .select_from(tagged)
        .where(tagged.c.value == ticker)
        .exists()
    )


def news_for_ticker(
    session: Session,
    ticker: str,
    *,
    since: dt.datetime | None = None,
    materiality: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[NewsItem], int]:
    """One page of an instrument's news, newest first, and how many there are.

    Returns the total as well as the page because a pager that cannot say how many
    pages exist is not a pager. Counted with the same predicate as the page, so the
    two cannot disagree.

    ``offset`` is safe here in a way it was not before: the row set is now defined
    entirely in SQL, so page two starts where page one stopped. Offsetting the old
    query would have paged through a different slice each time.
    """
    conditions: list[Any] = [mentions_ticker(ticker)]
    if since is not None:
        conditions.append(NewsItem.published_at >= since)
    if materiality:
        conditions.append(NewsItem.materiality == materiality)

    total = session.execute(
        select(func.count()).select_from(NewsItem).where(*conditions)
    ).scalar_one()

    statement: Select = (
        select(NewsItem)
        .where(*conditions)
        .order_by(NewsItem.published_at.desc(), NewsItem.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(statement).scalars().all()), int(total)


def appraisals_for(session: Session, items: list[NewsItem]) -> dict[int, Any]:
    """The sceptical appraisals for exactly these stories, keyed by news item id.

    Keyed so the template pairs them without a second lookup, and scoped to the page
    so a page of 25 does not load appraisals for a thousand.
    """
    from awltux.db.models import NewsAnalysis

    if not items:
        return {}
    rows = session.execute(
        select(NewsAnalysis).where(NewsAnalysis.news_item_id.in_([item.id for item in items]))
    ).scalars().all()
    return {row.news_item_id: row for row in rows}

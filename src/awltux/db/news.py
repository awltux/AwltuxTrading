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

from awltux.db.models import NewsAnalysis, NewsItem


def _mentions(column: Any, value: str):
    """SQL predicate: this news item's JSON array ``column`` contains ``value``.

    One expression for both join keys, because the instrument page and the sector page
    were two copies of the same wrong window and would have become two copies of this.
    """
    tagged = func.json_each(column).table_valued("value")
    return (
        select(literal(1))
        .select_from(tagged)
        .where(tagged.c.value == value)
        .exists()
    )


def mentions_ticker(ticker: str):
    """SQL predicate: this news item names the given instrument.

    Exposed because callers compose it into their own statements -- an ordering, an
    extra filter -- and duplicating the subquery is how the three wrong copies
    started.
    """
    return _mentions(NewsItem.tickers, ticker)


def mentions_sector(sector: str):
    """SQL predicate: this news item concerns the given sector directly.

    *Directly* is the whole of it: ``NewsItem.sectors`` is set by the feed grouping
    (``ingest.news.gather_for_sector``) and never derived from the tickers, so this is the
    same predicate ``analysis.news_analysis.subjects_of`` uses when it decides a story has
    a sector appraisal. A sector page that matched on its constituents' tickers instead
    would show stories that carry no sector verdict, and its appraisals would be missing.
    """
    return _mentions(NewsItem.sectors, sector)


def news_for_sector(
    session: Session,
    sector: str,
    *,
    since: dt.datetime | None = None,
    relevant_only: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[NewsItem], int]:
    """One page of a sector's news, newest first, and how many there are.

    The same window bug as :func:`news_for_ticker`, measured on the same corpus: the sector
    page took the newest 400 stories *globally* and kept the ones naming the sector in
    Python, so a sector with thousands of relevant stories showed whatever fell inside the
    global slice. Counting here rather than in the caller keeps the total and the page on
    one predicate, and ``relevant_only`` behaves as it does above.
    """
    conditions: list[Any] = [mentions_sector(sector)]
    if relevant_only:
        conditions.append(NewsItem.relevant.is_(True))
    if since is not None:
        conditions.append(NewsItem.published_at >= since)

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


def primary_credibility():
    """Scalar subquery: the credibility of the appraisal :func:`primary_subject` names.

    ``analysis.news_analysis.subjects_of`` orders a story's subjects instruments-first and
    then by id, and ``primary_subject`` takes the first; ``analysis/sentiment.py`` reduces
    the same way in Python when it weights a story. This is that rule as SQL, and it exists
    because the news page has to *order* by the resulting priority across the whole corpus,
    which it cannot do by loading the rows: measured 2026-10-09, hydrating all 27,895
    stories takes 2.0 seconds and their 6,974 appraisals another 0.8 -- per page click.

    **A third expression of one rule is a real cost**, so it is written once, here, beside
    the other composable news predicate, and it is tested against ``primary_subject``
    directly rather than assumed to agree
    (``tests/test_news_listing.py::TestThePriorityOrdering``). ``news_item_id`` is indexed,
    so the correlated lookup is a seek per row rather than a scan -- measured 2026-10-09,
    the ordering it serves runs over all 27,895 stored stories in 0.32s.

    ``DISTINCT ON`` would say this in one line and SQLite does not have it, which is the
    same portability limit `mentions_ticker` records above.
    """
    from awltux.analysis.news_analysis import INSTRUMENT

    return (
        select(NewsAnalysis.credibility)
        .where(NewsAnalysis.news_item_id == NewsItem.id)
        .order_by(
            (NewsAnalysis.subject_type != INSTRUMENT),
            NewsAnalysis.subject_id,
        )
        .limit(1)
        .scalar_subquery()
    )


def news_for_ticker(
    session: Session,
    ticker: str,
    *,
    since: dt.datetime | None = None,
    materiality: str | None = None,
    relevant_only: bool = False,
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

    ``relevant_only`` is off by default and is the caller's decision rather than this
    function's. A research digest wants every story with a direct concern entry,
    because "the classifier read this as a mention rather than a connection" is itself
    something the reader of a deep-dive should be told; the news page wants the
    relevant ones. Defaulting to the wider set is deliberate: a caller that has not
    thought about it cannot then lose rows without saying so.
    """
    conditions: list[Any] = [mentions_ticker(ticker)]
    if relevant_only:
        conditions.append(NewsItem.relevant.is_(True))
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


def appraisals_for(
    session: Session, items: list[NewsItem], *, subject: tuple[str, str] | None = None
) -> dict[int, Any]:
    """The sceptical appraisals for exactly these stories, keyed by news item id.

    Keyed so the template pairs them without a second lookup, and scoped to the page
    so a page of 25 does not load appraisals for a thousand.

    ``subject`` is ``(type, id)`` when the caller knows what the stories are being read
    *for* -- an instrument page passes its ticker, a sector page its sector, and those
    are the appraisals it must show. Without it each story falls back to its primary
    subject, which is the right answer only for a list that has no subject of its own.
    """
    from awltux.analysis.news_analysis import primary_subject
    from awltux.db.models import NewsAnalysis

    if not items:
        return {}
    statement = select(NewsAnalysis).where(
        NewsAnalysis.news_item_id.in_([item.id for item in items])
    )
    if subject is not None:
        statement = statement.where(
            NewsAnalysis.subject_type == subject[0], NewsAnalysis.subject_id == subject[1]
        )
    rows = session.execute(statement).scalars().all()

    if subject is not None:
        return {row.news_item_id: row for row in rows}

    # No subject given: pick each story's primary one. A story can have several
    # appraisals and they differ only where the subject's held-ness differs, but the
    # choice still has to be deterministic rather than whichever row came back first.
    wanted = {
        item.id: primary_subject(item) for item in items
    }
    chosen: dict[int, Any] = {}
    for row in rows:
        primary = wanted.get(row.news_item_id)
        if primary is not None and (row.subject_type, row.subject_id) == (primary.type, primary.id):
            chosen[row.news_item_id] = row
    return chosen

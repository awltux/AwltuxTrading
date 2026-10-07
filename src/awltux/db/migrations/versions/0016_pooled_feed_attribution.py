"""Undo the ticker accumulation on symbol-addressed news feeds.

Revision ID: 0016_pooled_feed_attribution
Revises: 0015_finnhub_attribution
Create Date: 2026-10-07

A Yahoo `?s=` feed returns a *pool* of articles rather than that symbol's own news, so
the same announcement arrived from many instruments' feeds and `_merge_duplicate`
appended a ticker for each one. Measured 2026-10-07: 21 `yahoo_rss` rows carried more
than three tickers and 49 more than one.

    id=6572  tickers=8  feed=s=PET.L
      "Fidelity Asian Values Plc - Transaction in Own Shares"
      PETl_EQ, ARRl_EQ, PMPl_EQ, AVGl_EQ, SCFl_EQ, PENl_EQ, BGFDl_EQ, CYNl_EQ

None of those is the subject and neither is the feed's own symbol.

**Truncating to the first ticker restores exactly what was lost.** `persist_items`
creates a row with the tickers the *storing* feed supplied, and `_merge_target` only ever
appends -- so element zero is the one attribution that came from a feed actually fetching
the article, and everything after it is an artefact of another feed being asked.

Nothing is invented here: the values are already on the row, and this takes the first.
Whether that first ticker is *right* is a separate question -- the feed is demonstrably
loose, and these rows are already `relevant=False` -- but it is the one the ingestion
actually established, and the remaining looseness is recorded in `TODO.md` rather than
papered over by deleting the attribution entirely.

Guarded on the column being JSON, since a row may store either a list or a string.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0016_pooled_feed_attribution"
down_revision = "0015_finnhub_attribution"
branch_labels = None
depends_on = None

_TABLE = "news_item"
#: Must match `ingest.news.SYMBOL_POOLED_SOURCES`. Written out rather than imported: a
#: migration that changes meaning when that set changes is a migration that re-runs
#: differently on two databases.
_SOURCE = "yahoo_rss"


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT id, tickers FROM {_TABLE} WHERE source = :source"),  # noqa: S608
        {"source": _SOURCE},
    ).all()
    for row_id, raw in rows:
        tickers = raw if isinstance(raw, list) else _loads(raw)
        if not isinstance(tickers, list) or len(tickers) <= 1:
            continue
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET tickers = :tickers WHERE id = :id"),  # noqa: S608
            {"id": row_id, "tickers": json.dumps(tickers[:1])},
        )


def _loads(raw: object) -> object:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "ignore")
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def downgrade() -> None:
    """Not reversible: the dropped tickers were never evidence of anything, and there is
    no record of which feed contributed which. Re-deriving them would re-create exactly
    the attribution this removes."""

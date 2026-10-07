"""Drop ticker attributions that were accumulated from unrelated requests.

Revision ID: 0015_finnhub_attribution
Revises: 0014_outflow_signs
Create Date: 2026-10-07

One row: `news_item.id = 2102`, source `finnhub` -- "New York Times: Beware Of Expensive
Legacy Stocks With No Moat" -- carrying **60** tickers, none of them the New York Times.

The cause was the cache key ignoring the query string, fixed in the previous revision.
`HttpClient` built its cache key from the URL path alone, so `/company-news` -- cached
for 15 minutes -- returned the same payload for every symbol searched, and
`_merge_duplicate` appended each requested symbol to the same stored row as it arrived.
Sixty requests, sixty tickers, one article.

**Why the attribution is cleared rather than narrowed.** Finnhub's `company-news`
response carries no symbol -- `raw` holds only `{"id": 142612913, "category": "company"}`,
and the ticker on the item was always the one that *asked*. So there is no way to recover
which company the article belongs to, and leaving one is a guess wearing the clothes of
evidence. An empty list is the truthful state: the story is in the store, and nothing
claims it is about any particular instrument. 131 sector-tagged stories are already in
that state.

Keyed on the signature and not on the id, because an id is a fact about this database
and the corruption is a fact about the row's shape. Anything above three tickers from
this source is an artefact of merging: Finnhub does not return multi-company articles.

Guarded on the column being JSON, since a row may store either a list or a string.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0015_finnhub_attribution"
down_revision = "0014_outflow_signs"
branch_labels = None
depends_on = None

_TABLE = "news_item"
_SOURCE = "finnhub"
#: Above this, the tickers cannot have come from one response.
IMPLAUSIBLE_TICKERS = 3


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT id, tickers FROM {_TABLE} WHERE source = :source"),  # noqa: S608
        {"source": _SOURCE},
    ).all()
    for row_id, raw in rows:
        tickers = raw if isinstance(raw, list) else _loads(raw)
        if not isinstance(tickers, list) or len(tickers) <= IMPLAUSIBLE_TICKERS:
            continue
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET tickers = :tickers WHERE id = :id"),  # noqa: S608
            {"id": row_id, "tickers": json.dumps([])},
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
    """Not reversible: the tickers were wrong, and there is no record of which were
    right. Re-inventing them would be re-creating the corruption this removes."""

"""Give a news item a `publisher`, so the source shown is the writer and not the feed.

Revision ID: 0023_news_publisher
Revises: 0022_sector_price_index
Create Date: 2026-10-09

Asked for directly: *"I think the Source should be the real source, not the feed."*

`news_item.source` is the pipe -- `google_news`, `yahoo_rss`, `finnhub` -- and the new
column is the writer. They come apart almost everywhere. Measured 2026-10-09 over the
27,895 stored stories: **26,591 (95.3%) carry a `news.google.com` URL**, which is a
redirect into the Google News reader, so no amount of reading the URL names the author.
The masthead Google News appends to the headline does: every one of those 26,591 titles
ends in " - Publisher", 59.9% of them name-like, 22.8% a single word and 12.3% a bare
domain. The remaining 1,304 rows store the publisher's own address and need no parse.

**Why it is stored rather than derived at render time.** A parse per row would answer the
column and nothing else. The page also *filters* and *sorts* by it, and a filter has to
happen in SQL. Storing it also means the value is fixed at the moment the row is written,
when the feed's own context is still known, rather than re-derived from a headline a
later change to the parser could read differently.

Existing rows are backfilled by `awltux news-publishers`, which also re-rates the stored
appraisals -- see that command for why the second half matters.

Additive and inspection-guarded, because `0001` builds the schema from the models: on a
fresh database the column is already there and this must be a no-op rather than a
duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_news_publisher"
down_revision = "0022_sector_price_index"
branch_labels = None
depends_on = None

_TABLE = "news_item"
_COLUMN = "publisher"
_INDEX = f"ix_{_TABLE}_{_COLUMN}"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.String(length=96), nullable=True))
        batch.create_index(_INDEX, [_COLUMN])


def downgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(_INDEX)
        batch.drop_column(_COLUMN)

"""Give a news item a `dismissed_at`, so the reader can stop a story being shown.

Revision ID: 0019_news_dismissed
Revises: 0018_news_title_key
Create Date: 2026-10-08

The ticker is curated by materiality and collapsed by headline, and still shows the same
acquisition from four outlets when the classifier graded all four `critical`. No filter can
know which of those the reader has already read, so the reader has to be able to say so.

**Not a delete.** The row stays: it is still a headline the system ingested and classified,
it is still a carrier of one event, and the calibration and scepticism work reads it. This
records one decision -- do not put this in the banner -- and nothing else.

A timestamp rather than a boolean, because "when did I stop wanting this" is answerable and
"was it dismissed" is not.

Additive and inspection-guarded, because `0001` builds the schema from the models: on a
fresh database the column is already there and this must be a no-op rather than a
duplicate-column error. Existing rows are NULL, which is "not dismissed" -- the behaviour
they already had.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_news_dismissed"
down_revision = "0018_news_title_key"
branch_labels = None
depends_on = None

_TABLE = "news_item"
_COLUMN = "dismissed_at"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)

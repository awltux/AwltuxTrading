"""Give a news item a `title_key`, so a syndicated headline is judged once.

Revision ID: 0018_news_title_key
Revises: 0017_marketaux_rotation
Create Date: 2026-10-07

Measured 2026-10-07: `news_classification` was 21,343 of 24,544 model calls, roughly one
per stored story, and 1,570 of the 26,008 stored headlines (6.0%) were the *same headline
under a different masthead* -- a wire story Google News returned once as "… - Yahoo
Finance" and again as "… - GlobeNewswire". Different URLs, so `url_hash` cannot see them
and each copy bought its own call.

The key is the headline with that " - Publisher" suffix stripped, digested. A shorter
prefix of the raw title was rejected: it matches 3,028 (11.6%) but also merges genuinely
different stories that share an opening, so a verdict would be copied onto a row it was
never reached about. Stripping the suffix and matching the whole headline finds about
half as many and every one checked was the same story.

Deliberately **not unique**: two real stories can share a headline, and this column only
answers "have we judged a headline like this already". Nothing about what may be stored
changes.

Additive and inspection-guarded, because `0001` builds the schema from the models: on a
fresh database the column is already there and this must be a no-op rather than a
duplicate-column error. Existing rows are left NULL -- there is nothing to backfill
*from*, and a NULL key simply means "no reuse candidate", which is the old behaviour.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_news_title_key"
down_revision = "0017_marketaux_rotation"
branch_labels = None
depends_on = None

_TABLE = "news_item"
_COLUMN = "title_key"
_INDEX = f"ix_{_TABLE}_{_COLUMN}"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.String(length=64), nullable=True))
        batch.create_index(_INDEX, [_COLUMN])


def downgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(_INDEX)
        batch.drop_column(_COLUMN)

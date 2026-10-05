"""Store whether a news story is a claim about a share price, and why.

Revision ID: 0005_news_relevance
Revises: 0004_news_scepticism
Create Date: 2026-10-05

The flash banner showed every stored headline in arrival order. Two columns make
it possible to show only the ones that touch a holding, and to say why:

* ``relevant`` -- names an instrument or sector *and* carries a direction. Nullable
  because "not assessed" is a different state from "assessed as irrelevant", and
  only one of those is worth chasing.
* ``relevance_reason`` -- the classifier's one-sentence justification, which every
  classification call has always produced and the ingest layer has always
  discarded at this boundary.

Existing rows are left NULL rather than back-filled in the migration. Deciding
relevance for 5,800 stored stories is a judgement, not a schema change, and it
belongs in the ``news_relevance`` job where it can be rationed, logged and
re-run -- not in a migration that runs unattended on container start.

**Why it is guarded.** ``0001`` builds the schema from the models, so a fresh
database already has both columns. Applying this revision to such a database must
be a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_news_relevance"
down_revision = "0004_news_scepticism"
branch_labels = None
depends_on = None

_TABLE = "news_item"
_RELEVANT_INDEX = "ix_news_item_relevant"


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def _indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)
        if index["name"]
    }


def upgrade() -> None:
    present = _columns()
    if "relevant" not in present or "relevance_reason" not in present:
        with op.batch_alter_table(_TABLE) as batch:
            if "relevant" not in present:
                batch.add_column(sa.Column("relevant", sa.Boolean(), nullable=True))
            if "relevance_reason" not in present:
                batch.add_column(sa.Column("relevance_reason", sa.Text(), nullable=True))
    if _RELEVANT_INDEX not in _indexes():
        op.create_index(_RELEVANT_INDEX, _TABLE, ["relevant"])


def downgrade() -> None:
    if _RELEVANT_INDEX in _indexes():
        op.drop_index(_RELEVANT_INDEX, table_name=_TABLE)
    present = _columns()
    with op.batch_alter_table(_TABLE) as batch:
        if "relevance_reason" in present:
            batch.drop_column("relevance_reason")
        if "relevant" in present:
            batch.drop_column("relevant")

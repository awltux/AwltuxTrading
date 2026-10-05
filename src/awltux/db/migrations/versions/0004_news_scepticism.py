"""Add the sceptical news analysis.

Revision ID: 0004_news_scepticism
Revises: 0003_exchange_fk
Create Date: 2026-10-05

Stores, per news item, the appraisal that decides how much weight it gets: who
published it and whether they have a stake, what presentational techniques it
uses, how many *independent* sources carry it, what it actually claims, what it
leaves out, where the underlying fact would be recorded, and the credibility
weight the arithmetic arrived at.

This is what turns the sentiment model's assumption -- "a headline is a
measurement" -- into something closer to "a headline is a claim by an interested
party, worth this much".

**Why it is guarded.** ``0001`` builds the schema from the models, so a fresh
database already contains ``news_analysis``. Applying the revision to such a
database must be a no-op, not a duplicate-table error; an existing database gets
the table for the first time.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from awltux.db.models import NewsAnalysis

revision = "0004_news_scepticism"
down_revision = "0003_exchange_fk"
branch_labels = None
depends_on = None

_TABLE = "news_analysis"
_ITEM_TABLE = "news_item"
_EVENT_TYPE_INDEX = "ix_news_item_event_type"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table)
        if index["name"]
    }


def upgrade() -> None:
    # The classifier has always produced an event type and the ingest layer has
    # always thrown it away, which left primary-source resolution with nothing to
    # route on. It is persisted now.
    if "event_type" not in _columns(_ITEM_TABLE):
        with op.batch_alter_table(_ITEM_TABLE) as batch:
            batch.add_column(sa.Column("event_type", sa.String(24), nullable=True))
    if _EVENT_TYPE_INDEX not in _indexes(_ITEM_TABLE):
        op.create_index(_EVENT_TYPE_INDEX, _ITEM_TABLE, ["event_type"])

    if _TABLE in _tables():
        return
    NewsAnalysis.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)

    if _EVENT_TYPE_INDEX in _indexes(_ITEM_TABLE):
        op.drop_index(_EVENT_TYPE_INDEX, table_name=_ITEM_TABLE)
    if "event_type" in _columns(_ITEM_TABLE):
        with op.batch_alter_table(_ITEM_TABLE) as batch:
            batch.drop_column("event_type")

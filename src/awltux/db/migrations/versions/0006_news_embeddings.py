"""Store a vector per news story, so one event can be shown as one entry.

Revision ID: 0006_news_embeddings
Revises: 0005_news_relevance
Create Date: 2026-10-05

A profit warning arrives five or six times from different outlets, rewritten each
time. ``news_analysis`` already collapses *syndication* -- the same text pasted
everywhere -- by comparing word sets. It cannot see the same event reported in
different words, which is the case that matters, and a vector can.

No existing row is back-filled here. Embedding costs a provider call per story, and
a migration runs unattended on container start with nobody watching the spend; the
``news_embeddings`` job does it, rationed and logged.

**Why it is guarded.** ``0001`` builds the schema from the models, so a fresh
database already has the table. Applying this revision to such a database must be a
no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from awltux.db.models import NewsEmbedding

revision = "0006_news_embeddings"
down_revision = "0005_news_relevance"
branch_labels = None
depends_on = None

_TABLE = "news_embedding"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE in tables:
        return
    NewsEmbedding.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE in tables:
        op.drop_table(_TABLE)

"""Record on the instrument whether its shareholders' reports are downloaded.

Revision ID: 0007_annual_reports_flag
Revises: 0006_news_embeddings
Create Date: 2026-10-06

The documents themselves live in ``filing`` and on disk; this is the *flag* that
says whether they are there, because the question "can I read this company's
accounts?" is asked once per row on the dashboard and once per instrument by the
acquisition job -- and answering it from ``filing`` means a join over the largest
table in the database to learn something that changes once a day.

**Why the column exists rather than being derived.** Deriving it would also be
correct, and is what the coverage probe does. But the job's selection is "which
instruments still need reports", it runs against the whole universe every hour, and
a stored count makes that a single indexed read rather than a grouped join. The
count is maintained by the job that fetches the documents, which is the only writer
that can change it.

**Why the default is zero and not null.** Zero means "none held", which is a true
statement about a fresh install. ``reports_synced_at`` is what distinguishes an
instrument nobody has looked at yet from one whose reports genuinely do not exist,
and a null count would make a third state that every reader would have to handle.

**Why it is guarded.** ``0001`` builds the schema from the models, so a fresh
database already has both columns. Applying this revision to such a database must be
a no-op rather than a duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_annual_reports_flag"
down_revision = "0006_news_embeddings"
branch_labels = None
depends_on = None

_TABLE = "instrument"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    columns = _columns(_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        if "annual_reports" not in columns:
            batch.add_column(
                sa.Column("annual_reports", sa.Integer(), nullable=False, server_default="0")
            )
        if "reports_synced_at" not in columns:
            batch.add_column(
                sa.Column("reports_synced_at", sa.DateTime(timezone=True), nullable=True)
            )


def downgrade() -> None:
    columns = _columns(_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        if "reports_synced_at" in columns:
            batch.drop_column("reports_synced_at")
        if "annual_reports" in columns:
            batch.drop_column("annual_reports")

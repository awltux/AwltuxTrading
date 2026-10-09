"""Give the deep-dive research reports a table.

Revision ID: 0025_research_report
Revises: 0024_provider_balance_reading
Create Date: 2026-10-09

Asked for: a Research button on the instrument and sector pages, an editable prompt, a
background job, and a report stored on disk and listed on the page.

Two of the columns are denormalised out of ``result`` and the reason is worth stating:
``exec_summary`` and ``verdict`` are read on **every request of every tab** of the subject's
page, to print the summary strip at the top, while ``result`` is a JSON document holding the
whole validated finding set. Loading and parsing that to print two fields would be work nobody
asked for on the hot path; the JSON stays the record and these two are the index into it.

``refresh`` is its own column rather than a key inside ``inventory`` because it answers a
different question: the inventory says what evidence existed, and this says whether the run
refreshed the subject first and what that refresh did. A report built on a skipped refresh and
one built on a fresh pipeline are not the same claim.

Additive and inspection-guarded on the table list, because `0001` builds the schema from the
models: on a fresh database the table is already there and this must be a no-op rather than a
duplicate-table error. There is nothing to backfill -- no report has ever been generated.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_research_report"
down_revision = "0024_provider_balance_reading"
branch_labels = None
depends_on = None

_TABLE = "research_report"
_SUBJECT_INDEX = "ix_research_subject_created"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("exec_summary", sa.Text(), nullable=True),
        sa.Column("verdict", sa.String(length=24), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("inventory", sa.JSON(), nullable=True),
        sa.Column("refresh", sa.JSON(), nullable=True),
        sa.Column("raw_path", sa.String(length=512), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("llm_call_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # `TimestampMixin`, written by the model rather than by hand: both are NOT NULL
        # there, so they are here too or a fresh database and a migrated one would differ.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(f"ix_{_TABLE}_subject_type", _TABLE, ["subject_type"])
    op.create_index(f"ix_{_TABLE}_subject_id", _TABLE, ["subject_id"])
    op.create_index(f"ix_{_TABLE}_status", _TABLE, ["status"])
    op.create_index(_SUBJECT_INDEX, _TABLE, ["subject_type", "subject_id", "created_at"])


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    op.drop_index(_SUBJECT_INDEX, table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_status", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_subject_id", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_subject_type", table_name=_TABLE)
    op.drop_table(_TABLE)

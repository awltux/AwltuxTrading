"""Record a job's per-instrument failures, so they stop being invisible.

Revision ID: 0009_instrument_blocker
Revises: 0008_news_poll_cursor
Create Date: 2026-10-07

A new table, so this migration has no inspection guard on the columns and instead asks
whether the table already exists -- ``0001`` builds the schema from the models, so
applying this to a fresh database must be a no-op rather than a duplicate-table error.

**Why this exists.** Per-instrument failures were already recorded, in
``IngestRun.detail`` as free text:

    "failures": ["ADVl_EQ: [yahoo] no statements available for ADV.L"]

Measured 2026-10-07 against the live database: scanning the last **400 runs** for
per-instrument failure strings found **5 instruments**. Two reasons, and both are
structural rather than accidental. Each job rations itself to a couple of instruments
per run (``fundamentals`` at 2, ``xbrl_statements`` at 60), so a given instrument is
touched rarely; and ``retention`` prunes run detail, so the evidence expires. Nothing
about the format is stable either -- every job words its own list differently, and
three of them key the entries by ticker with different separators.

A signal that decays and has no schema is not a record, and the dashboard needs one:
the difference between "we tried and this company's statements cannot be had" and "we
have not got to it yet" is exactly what the reader has to know, and today both render
as the same em-dash.

**Why a table rather than a column on ``instrument``.** One instrument can be blocked by
several jobs at several steps, and the questions asked of it are per-(job, stage): is
this *still* broken, since when, and how many times. A single column could hold one
reason, and the second failure would overwrite the first -- which is how a job that
fails every night ends up looking like it failed once.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_instrument_blocker"
down_revision = "0008_news_poll_cursor"
branch_labels = None
depends_on = None

_TABLE = "instrument_blocker"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_t212_ticker", sa.String(length=64), nullable=False),
        sa.Column("job", sa.String(length=48), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_t212_ticker"],
            ["instrument.t212_ticker"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "instrument_t212_ticker", "job", "stage", name="uq_instrument_blocker"
        ),
    )
    op.create_index(
        "ix_instrument_blocker_instrument_t212_ticker",
        _TABLE,
        ["instrument_t212_ticker"],
    )
    op.create_index("ix_instrument_blocker_last_seen_at", _TABLE, ["last_seen_at"])
    op.create_index("ix_instrument_blocker_resolved_at", _TABLE, ["resolved_at"])


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    for index in (
        "ix_instrument_blocker_resolved_at",
        "ix_instrument_blocker_last_seen_at",
        "ix_instrument_blocker_instrument_t212_ticker",
    ):
        op.drop_index(index, table_name=_TABLE)
    op.drop_table(_TABLE)

"""A per-instrument lease, so one company can be refreshed without racing the sweeps.

Revision ID: 0010_instrument_refresh
Revises: 0009_instrument_blocker
Create Date: 2026-10-07

A new table, so this asks whether it already exists -- ``0001`` builds the schema from
the models, and applying this to a fresh database must be a no-op rather than a
duplicate-table error.

**Why a table.** A one-instrument refresh runs the pipeline stages for a single company,
and the universe-wide jobs are walking the same companies on their own schedule. The
plan for a collision is not to hope: the refresh takes a lease on the instrument, and the
sweeps skip an instrument whose lease is held. That needs a row every process can see --
the refresh runs on the web process's thread and the sweeps on the scheduler's, and they
already agree on nothing except the database.

**Why the primary key is the ticker.** One row per instrument *is* the lock: a second
refresh of the same company finds the row held. And the same row carries the progress, so
the page that offers the button can report what it is doing without a second table that
could disagree with the lock about whether a refresh is running.

**Why a lease rather than a flag.** ``expires_at`` is renewed between steps, so a crashed
refresh releases the instrument instead of removing it from every sweep forever. A flag
would need a separate reaper, and a reaper that ran while a slow refresh was still working
would do the very thing the lock exists to prevent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_instrument_refresh"
down_revision = "0009_instrument_blocker"
branch_labels = None
depends_on = None

_TABLE = "instrument_refresh"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return

    op.create_table(
        _TABLE,
        sa.Column("instrument_t212_ticker", sa.String(length=64), primary_key=True),
        sa.Column("token", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_t212_ticker"],
            ["instrument.t212_ticker"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_instrument_refresh_state", _TABLE, ["state"])
    op.create_index("ix_instrument_refresh_expires_at", _TABLE, ["expires_at"])


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    for index in ("ix_instrument_refresh_expires_at", "ix_instrument_refresh_state"):
        op.drop_index(index, table_name=_TABLE)
    op.drop_table(_TABLE)

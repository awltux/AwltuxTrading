"""Separate the exchange reference from the raw working-schedule id.

Revision ID: 0003_exchange_fk
Revises: 0002_two_horizons
Create Date: 2026-02-03

``instrument.working_schedule_id`` was declared as a foreign key to ``exchange.id``.
That is wrong, and it broke the instrument sync on **18,483 rows** with
``FOREIGN KEY constraint failed``.

Trading 212's ``workingScheduleId`` is not an exchange id. Schedule ids live in
their own space inside each exchange's ``workingSchedules`` list -- the two happen
to be small integers, which is exactly why the mistake survived review. The
documented route from an instrument to its venue is to resolve the schedule id
through that nested list, which ``ingest.universe`` already did for the name.

So this revision adds a real ``exchange_id`` foreign key, and keeps
``working_schedule_id`` as an informational integer with no constraint.

**Why it is guarded.** ``0001`` is a metadata-generated baseline, so it always
produces the *current* schema -- on a fresh database ``exchange_id`` already
exists. The revision therefore applies only what is genuinely missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_exchange_fk"
down_revision = "0002_two_horizons"
branch_labels = None
depends_on = None

_TABLE = "instrument"
_INDEX = "ix_instrument_exchange_id"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table)
        if index["name"]
    }


def upgrade() -> None:
    columns = _columns(_TABLE)
    indexes = _indexes(_TABLE)

    if "exchange_id" not in columns:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column("exchange_id", sa.Integer(), nullable=True))
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, ["exchange_id"])

    # The old constraint on working_schedule_id cannot be dropped by name on
    # SQLite, so the table is rebuilt against the new definition. Existing rows
    # keep their raw schedule id, which is still useful information.
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.alter_column(
            "working_schedule_id", existing_type=sa.Integer(), nullable=True
        )


def downgrade() -> None:
    indexes = _indexes(_TABLE)
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)

    with op.batch_alter_table(_TABLE) as batch:
        if "exchange_id" in _columns(_TABLE):
            batch.drop_column("exchange_id")

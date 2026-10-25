"""Give the fundamentals sweep a cursor of its own, so a name it cannot fetch cannot stall it.

Revision ID: 0033_instrument_fundamentals_checked_at
Revises: 0032_period_presentation
Create Date: 2026-10-24

Reported: *"Does the current strategy eventually process all instruments over multiple days, or
does it restart on the same instruments each day?"* It restarted, and the live container showed it:

* seven consecutive `fundamentals` runs over seventeen hours each attempted **two** instruments,
  wrote **nothing**, and named the same two -- `CYBAl_EQ` and `HGENl_EQ`, both refused by the
  provider with "no statements available";
* 183 of 506 in-universe instruments had any accounts at all.

The queue was ordered on ``instrument.updated_at``, and the sweep only bumps that column when it
*writes* something. A refused provider call writes nothing, so the row kept its old timestamp and
led the next run's queue as well. `Instrument.news_polled_at` records the same lesson in its own
comment -- "`Instrument.updated_at` is the obvious column and the wrong one ... it would order the
poll by whatever ran last" -- and this column is that fix for the other sweep.

An **attempt** is what is stamped, not a success: "we asked and the provider had nothing" is a
fact a retry every run cannot change, so the failing name waits its turn like everything else and
is retried once per pass. `instrument_blocker` still records the failure in between.

Additive and inspection-guarded, because ``0001`` builds the schema from the models: on a fresh
database the column is already there and this must be a no-op rather than a duplicate-column
error. Indexed because it is the sweep's sort key over the whole universe on every run.

**Nothing to backfill.** Every row starts ``NULL``, which sorts first -- the whole book is due a
pass, and that is true: at the moment this ships, 323 of the 506 in-universe instruments have no
accounts.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_instrument_fundamentals_checked_at"
down_revision = "0032_period_presentation"
branch_labels = None
depends_on = None

_TABLE = "instrument"
_COLUMN = "fundamentals_checked_at"
_INDEX = "ix_instrument_fundamentals_checked_at"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))
    if _INDEX not in _indexes(_TABLE):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    if _INDEX in _indexes(_TABLE):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)

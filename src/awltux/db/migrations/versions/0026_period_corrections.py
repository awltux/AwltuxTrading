"""Let a period's accounts carry the corrections a reader has made to them.

Revision ID: 0026_period_corrections
Revises: 0025_research_report
Create Date: 2026-10-09

Asked for directly: *"Lines in an account section must be deleteable, as I've found
mistakes in the automated extraction process."* A line on the accounts page is a stored
metric, so deleting one means editing the period -- and the edit has to be recorded rather
than merely applied, or the next reader cannot tell a corrected figure from an extracted one,
and the next `companyfacts` re-derive silently restores whatever was removed.

One nullable JSON column, so nothing is backfilled and no reader changes: the corrected
values themselves go into the existing ``metrics``/``metric_sources`` columns (that is what
makes every consumer see them), and this holds the record of what was changed -- the
extractor's figure for a removed line, the tag and filing URL a clicked value came from, and
when. ``analysis/corrections.py`` owns the shape.

Additive and inspection-guarded, because `0001` builds the schema from the models: on a fresh
database the column is already there and this must be a no-op rather than a duplicate-column
error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_period_corrections"
down_revision = "0025_research_report"
branch_labels = None
depends_on = None

_TABLE = "fundamental_period"
_COLUMN = "corrections"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)

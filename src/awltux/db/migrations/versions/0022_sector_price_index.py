"""Store each sector's equal-weighted price index, so its page can draw one line.

Revision ID: 0022_sector_price_index
Revises: 0021_t212_order
Create Date: 2026-10-08

The sector page lists its instruments and each instrument's page draws its own price line, so
the sector itself had no price view at all. The average cannot be an average of *prices* --
a 3,000p share and a 30p share are not on the same scale, and the constituents report in
different currencies -- so it is an index: each instrument is rebased to 100 at its first bar
in the window, and the level is the mean of those ratios. Rebasing is also what makes the
currencies cancel, so no FX rate has to be invented or fetched.

Stored rather than derived per page because the derivation reads every constituent's bars:
measured 2026-10-08, 20,753 rows and 135 ms for Information Technology, 61,728 rows and
445 ms for the unclassified bucket, on a page that re-renders on every column sort.

Additive: a new table, so `upgrade` is a no-op on a fresh database, where `0001` has already
built it from the models. Guarded by `inspect` anyway, so the pattern matches its siblings.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_sector_price_index"
down_revision = "0021_t212_order"
branch_labels = None
depends_on = None

_TABLE = "sector_price_index"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        # No separate id: a sector has one level per day, and that pair is the key.
        sa.Column("sector", sa.String(length=96), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("level", sa.Float(), nullable=False),
        sa.Column("contributors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_date", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    op.drop_table(_TABLE)

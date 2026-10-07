"""A coarse sector on the instrument, so a sector page and a sector news query exist.

Revision ID: 0012_inst_sector_group
Revises: 0011_news_metric
Create Date: 2026-10-07

The universe's sector is the SEC's SIC *industry description*: 148 distinct strings over
500 in-universe instruments, most holding one or two names. Measured 2026-10-07 --
``Services-Computer Programming, Data Processing, Etc.`` is a sector of five, and 185
in-universe instruments have no sector at all. A page per one of those is a page nobody
visits and a Google News query for one returns nothing, so the sector page needs a
vocabulary that is small, stable and recognisable.

``analysis/sectors.py`` derives one of eleven from ``sic_code``, and this column stores
the result. It is **stored rather than derived on read** for two reasons: the sector
index groups by it, which a per-render derivation cannot do in SQL, and a job can then
report the instruments it cannot classify instead of a page silently showing nothing.

The backfill runs the same pure function over every existing row. It classifies **315 of
18,488 instruments**, and all eleven sectors have instruments behind them -- so no sector
page is empty. The other 18,173 have neither a SIC code nor a sector string; they stay
``NULL``, which is the honest state and the one the page has to be able to show.

Guarded, because ``0001`` builds the schema from the models: applying this to a fresh
database must be a no-op rather than a duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_inst_sector_group"
down_revision = "0011_news_metric"
branch_labels = None
depends_on = None

_TABLE = "instrument"
_COLUMN = "sector_group"
_INDEX = "ix_instrument_sector_group"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.String(length=32), nullable=True))
    if _INDEX not in _indexes(_TABLE):
        op.create_index(_INDEX, _TABLE, [_COLUMN])
    _backfill()


def _backfill() -> None:
    """Classify every row that has something to classify.

    Done in Python rather than as SQL because the rule is a curated table, not an
    expression -- and it is the *same* function the ingest path calls, so the backfill
    and steady state cannot disagree about what a SIC code means.
    """
    from awltux.analysis.sectors import group_for

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT t212_ticker, sic_code, sector FROM {_TABLE}")  # noqa: S608 - fixed name
    ).all()
    updates = []
    for ticker, sic_code, sector in rows:
        group = group_for(sic_code, sector)
        if group is not None:
            updates.append({"ticker": ticker, "group": group})
    if updates:
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = :group WHERE t212_ticker = :ticker"),  # noqa: S608
            updates,
        )


def downgrade() -> None:
    if _INDEX in _indexes(_TABLE):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)

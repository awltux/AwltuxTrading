"""Give an instrument the levers its business is exposed to.

Revision ID: 0027_instrument_lever
Revises: 0026_period_corrections
Create Date: 2026-10-10

Asked for directly: *"an instrument should have a short description of what the company does
... and what the primary levers are that affect its performance. The levers is a particularly
interesting addition that could be used to analyse which instruments are affected by a
specific lever e.g. interest rates, exchange rates, inflation, resource costs, technology."*

One table, one row per (instrument, lever), because the question that makes the feature worth
having is asked *across* instruments -- **which** businesses does a lever move -- and that is
an indexed lookup on ``lever`` rather than a scan of a document per instrument. The reasoning,
the vocabulary and the direction convention are all in ``analysis/levers.py`` and on
:class:`~awltux.db.models.InstrumentLever`.

Additive and inspection-guarded on the table list, because `0001` builds the schema from the
models: on a fresh database the table is already there and this must be a no-op rather than a
duplicate-table error. Nothing to backfill -- no lever has ever been recorded.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_instrument_lever"
down_revision = "0026_period_corrections"
branch_labels = None
depends_on = None

_TABLE = "instrument_lever"
_UNIQUE = "uq_instrument_lever"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_t212_ticker", sa.String(length=64), nullable=False),
        sa.Column("lever", sa.String(length=48), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("strength", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        # `TimestampMixin`, written by the model rather than by hand: both are NOT NULL
        # there, so they are here too or a fresh database and a migrated one would differ.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_t212_ticker"], ["instrument.t212_ticker"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("instrument_t212_ticker", "lever", name=_UNIQUE),
    )
    op.create_index(f"ix_{_TABLE}_instrument_t212_ticker", _TABLE, ["instrument_t212_ticker"])
    op.create_index(f"ix_{_TABLE}_lever", _TABLE, ["lever"])


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    op.drop_index(f"ix_{_TABLE}_lever", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_instrument_t212_ticker", table_name=_TABLE)
    op.drop_table(_TABLE)

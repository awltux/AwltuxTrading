"""Store Trading 212's order history, so an instrument page can show its buy and sell dates.

Revision ID: 0021_t212_order
Revises: 0020_instrument_position
Create Date: 2026-10-08

`T212Provider.get_order_history()` has existed since the provider was written and had **no
callers** -- the scope map, the budget scope and the pagination were all wired and nothing
ever asked. Probed live 2026-10-08, `GET /equity/history/orders` is a synchronous GET (not an
async report) that this key can read and returns, per order:

    {"order": {"id": 58419120582, "ticker": "AIT_US_EQ", "side": "BUY",
               "status": "FILLED", "type": "MARKET", "strategy": "VALUE",
               "createdAt": "2026-10-05T16:00:20Z", "filledValue": 252.47,
               "currency": "GBP"},
     "fill":  {"quantity": 0.95851493, "price": 347.6, "type": "TRADE",
               "filledAt": "2026-10-05T16:00:21Z",
               "walletImpact": {"netValue": 252.47, ...}}}

`order.id` is T212's and is unique here: history is re-read from the newest page backwards, a
page can be re-read after a failed run, and the write upserts on it rather than assuming each
order is seen once.

`instrument_t212_ticker` is **nullable**. The account can hold something outside the stored
universe, and dropping the row would lose a real trade to a gap in our own metadata.

Additive: a new table, so `upgrade` is a no-op on a fresh database, where `0001` has already
built it from the models. Guarded by `inspect` anyway, so the pattern matches its siblings.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_t212_order"
down_revision = "0020_instrument_position"
branch_labels = None
depends_on = None

_TABLE = "t212_order"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("instrument_t212_ticker", sa.String(length=32), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=True),
        sa.Column("order_type", sa.String(length=16), nullable=True),
        sa.Column("strategy", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_quantity", sa.Float(), nullable=True),
        sa.Column("fill_price", sa.Float(), nullable=True),
        sa.Column("fill_type", sa.String(length=32), nullable=True),
        sa.Column("net_value", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Unique, not merely indexed: this is the idempotency key the upsert depends on.
    op.create_index(f"ix_{_TABLE}_order_id", _TABLE, ["order_id"], unique=True)
    op.create_index(
        f"ix_{_TABLE}_instrument_t212_ticker", _TABLE, ["instrument_t212_ticker"]
    )
    op.create_index(f"ix_{_TABLE}_filled_at", _TABLE, ["filled_at"])


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    op.drop_table(_TABLE)

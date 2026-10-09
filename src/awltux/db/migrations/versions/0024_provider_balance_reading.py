"""Store every balance reading, so a provider's spend can be estimated from the drops.

Revision ID: 0024_provider_balance_reading
Revises: 0023_news_publisher
Create Date: 2026-10-09

Suggested directly for fal: *"the fal costs could be roughly calculated by storing the
balance each time it's updated and comparing it to the next balance update. It's not key
specific, but it's useful."*

It is the only route for that provider. `GET /account/billing` refuses this project's
model key with a 403 (its Platform APIs want an Admin-scope key), and nothing logs what an
embeddings request cost -- `llm_call` is written by `llm/deepseek.py` alone -- so for fal
there is no spend figure anywhere, only the balance itself.

**The existing storage cannot do this.** `app_setting['provider_balance']` holds the
*latest* reading per provider, merged, and each hourly run overwrites the one before it.
That is what the banner needs and it is the wrong shape for a difference: it keeps one
point, and a series needs two.

**Additive and inspection-guarded**, because `0001` builds the schema from the models: on a
fresh database the table is already there and this must be a no-op rather than a
duplicate-table error. There is nothing to backfill -- the readings that would populate it
were never written down, and inventing them from `llm_call` would produce a DeepSeek delta
under fal's name.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_provider_balance_reading"
down_revision = "0023_news_publisher"
branch_labels = None
depends_on = None

_TABLE = "provider_balance_reading"
_INDEX = "ix_provider_balance_provider_read"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("key_name", sa.String(length=64), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(_INDEX, _TABLE, ["provider", "read_at"])
    op.create_index(f"ix_{_TABLE}_provider", _TABLE, ["provider"])


def downgrade() -> None:
    if _TABLE not in _tables():
        return
    op.drop_index(f"ix_{_TABLE}_provider", table_name=_TABLE)
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)

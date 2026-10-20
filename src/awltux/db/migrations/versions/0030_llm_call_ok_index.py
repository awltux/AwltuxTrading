"""Index the ledger by success, for the ceiling this app enforces before every call.

Revision ID: 0030_llm_call_ok_index
Revises: 0029_llm_call_spend_index
Create Date: 2026-10-20

`0029` indexed `(provider, created_at, cost_usd)`, which is what the strip's *per-provider*
aggregate needs. The other half of the same banner is `llm/deepseek.py::_spend_since`, and it
asks a different question: the month's spend across **all** providers, filtered to calls that
succeeded. `ok` is not in `0029`'s index, so the plan fell back to `ix_llm_call_created_at`
and fetched `cost_usd` and `ok` from the table for every row.

Measured 2026-10-20 on 47,905 rows, three runs each, before and after:

    month-to-date spend   105.6 ms -> 5.8 ms   COVERING INDEX (created_at, ok, cost_usd)
    per-provider 30 days   14.6 ms -> 13.2 ms  (unchanged; it uses 0029's index)
    payment failures       39.4 ms -> 24.3 ms  (by-product of the plan change)

Two indexes rather than one because the two queries cannot share: ordered `provider` first the
month-to-date sum is 7.4 ms and the grouped one 36.5 ms, and ordered `created_at` first the
grouped one loses its index order and needs a temp b-tree. Both are read on **every page**, and
`_spend_since` is also what `_check_budget` runs before **every model call**, so the second
index is paid for by the fastest path in the application.

Additive and inspection-guarded; no data change, and ``downgrade`` only drops it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_llm_call_ok_index"
down_revision = "0029_llm_call_spend_index"
branch_labels = None
depends_on = None

_TABLE = "llm_call"
_INDEX = "ix_llm_call_spend_ok"


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if _INDEX not in _indexes(_TABLE):
        op.create_index(_INDEX, _TABLE, ["created_at", "ok", "cost_usd"])


def downgrade() -> None:
    if _INDEX in _indexes(_TABLE):
        op.drop_index(_INDEX, table_name=_TABLE)

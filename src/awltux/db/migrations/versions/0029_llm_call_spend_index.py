"""Index the model-call ledger by what the credit strip sums.

Revision ID: 0029_llm_call_spend_index
Revises: 0028_instrument_business_summary
Create Date: 2026-10-20

Found by profiling one instrument page after the report that *ten open tabs stall the app*:
**224 ms of the page's 290 ms was the header's credit banner**, because it aggregates
``llm_call`` on every request -- thirty days of spend per provider, and the month's spend for
the provider the app's own ceiling governs.

Both queries were reading the whole table through a single-column index: measured 2026-10-20
on **47,890** rows, ``_credit_spend`` was **102 ms** (``SCAN llm_call USING INDEX
ix_llm_call_provider``) and ``month_to_date_spend`` **105 ms** (``SEARCH ... (provider=?)``),
each fetching ``cost_usd`` from the table per row. The composite index below is *covering* for
both -- ``provider`` first so the month-to-date seek is exact, then ``created_at`` for the
range, then ``cost_usd`` so no table lookup is needed -- and the same index also speeds the
month-to-date check that runs before **every** model call (``llm/deepseek.py::_check_budget``).

Additive and inspection-guarded, because ``0001`` builds the schema from the models: on a fresh
database ``LLMCall.__table_args__`` already declares it and this must be a no-op rather than a
duplicate-index error.

No backfill and no data change: an index is derived, and ``downgrade`` only drops it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_llm_call_spend_index"
down_revision = "0028_instrument_business_summary"
branch_labels = None
depends_on = None

_TABLE = "llm_call"
_INDEX = "ix_llm_call_spend"


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if _INDEX not in _indexes(_TABLE):
        op.create_index(
            _INDEX,
            _TABLE,
            ["provider", "created_at", "cost_usd"],
        )


def downgrade() -> None:
    if _INDEX in _indexes(_TABLE):
        op.drop_index(_INDEX, table_name=_TABLE)

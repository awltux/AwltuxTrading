"""Keep the broker's own view of each position, and the date it was opened.

Revision ID: 0020_instrument_position
Revises: 0019_news_dismissed
Create Date: 2026-10-08

`sync_instruments` has always read `/equity/positions` -- it is how `is_held` is decided --
and kept only the ticker. Everything else in the payload was discarded, including
`createdAt`, which the API documents as *"the ISO 8601 formatted date of when the position
was opened"*. Probed live 2026-10-08:

    {"instrument": {"ticker": "GWW_US_EQ", ...}, "createdAt": "2025-01-31T17:29:15+02:00",
     "quantity": 1.1848359, "quantityInPies": 0, "currentPrice": 1261.38,
     "averagePricePaid": 1097.71319387,
     "walletImpact": {"currency": "GBP", "totalCost": 977.35, "currentValue": 1133.08,
                      "unrealizedProfitLoss": 155.73, "fxImpact": 8.71}}

So the columns cost no extra request and no extra scope: the data already arrives once a
day and is thrown away at the parse.

**On `instrument`, not in a child table.** This is current state, one row per instrument,
replaced wholesale on every sync, and `is_held` is already here. A child table would need a
"which row is current" rule for nothing.

**Nullable, and cleared when the position closes.** `None` is "no open position", which is
the state every existing row is already in. The clearing happens in the same write that
clears `is_held` -- see `ingest/jobs.py::_apply_positions` -- because a sold instrument
keeping a position for ever is this feature inverted.

Additive and inspection-guarded, because `0001` builds the schema from the models: on a
fresh database the columns are already there and this must be a no-op rather than a
duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_instrument_position"
down_revision = "0019_news_dismissed"
branch_labels = None
depends_on = None

_TABLE = "instrument"

#: Added together, and dropped together. Named `_gbp` only because this account's primary
#: currency is GBP; `position_currency` records what the broker actually said.
_COLUMNS = (
    ("position_opened_at", sa.DateTime(timezone=True)),
    ("position_quantity", sa.Float()),
    ("position_average_price", sa.Float()),
    ("position_in_pies", sa.Float()),
    ("position_cost_gbp", sa.Float()),
    ("position_value_gbp", sa.Float()),
    ("position_unrealised_gbp", sa.Float()),
    ("position_currency", sa.String(length=8)),
    ("position_synced_at", sa.DateTime(timezone=True)),
)


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    present = _columns(_TABLE)
    missing = [(name, kind) for name, kind in _COLUMNS if name not in present]
    if not missing:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name, kind in missing:
            batch.add_column(sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    present = _columns(_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        for name, _kind in reversed(_COLUMNS):
            if name in present:
                batch.drop_column(name)

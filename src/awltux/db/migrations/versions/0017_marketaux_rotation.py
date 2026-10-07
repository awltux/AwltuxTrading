"""Give the marketaux quota its own cursor, so the ration rotates.

Revision ID: 0017_marketaux_rotation
Revises: 0016_pooled_feed_attribution
Create Date: 2026-10-07

Marketaux's free plan allows **100 requests a day**, and one request returns news for one
symbol, so a marketaux pass covers a fifth of a 500-name universe. The provider platform
emailed about the daily limit being reached, which is what this and the surrounding change
answer.

The old behaviour had two faults, and the column fixes the first:

* **The quota followed the news poll's cursor.** `marketaux.news([symbol])` was called
  once per instrument during the universe walk, so the 100 requests went to whichever
  names the *poll* happened to reach first. The poll's cursor advances a whole universe
  per sweep, so the marketaux quota landed on a different arbitrary fifth every day
  rather than rotating through the book in any ordered way -- and because it was spent in
  the first two hours, the remaining twenty-two had no marketaux at all. Measured
  2026-10-07: `provider_budget` held `marketaux used=100`, window started 17:49.
* **Nothing recorded who had been asked.** A quota that must choose 100 of 500 names needs
  a record of the last time each was chosen, or the choice cannot be fair.

So this is the same shape as `news_polled_at` (migration `0008`) for the same reason, and
deliberately a *separate* column: the poll's stamp marks "the feeds were asked", which
happens for every instrument every sweep, while this marks "the rationed provider was
spent here", which happens for three instruments an hour. Sharing one column would make
the ration follow the poll again.

Guarded, because `0001` builds the schema from the models: applying this to a fresh
database must be a no-op rather than a duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_marketaux_rotation"
down_revision = "0016_pooled_feed_attribution"
branch_labels = None
depends_on = None

_TABLE = "instrument"
_COLUMN = "marketaux_polled_at"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))
        batch.create_index(f"ix_{_TABLE}_{_COLUMN}", [_COLUMN])


def downgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(f"ix_{_TABLE}_{_COLUMN}")
        batch.drop_column(_COLUMN)

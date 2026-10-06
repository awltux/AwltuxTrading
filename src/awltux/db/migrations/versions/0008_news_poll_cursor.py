"""Give the news poll a cursor, so it resumes instead of restarting.

Revision ID: 0008_news_poll_cursor
Revises: 0007_annual_reports_flag
Create Date: 2026-10-06

``ingest_rss_news`` walks every instrument in the universe and takes hours: measured
2026-10-06, it classified 3,033 headlines in 97 minutes at a flat ~31 a minute with no
sign of slowing, and ``news_rss`` had **0 successful runs in 7 attempts**. The selection
had no ``ORDER BY`` at all, so every run started at the same first row.

What that cost, precisely:

* **An interrupted run lost its position.** The articles already stored survive -- the
  loop commits per instrument and `url_hash` dedupes -- but the *walk* restarted, so the
  next run re-fetched every feed it had already fetched. The work was idempotent rather
  than wasted, and the time was spent twice.
* **The end of the list was reached only by luck.** Nothing rotated, so an instrument
  late in rowid order was polled only on a run that got that far.

Ordering on this column makes the walk continue where it stopped, and it makes the sweep
wrap without anything resetting a counter: once every row carries a timestamp, the least
recently polled is the first one polled last time, so the next run starts at the
beginning again.

**Why a column rather than a derived value.** ``max(NewsItem.created_at)`` looks like it
would do and does not: an instrument whose feeds carry no news never gains a row, so it
would sit at the front of every run forever and starve everything behind it. The cursor
has to record *attempts*, not results.

**Why not ``Instrument.updated_at``.** Nothing in this job otherwise touches the
instrument row, but other jobs do, so ordering on it would order the poll by whatever
ran last -- the same trap ``sync_xbrl_fundamentals`` documents for its own rotation.

Guarded, because ``0001`` builds the schema from the models: applying this to a fresh
database must be a no-op rather than a duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_news_poll_cursor"
down_revision = "0007_annual_reports_flag"
branch_labels = None
depends_on = None

_TABLE = "instrument"
_COLUMN = "news_polled_at"


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

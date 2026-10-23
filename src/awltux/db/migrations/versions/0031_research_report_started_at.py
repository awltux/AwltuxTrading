"""Record when a deep-dive was claimed, so a queued run can be told from a stuck one.

Revision ID: 0031_research_report_started_at
Revises: 0030_llm_call_ok_index
Create Date: 2026-10-21

Asked for: *"Currently only one Research job can run at once, launching a second Research job
fails. Add a queue system for the Research jobs, so they are eventually processed."*

The queue lives in ``research_report`` itself: a press writes a ``queued`` row, and a consumer
claims the oldest one with ``UPDATE ... WHERE status = 'queued'``. That needs one more fact than
the table had, and it is not the request time: ``created_at`` says when the reader pressed the
button, which for a run that waited an hour behind another deep-dive is *before* the run began.

Without this column, staleness has no honest anchor. The page marks a ``running`` row stale when
it is older than ``research.stale_minutes`` -- correct while a run started the moment it was
requested, and a lie the moment a queue exists: a deep-dive claimed after a long wait would be
printed as stale the instant it started, and its subject would look abandoned while the model
was answering.

Additive and inspection-guarded, because ``0001`` builds the schema from the models: on a fresh
database the column is already there and this must be a no-op rather than a duplicate-column
error.

**Nothing to backfill, deliberately.** Rows written before this change were never queued, so
their run began when they were created; leaving the column ``NULL`` expresses exactly that, and
every reader of it falls back to ``created_at``. Copying one into the other would turn "we do
not know" into a fact, and the fallback is the same answer without the claim.

No index: the column is read per row on a list bounded to 25, and nothing filters or sorts on
it -- the queue orders by ``id``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_research_report_started_at"
down_revision = "0030_llm_call_ok_index"
branch_labels = None
depends_on = None

_TABLE = "research_report"
_COLUMN = "started_at"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)

"""Keep the captions a source states that this project's vocabulary has no name for.

Revision ID: 0032_period_presentation
Revises: 0031_research_report_started_at
Create Date: 2026-10-25

Asked for after working through one set of accounts: *"It appears each company can use their own
terminology and accounting practices. So the accounting system cannot depend on where a line title
might end up ... it is difficult to construct accounts from just the prescribed titles, and
suggests a more flexible way of constructing/modifying the accounts is required."*

The measurement behind it, on ``JELl_EQ`` (Jersey Electricity) FY2025 from a Yahoo statement: its
income statement states ``Operating Expense`` and ``Other Operating Expenses`` as the same
38,688,000, with ``Selling General And Administration`` absent for 2023-2025, and
53,465,000 - 38,688,000 = 14,777,000 -- the stated operating income, to the pound. The section was
out by 26,867,000 on the page because ``STATEMENT_LABELS`` has no name for that caption and
`metrics_from_statements` keeps only the labels it names, so the figure was discarded at ingest.
It could not even be typed in: a line learned from a filing is keyed by its taxonomy tag, and a
provider statement has none.

So the caption and its figure are stored beside the figures the vocabulary did understand, and the
accounts page can offer them as lines for a reader to place. Only the surplus is kept -- a label a
canonical key already reads is dropped, and so is a stated zero -- so the column is small: one list
per statement, of ``{label, key, value}``.

**Additive and inspection-guarded**, because ``0001`` builds the schema from the models: on a fresh
database the column is already there and this must be a no-op rather than a duplicate-column error.

**Nothing to backfill, deliberately.** Rows written before this change did not keep the captions,
and the payload is not stored anywhere else, so there is nothing to recover: they pick it up at
their next sync. Writing an empty object in would claim the source stated no other caption, which
is a different and false fact -- ``NULL`` is "not recorded".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_period_presentation"
down_revision = "0031_research_report_started_at"
branch_labels = None
depends_on = None

_TABLE = "fundamental_period"
_COLUMN = "presentation"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)

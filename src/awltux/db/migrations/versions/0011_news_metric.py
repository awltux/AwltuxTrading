"""Three keys on a news item: what the story's numbers are of, when, and how big.

Revision ID: 0011_news_metric
Revises: 0010_instrument_refresh
Create Date: 2026-10-07

The same-event grouping was joining stories that the same classifier had already said
were different things. Measured 2026-10-07 over the 1,000 embedded stories at the
threshold then in force: of the 672 joins the cosine made, **439 (65%) contradicted
their own group on the stored ``event_type`` or ``direction``** -- "Canadian National
Railway stock falls Wednesday" grouped with "CN Rail stock rises Wednesday", and a
Claritev margin story grouped with an insider share sale, a buyback launch and a DOJ
probe. A cosine cannot see that: every one of those pairs is the same company on the
same day written in the same register, which is exactly what makes them score high.

``event_type`` and ``direction`` were already stored and now filter the grouping.
``metric`` is the field that was missing. It is independent of ``event_type``: "Golar
LNG gains 1.65% in October 5 trading" and "BTIG raises its Golar price target to $75"
are one company, one day and no news, and the only thing separating them is that the
first is about ``share_price`` and the second about ``price_target``. Likewise Expedia
on a raised target against Expedia up 60% this year.

``period`` and ``magnitude`` are stored but **not compared**: the period that separates
"falls Wednesday" from "rises Friday" is free text as the story writes it, and a wrong
comparison silently vetoes a real join. They are recorded to be shown, and normalising
them into something comparable is its own job.

All three are nullable and unpopulated on every existing row. That is the designed
state: the grouping treats an absent key as "not stated" rather than "different", so
the filter is live the moment this is applied and the backfill strengthens it as the
rationed re-classification reaches rows.

Guarded, because ``0001`` builds the schema from the models: applying this to a fresh
database must be a no-op rather than a duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_news_metric"
down_revision = "0010_instrument_refresh"
branch_labels = None
depends_on = None

_TABLE = "news_item"
_COLUMNS = {
    "metric": sa.String(length=24),
    "period": sa.String(length=32),
    "magnitude": sa.String(length=32),
}


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    present = _columns(_TABLE)
    missing = {name: type_ for name, type_ in _COLUMNS.items() if name not in present}
    if not missing:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name, type_ in missing.items():
            batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    present = _columns(_TABLE)
    dropped = [name for name in _COLUMNS if name in present]
    if not dropped:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name in dropped:
            batch.drop_column(name)

"""Give an instrument the provider's own description of what the company does.

Revision ID: 0028_instrument_business_summary
Revises: 0027_instrument_lever
Create Date: 2026-10-15

Asked for: *"in recommendations, provide a hover hint on the instrument link about the
Company e.g. Name and overview."*

Trading 212's metadata carries no description of any kind -- the panel in
``web/listing.py`` says so on every instrument that has no deep-dive -- so an overview has to
come from somewhere else. Yahoo's ``longBusinessSummary`` is already inside the ``info``
payload the fundamentals job fetches for its profile fields, so this costs no extra provider
call: the only new thing is somewhere to keep it.

Additive and inspection-guarded, because ``0001`` builds the schema from the models: on a
fresh database the column is already there and this must be a no-op rather than a
duplicate-column error.

**Nothing to backfill, and that is not an omission.** The value is a provider's prose, so a
migration cannot invent it for the rows that already exist; they fill in as
``fundamentals_rotation_per_day`` visits each instrument, and ``held_refresh`` reaches the
held names hourly. Until then the column is ``NULL``, which is the state the hover hint and
the model both treat as "no description held" rather than as an empty one.

No index: the column is ``Text`` and is never filtered, sorted or grouped on.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_instrument_business_summary"
down_revision = "0027_instrument_lever"
branch_labels = None
depends_on = None

_TABLE = "instrument"
_COLUMN = "business_summary"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _COLUMN not in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade() -> None:
    if _COLUMN in _columns(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)

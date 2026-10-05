"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-01

This baseline is generated from the SQLAlchemy metadata rather than hand-written
DDL. For a greenfield schema that is the honest representation: the models are
the source of truth, and a hand-copied baseline would be a second definition
that can silently drift from them. Subsequent revisions should be explicit
``op.*`` operations so that each schema change is reviewable on its own.
"""

from __future__ import annotations

from alembic import op

from awltux.db.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

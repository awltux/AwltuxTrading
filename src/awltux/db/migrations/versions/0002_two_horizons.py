"""Two decision horizons: long term and short term.

Revision ID: 0002_two_horizons
Revises: 0001_initial
Create Date: 2026-02-02

Splits the single collapsed `action` into independent long-term and short-term
verdicts, each with its own composite, confidence and risk-gate verdict.

**Why this migration inspects before acting.** ``0001`` is a squashed baseline
generated from the SQLAlchemy metadata, so it always produces the *current*
schema and cannot describe a historical one. On a fresh database the columns this
revision adds therefore already exist, and a plain rename would fail. The upgrade
is guarded so it is correct in both states that actually exist: a database created
before this change, and one created after it.

**Why index work happens outside the batch blocks.** On SQLite, ``batch_alter_table``
rebuilds the table and applies its operations against the table *as reflected at
the start of the block*. An index referring to a column that was renamed or added
within the same block therefore cannot be resolved, and raises. Keeping renames,
additions and index changes in separate steps avoids that entirely -- and it is the
upgrade path (old database, real rename) where it would have bitten, not the fresh
one where the columns happen to already exist.

**Existing rows are deliberately left half-populated.** Their `action` becomes
`long_term_action`, and the short-term columns stay NULL. That is the honest
outcome: those decisions were made before a tactical horizon existed, and
inventing one would fabricate a verdict nobody produced. The ledger's integrity
check reports such rows as `no_short_term_action` -- "this call predates the second
horizon" -- rather than a silently back-filled value.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_two_horizons"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_TABLE = "decision_run"
_OUTCOMES = "decision_outcome"

#: Columns this revision adds to ``decision_run``.
_ADDED_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("short_term_composite", sa.JSON()),
    ("short_term_composite_score", sa.Float()),
    ("short_term_action", sa.String(24)),
    ("short_term_confidence", sa.Float()),
    ("short_term_gate", sa.JSON()),
    ("short_term_gate_allowed", sa.Boolean()),
    ("horizon_fit", sa.String(16)),
)

#: Indexes this revision introduces.
#:
#: Names match what SQLAlchemy generates for ``index=True`` on the model
#: (``ix_<table>_<column>``), plus the two composite indexes declared explicitly in
#: ``__table_args__``. Using different names here would leave a freshly-migrated
#: database with duplicate indexes that a freshly-created one does not have -- the
#: kind of drift that only shows up as a mysterious performance difference later.
_NEW_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ("ix_decision_run_long_term_action", ["long_term_action"]),
    ("ix_decision_run_short_term_action", ["short_term_action"]),
    ("ix_decision_run_short_term_composite_score", ["short_term_composite_score"]),
    ("ix_decision_run_short_term_gate_allowed", ["short_term_gate_allowed"]),
    ("ix_decision_run_horizon_fit", ["horizon_fit"]),
    ("ix_decision_long_gate", ["long_term_action", "gate_allowed"]),
    ("ix_decision_short_gate", ["short_term_action", "short_term_gate_allowed"]),
)

#: Indexes this revision replaces: the explicit composite one and the implicit
#: single-column one SQLAlchemy generated for the old ``action`` column.
_REPLACED_INDEXES = ("ix_decision_action_gate", "ix_decision_run_action")
_OUTCOME_INDEX = "ix_decision_outcome_horizon"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table)
        if index["name"]
    }


def upgrade() -> None:
    columns = _columns(_TABLE)
    indexes = _indexes(_TABLE)

    # --- 1. reshape the table (rename + new columns) ------------------------
    with op.batch_alter_table(_TABLE) as batch:
        if "action" in columns and "long_term_action" not in columns:
            batch.alter_column("action", new_column_name="long_term_action")

        for name, column_type in _ADDED_COLUMNS:
            if name in columns:
                continue
            if name == "short_term_gate_allowed":
                batch.add_column(
                    sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
                )
            else:
                batch.add_column(sa.Column(name, column_type, nullable=True))

    # --- 2. index work, once the shape is final -----------------------------
    for name in _REPLACED_INDEXES:
        if name in indexes:
            op.drop_index(name, table_name=_TABLE)
    for name, columns_in_index in _NEW_INDEXES:
        if name not in indexes:
            op.create_index(name, _TABLE, columns_in_index)

    # --- 3. outcomes are scored per horizon ---------------------------------
    outcome_columns = _columns(_OUTCOMES)
    if "horizon" not in outcome_columns:
        with op.batch_alter_table(_OUTCOMES) as batch:
            # Existing rows were long-term outcomes; backfilling that is accurate,
            # unlike inventing a tactical verdict.
            batch.add_column(
                sa.Column("horizon", sa.String(16), nullable=False, server_default="long_term")
            )
            # The old uniqueness was (decision, horizon_days); the new one adds
            # horizon so one window can be scored for both verdicts.
            batch.drop_constraint("uq_outcome_horizon", type_="unique")
            batch.create_unique_constraint(
                "uq_outcome_horizon", ["decision_run_id", "horizon", "horizon_days"]
            )
        op.create_index(_OUTCOME_INDEX, _OUTCOMES, ["horizon"])


def downgrade() -> None:
    # Everything is inspected before opening a batch block; see the module
    # docstring for why querying inside one is unreliable.
    decision_columns = _columns(_TABLE)
    decision_indexes = _indexes(_TABLE)
    outcome_columns = _columns(_OUTCOMES)
    outcome_indexes = _indexes(_OUTCOMES)

    # --- 3. outcomes --------------------------------------------------------
    if "horizon" in outcome_columns:
        if _OUTCOME_INDEX in outcome_indexes:
            op.drop_index(_OUTCOME_INDEX, table_name=_OUTCOMES)
        with op.batch_alter_table(_OUTCOMES) as batch:
            batch.drop_constraint("uq_outcome_horizon", type_="unique")
            batch.create_unique_constraint(
                "uq_outcome_horizon", ["decision_run_id", "horizon_days"]
            )
            batch.drop_column("horizon")

    # --- 2. indexes ---------------------------------------------------------
    for name, _ in _NEW_INDEXES:
        if name in decision_indexes:
            op.drop_index(name, table_name=_TABLE)

    # --- 1. reshape back ----------------------------------------------------
    with op.batch_alter_table(_TABLE) as batch:
        for name, _ in _ADDED_COLUMNS:
            if name in decision_columns:
                batch.drop_column(name)
        if "long_term_action" in decision_columns and "action" not in decision_columns:
            batch.alter_column("long_term_action", new_column_name="action")

    # Recreate the old indexes, outside the batch block for the same reason as
    # above: the renamed column is not visible to batch-mode index operations.
    restored = _columns(_TABLE)
    if "ix_decision_run_action" not in decision_indexes and "action" in restored:
        op.create_index("ix_decision_run_action", _TABLE, ["action"])
    if "ix_decision_action_gate" not in decision_indexes and "action" in restored:
        op.create_index("ix_decision_action_gate", _TABLE, ["action", "gate_allowed"])

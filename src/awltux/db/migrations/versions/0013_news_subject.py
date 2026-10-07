"""An appraisal per story per subject, not per story.

Revision ID: 0013_news_subject
Revises: 0012_inst_sector_group
Create Date: 2026-10-07

``news_item_id`` was ``unique``, so a story got exactly one appraisal however many
things it was about. Measured 2026-10-07: of 19,475 stories, 19,369 name one ticker and
106 name more -- and the 57 that name a sector were appraised as though the sector did
not exist. The appraisal is not the same for each subject, because whether the *subject*
is held is what decides whether the model is asked to read the piece deeply
(``appraise_item``'s ``is_held``), and a sector is held when any instrument in it is.

**The backfill is the honest part of this.** The subject an existing row was built for
was never recorded -- one row per story meant there was nothing to record -- so it is
recovered from the story's own first ticker. That is exactly right for the 19,369
single-ticker stories, which is 99.5% of them, and it is a *guess* for the 106
multi-ticker ones: the row may have been built while a different ticker was in play.
The alternative was to delete them all and re-appraise, which spends model budget to
recover an answer that is right 99.5% of the time already. A re-appraisal overwrites
whichever row it finds for that subject, so the guess corrects itself as the job runs.

Guarded, because ``0001`` builds the schema from the models: applying this to a fresh
database must be a no-op rather than a duplicate-column error.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_news_subject"
down_revision = "0012_inst_sector_group"
branch_labels = None
depends_on = None

_TABLE = "news_analysis"
_ITEM_INDEX = "ix_news_analysis_news_item_id"
_UNIQUE = "uq_news_analysis_subject"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def _unique_constraints(table: str) -> set[str]:
    try:
        found = sa.inspect(op.get_bind()).get_unique_constraints(table)
    except NotImplementedError:  # pragma: no cover - dialect without the inspector
        return set()
    return {constraint["name"] for constraint in found if constraint.get("name")}


def upgrade() -> None:
    present = _columns(_TABLE)
    if "subject_type" in present and "subject_id" in present and _is_done():
        return

    # Three passes rather than one, because the columns are NOT NULL and SQLite will
    # not add a NOT NULL column without a default. Adding them nullable, filling them,
    # then tightening is the only order that leaves no window in which a row could be
    # written without a subject -- and a NULL subject is invisible to the unique
    # constraint below, because SQLite treats NULLs as distinct.
    if "subject_type" not in present:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column("subject_type", sa.String(length=16), nullable=True))
    if "subject_id" not in present:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column("subject_id", sa.String(length=64), nullable=True))

    _backfill(op.get_bind())

    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("subject_type", nullable=False, existing_type=sa.String(length=16))
        batch.alter_column("subject_id", nullable=False, existing_type=sa.String(length=64))

    if _ITEM_INDEX in _indexes(_TABLE):
        op.drop_index(_ITEM_INDEX, table_name=_TABLE)
    op.create_index(_ITEM_INDEX, _TABLE, ["news_item_id"])
    for column in ("subject_type", "subject_id"):
        name = f"ix_{_TABLE}_{column}"
        if name not in _indexes(_TABLE):
            op.create_index(name, _TABLE, [column])
    if _UNIQUE not in _unique_constraints(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.create_unique_constraint(_UNIQUE, ["news_item_id", "subject_type", "subject_id"])


def _is_done() -> bool:
    """Whether the subject columns are already populated, for a re-run."""
    bind = op.get_bind()
    try:
        missing = bind.execute(
            sa.text(f"SELECT count(*) FROM {_TABLE} WHERE subject_id IS NULL OR subject_id = ''")  # noqa: S608
        ).scalar_one()
    except sa.exc.SQLAlchemyError:
        return False
    return int(missing) == 0


def _backfill(bind) -> None:
    """Give every stored appraisal the subject of the story's first ticker.

    Takes its connection rather than reaching for ``op.get_bind()`` so it can be run
    against a real seeded database in a test. The rest of the migration needs Alembic's
    machinery; this half does not, and it is the half that can silently write the wrong
    subject -- ``_first`` is parsing a JSON list out of a ``text()`` query, where no
    column type is in play and the value arrives as a string.

    In Python rather than SQL because the tickers are a JSON list, and because the
    fallback chain -- first ticker, else first sector, else the empty string -- reads
    as one sentence here and as a ``COALESCE`` over ``json_extract`` there.
    """
    tickers = {
        int(row[0]): (row[1], row[2])
        for row in bind.execute(sa.text("SELECT id, tickers, sectors FROM news_item")).all()
    }
    updates = []
    for row in bind.execute(sa.text(f"SELECT id, news_item_id FROM {_TABLE}")).all():  # noqa: S608
        analysis_id, item_id = int(row[0]), int(row[1])
        item_tickers, item_sectors = tickers.get(item_id, (None, None))
        first_ticker = _first(item_tickers)
        first_sector = _first(item_sectors)
        if first_ticker:
            updates.append({"id": analysis_id, "t": "instrument", "s": first_ticker})
        elif first_sector:
            updates.append({"id": analysis_id, "t": "sector", "s": first_sector})
        else:
            updates.append({"id": analysis_id, "t": "instrument", "s": ""})
    if updates:
        bind.execute(
            sa.text(
                f"UPDATE {_TABLE} SET subject_type = :t, subject_id = :s WHERE id = :id"  # noqa: S608
            ),
            updates,
        )


def _first(value: object) -> str:
    """The first element of one of the JSON list columns, as stored by SQLite."""
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str) and value.strip().startswith("["):
        import json

        try:
            parsed = json.loads(value)
        except ValueError:
            return ""
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
    return ""


def downgrade() -> None:
    if _UNIQUE in _unique_constraints(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_constraint(_UNIQUE, type_="unique")
    for column in ("subject_type", "subject_id"):
        name = f"ix_{_TABLE}_{column}"
        if name in _indexes(_TABLE):
            op.drop_index(name, table_name=_TABLE)
        if column in _columns(_TABLE):
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(column)

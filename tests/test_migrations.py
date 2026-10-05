"""The deployment path must migrate an existing database, not just create one.

``init_db`` is ``Base.metadata.create_all``: it creates *missing* tables and never
alters existing ones. So an upgraded application running against a previous
version's data volume keeps the old schema, and every query against a renamed or
newly added column fails at runtime.

This is not hypothetical. When the single ``action`` column was split into two
horizons, the dashboard 500'd against the existing Docker volume while the whole
test suite stayed green -- because tests always build a fresh database, which is
exactly the blind spot these tests close.
"""

from __future__ import annotations

import sqlite3

from awltux.config import Settings
from awltux.db.migrate import current_revision, run_migrations
from awltux.db.session import get_engine, reset_engine

#: Columns 0002 introduces, and the column it renames.
HORIZON_COLUMNS = (
    "short_term_composite",
    "short_term_composite_score",
    "short_term_action",
    "short_term_confidence",
    "short_term_gate",
    "short_term_gate_allowed",
    "horizon_fit",
)


def columns(db_path, table: str) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    finally:
        connection.close()


def strip_to_old_schema(db_path) -> None:
    """Remove the two-horizon shape, leaving a pre-0002 database behind.

    Rewinding ``alembic_version`` is part of the simulation, not an afterthought:
    without it Alembic correctly concludes the database is already at head and
    does nothing, and the test would pass while proving nothing.
    """
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        # Indexes must go first: SQLite refuses to drop a column that an index
        # still references. Recreating the pre-0002 indexes keeps the simulation
        # faithful, so the migration's index handling is genuinely exercised.
        for name in (
            "ix_decision_run_long_term_action",
            "ix_decision_run_short_term_action",
            "ix_decision_run_short_term_composite_score",
            "ix_decision_run_short_term_gate_allowed",
            "ix_decision_run_horizon_fit",
            "ix_decision_long_gate",
            "ix_decision_short_gate",
        ):
            connection.execute(f"DROP INDEX IF EXISTS {name}")

        for name in HORIZON_COLUMNS:
            connection.execute(f"ALTER TABLE decision_run DROP COLUMN {name}")
        connection.execute("ALTER TABLE decision_run RENAME COLUMN long_term_action TO action")
        connection.execute("CREATE INDEX ix_decision_run_action ON decision_run (action)")
        connection.execute(
            "CREATE INDEX ix_decision_action_gate ON decision_run (action, gate_allowed)"
        )

        # decision_outcome references `horizon` in an index and a unique
        # constraint, so SQLite refuses to drop the column -- rebuild the table.
        connection.execute("DROP INDEX IF EXISTS ix_decision_outcome_horizon")
        connection.execute("DROP TABLE IF EXISTS decision_outcome")
        connection.execute(
            """
            CREATE TABLE decision_outcome (
                id INTEGER NOT NULL PRIMARY KEY,
                decision_run_id INTEGER NOT NULL
                    REFERENCES decision_run(id) ON DELETE CASCADE,
                horizon_days INTEGER NOT NULL,
                price_at_decision FLOAT,
                price_at_horizon FLOAT,
                return_pct FLOAT,
                benchmark_return_pct FLOAT,
                verdict VARCHAR(24),
                computed_at DATETIME NOT NULL,
                CONSTRAINT uq_outcome_horizon UNIQUE (decision_run_id, horizon_days)
            )
            """
        )
        # Rewind the recorded revision so the upgrade has something to do.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute("DELETE FROM alembic_version")
        connection.execute("INSERT INTO alembic_version VALUES ('0001_initial')")
        connection.commit()
    finally:
        connection.close()


def seed_decision(settings: Settings, *, action: str | None = None) -> None:
    """Insert one instrument and one decision, using the ORM.

    Raw SQL would have to enumerate every NOT NULL column and satisfy the foreign
    key by hand; the point of these tests is the migration, not the insert.
    """
    from awltux.db import DecisionRun, Instrument, session_scope, utcnow

    reset_engine()
    with session_scope() as session:
        session.add(
            Instrument(
                t212_ticker="TEST_US_EQ",
                name="Test Industries",
                currency_code="USD",
                instrument_type="STOCK",
                yahoo_symbol="TEST",
                in_universe=True,
            )
        )
        session.flush()
        session.add(
            DecisionRun(
                instrument_t212_ticker="TEST_US_EQ",
                created_at=utcnow(),
                state={"instrument": {"ticker": "TEST_US_EQ"}},
                state_sha256="0" * 64,
                questions={"definitions": {}},
                engine="offline",
                answers={"long_term_action": {"type": "choice", "value": "buy"}},
                app_version="0.1.0",
                long_term_action=action,
            )
        )


def head_revision() -> str:
    """The current head, read from the migration scripts.

    Looked up rather than hardcoded: a test that has to be edited every time a
    migration is added stops being a regression test and becomes a chore.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from awltux.db.migrate import _paths

    config_path, script_location = _paths()
    config = Config(str(config_path))
    config.set_main_option("script_location", str(script_location))
    return ScriptDirectory.from_config(config).get_current_head()


class TestMigrationPath:
    def test_a_fresh_database_reaches_head(self, settings: Settings):
        reset_engine()
        revision = run_migrations(settings)
        assert revision == head_revision()
        assert set(HORIZON_COLUMNS) <= columns(settings.db_path, "decision_run")
        assert "horizon" in columns(settings.db_path, "decision_outcome")
        # 0003's column, so a fresh database gets the exchange reference too.
        assert "exchange_id" in columns(settings.db_path, "instrument")

    def test_migrating_twice_is_idempotent(self, settings: Settings):
        """A container restarts often; a migration that requires a clean database
        would be unusable."""
        reset_engine()
        first = run_migrations(settings)
        reset_engine()
        second = run_migrations(settings)
        assert first == second == head_revision()

    def test_an_existing_old_database_is_upgraded(self, settings: Settings):
        """The case that actually broke: rows already present, schema out of date."""
        reset_engine()
        run_migrations(settings)
        seed_decision(settings)

        strip_to_old_schema(settings.db_path)
        assert "action" in columns(settings.db_path, "decision_run")
        assert not set(HORIZON_COLUMNS) & columns(settings.db_path, "decision_run")

        # The app would be serving 500s at this point. Migrating must fix it.
        reset_engine()
        revision = run_migrations(settings)

        assert revision == head_revision()
        shape = columns(settings.db_path, "decision_run")
        assert "long_term_action" in shape
        assert "action" not in shape
        assert set(HORIZON_COLUMNS) <= shape

    def test_existing_rows_survive_and_keep_their_verdict(self, settings: Settings):
        """Migrating must not lose history, and must not invent a tactical verdict."""
        reset_engine()
        run_migrations(settings)
        seed_decision(settings, action="buy")

        strip_to_old_schema(settings.db_path)
        reset_engine()
        run_migrations(settings)

        connection = sqlite3.connect(settings.db_path)
        try:
            rows = list(
                connection.execute(
                    "SELECT long_term_action, short_term_action FROM decision_run"
                )
            )
        finally:
            connection.close()

        assert rows == [("buy", None)], (
            "the long-term verdict should carry across, and the short-term one "
            "should stay NULL: inventing a tactical verdict for a decision made "
            "before that horizon existed would fabricate a judgement"
        )

    def test_current_revision_reports_what_the_database_holds(self, settings: Settings):
        reset_engine()
        run_migrations(settings)
        assert current_revision() == head_revision()

    def test_the_container_runs_migrations_before_serving(self):
        """A guard on the deployment wiring, not the code.

        If the image stops running ``migrate`` on start, an existing volume
        silently keeps an old schema and the app serves 500s -- which is precisely
        how this went unnoticed the first time.
        """
        dockerfile = __import__("pathlib").Path(__file__).resolve().parent.parent / "Dockerfile"
        text = dockerfile.read_text(encoding="utf-8")
        assert "awltux.cli migrate" in text, "the image must migrate on startup"
        assert "alembic.ini" in text, "the image must ship alembic.ini to migrate"

    def test_get_engine_is_not_needed_by_the_migration_path(self, settings: Settings):
        """Migrations run before the app opens its engine, so they must not depend
        on one already existing."""
        reset_engine()
        run_migrations(settings)
        assert get_engine(settings) is not None

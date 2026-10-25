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

import json
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
        # 0007's flag: whether the shareholders' reports are held.
        assert {"annual_reports", "reports_synced_at"} <= columns(
            settings.db_path, "instrument"
        )
        # 0032's column: the captions a source states that no canonical metric claims, which is
        # what lets the accounts page offer a line this project's vocabulary has no name for.
        assert "presentation" in columns(settings.db_path, "fundamental_period")
        # 0033's column: when the fundamentals sweep last *attempted* an instrument, which is the
        # queue's cursor -- keyed on a success, a name the provider cannot serve never advances.
        assert "fundamentals_checked_at" in columns(settings.db_path, "instrument")

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


class TestTheSubjectBackfill:
    """0013 gives every stored appraisal a subject, and it had 2,934 rows to do it to.

    The subject a row was built for was never recorded -- one row per story meant there
    was nothing to record -- so it is recovered from the story's own first ticker. Exact
    for the 19,369 single-ticker stories (99.5% of them), a documented guess for the 106
    multi-ticker ones.

    Tested by calling the backfill rather than by replaying Alembic, because the
    backfill is where a wrong answer hides and it needs no migration machinery: the
    tickers arrive from a ``text()`` query as a *string*, with nothing about the column
    type in play, and that is the parse this pins down.
    """

    def _module(self):
        import importlib

        return importlib.import_module("awltux.db.migrations.versions.0013_news_subject")

    def _backfill(self, settings):
        from awltux.db.session import get_engine

        with get_engine(settings).begin() as connection:
            self._module()._backfill(connection)

    def _seed(self, settings, *, tickers, sectors, title="Acme warns"):
        """A story and a placeholder appraisal, as migration 0012 would have left them."""
        connection = sqlite3.connect(settings.db_path)
        try:
            connection.execute(
                "INSERT INTO news_item (source, url, url_hash, title, tickers, sectors, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "google_news",
                    "https://x.test/1",
                    f"hash-{title}",
                    title,
                    json.dumps(tickers),
                    json.dumps(sectors),
                    "2026-01-01 00:00:00",
                    "2026-01-01 00:00:00",
                ),
            )
            item_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            connection.execute(
                "INSERT INTO news_analysis (news_item_id, source_domain, source_biases, "
                "credibility, flags, warnings, caveats, claims, omissions, techniques, "
                "corroboration, factors, analysed_at, created_at, subject_type, subject_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    "x.test",
                    "[]",
                    0.5,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    "{}",
                    "{}",
                    "2026-01-01 00:00:00",
                    "2026-01-01 00:00:00",
                    "instrument",
                    "PLACEHOLDER",
                ),
            )
            connection.commit()
            return item_id
        finally:
            connection.close()

    def _subject(self, settings, item_id):
        connection = sqlite3.connect(settings.db_path)
        try:
            return connection.execute(
                "SELECT subject_type, subject_id FROM news_analysis WHERE news_item_id = ?",
                (item_id,),
            ).fetchone()
        finally:
            connection.close()

    def test_the_first_ticker_becomes_the_subject(self, settings: Settings):
        reset_engine()
        run_migrations(settings)
        item_id = self._seed(settings, tickers=["ACME_US_EQ", "BETA_US_EQ"], sectors=[])

        self._backfill(settings)

        assert self._subject(settings, item_id) == ("instrument", "ACME_US_EQ"), (
            "the first ticker as stored, not the alphabetically smallest"
        )

    def test_a_story_with_no_ticker_falls_back_to_its_sector(self, settings: Settings):
        reset_engine()
        run_migrations(settings)
        item_id = self._seed(settings, tickers=[], sectors=["Industrials"])

        self._backfill(settings)

        assert self._subject(settings, item_id) == ("sector", "Industrials")

    def test_a_story_with_neither_is_still_given_a_subject(self, settings: Settings):
        """The columns are NOT NULL, so a row left NULL would fail the migration -- and
        a NULL is invisible to the unique constraint, because SQLite treats NULLs as
        distinct, so two such rows would both be accepted."""
        reset_engine()
        run_migrations(settings)
        item_id = self._seed(settings, tickers=[], sectors=[])

        self._backfill(settings)

        assert self._subject(settings, item_id) == ("instrument", "")

    def test_the_container_runs_migrations_before_serving(self):
        """A guard on the deployment wiring, not the code.

        If the image stops running ``migrate`` on start, an existing volume
        silently keeps an old schema and the app serves 500s -- which is precisely
        how this went unnoticed the first time.

        Since 2026-10-20 the container runs a supervisor rather than a chained command, so the
        guard follows the chain the image actually takes: the Dockerfile's CMD names a script,
        and that script migrates **before** it starts either process. The *order* is the part
        worth asserting -- a script that migrated after `serve` would have the same failure.
        """
        from pathlib import Path

        repo = Path(__file__).resolve().parent.parent
        dockerfile = (repo / "Dockerfile").read_text(encoding="utf-8")
        assert "alembic.ini" in dockerfile, "the image must ship alembic.ini to migrate"

        script_name = next(
            (line for line in dockerfile.splitlines() if "entrypoint.sh" in line and "COPY" in line),
            None,
        )
        assert script_name is not None, "the image must copy the supervisor it runs"

        script = (repo / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        migrate_at = script.find("awltux.cli migrate")
        serve_at = script.find("awltux.cli serve")
        assert migrate_at != -1, "the container must migrate on startup"
        assert -1 < migrate_at < serve_at, (
            "the migration must run before the server starts, or an old volume serves 500s"
        )

    def test_serve_migrates_before_starting_the_server(self, settings, monkeypatch):
        """`serve` used to call only init_db, which creates missing tables and
        never alters existing ones.

        So a local run against a database from a previous version died at the first
        query with a raw ``no such column``. The container was immune because the
        image chains ``migrate && serve``; the source path was not, and that is the
        path a developer uses.
        """
        import awltux.cli as cli
        import awltux.db.migrate as migrate

        calls: list[str] = []
        monkeypatch.setattr(migrate, "run_migrations", lambda *a, **k: calls.append("migrate") or "head")
        monkeypatch.setattr(
            "uvicorn.run", lambda *a, **k: calls.append("serve")
        )

        code = cli.main(["serve"])

        assert code == 0
        assert calls == ["migrate", "serve"], "migration must happen before serving"

    def test_serve_still_starts_when_migration_fails(self, settings, monkeypatch):
        """A migration failure must not turn a recoverable state into a dead one.

        On a fresh database init_db still builds the schema during the app's
        lifespan, so refusing to start would break the simplest case in order to
        protect the rarest one.
        """
        import awltux.cli as cli
        import awltux.db.migrate as migrate

        def explode(*_a, **_k):
            raise FileNotFoundError("alembic.ini not found")

        started: list[str] = []
        monkeypatch.setattr(migrate, "run_migrations", explode)
        monkeypatch.setattr("uvicorn.run", lambda *a, **k: started.append("serve"))

        assert cli.main(["serve"]) == 0
        assert started == ["serve"]

    def test_get_engine_is_not_needed_by_the_migration_path(self, settings: Settings):
        """Migrations run before the app opens its engine, so they must not depend
        on one already existing."""
        reset_engine()
        run_migrations(settings)
        assert get_engine(settings) is not None


def _other_settings(temp_dir, config_file):
    """A second, independent database beside the fixture's own."""
    from awltux.config import EnvSettings, build_settings

    other_dir = temp_dir / "other"
    other_dir.mkdir(parents=True, exist_ok=True)
    return build_settings(
        EnvSettings(
            _env_file=None,
            data_dir=other_dir,
            config_file=config_file,
            log_level="WARNING",
        )
    )


def _revision_recorded(db_path) -> str | None:
    connection = sqlite3.connect(db_path)
    try:
        try:
            rows = list(connection.execute("SELECT version_num FROM alembic_version"))
        except sqlite3.Error:
            return None
        return rows[0][0] if rows else None
    finally:
        connection.close()


class TestTheTargetDatabaseIsTheOneThatWasAskedFor:
    """``run_migrations(settings)`` must migrate *that* database.

    It did not. ``env.py`` re-resolved the URL from the process-wide
    ``get_settings()`` singleton, so the argument was ignored whenever the two
    disagreed. In the test suite they never disagree -- ``conftest`` patches every
    module's ``get_settings`` -- which is exactly why it went unnoticed until a
    rehearsal against a *copy* of a database migrated the original instead.
    """

    def test_the_argument_wins_over_the_ambient_settings(
        self, settings: Settings, temp_dir, config_file
    ):
        other = _other_settings(temp_dir, config_file)

        reset_engine()
        revision = run_migrations(other)

        assert revision == head_revision()
        assert _revision_recorded(other.db_path) == head_revision(), (
            "the database named by the argument must be the one migrated"
        )
        assert _revision_recorded(settings.db_path) is None, (
            "the ambient database must be left alone"
        )

    def test_a_backup_is_taken_before_a_pending_migration(
        self, settings: Settings, temp_dir, config_file
    ):
        """An out-of-date database is copied aside before it is rewritten."""
        other = _other_settings(temp_dir, config_file)

        # Build it, then rewind so there is genuinely something to upgrade.
        reset_engine()
        run_migrations(other)
        strip_to_old_schema(other.db_path)

        backups = other.db_path.parent / "backups"
        before = sorted(backups.glob("*.db"))

        reset_engine()
        run_migrations(other)

        after = sorted(backups.glob("*.db"))
        assert len(after) == len(before) + 1, "a migration must leave a way back"
        assert _revision_recorded(after[-1]) != head_revision(), (
            "the backup must be the pre-migration state"
        )

    def test_a_no_op_run_does_not_accumulate_backups(
        self, settings: Settings, temp_dir, config_file
    ):
        """Every container start migrates, and almost all of them have nothing to
        do. A backup per start would bury the ones that matter."""
        other = _other_settings(temp_dir, config_file)

        reset_engine()
        run_migrations(other)

        backups = other.db_path.parent / "backups"
        after_first = sorted(backups.glob("*.db"))

        reset_engine()
        run_migrations(other)

        assert sorted(backups.glob("*.db")) == after_first

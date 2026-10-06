"""Programmatic Alembic migrations, for the deployment path.

``init_db`` (which is ``Base.metadata.create_all``) creates *missing* tables but
never alters existing ones. That is fine for a fresh install and for tests, but it
means an upgraded application running against a previous version's database volume
would keep the old schema -- and every query against a renamed or added column
would fail at runtime.

That is not hypothetical: it happened when the single ``action`` column was split
into two horizons. The dashboard pages 500'd against an existing volume while the
tests -- which always build a fresh database -- were perfectly green.

So the deployment path runs migrations. ``0001`` is a metadata-generated baseline
whose ``create_all`` is a no-op on existing tables, and ``0002`` is inspection-
guarded, so ``upgrade head`` is correct for both a brand-new database and one
created by an earlier version.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from awltux.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _paths() -> tuple[Path, Path]:
    """Locate ``alembic.ini`` and the migrations directory.

    Neither path can be derived from one assumption, because the two layouts
    differ:

    * **Migrations** are always a sibling of this module (``awltux/db/migrations``),
      which holds in the repository *and* when the package is installed into
      site-packages. So that one is derived directly and cannot drift.
    * **``alembic.ini``** is a repository-root file that is not part of the
      package, so it is *searched* for rather than computed -- and the search
      includes ``AWLTUX_ALEMBIC_INI`` so a deployment can be explicit.

    Getting this wrong is not cosmetic: the container reported "alembic.ini not
    found at /opt/venv/lib/python3.12/alembic.ini" and then served a stale schema.
    """
    migrations = Path(__file__).resolve().parent / "migrations"

    candidates: list[Path] = []
    if configured := os.environ.get("AWLTUX_ALEMBIC_INI"):
        candidates.append(Path(configured))
    candidates.append(Path.cwd() / "alembic.ini")
    # Walk up from this file; covers both <repo>/src/awltux/db and
    # <site-packages>/awltux/db.
    candidates.extend(parent / "alembic.ini" for parent in Path(__file__).resolve().parents)
    candidates.append(Path("/app/alembic.ini"))

    for candidate in candidates:
        if candidate.is_file():
            return candidate, migrations

    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"alembic.ini not found (searched: {searched}). Set AWLTUX_ALEMBIC_INI to "
        "point at it explicitly."
    )


def run_migrations(settings: Settings | None = None) -> str:
    """Bring the database up to ``head``. Returns the resulting revision."""
    from alembic import command
    from alembic.config import Config

    settings = settings or get_settings()
    settings.ensure_dirs()

    config_path, script_location = _paths()
    if not config_path.exists():
        raise FileNotFoundError(
            f"alembic.ini not found at {config_path}; cannot migrate the database"
        )

    config = Config(str(config_path))
    config.set_main_option("script_location", str(script_location))
    # Set explicitly so migration never depends on whatever alembic.ini happens
    # to contain, and always targets the database the app actually uses. The same
    # value travels in ``attributes`` because ``env.py`` is executed by Alembic
    # and would otherwise re-resolve it from the process-wide settings singleton,
    # silently ignoring the ``settings`` argument this function was given.
    config.set_main_option("sqlalchemy.url", settings.database_url)
    config.attributes["awltux_database_url"] = settings.database_url
    config.attributes["configure_logger"] = False

    if _has_pending_revisions(config):
        # The database is about to be rewritten, and it holds every fact this
        # system has recorded. Copy it first: SQLite makes that one cheap,
        # self-contained file copy, so there is no reason to alter it without a
        # way back.
        backup = _backup_database(settings)
        if backup is not None:
            logger.info("backed the database up to %s before migrating", backup)

    logger.info("running database migrations against %s", settings.db_path)
    command.upgrade(config, "head")

    revision = current_revision(config)
    logger.info("database is at revision %s", revision)
    return revision


def _head_revision(config) -> str:
    """The newest revision in the migration scripts."""
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(config).get_current_head()


def _has_pending_revisions(config) -> bool:
    """Whether ``upgrade head`` would write anything.

    Used to decide if a backup is worth taking. A no-op run is common -- every
    container start performs one -- and a backup per no-op would bury the backups
    that matter.
    """
    try:
        return current_revision(config) != _head_revision(config)
    except Exception as exc:  # pragma: no cover - unreadable database
        logger.warning("could not compare revisions (%s); backing up anyway", exc)
        return True


def _backup_database(settings: Settings) -> Path | None:
    """Copy the database alongside itself, returning the copy's path.

    A failure here is logged and not raised. Refusing to migrate because the
    backup could not be written would turn a read-only backup directory into an
    application that will not start, which is a worse failure than the one the
    backup exists to prevent.
    """
    import datetime as dt
    import shutil

    db_path = settings.db_path
    if not db_path.exists():
        return None

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    destination = db_path.parent / "backups" / f"{db_path.stem}-{stamp}.db"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_path, destination)
    except OSError as exc:
        logger.warning("could not back up %s (%s); migrating anyway", db_path, exc)
        return None
    return destination


def current_revision(config=None) -> str | None:
    """The revision recorded in the database, or ``None`` if it has none."""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    if config is None:
        config_path, script_location = _paths()
        config = Config(str(config_path))
        config.set_main_option("script_location", str(script_location))
        config.set_main_option("sqlalchemy.url", get_settings().database_url)

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

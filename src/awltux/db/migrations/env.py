"""Alembic environment.

The database URL is taken from the application's own settings rather than
``alembic.ini``, so migrations always target the same database the app uses --
including the ``/data`` volume path inside the container. A URL duplicated in a
config file is a URL that will eventually point somewhere else.

**A URL chosen by the caller wins.** :func:`awltux.db.migrate.run_migrations` may
be handed an explicit ``Settings``, and it used to set the URL on the config only
for this module to overwrite it with the process-wide ``get_settings()``
singleton. So the argument was silently ignored and the migration targeted
whatever the *environment* resolved. That is not a harmless inconsistency: it
turned a rehearsal against a copy of the database into a migration of the live
one. The caller's URL now arrives in ``config.attributes`` and takes precedence,
falling back to ``get_settings()`` for a bare ``alembic upgrade`` from the CLI.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from awltux.config import get_settings
from awltux.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
database_url = config.attributes.get("awltux_database_url") or settings.database_url
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rebuilds the table
        # instead, which is what makes column changes possible at all.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_config
from app.db import models  # noqa: F401  (registers all seven tables on Base.metadata)
from app.db.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The ORM metadata is the single source of truth for autogenerate. The database
# URL comes from the app's own config (DATA_DIR), not from alembic.ini, so there
# is exactly one place that env var is interpreted.
target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_config().sync_database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # render_as_batch=True (Phase 1 decision, approved): SQLite has no ALTER TABLE
        # ADD/DROP CONSTRAINT, so a later migration that changes a constraint must
        # recreate the table. Batch mode does that automatically. foreign_keys stays
        # off on this connection (SQLite's default) because batch mode drops and
        # recreates tables; with it on, that could fire an ON DELETE CASCADE.
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

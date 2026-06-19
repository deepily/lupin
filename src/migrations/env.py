from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Resolve the SQLAlchemy URL from a SINGLE source of truth.
#
# Resolution order (first hit wins):
#   1. DATABASE_URL env var          — explicit override (CI, ad-hoc, legacy).
#   2. config.attributes["injected_db_url"] — a URL injected programmatically
#      by the in-process auto-migrator / tests (e.g. a throwaway test DB).
#   3. cosa.rest.db.database.get_database_url() — the APP'S OWN builder, so
#      alembic connects EXACTLY like the running app in every environment
#      (local dev, testing, cloud Cloud-SQL socket). NO duplicated connection
#      logic lives here.
#
# `config.attributes` is a plain dict (no configparser interpolation), so a URL
# containing '%' or a '/cloudsql/...' socket path passes through untouched;
# set_main_option escapes '%' for the configparser layer.
database_url = os.environ.get( "DATABASE_URL" )
if not database_url:
    database_url = config.attributes.get( "injected_db_url" )
if not database_url:
    from cosa.rest.db.database import get_database_url
    database_url = get_database_url()
config.set_main_option( "sqlalchemy.url", database_url )

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from cosa.rest.postgres_models import Base
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


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
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

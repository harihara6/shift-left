"""Alembic environment. Runs migrations over the same async engine settings the service uses."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.core.config import get_settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# An explicit -x url=... or a URL set programmatically (the migration test) wins over settings.
url = context.get_x_argument(as_dictionary=True).get("url") or config.get_main_option("sqlalchemy.url")
if not url:
    url = get_settings().database_url
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def _configure(connection: Connection | None = None) -> None:
    context.configure(
        connection=connection,
        url=None if connection is not None else url,
        target_metadata=target_metadata,
        literal_binds=connection is None,
        compare_type=True,
        # SQLite cannot ALTER most things in place; batch mode rebuilds the table instead.
        render_as_batch=url.startswith("sqlite"),
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout (`alembic upgrade head --sql`) for a DBA to review and apply."""
    _configure()
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

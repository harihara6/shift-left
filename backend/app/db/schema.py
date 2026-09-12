"""Keeping a local database at the schema the models declare.

Alembic owns the schema in every deployed environment (`make migrate` before start). Locally the
service has always built its own, so development stays one command - but `create_all` only ever
*adds* tables. It cannot add a column to a table that already exists, and it leaves no revision
stamp, so a database built that way could not be migrated either. A model change then reached the
developer as a 500 at request time, from a column the database had never heard of.

So startup now reconciles rather than assumes:

* **A fresh database** is built by `create_all` and stamped at head - true by construction, and it
  means every later revision applies to it normally.
* **A stamped database behind head** is upgraded, which is what a developer pulling a schema change
  wants to happen by itself.
* **A database that is neither** - built by an older `create_all`, missing columns, unstamped -
  cannot have its revision guessed, so the service refuses to start and says the two commands that
  fix it. Refusing is the point: the alternative is the 500 this replaced.

`SHIFTLEFT_AUTO_CREATE_SCHEMA=false` turns all of it off, which is what deployments run with.
"""

import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

import app.models  # noqa: F401 - registers every table on Base.metadata, as migrations/env.py does
from app.db.base import Base

logger = logging.getLogger("shiftleft")
BACKEND = Path(__file__).resolve().parents[2]


class SchemaBehind(RuntimeError):
    """The database is missing something the models declare, and cannot be reconciled here."""


def _config() -> Config:
    """Alembic's own configuration, resolved from this file rather than the working directory."""
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head() or ""


def _stamp(connection: Connection) -> str:
    return MigrationContext.configure(connection).get_current_revision() or ""


def _missing(connection: Connection) -> dict[str, list[str]]:
    """Per table, the columns the models declare that the database doesn't have.

    Only what is absent: a column the database has and the models don't is somebody's own, and
    dropping it is not this function's business.
    """
    inspector = inspect(connection)
    present = set(inspector.get_table_names())
    gaps: dict[str, list[str]] = {}
    for name, table in Base.metadata.tables.items():
        if name not in present:
            # The whole table: listing its columns would bury the point.
            gaps[name] = []
            continue
        have = {c["name"] for c in inspector.get_columns(name)}
        if absent := [c.name for c in table.columns if c.name not in have]:
            gaps[name] = absent
    return gaps


def _tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names()) - {"alembic_version"}


async def reconcile(engine: AsyncEngine) -> None:
    """Bring the local database to the schema the models declare, or say exactly why it can't be."""
    async with engine.begin() as conn:
        existing = await conn.run_sync(_tables)
        stamp = await conn.run_sync(_stamp)

    if not existing:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # Built from the models, so it *is* head. Saying so is what lets later revisions apply.
        await asyncio.to_thread(command.stamp, _config(), "head")
        logger.info("Created the local schema and stamped it at %s", head())
        return

    if stamp and stamp != head():
        # Alembic's env.py starts its own loop, so it runs off this one.
        await asyncio.to_thread(command.upgrade, _config(), "head")
        logger.info("Upgraded the local schema from %s to %s", stamp, head())

    async with engine.begin() as conn:
        gaps = await conn.run_sync(_missing)
    if not gaps:
        if not stamp:
            # Already matches the models, just never stamped: recording that is safe and true.
            await asyncio.to_thread(command.stamp, _config(), "head")
            logger.info("Stamped the existing local schema at %s", head())
        return

    behind = "; ".join(
        f"{table} is missing entirely" if not columns else f"{table} is missing {', '.join(columns)}"
        for table, columns in sorted(gaps.items())
    )
    raise SchemaBehind(
        f"The database is behind the models: {behind}. It has tables but no Alembic revision, so "
        "the revision it matches can't be guessed here. Stamp it at the last revision its schema "
        "already contains and upgrade - for a database from before this check, that is "
        "`cd backend && .venv/bin/alembic stamp 0004 && .venv/bin/alembic upgrade head`. "
        "Check `alembic history` if you are not sure which revision to stamp."
    )

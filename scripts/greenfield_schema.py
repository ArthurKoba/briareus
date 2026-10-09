"""Explicit *dev-only* greenfield schema initializer; never called at startup.

No legacy tables are imported, and no existing database is upgraded. An
operator must provide a dedicated disposable DB and the explicit dev guard.
This is not an Alembic revision or a production installation workflow.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.schema import CreateSchema

from authorization.platform_composition import platform_metadata
from common.platform_db import PlatformDatabase, PlatformDatabaseSettings

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

SCHEMAS = (
    "identity",
    "teams",
    "projects",
    "agents",
    "authorization",
    "sessions",
    "resources",
    "runtime",
    "files",
    "reverse",
)


def _require_empty(connection: Connection) -> None:
    """Refuse any preexisting *user* relation, including unknown schemas.

    Checking only the ten intended domains could otherwise let a stale
    public.legacy_users, foreign Project or independent application coexist
    with a purportedly disposable empty greenfield database. The guard
    accounts for views, materialized views, sequences and foreign tables.
    """
    relation = connection.execute(
        text(
            """
            SELECT n.nspname, c.relname
              FROM pg_catalog.pg_class AS c
              JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname !~ '^pg_'
               AND n.nspname <> 'information_schema'
               AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
             ORDER BY n.nspname, c.relname
             LIMIT 1
            """
        )
    ).first()
    if relation is not None:
        # Only non-sensitive object kinds are reported, never connection
        # details, ownership, table content or credentials.
        raise RuntimeError(
            "refusing nonempty disposable dev database: "
            "preexisting user relation present"
        )


async def initialize() -> None:
    settings = PlatformDatabaseSettings()
    database = PlatformDatabase(settings)
    metadata = platform_metadata()
    try:
        async with database.engine.begin() as connection:
            name = (await connection.execute(text("SELECT current_database()"))).scalar_one()
            if not isinstance(name, str) or not name.endswith("_dev"):
                raise RuntimeError("refusing database whose name does not end in '_dev'")
            claimed = (
                await connection.execute(
                    text("SELECT pg_try_advisory_xact_lock(47071, 7)")
                )
            ).scalar_one()
            if not claimed:
                raise RuntimeError("dev schema creation already in progress")
            await connection.run_sync(_require_empty)
            for schema in SCHEMAS:
                await connection.execute(CreateSchema(schema, if_not_exists=True))
            await connection.run_sync(metadata.create_all)
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--i-confirm-disposable-empty-dev-db", action="store_true", required=True)
    args = parser.parse_args()
    if not args.i_confirm_disposable_empty_dev_db:
        raise SystemExit("a disposable database confirmation is required")
    asyncio.run(initialize())


if __name__ == "__main__":
    main()

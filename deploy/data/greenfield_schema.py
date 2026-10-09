"""Explicit *dev-only* greenfield schema initializer; never called at startup.

No legacy tables are imported, and no existing database is upgraded. An
operator must provide a dedicated disposable DB and the explicit dev guard.
This is not an Alembic revision or a production installation workflow.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text
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
    inspector = inspect(connection)
    for schema in SCHEMAS:
        if schema in inspector.get_schema_names():
            tables = inspector.get_table_names(schema=schema)
            if tables:
                raise RuntimeError(
                    f"refusing to initialize nonempty schema: {schema} has {len(tables)} tables"
                )


async def initialize() -> None:
    settings = PlatformDatabaseSettings()
    database = PlatformDatabase(settings)
    metadata = platform_metadata()
    try:
        async with database.engine.begin() as connection:
            name = (await connection.execute(text("SELECT current_database()"))).scalar_one()
            if not name.endswith("_dev"):
                raise RuntimeError("refusing database whose name does not end in '_dev'")
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

"""Greenfield disposable-dev Alembic; revisions stay outside source Git."""

from __future__ import annotations

import asyncio

from alembic import context
from alembic.script import ScriptDirectory
from pydantic import Field, SecretStr
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.schema import CreateSchema

from authorization.platform_composition import platform_metadata
from common.settings import ProcessSettings

config = context.config


class DevMigrationSettings(ProcessSettings):
    database_url: SecretStr = Field(validation_alias="PLATFORM_DATABASE_URL")


settings = DevMigrationSettings()
url = settings.database_url.get_secret_value()
if not url.startswith("postgresql+asyncpg://"):
    raise ValueError("PLATFORM_DATABASE_URL must use postgresql+asyncpg")

target_metadata = platform_metadata()


def _require_approved_migration_head() -> None:
    # No source-tracked initial Alembic revision exists yet. Silently
    # running "upgrade head" against a new dev DB would otherwise report
    # success after creating an empty version table but NO platform tables.
    # Revisions are generated and independently accepted in local/ only.
    if not ScriptDirectory.from_config(config).get_heads():
        raise RuntimeError(
            "no approved greenfield Alembic revision exists; "
            "use the guarded disposable-dev schema initializer only"
        )


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


def _configure_and_run(connection: Connection) -> None:
    database = connection.execute(text("SELECT current_database()")).scalar_one()
    if not str(database).endswith("_dev"):
        raise RuntimeError("Alembic is restricted to explicitly named disposable *_dev DBs")
    for schema in SCHEMAS:
        connection.execute(CreateSchema(schema, if_not_exists=True))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema="authorization",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    # SQL output is not proof of an applied schema.
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="authorization",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_configure_and_run)
    finally:
        await engine.dispose()


_require_approved_migration_head()
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_online())

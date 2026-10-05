from __future__ import annotations

import asyncio
import os
import re

import asyncpg

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _identifier(value: str, *, name: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise RuntimeError(f"{name} must be a simple PostgreSQL identifier")
    return value


async def _quoted(connection: asyncpg.Connection, value: str, *, literal: bool) -> str:
    function = "quote_literal" if literal else "quote_ident"
    result = await connection.fetchval(f"SELECT {function}($1)", value)
    if not isinstance(result, str):
        raise RuntimeError(f"PostgreSQL failed to quote {value!r}")
    return result


async def _ensure_role(
    connection: asyncpg.Connection,
    *,
    role: str,
    password: str,
) -> None:
    role = _identifier(role, name="service role")
    quoted_role = await _quoted(connection, role, literal=False)
    quoted_password = await _quoted(connection, password, literal=True)
    exists = await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role)
    if exists:
        await connection.execute(
            f"ALTER ROLE {quoted_role} WITH LOGIN NOSUPERUSER NOCREATEDB "
            f"NOCREATEROLE NOREPLICATION PASSWORD {quoted_password}"
        )
        return
    await connection.execute(
        f"CREATE ROLE {quoted_role} WITH LOGIN NOSUPERUSER NOCREATEDB "
        f"NOCREATEROLE NOREPLICATION PASSWORD {quoted_password}"
    )


async def _ensure_database(
    connection: asyncpg.Connection,
    *,
    database: str,
    owner: str,
) -> None:
    database = _identifier(database, name="service database")
    owner = _identifier(owner, name="service role")
    quoted_database = await _quoted(connection, database, literal=False)
    quoted_owner = await _quoted(connection, owner, literal=False)
    exists = await connection.fetchval(
        "SELECT 1 FROM pg_database WHERE datname=$1",
        database,
    )
    if not exists:
        await connection.execute(
            f"CREATE DATABASE {quoted_database} OWNER {quoted_owner}"
        )
    else:
        await connection.execute(
            f"ALTER DATABASE {quoted_database} OWNER TO {quoted_owner}"
        )
    await connection.execute(f"REVOKE ALL ON DATABASE {quoted_database} FROM PUBLIC")
    await connection.execute(
        f"GRANT CONNECT, TEMPORARY ON DATABASE {quoted_database} TO {quoted_owner}"
    )


async def main() -> None:
    admin_host = _env("POSTGRES_HOST", "postgres")
    admin_port = int(_env("POSTGRES_PORT", "5432"))
    admin_database = _env("POSTGRES_DB", "mcp-bridge")
    admin_user = _env("POSTGRES_USER")
    admin_password = _env("POSTGRES_PASSWORD")

    services = (
        (
            _env("AUTH_POSTGRES_DB", "auth"),
            _env("AUTH_POSTGRES_USER"),
            _env("AUTH_POSTGRES_PASSWORD"),
        ),
        (
            _env("ACCESS_POSTGRES_DB", "access"),
            _env("ACCESS_POSTGRES_USER"),
            _env("ACCESS_POSTGRES_PASSWORD"),
        ),
    )

    connection = await asyncpg.connect(
        host=admin_host,
        port=admin_port,
        database=admin_database,
        user=admin_user,
        password=admin_password,
    )
    try:
        for database, role, password in services:
            await _ensure_role(connection, role=role, password=password)
            await _ensure_database(connection, database=database, owner=role)
            print(f"ready database={database} role={role}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())

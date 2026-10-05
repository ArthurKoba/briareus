from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, func, insert, select, text
from sqlalchemy.sql.schema import Column, Table

from .database import Base, DatabaseManager

_BATCH_SIZE = 500
_SQLITE_INTERNAL_PREFIX = "sqlite_"
_LEGACY_TABLES: dict[str, str] = {"admin_config": "management_config"}
_MIGRATION_MARKER_TABLE = "admin_migration_state"
_MIGRATION_MARKER_KEY = "legacy_sqlite_import_v1"


@dataclass(frozen=True)
class TableMigration:
    table: str
    source_rows: int
    target_rows: int
    imported_columns: tuple[str, ...]
    skipped_source_columns: tuple[str, ...]
    defaulted_target_columns: tuple[str, ...]


@dataclass(frozen=True)
class MigrationReport:
    source: Path
    tables: tuple[TableMigration, ...]
    ignored_empty_tables: tuple[str, ...]
    already_migrated: bool = False

    @property
    def source_rows(self) -> int:
        return sum(item.source_rows for item in self.tables)

    @property
    def target_rows(self) -> int:
        return sum(item.target_rows for item in self.tables)


def _open_source(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError(f"SQLite source is not a file: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _source_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _table_count(connection: sqlite3.Connection, table_name: str) -> int:
    quoted = table_name.replace('"', '""')
    row = connection.execute(f'SELECT COUNT(*) AS count FROM "{quoted}"').fetchone()
    return int(row["count"]) if row is not None else 0


def _source_columns(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    quoted = table_name.replace('"', '""')
    rows = connection.execute(f'PRAGMA table_info("{quoted}")').fetchall()
    return tuple(str(row["name"]) for row in rows)


def _coerce_datetime(value: object) -> object:
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"expected datetime text, got {type(value).__name__}")
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _coerce_value(column: Column[Any], value: object) -> object:
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return _coerce_datetime(value)
    if isinstance(column.type, Boolean):
        return bool(value)
    return value


def _required_without_default(column: Column[Any]) -> bool:
    return (
        not column.nullable
        and column.default is None
        and column.server_default is None
        and not column.primary_key
    )


def _prepare_columns(
    table: Table,
    source_columns: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    target_names = {column.name for column in table.columns}
    source_names = set(source_columns)
    imported = tuple(column.name for column in table.columns if column.name in source_names)
    skipped = tuple(sorted(source_names - target_names))
    defaulted = tuple(column.name for column in table.columns if column.name not in source_names)

    missing_required = [
        column.name
        for column in table.columns
        if column.name not in source_names and _required_without_default(column)
    ]
    if missing_required:
        raise RuntimeError(
            f"SQLite table {table.name} is missing required PostgreSQL columns: "
            + ", ".join(sorted(missing_required))
        )
    return imported, skipped, defaulted


def _iter_source_batches(
    connection: sqlite3.Connection,
    table: Table,
    imported_columns: Sequence[str],
    *,
    source_table: str | None = None,
    batch_size: int,
) -> Iterable[list[dict[str, object]]]:
    if not imported_columns:
        return

    quoted_table = (source_table or table.name).replace('"', '""')
    quoted_columns = ", ".join(
        f'"{name.replace(chr(34), chr(34) * 2)}"' for name in imported_columns
    )
    cursor = connection.execute(f'SELECT {quoted_columns} FROM "{quoted_table}"')
    column_map = {column.name: column for column in table.columns}

    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        yield [
            {name: _coerce_value(column_map[name], row[name]) for name in imported_columns}
            for row in rows
        ]


async def _target_counts(manager: DatabaseManager) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with manager.engine.connect() as connection:
        for name, table in Base.metadata.tables.items():
            value = await connection.scalar(select(func.count()).select_from(table))
            counts[name] = int(value or 0)
    return counts


async def _ensure_migration_marker_table(manager: DatabaseManager) -> None:
    async with manager.engine.begin() as connection:
        await connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {_MIGRATION_MARKER_TABLE} (
                    migration_key TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )


async def _migration_completed(manager: DatabaseManager) -> bool:
    async with manager.engine.connect() as connection:
        value = await connection.scalar(
            text(
                f"""
                SELECT 1
                FROM {_MIGRATION_MARKER_TABLE}
                WHERE migration_key = :migration_key
                """
            ),
            {"migration_key": _MIGRATION_MARKER_KEY},
        )
    return value is not None


def _nonempty_unknown_tables(
    source: sqlite3.Connection,
    source_tables: Sequence[str],
) -> tuple[list[str], list[str]]:
    known = set(Base.metadata.tables) | set(_LEGACY_TABLES.values())
    nonempty: list[str] = []
    empty: list[str] = []
    for table_name in source_tables:
        if table_name in known or table_name.startswith(_SQLITE_INTERNAL_PREFIX):
            continue
        if _table_count(source, table_name):
            nonempty.append(table_name)
        else:
            empty.append(table_name)
    return nonempty, empty


async def migrate_sqlite_to_postgres(
    sqlite_path: Path,
    *,
    host: str = "postgres",
    port: int = 5432,
    database: str = "mcp-bridge",
    username: str,
    password: str,
    batch_size: int = _BATCH_SIZE,
) -> MigrationReport:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    manager = DatabaseManager(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
    )
    source: sqlite3.Connection | None = None
    source_path = sqlite_path
    try:
        await manager.ensure_schema()
        await _ensure_migration_marker_table(manager)
        if await _migration_completed(manager):
            return MigrationReport(
                source=source_path,
                tables=(),
                ignored_empty_tables=(),
                already_migrated=True,
            )

        source_path = await asyncio.to_thread(lambda: sqlite_path.expanduser().resolve(strict=True))
        source = _open_source(source_path)
        source_tables = _source_tables(source)
        unknown_nonempty, ignored_empty = _nonempty_unknown_tables(source, source_tables)
        if unknown_nonempty:
            raise RuntimeError(
                "refusing migration because SQLite contains unmapped non-empty tables: "
                + ", ".join(unknown_nonempty)
            )

        before_counts = await _target_counts(manager)
        nonempty_target = {name: count for name, count in before_counts.items() if count}
        if nonempty_target:
            rendered = ", ".join(
                f"{name}={count}" for name, count in sorted(nonempty_target.items())
            )
            raise RuntimeError("refusing migration into non-empty PostgreSQL target: " + rendered)

        migrations: list[TableMigration] = []
        finalized: list[TableMigration] = []
        async with manager.engine.begin() as target:
            for table_name, table in Base.metadata.tables.items():
                source_table = table_name
                legacy_table = _LEGACY_TABLES.get(table_name, "")
                if source_table not in source_tables and legacy_table in source_tables:
                    source_table = legacy_table

                if source_table not in source_tables:
                    migrations.append(
                        TableMigration(
                            table=table_name,
                            source_rows=0,
                            target_rows=0,
                            imported_columns=(),
                            skipped_source_columns=(),
                            defaulted_target_columns=tuple(column.name for column in table.columns),
                        )
                    )
                    continue

                source_columns = _source_columns(source, source_table)
                imported, skipped, defaulted = _prepare_columns(table, source_columns)
                source_count = _table_count(source, source_table)

                for batch in _iter_source_batches(
                    source,
                    table,
                    imported,
                    source_table=source_table,
                    batch_size=batch_size,
                ):
                    if batch:
                        await target.execute(insert(table), batch)

                migrations.append(
                    TableMigration(
                        table=table_name,
                        source_rows=source_count,
                        target_rows=0,
                        imported_columns=imported,
                        skipped_source_columns=skipped,
                        defaulted_target_columns=defaulted,
                    )
                )

            # Validate before commit so any mismatch rolls back the complete copy.
            for item in migrations:
                table = Base.metadata.tables[item.table]
                value = await target.scalar(select(func.count()).select_from(table))
                target_count = int(value or 0)
                if target_count != item.source_rows:
                    raise RuntimeError(
                        f"row-count mismatch for {item.table}: "
                        f"SQLite={item.source_rows}, PostgreSQL={target_count}"
                    )
                finalized.append(
                    TableMigration(
                        table=item.table,
                        source_rows=item.source_rows,
                        target_rows=target_count,
                        imported_columns=item.imported_columns,
                        skipped_source_columns=item.skipped_source_columns,
                        defaulted_target_columns=item.defaulted_target_columns,
                    )
                )

            await target.execute(
                text(
                    f"""
                    INSERT INTO {_MIGRATION_MARKER_TABLE}
                        (migration_key, source_path)
                    VALUES (:migration_key, :source_path)
                    """
                ),
                {
                    "migration_key": _MIGRATION_MARKER_KEY,
                    "source_path": str(source_path),
                },
            )

        return MigrationReport(
            source=source_path,
            tables=tuple(finalized),
            ignored_empty_tables=tuple(ignored_empty),
        )
    finally:
        if source is not None:
            source.close()
        await manager.dispose()


def _print_report(report: MigrationReport) -> None:
    print(f"source={report.source}")
    if report.already_migrated:
        print("status=already-migrated")
        return
    for item in report.tables:
        print(
            f"{item.table}: sqlite={item.source_rows} postgres={item.target_rows} "
            f"columns={len(item.imported_columns)}"
        )
        if item.skipped_source_columns:
            print("  skipped-source: " + ", ".join(item.skipped_source_columns))
        if item.defaulted_target_columns:
            print("  target-defaults: " + ", ".join(item.defaulted_target_columns))
    if report.ignored_empty_tables:
        print("ignored-empty-tables: " + ", ".join(report.ignored_empty_tables))
    print(f"total: sqlite={report.source_rows} postgres={report.target_rows}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate the legacy Admin SQLite database into empty PostgreSQL."
    )
    parser.add_argument("sqlite_path", type=Path)
    parser.add_argument(
        "--postgres-host",
        default=os.environ.get("POSTGRES_HOST", "postgres"),
    )
    parser.add_argument(
        "--postgres-port",
        type=int,
        default=int(os.environ.get("POSTGRES_PORT", "5432")),
    )
    parser.add_argument(
        "--postgres-db",
        default=os.environ.get("POSTGRES_DB", "mcp-bridge"),
    )
    parser.add_argument("--postgres-user", default=os.environ.get("POSTGRES_USER", ""))
    parser.add_argument(
        "--postgres-password",
        default=os.environ.get("POSTGRES_PASSWORD", ""),
    )
    parser.add_argument("--batch-size", type=int, default=_BATCH_SIZE)
    return parser


async def _main() -> None:
    args = _parser().parse_args()
    missing = [
        name
        for name, value in (
            ("POSTGRES_USER", args.postgres_user),
            ("POSTGRES_PASSWORD", args.postgres_password),
        )
        if not value
    ]
    if missing:
        raise SystemExit("missing PostgreSQL settings: " + ", ".join(missing))
    report = await migrate_sqlite_to_postgres(
        args.sqlite_path,
        host=args.postgres_host,
        port=args.postgres_port,
        database=args.postgres_db,
        username=args.postgres_user,
        password=args.postgres_password,
        batch_size=args.batch_size,
    )
    _print_report(report)


if __name__ == "__main__":
    asyncio.run(_main())

"""The *only* Briareus schema upgrader: Authorization normal startup.

Alembic versions are immutable, reviewed source in the Authorization wheel.
No automatic revision generation, create_all/stamp, separate schema-init app,
manual bootstrap SQL or import of a legacy schema is permitted. A PostgreSQL
SESSION advisory lock is held over version preflight, transactional Alembic
upgrade and post-commit schema/head verification, including concurrent boots.

D4 provisions the exact database/role and calls the packaged Authorization
ASGI application; a DB being reachable is not C1-B2/C2 transport approval.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection

from common.platform_db import PlatformDatabase, PlatformDatabaseSettings

from .platform_composition import platform_metadata

# Two-int session-level lock namespace is exclusively owned by Authorization.
# It is deliberately not the old disposable DB transaction advisory lock.
_MIGRATION_LOCK = {"namespace": 140995, "resource": 39001}
_CONNECT_DEADLINE = 75.0
_LOCK_DEADLINE = 120.0
_TOTAL_MIGRATION_DEADLINE = 240.0
_RETRY_SECONDS = 0.75
_CONNECT_ATTEMPT_SECONDS = 12.0


class SchemaUpgradeRejected(RuntimeError):
    """No public route/readiness may continue after unverified schema state."""


@dataclass(frozen=True, slots=True)
class BriareusSchemaStatus:
    revision: str
    changed: bool
    table_count: int
    verified_at: datetime


def _config() -> Config:
    """Use the SAME checked-in revision source in checkout or packaged wheel."""
    packaged = Path(__file__).resolve().parent / "alembic.ini"
    source = Path(__file__).resolve().parents[2] / "scripts" / "alembic.ini"
    location = packaged if packaged.is_file() else source
    if not location.is_file():
        raise SchemaUpgradeRejected("Authorization image omitted bundled Alembic versions")
    cfg = Config(str(location))
    graph = ScriptDirectory.from_config(cfg)
    heads = graph.get_heads()
    if len(heads) != 1:
        raise SchemaUpgradeRejected("Authorization requires exactly one reviewed Alembic head")
    # All later migrations MUST descend from this root; no separate branch,
    # fake head or silently substituted schema-init script can become owner.
    revisions = list(graph.walk_revisions(head=heads[0]))
    if not revisions or revisions[-1].revision != "0001_briareus_baseline":
        raise SchemaUpgradeRejected("Briareus baseline missing or not the single root")
    # Authoritative sequence MUST be a strictly linear reviewed upgrade path;
    # Alembic supports merges/branches, but those are not approved here.
    for newer, older in pairwise(revisions):
        if newer.down_revision != older.revision:
            raise SchemaUpgradeRejected("branched/merged Alembic migrations not approved")
    if revisions[-1].down_revision is not None:
        raise SchemaUpgradeRejected("Briareus root cannot have another parent")
    return cfg


def _current_db_version(connection: Connection) -> str | None:
    rows = (
        connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
    )
    if len(rows) != 1 or not isinstance(rows[0], str):
        raise SchemaUpgradeRejected("invalid Briareus Alembic version table cardinality")
    return rows[0]


def _before_upgrade(
    connection: Connection, cfg: Config, settings: PlatformDatabaseSettings
) -> tuple[str, str | None]:
    db_name, db_user = connection.execute(text("SELECT current_database(), current_user")).one()
    if db_name != settings.postgres_db or db_user != settings.postgres_user:
        raise SchemaUpgradeRejected("Authorization connection does not match approved DB and role")

    graph = ScriptDirectory.from_config(cfg)
    heads = graph.get_heads()
    if len(heads) != 1:
        raise SchemaUpgradeRejected("multiple or missing Alembic heads are forbidden")
    head = heads[0]
    ancestor_revisions = {item.revision for item in graph.walk_revisions(base="base", head=head)}
    if "0001_briareus_baseline" not in ancestor_revisions:
        raise SchemaUpgradeRejected("new head does not descend from the reviewed Briareus baseline")

    allowed_schemas = {t.schema for t in platform_metadata().tables.values()}
    namespace_rows = (
        connection.execute(
            text(
                """
        SELECT nspname FROM pg_catalog.pg_namespace
         WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'
        """
            )
        )
        .scalars()
        .all()
    )
    if any(name != "public" and name not in allowed_schemas for name in namespace_rows):
        raise SchemaUpgradeRejected("foreign database schema found; refusing automatic migration")

    table_names = set(platform_metadata().tables)
    rows = connection.execute(
        text(
            """
        SELECT n.nspname, c.relname, c.relkind
          FROM pg_catalog.pg_class AS c
          JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
         WHERE n.nspname !~ '^pg_'
           AND n.nspname <> 'information_schema'
           AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
        """
        )
    ).all()
    found = {f"{ns}.{name}": kind for ns, name, kind in rows}
    recognized = table_names | {"public.alembic_version"}
    if any(name not in recognized for name in found):
        raise SchemaUpgradeRejected("unexpected user relation: refusing unowned database")
    if any(kind not in {"r", "p"} for kind in found.values()):
        raise SchemaUpgradeRejected("foreign view/sequence/foreign-table in Briareus database")

    if "public.alembic_version" not in found:
        if rows or any(name != "public" for name in namespace_rows):
            raise SchemaUpgradeRejected("nonempty unversioned database; never stamp into Briareus")
        return head, None

    version = _current_db_version(connection)
    if version not in ancestor_revisions:
        raise SchemaUpgradeRejected("unknown, foreign or newer database migration head")
    return head, version


def _verify_expected_schema(connection: Connection, *, head: str) -> int:
    current = _current_db_version(connection)
    if current != head:
        raise SchemaUpgradeRejected("Authorization migration did not reach committed head")
    metadata = platform_metadata()
    inspector = inspect(connection)
    if len(metadata.tables) < 1:
        raise SchemaUpgradeRejected("empty metadata cannot validate migration")

    # Consumer verification must be as strict about foreign/legacy data as
    # the only migration owner's preflight. A copied version marker and
    # matching tables must not authorize an unrelated mixed-use database.
    approved_schemas = {t.schema for t in metadata.tables.values()} | {"public"}
    actual_schemas = (
        connection.execute(
            text(
                """
        SELECT nspname FROM pg_catalog.pg_namespace
         WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'
        """
            )
        )
        .scalars()
        .all()
    )
    if any(name not in approved_schemas for name in actual_schemas):
        raise SchemaUpgradeRejected("unapproved schema in Authorization database")
    relation_rows = connection.execute(
        text(
            """
        SELECT n.nspname, c.relname, c.relkind
          FROM pg_catalog.pg_class AS c
          JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
         WHERE n.nspname !~ '^pg_'
           AND n.nspname <> 'information_schema'
           AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
        """
        )
    ).all()
    recognized_relations = set(metadata.tables) | {"public.alembic_version"}
    if any(
        f"{schema}.{name}" not in recognized_relations or kind not in {"r", "p"}
        for schema, name, kind in relation_rows
    ):
        raise SchemaUpgradeRejected("unrecognized relation in Authorization database")

    actual_count = 0
    for table in metadata.sorted_tables:
        schema = table.schema
        if schema is None:
            raise SchemaUpgradeRejected("domain table missing declared schema")
        if table.name not in inspector.get_table_names(schema=schema):
            raise SchemaUpgradeRejected("schema head does not contain all required domain tables")
        columns = inspector.get_columns(table.name, schema=schema)
        actual = {row["name"]: row for row in columns}
        expected = {column.name: column for column in table.columns}
        if actual.keys() != expected.keys():
            raise SchemaUpgradeRejected("domain table columns differ from approved metadata")
        dialect = connection.dialect
        for column_name, source in expected.items():
            observed = actual[column_name]
            if (
                bool(observed["nullable"]) != source.nullable
                or source.type.compile(dialect=dialect).casefold()
                != observed["type"].compile(dialect=dialect).casefold()
            ):
                raise SchemaUpgradeRejected("domain column type/nullability mismatch")
        # Default-denied browser consent is a security invariant, not a UI
        # preference. A DB-migrated NULL or default-true bit must fail readiness.
        if table.fullname == "identity.users":
            consent_default = str(
                actual["browser_telemetry_opt_in"].get("default", "")
            ).strip().casefold()
            if consent_default not in {
                "false", "false::boolean", "'false'::boolean",
            }:
                raise SchemaUpgradeRejected("browser consent default must deny by default")
        current_pk = inspector.get_pk_constraint(table.name, schema=schema)
        required_pk = [col.name for col in table.primary_key.columns]
        if set(current_pk["constrained_columns"]) != set(required_pk):
            raise SchemaUpgradeRejected("domain primary key differs from approved metadata")

        actual_indexes = {
            str(item["name"]): (
                tuple(item["column_names"]),
                bool(item.get("unique", False)),
            )
            for item in inspector.get_indexes(table.name, schema=schema)
        }
        expected_indexes = {
            str(index.name): (
                tuple(column.name for column in index.columns),
                index.unique,
            )
            for index in table.indexes
        }
        if any(actual_indexes.get(name) != value for name, value in expected_indexes.items()):
            raise SchemaUpgradeRejected("missing or changed domain index on versioned schema")

        actual_checks = {
            str(item["name"]) for item in inspector.get_check_constraints(table.name, schema=schema)
        }
        required_checks = {
            str(c.name)
            for c in table.constraints
            if isinstance(c, CheckConstraint) and c.name is not None
        }
        if not required_checks.issubset(actual_checks):
            raise SchemaUpgradeRejected("missing required CHECK constraint")

        actual_fks = {
            str(item["name"]) for item in inspector.get_foreign_keys(table.name, schema=schema)
        }
        required_fks = {
            str(c.name)
            for c in table.constraints
            if isinstance(c, ForeignKeyConstraint) and c.name is not None
        }
        if not required_fks.issubset(actual_fks):
            raise SchemaUpgradeRejected("missing required foreign key")
        # Most SQLAlchemy-mapped FK constraints are unnamed. Checking only
        # their names would silently accept missing Project/User/Session FKs.
        actual_fk_shapes = {
            (
                tuple(item["constrained_columns"]),
                item["referred_schema"],
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys(table.name, schema=schema)
        }
        expected_fk_shapes = {
            (
                tuple(element.parent.name for element in fk.elements),
                fk.referred_table.schema,
                fk.referred_table.name,
                tuple(element.column.name for element in fk.elements),
            )
            for fk in table.foreign_key_constraints
        }
        if not expected_fk_shapes.issubset(actual_fk_shapes):
            raise SchemaUpgradeRejected("domain foreign key ownership/provenance differs")

        actual_uniques = {
            str(item["name"])
            for item in inspector.get_unique_constraints(table.name, schema=schema)
        }
        required_uniques = {
            str(c.name)
            for c in table.constraints
            if isinstance(c, UniqueConstraint) and c.name is not None
        }
        if not required_uniques.issubset(actual_uniques):
            raise SchemaUpgradeRejected("missing required unique constraint")
        actual_count += 1
    return actual_count


def _apply_under_lock(
    connection: Connection, cfg: Config, settings: PlatformDatabaseSettings
) -> BriareusSchemaStatus:
    head, original = _before_upgrade(connection, cfg, settings)
    if original != head:
        # Versioned, reviewed SQL only; never autogenerate, stamp or create_all.
        cfg.attributes["connection"] = connection
        try:
            command.upgrade(cfg, "head")
        finally:
            cfg.attributes.pop("connection", None)
    count = _verify_expected_schema(connection, head=head)
    return BriareusSchemaStatus(
        revision=head,
        changed=original != head,
        table_count=count,
        verified_at=datetime.now(UTC),
    )


async def _connect_bounded(db: PlatformDatabase) -> AsyncConnection:
    deadline = time.monotonic() + _CONNECT_DEADLINE
    while time.monotonic() < deadline:
        try:
            return await asyncio.wait_for(
                db.engine.connect(),
                timeout=_CONNECT_ATTEMPT_SECONDS,
            )
        except (OSError, OperationalError, TimeoutError) as exc:
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if sqlstate in {"28P01", "28000", "3D000", "42501"}:
                raise SchemaUpgradeRejected(
                    "Authorization DB identity/permissions rejected"
                ) from None
            await asyncio.sleep(min(_RETRY_SECONDS, max(0, deadline - time.monotonic())))
    raise SchemaUpgradeRejected(
        "Authorization PostgreSQL was not reachable before startup deadline"
    )


async def run_authorization_schema_migrations(
    db: PlatformDatabase,
    settings: PlatformDatabaseSettings,
) -> BriareusSchemaStatus:
    """Only normal Authorization lifecycle calls this; never Data/Gateway."""
    config = _config()
    conn = await _connect_bounded(db)
    owned = False
    try:
        async with asyncio.timeout(_TOTAL_MIGRATION_DEADLINE):
            deadline = time.monotonic() + _LOCK_DEADLINE
            while time.monotonic() < deadline:
                owned = bool(
                    await conn.scalar(
                        text("SELECT pg_try_advisory_lock(:namespace, :resource)"),
                        _MIGRATION_LOCK,
                    )
                )
                # The PostgreSQL SESSION lock intentionally survives COMMIT.
                await conn.commit()
                if owned:
                    break
                await asyncio.sleep(_RETRY_SECONDS)
            if not owned:
                raise SchemaUpgradeRejected("Authorization migration advisory lock timed out")
            async with conn.begin():
                await conn.execute(text("SELECT set_config('statement_timeout', '90000ms', true)"))
                await conn.execute(text("SELECT set_config('lock_timeout', '75000ms', true)"))
                status = await conn.run_sync(_apply_under_lock, config, settings)
            # The lock remains held while we recheck the committed Alembic
            # marker rather than trusting only the in-transaction prediction.
            async with conn.begin():
                committed = await conn.scalar(
                    text("SELECT version_num FROM public.alembic_version")
                )
                if committed != status.revision:
                    raise SchemaUpgradeRejected("post-commit migration revision mismatch")
            return status
    except TimeoutError:
        raise SchemaUpgradeRejected(
            "Authorization schema upgrade exceeded bounded startup deadline"
        ) from None
    finally:
        if owned:
            try:
                await conn.rollback()
                unlocked = bool(
                    await conn.scalar(
                        text("SELECT pg_advisory_unlock(:namespace, :resource)"),
                        _MIGRATION_LOCK,
                    )
                )
                await conn.commit()
                if not unlocked:
                    await conn.invalidate()
            except Exception:
                # A pooled session retaining a session-level lock would be
                # dangerous; force physical connection destruction on error.
                await conn.invalidate()
        await conn.close()


async def verify_authorization_schema_for_consumer(db: PlatformDatabase) -> str:
    """Read-only Admin/Gateway schema fence. NEVER runs Alembic or creates DDL.

    Consumers may open business sessions only after Authorization has
    committed its reviewed versioned head, with the exact expected tables
    and constraints. Any half-migrated/foreign/future schema returns DENY.
    """
    config = _config()
    expected_head = ScriptDirectory.from_config(config).get_heads()[0]
    try:
        async with db.engine.connect() as conn:
            result = await conn.execute(text("SELECT current_database(), current_user"))
            database_name, username = result.one()
            if database_name != db.engine.url.database or username != db.engine.url.username:
                raise SchemaUpgradeRejected("Admin DB target/role does not match Authorization")
            await conn.run_sync(_verify_expected_schema, head=expected_head)
            return expected_head
    except SchemaUpgradeRejected:
        raise
    except Exception:
        # No ASGI/trace/production log may echo DSN, credentials or SQL
        # parameters during forbidden partial/unknown schema reads.
        raise SchemaUpgradeRejected(
            "Authorization database schema is not at an accepted committed head"
        ) from None


async def require_current_authorization_revision(db: PlatformDatabase) -> str:
    """Cheap read-only head fence for already-started Authorization/Admin.

    During rolling deployments a newly started Authorization may migrate to
    a newer revision while an older process is still alive. Never use the
    previous process's one-time startup readiness as permission to execute
    against an unknown/newer schema. This query has no DDL or migration path.
    """
    config = _config()
    expected_head = ScriptDirectory.from_config(config).get_heads()[0]
    try:
        async with db.engine.connect() as conn:
            actual_db, actual_user, current_head = (
                await conn.execute(
                    text(
                        "SELECT current_database(), current_user, "
                        "(SELECT version_num FROM public.alembic_version)"
                    )
                )
            ).one()
            if (
                actual_db != db.engine.url.database
                or actual_user != db.engine.url.username
                or current_head != expected_head
            ):
                raise SchemaUpgradeRejected(
                    "Authorization schema revision changed after process startup"
                )
        return expected_head
    except SchemaUpgradeRejected:
        raise
    except Exception:
        raise SchemaUpgradeRejected(
            "current committed Authorization schema revision unverified"
        ) from None

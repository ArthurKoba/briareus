"""Versioned Briareus schema owned exclusively by Authorization startup.

The caller MUST provide an already authenticated, advisory-locked SQLAlchemy
connection. Running Alembic manually, generating versions dynamically,
declaring a separate init container or connecting without the migration
coordinator is prohibited. Version table lives in public so baseline may
create its ten domain schemas within the first tracked revision.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from authorization.platform_composition import platform_metadata

connection: Connection | None = context.config.attributes.get("connection")
if connection is None or context.is_offline_mode():
    raise RuntimeError(
        "Briareus migrations run only inside Authorization startup's "
        "locked, verified PostgreSQL transaction"
    )

context.configure(
    connection=connection,
    target_metadata=platform_metadata(),
    version_table="alembic_version",
    version_table_schema="public",
    include_schemas=True,
    compare_type=True,
    transactional_ddl=True,
    transaction_per_migration=False,
)

with context.begin_transaction():
    context.run_migrations()

# Shared infrastructure

`infrastructure.yaml` is the long-lived external dependency layer for the MCP project. It contains only services that do not build project source code:

- `postgres` — durable primary relational database;
- `valkey` — disposable Redis-compatible cache.

Deploy it as one Git-backed Docker Compose resource in Coolify on the `mcp-bridge-network` destination. Changes to Python/TypeScript application code must not rebuild this resource.

## Compose location

```text
/deploy/coolify/infrastructure.yaml
```

## Internal DNS

```text
postgres:5432
valkey:6379
```

## Persistence

Only PostgreSQL is persistent. Valkey deliberately has persistence disabled because PostgreSQL is authoritative.

## Generated/bootstrap variables

```text
POSTGRES_DB=core
POSTGRES_USER=core
POSTGRES_PASSWORD=${SERVICE_PASSWORD_64_POSTGRES}
```

Optional capacity overrides:

```text
POSTGRES_MEMORY_LIMIT=2g
POSTGRES_CPU_LIMIT=2.0
VALKEY_MAX_MEMORY=128mb
VALKEY_MEMORY_LIMIT=192m
VALKEY_CPU_LIMIT=0.5
INFRA_NETWORK_NAME=mcp
```

Application database migration is separate from provisioning this infrastructure. Until the Admin API source accepts a PostgreSQL URL and the SQLite data is migrated, PostgreSQL may be healthy but unused.

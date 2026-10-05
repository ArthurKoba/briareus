# Deployment

Production applications are separate Git-backed Coolify Applications built from the root `Dockerfile`.
Do not create per-service Compose wrappers for application runtimes.

Application Docker targets:

- `admin-api`
- `auth`
- `gateway`
- `github`
- `gitlab`
- `files`
- `web`
- `terminal`
- `analysis`
- `ghidra`
- `observability`

`admin-ui` is built from `admin-web-app/Dockerfile`.

All MCP production resources use the Coolify destination/network `mcp-bridge-network` (`mcp`).
Internal service addressing should use the stable service/container names configured in Coolify.

The root `docker-compose.yaml` contains only long-lived external infrastructure that does not build project source:

- PostgreSQL — durable primary relational database;
- Valkey — disposable Redis-compatible cache.

Application source changes must not rebuild the infrastructure resource.

Admin API accepts `POSTGRES_HOST`, `POSTGRES_PORT` and `POSTGRES_DB` with defaults `postgres`, `5432` and `mcp-bridge`, plus shared `POSTGRES_USER` and `POSTGRES_PASSWORD`; it selects the SQLAlchemy `postgresql+asyncpg` driver internally. The legacy SQLite database is a one-time migration source only; use `infrastructure.sqlite_to_postgres` during cutover and retain the original file until acceptance is complete.

Auth owns both OAuth identity and agent-access state in one PostgreSQL database/role. Provision it idempotently against the existing cluster with:

```text
python scripts/provision_auth_database.py
```

The provisioner uses the cluster-admin `POSTGRES_*` connection and the service-specific `AUTH_POSTGRES_*` credentials. The auth runtime receives only the auth database credentials.

Auth additionally requires local bootstrap credentials, an ES256 private signing key, one gateway service token and one admin service token. Gateway receives only `AUTH_JWT_PUBLIC_KEY_PEM` plus the gateway token for agent-session checks. Agent-session state uses Valkey as a read-through cache; cache loss falls back to durable state in the same auth database.
Gateway reaches the private auth runtime through `AUTH_SERVICE_URL` (default `http://auth:8000`), so split/local topologies do not depend on a hard-coded container address.

The legacy monolith remains pinned to `e41085d9c86124a0f711411314265b36f4c23dea` until split-runtime acceptance is complete.

The static infrastructure Compose stack attaches `postgres` and `valkey` directly to the pre-existing external Docker network `mcp`; it does not rely on a Compose-generated default network or manual `docker network connect`.

Coolify resource environment variables are the Compose inputs. Production references shared variables rather than generated `SERVICE_*` placeholders:

```text
POSTGRES_DB={{project.SERVICE_NAMESPACE}}
POSTGRES_USER={{environment.POSTGRES_USER}}
POSTGRES_PASSWORD={{environment.POSTGRES_PASSWORD}}
```

`POSTGRES_DB` remains optional at the Compose level and defaults to `mcp-bridge`. `POSTGRES_USER` and `POSTGRES_PASSWORD` are required. The PostgreSQL healthcheck reads the resolved container environment instead of re-interpolating Compose inputs.

The completed legacy SQLite -> PostgreSQL migration was performed as a one-shot process outside the Admin API runtime. Any future recovery/import operation must mount its legacy SQLite source read-only and keep the PostgreSQL target/row-count validation rules from the importer.

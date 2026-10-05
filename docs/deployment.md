# Deployment

Production applications are separate Git-backed Coolify Applications built from the root `Dockerfile`.
Do not create per-service Compose wrappers for application runtimes.

Application Docker targets:

- `admin-api`
- `auth`
- `access`
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

Auth and access use separate PostgreSQL databases and roles on the same cluster. Provision them idempotently against an existing cluster with:

```text
python scripts/provision_auth_access_databases.py
```

The provisioner uses the cluster-admin `POSTGRES_*` connection and the service-specific `AUTH_POSTGRES_*` / `ACCESS_POSTGRES_*` credentials. Auth/access runtimes receive only their own database credentials.

Auth additionally requires local bootstrap credentials, an ES256 private signing key, and distinct service tokens for access/admin internal calls. Gateway receives only `AUTH_JWT_PUBLIC_KEY_PEM`. Access requires distinct gateway/admin service tokens and uses Valkey as a read-through cache; Redis loss falls back to the durable access database.

The legacy monolith remains pinned to `e41085d9c86124a0f711411314265b36f4c23dea` until split-runtime acceptance is complete.

The static infrastructure Compose stack attaches `postgres` and `valkey` directly to the pre-existing external Docker network `mcp`; it does not rely on a Compose-generated default network or manual `docker network connect`.

Coolify resource environment variables are the Compose inputs. Production references shared variables rather than generated `SERVICE_*` placeholders:

```text
POSTGRES_DB={{project.SERVICE_NAMESPACE}}
POSTGRES_USER={{environment.POSTGRES_USER}}
POSTGRES_PASSWORD={{environment.POSTGRES_PASSWORD}}
```

`POSTGRES_DB` remains optional at the Compose level and defaults to `mcp-bridge`. `POSTGRES_USER` and `POSTGRES_PASSWORD` are required. The PostgreSQL healthcheck reads the resolved container environment instead of re-interpolating Compose inputs.

Run the SQLite -> PostgreSQL migration as a one-shot process/container outside the Admin API runtime. Mount the legacy `management` volume read-only, attach the process to Docker network `mcp`, and invoke `python -m infrastructure.sqlite_to_postgres /management/management.sqlite3`. The target PostgreSQL database must be empty. Remove the temporary migration container after row-count validation succeeds.

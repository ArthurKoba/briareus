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

Admin API receives discrete `POSTGRES_*` connection settings and builds the SQLAlchemy `postgresql+asyncpg` URL internally. The legacy SQLite database is a one-time migration source only; use `infrastructure.sqlite_to_postgres` during cutover and retain the original file until acceptance is complete.

The legacy monolith remains pinned to `e41085d9c86124a0f711411314265b36f4c23dea` until split-runtime acceptance is complete.

Infrastructure bootstrap defaults:

```text
POSTGRES_DB=mcp-bridge
POSTGRES_USER=${SERVICE_USER_POSTGRES}
POSTGRES_PASSWORD=${SERVICE_PASSWORD_64_POSTGRES}
```

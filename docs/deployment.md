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

PostgreSQL provisioning and Admin API migration are separate steps. The Admin API currently still derives its database URL from the SQLite `ADMIN_API_DATABASE_PATH` contract, so switching to PostgreSQL requires source support and a data migration first.

The legacy monolith remains pinned to `e41085d9c86124a0f711411314265b36f4c23dea` until split-runtime acceptance is complete.

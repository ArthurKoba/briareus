# Deployment

## Deployment units and migration strategy

The **current** production split runtimes use independent Git-backed Coolify Dockerfile
Applications built from the shared multi-stage root `Dockerfile`. The legacy monolith
still uses its own pinned branch and Compose resource. Both are intentionally preserved
until the replacements pass runtime acceptance.

The target is **one Git repository and one shared Dockerfile, with one independent
Git-backed Coolify Compose Application per runtime deployment unit**. Each resource
has a small Compose manifest selecting exactly one Docker build target. Coolify
Watch Paths filter Git webhook deployments *per application*, not individual
services inside one multi-container resource. This changes deployment packaging,
not the source-level ownership boundaries or the application APIs.

The first staged manifest is `deploy/coolify/authorization/docker-compose.yaml`.
It is an undeployed migration candidate, not a claim about the active Auth resource.
Only switch an existing Coolify application after its generated Compose, domains,
secret references, network membership and rollback have been verified. Do not
repoint or retire the running legacy Compose deployment during this experiment.

Authorization pilot configuration for a **Git-backed Docker Compose Application**:

- Repository: `ArthurKoba/mcp-bridge`, target branch `main` after acceptance.
- Base Directory: `/deploy/coolify/authorization`.
- Docker Compose Location (relative to Base Directory): `/docker-compose.yaml`.
- Build context in the manifest: `../../..` (the repository root);
  Dockerfile target: `authorization`.
- Domain: `https://authorization.mcp.koba-nexus.ru` on service `authorization`,
  internal port `8000` — move the live domain only at controlled cutover.
- Networking: existing destination `mcp-bridge-network` / external `mcp` network;
  verify `postgres`, `valkey` and the `authorization` DNS alias on the real host.
- Use normal Coolify Compose processing, **not Raw**, and connect to the
  selected predefined destination network when required for proxy reachability.
- Watch Paths (one path per line):
  `deploy/coolify/authorization/docker-compose.yaml`, `services/authorization/**`,
  `services/common/**`, `scripts/provision_authorization_database.py`,
  `Dockerfile`, `docker-entrypoint.sh`, `pyproject.toml`, `uv.lock`.
  These filter Git webhooks; manual Deploy/Redeploy is always an explicit override.
- **All** `${VAR:?}` values must be assigned in Coolify before deployment.
  Secret values belong to runtime-only protected variables or scoped shared
  references, never Git or build arguments. Mark the signing key secret and
  multiline; keep its existing value when rotating an active installation.
- Provision the Auth PostgreSQL role/database separately using the existing
  idempotent provisioner and cluster-admin authority. Do **not** inject cluster
  superuser credentials into the steady-state Auth container. Coordinate the
  Gateway and Admin API shared-service tokens and public verification key.
- Accept in stages: offline manifest/schema verification -> Coolify parsed
  required-variable/domain/network inspection -> disposable non-production
  runtime check -> controlled replacement -> `/health`, JWKS, private service
  access, persistence, OAuth and rollback verification. Production acceptance
  cannot be inferred from a passing Docker build or smoke import.

Each future deployment unit (Gateway, providers, Web, Terminal, etc.) gets its
own scoped manifest and Coolify resource only as required. Do not introduce
extra Python microservices merely to achieve independent build triggers.
Keep browser profiles, shared workspace storage and durable DB volumes under
explicit existing ownership rather than adopting freshly generated volume names.

## Runtime Docker targets

Application Docker targets:

- `admin-api`
- `authorization`
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

Authorization owns both OAuth identity and agent-access state in one PostgreSQL database/role. Provision it idempotently against the existing cluster with:

```text
python scripts/provision_authorization_database.py
```

The provisioner uses the cluster-admin `POSTGRES_*` connection and the service-specific `AUTHORIZATION_POSTGRES_*` credentials. The authorization runtime receives only the authorization database credentials.

Authorization additionally requires `AUTHORIZATION_PUBLIC_BASE_URL`, `MCP_PUBLIC_BASE_URL`, local bootstrap credentials, an ES256 private signing key, one gateway service token and one admin service token. Production authorization is public at `https://authorization.mcp.koba-nexus.ru`; MCP resources stay at `https://mcp.koba-nexus.ru`. Gateway receives `AUTHORIZATION_PUBLIC_BASE_URL`, `MCP_PUBLIC_BASE_URL`, `AUTHORIZATION_JWT_PUBLIC_KEY_PEM` and the gateway token for agent-session checks. Gateway does not proxy OAuth endpoints. Agent-session state uses Valkey as a read-through cache; cache loss falls back to durable state in the same authorization database. Admin API reaches authorization privately through `AUTHORIZATION_INTERNAL_URL` (default `http://authorization:8000`).

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

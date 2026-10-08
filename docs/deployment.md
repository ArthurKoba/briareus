# Deployment

## Independent deployment units and reusable Compose overlays

The current runtime transition uses independent Git-backed Coolify Applications
built from the shared multi-stage Dockerfile. The legacy deployment is still
running from its pinned branch and must not be repointed during this migration.

Deployment definitions for each application live in a **flat service directory**:

```text
deploy/authorization/
  docker-compose.yaml          # portable Docker Compose definition
  docker-compose.coolify.yaml  # Coolify-specific override/adapter
```

`docker-compose.yaml` owns the deployable service, Docker build target,
portable environment contract and health check. It has no Coolify-only
magic variables, environment-specific domains, networks or host limits.
External PostgreSQL and Valkey belong to other deployment resources.

`docker-compose.coolify.yaml` is an optional adapter which references the base
service through Docker Compose `extends`, adds a Coolify service URL directive,
resource limits and an operator-selected existing shared network. It
never copies production secrets into Git or creates another database/cache.
Other orchestrators can supply their own adapter beside the portable base,
without new directory levels such as `deploy/coolify/authorization/`.

**Acceptance constraint:** Docker Compose supports cross-file `extends`, but the
Coolify parser may inspect only the selected YAML before Docker Compose expands
it. The selected Coolify version must be shown to discover the inherited
`build:` target and all required environment variables before switching a live
resource. These two source files are a staged pattern, not evidence of parser
or runtime acceptance. Do not use Raw mode merely to bypass validation.

### Portable local deployment

Use the base manifest with Docker Compose on a machine with the external
PostgreSQL and Valkey dependencies available. Provide the required environment
variables through an untracked secret provider or local env file. Build context
`../..` resolves to the repository root from `deploy/authorization/`.

### Coolify-specific adapter pilot

For a Git-backed Coolify Application **after parser acceptance**:

- Base Directory: `/deploy/authorization`.
- Docker Compose Location: `/docker-compose.coolify.yaml`.
- Build target (in the portable base): `authorization`.
- Assign `${AUTHORIZATION_SHARED_NETWORK:?}` to the external network available
  on the destination; do not hardcode a deployment-specific network into source.
- Supply all `${VAR:?}` runtime inputs as protected resource or shared variables.
  The signing private key must remain secret and multiline. Reuse an existing
  key during cutover rather than silently rotating the issuer.
- Set the public service domain on `authorization` port `8000` only during a
  controlled domain cutover; do not hardcode a public hostname in either YAML.
- Narrow Watch Paths to the two Compose files, `services/authorization/**`,
  `services/common/**`, root `Dockerfile`, `docker-entrypoint.sh`, `pyproject.toml`
  and `uv.lock`. Source changes belonging only to another provider must not
  cause an authorization deployment.
- Keep credentialed PostgreSQL provisioning a separate privileged one-shot
  operation (`scripts/provision_authorization_database.py`); runtime Auth must
  not hold cluster-superuser credentials.
- Confirm generated Coolify Compose, discovered required variables, domain,
  external network, clean startup, health, OAuth/JWKS and rollback **before**
  replacing the existing Dockerfile Application. Do not modify the legacy
  Compose resource as part of this pilot.

A new Coolify Application remains a distinct deploy unit regardless of how many
Python modules live in the shared repository. This solves the original global
restart problem without multiplying independent Python microservices.

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

## Current deployment-specific notes (not part of the portable templates)

These details describe one active infrastructure and are not defaults for other
users of the Compose files above. Durable live infrastructure authority belongs
in its own infrastructure inventory.

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

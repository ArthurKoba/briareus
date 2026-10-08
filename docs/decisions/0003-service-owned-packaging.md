# ADR 0003: Service-owned deployment packaging, independent release units

Status: accepted for source layout; Coolify adapter deployment remains gated

## Context

The legacy MCP Bridge uses one Coolify Docker Compose resource containing many
runtime containers. The resource-level deploy loop scans/builds a whole stack;
updates to shared source can invalidate multiple Docker targets and have caused
unacceptable disruption to long-lived browser and workspace processes. The
exact set of containers restarted on each legacy deploy is not yet proven.

Moving every Python package into a distinct microservice is not necessary to
solve a *deployment* isolation problem. The current root Dockerfile and
`docker-entrypoint.sh` also force unrelated runtime setup and the database
provisioner script into every image. Existing Auth, Admin API, and Admin UI are
separate Coolify resources, but the new Auth is not yet accepted at runtime.

## Decision

1. Each **deployment unit** owns its Dockerfile and two Compose definitions
   beside its code: a portable `docker-compose.yaml` and an optional
   `docker-compose.coolify.yaml`. Ordinary units belong within `services/`.
   The old `deploy/authorization/` pilot is superseded.
2. Each deployment unit has its **own Coolify Application** and repository-
   relative Watch Paths. A Git webhook for one provider must not cause a
   release of the full legacy stack. A shared source/lockfile change should
   trigger only units that actually consume it. Manual deploy is explicit.
3. Application topology and the number of Python bounded contexts are
   independent of deployment units. Keep Auth (OAuth identity and durable
   agent access) separate from the public Gateway. Preserve existing Web/
   Chromium, Terminal and Ghidra state boundaries until individually reviewed.
4. The Docker **build context may remain the repository root** for shared
   `pyproject.toml`, `uv.lock`, and `services/common`. A service-owned Dockerfile
   should explicitly copy only its own package and the true shared runtime
   dependencies, instead of importing all root Dockerfile stages. Initially
   build Auth as an isolated pilot; retain root Dockerfile for unconverted
   consumers until their source and runtime acceptance gates pass.
5. The portable Compose file contains no Coolify `SERVICE_*`, production
   hostnames or physical Docker network names. The adapter adds only the
   necessary Coolify route and attachment to an existing network. Docker
   The installed Coolify parser does not discover required environment inputs
   inherited only through `extends.file`. Mirror portable environment keys in
   the selected Coolify adapter; the regression test enforces exact matching.
   Docker Compose must still expand `extends` at deployment time.
6. PostgreSQL remains durable authority, Valkey a disposable cache. Do not
   recreate their current Compose stack or volumes. The database provisioner
   is a separate trusted one-shot operation, never shipped into the Auth
   image. Reusing the existing shared DB account is an explicitly accepted
   interim privilege trade-off; in this mode the provisioner must never
   alter the existing database account or owner of an existing database.
7. Coolify Environment Shared Variables are **not auto-inherited**. Auth uses
   the existing canonical `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
   `POSTGRES_USER`, `POSTGRES_PASSWORD`, not synthetic `AUTHORIZATION_POSTGRES_*`
   runtime aliases. Bind `POSTGRES_USER/PASSWORD` to the existing Production
   Environment Shared Variables. Use `POSTGRES_DB=authorization` for Auth
   (Admin API has an incompatible `oauth_sessions` schema in `mcp-bridge`).
   The existing external Docker network is `mcp`, no new network variable.
   Use `${VAR:?}` for required inputs, runtime secrets are not build arguments.
   Preserve existing JWT private key and service tokens.

## Initial Auth dependency inventory

- `services/authorization/` consumes `services/common/` (contracts, settings,
  cache, observability and MCP resource helpers), plus the pinned root Python
  dependencies. It does **not** import sibling `modules/` or `bridge/` source.
- `authorization.runtime` imports the ASGI app and validates nine bootstrap
  settings; its lifespan creates/checks Auth schema in PostgreSQL and then
  provisions the local bootstrap user. Auth cannot become healthy without a
  valid PostgreSQL database and shared credentials. The one-shot provisioner
  creates the separate Auth database when absent, but does not mutate the
  shared PostgreSQL role or existing database ownership.
- The root entrypoint's mkdir/chown of Browser/Terminal/Admin locations is
  unrelated to Auth. The service-owned Auth Dockerfile creates only its own
  runtime dirs as root at build time, and runs ASGI as uid/gid 1000 without
  a runtime chown helper. The stock root Dockerfile stays untouched.
- `admin-api` consumes `modules.files` and its own application, infrastructure
  and presentation packages; Web and Analysis also import `modules.files`.
  A mechanical service-folder move without checking these imports is invalid.
- The root `uv.lock` and common code remain shared inputs during the pilot.
  Updating shared `settings.py` may trigger rebuilds of other consumers through
  their existing Watch Paths; this migration cannot yet eliminate that coupling.
  Separate locks/build graphs should be considered only when measured.

## Auth variable ownership (source-level contract)

| Input | Owner/source | Runtime behavior |
| --- | --- | --- |
| `AUTHORIZATION_PUBLIC_BASE_URL` | Auth public issuer | Defaults to Coolify-generated `SERVICE_URL_AUTHORIZATION` in the adapter, explicit override allowed; runtime validates nonempty URL |
| `MCP_PUBLIC_BASE_URL` | Gateway/public resource owner | Required; enumerates OAuth resource audiences, not internal host |
| `POSTGRES_{HOST,PORT}` | Existing internal PostgreSQL connection | Defaults `postgres`/`5432` |
| `POSTGRES_DB` | Auth resource | Default `authorization`; MUST NOT reuse Admin API's `mcp-bridge` database |
| `POSTGRES_USER` | Existing Production Environment Shared Variable | Required `{{environment.POSTGRES_USER}}`; runtime-only |
| `POSTGRES_PASSWORD` | Existing Production Environment Shared Variable | Required `{{environment.POSTGRES_PASSWORD}}`; runtime-only protected |
| `AUTHORIZATION_BOOTSTRAP_USERNAME` | Auth operator identity | Required; stable across upgrades |
| `AUTHORIZATION_BOOTSTRAP_PASSWORD` | Auth bootstrap credential | Required; protected runtime-only |
| `AUTHORIZATION_JWT_PRIVATE_KEY_PEM` | Auth issuer signing key | Required; protected multiline, runtime-only; preserve key identity |
| `AUTHORIZATION_GATEWAY_SERVICE_TOKEN` | Auth ↔ Gateway shared secret | Required; same referenced value in consumers |
| `AUTHORIZATION_ADMIN_SERVICE_TOKEN` | Auth ↔ Admin API shared secret | Required; same referenced value in consumers |
| `VALKEY_URL` | External disposable cache endpoint | Optional overridable internal DNS default |
| Docker network | Existing Coolify `mcp` network | Constant in Coolify adapter, not a new environment variable |

For the current environment, Shared Variable names and scopes must be verified
against the live Coolify Project/Environment control plane. If a required key
is absent at the correct scope, stop rather than silently generating/replacing
secrets. Literal, multiline and buildtime flags must be audited without
revealing plaintext values. No real environment values belong in this ADR.

## Validation and migration boundaries

- Local source: `ruff`, `mypy`, deterministic Compose/Dockerfile checks; preserve
  existing tests. No heavyweight integration or three-image matrix on each PR.
- Isolated build: a single explicit manual Zoomies job checks the Auth image
  and that Docker Compose can expand the two files. A passing build does not
  establish installed Coolify parser support.
- Coolify acceptance: use a **disposable, non-production resource** to prove
  inherited `build:` and required variables are surfaced correctly; confirm
  path resolution, explicit Shared Variable references, SSL/domain and network
  attachments. Do not use Raw mode simply to mask parser incompatibility.
- Cutover: snapshot current application/shared-variable flags and resolve
  conflicting/stale resource keys. Confirm the provisioning role, startup,
  `/health`, JWKS/OAuth, database persistence and user flows, then explicitly
  switch one resource. Keep rollback and the healthy legacy Compose available.
- Repeat migration for another service **only after** its dependency, storage,
  resource and Watch Paths contracts are observed and verified. Test what
  actually rebuilds/restarts, including Web browser persistence, not merely
  whether Coolify returns `finished`.

## Consequences and known blockers

This intentionally duplicates a few stable Dockerfile lines while removing
unnecessary root-container setup. It does **not** claim production readiness.
Real Coolify `extends` materialization, live PostgreSQL connectivity, secret
resolution and the stale `POSTGRES_USER=POSTGRES_USER is required` parsing
issue remain unresolved runtime gates. The existing root infrastructure
Compose file is left alone to avoid restarting a live database/cache stack.

Implementation and deployment tracking are owned by the selected infrastructure workspace.

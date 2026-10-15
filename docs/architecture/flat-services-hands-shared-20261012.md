# Briareus: flat Services, Hands, Shared — owner decision 2026-10-12

**Status: selected target; incremental migration, not evidence of an already deployed cutover.** This is the newest owner decision and overrides the nested `services/control-panel/{api,ui}`, `services/infrastructure/gateway`, `services/platform/<owner>` and `services/hands/<name>` target layouts in older documents. Rauthy + Cedar remains selected. Product/API business semantics, independent service ownership, retention of data, Coolify access scope, and required GitHub checks remain in force.

## Repository root

```text
services/
  api/                   # Python Control Panel management API/BFF; optional to MCP dataplane
  ui/                    # independently deployed Control Panel frontend
  gateway/               # MCP ingress/stream routing and coarse authorization admission
  authorization/         # authoritative grants, AgentSession, approval/revocation, embedded Cedar
  external/              # existing vendor stack: PostgreSQL, Valkey and upstream Rauthy
  platform/              # independent Team/Project owner IF/WHEN retained as a separate deploy
  resources/             # independent Resource Catalog IF/WHEN deployed independently
hands/
  files/ terminal/ web/ svc/ infrastructure/ reverse/ ...
shared/
  contracts/             # narrow shared DTO and wire contracts only
  transport/             # optional small reusable protocol helpers
  telemetry/             # optional small reusable observability helpers
  security/              # optional small reusable security *primitives*, no domain permissions

docs/services/{api,ui,gateway,authorization,external,platform,resources}/
docs/hands/<hand>/
docs/shared/<topic>/
```

Each independently deployed first-party module owns its **own** `src/`, `Dockerfile`, `docker-compose.yaml`, `docker-compose.coolify.yaml`, uv/Bun manifest+lock, health/start and **its own migration only when necessary**. No central `deploy/` as the target. Separate documents from deployment-watch directories. No nested layout prefixes just to repeat `control-panel`, `infrastructure` or `platform` when the service has a unique name. Place MCP tools/providers **only** in `hands/`, never mix them into internal `services/`. Common cross-service DTO may live in `shared/contracts/<topic>`, with one selected editor and explicitly narrow consumers. Do not treat a shared package as permission to import owner ORM, database tables or business rules across services.

The existing approved Coolify External Services application is one vendor stack
with three separate private services: PostgreSQL, Valkey and upstream Rauthy.
Its sole source folder is `services/external/**`, not `deploy/data/**`.
This is a deliberate infrastructure-only shared deployment unit, not permission
to package API, UI, Gateway, Authorization or Hands together. The existing
PostgreSQL and Valkey volume names and network must remain stable; Rauthy
uses its own logical database and a separate durable volume. The latest
owner instruction allows removing the unused legacy `deploy/data/**` source
during migration; do not delete data volumes or inspect plaintext secrets.

**Newer owner overrides (14 October 2026):** Control Panel implements its OWN human sign-in/MFA/recovery UI and Control Panel API brokers Rauthy session/challenge/OIDC; no browser redirect to Rauthy/Gateway-hosted login ([#536](https://github.com/KobaProduction/briareus/issues/536#issuecomment-6176839823)). Every existing Coolify service/Hand additionally watches the broad directory `services/external/**` alongside its module and any imported shared paths. These changes do not convert this source target into a verified Development cutover.

## Core infrastructure and future Node execution boundary (owner 2026-10-15)

**MVP physical placement: one existing host, existing allowed Coolify applications.**
This is a logical trust/dependency split, not an instruction to introduce
multi-node, DinD, rootless child agents, new database services or new app UUIDs.
The future multi-node plan is [#544](https://github.com/KobaProduction/briareus/issues/544);
current single-host architecture and release coordination are tracked in
[#536](https://github.com/KobaProduction/briareus/issues/536#issuecomment-6186302840).

- **Core / infrastructure control plane:** upstream Rauthy, the existing
  PostgreSQL and Valkey dependencies, Platform (verified User, Team, Project),
  Authorization (Cedar, AgentSession, grants/revoke), Resources, and the
  separately deployed Control Panel API/UI. Each durable business owner
  controls *its own* database migrations and protects its owner API. Rauthy
  alone stores human credentials/MFA and signs identity/resource tokens.
- **Node / execution plane:** Gateway transport/coarse admission, independently
  isolated Files, Terminal, Web/Browser and other Hands. Gateway logically
  belongs to execution placement when Node Agent arrives, but its public
  route/DNS is unchanged in MVP. Neither Gateway nor Hands receives human
  passwords, direct owner Postgres access, an upstream privileged Rauthy API
  key, or authority to declare Platform membership/Cedar grants. A Hand's
  start/liveness may precede Core readiness; *every protected effect* remains
  unavailable until real trusted identity, Project, original MCP resource
  audience, fresh Access/Cedar decision and peer/root mapping are confirmed.
  This is a **logical boundary**, not current physical network isolation:
  the approved single-host stack still shares the `briareus-net` transport.
  Separate network-level Node/Core trust must be proved before moving Hands.
- **Future Workspace placement:** Files, Terminal and local Git operate in one
  owner-scoped filesystem on a chosen node. Do not add hardwired multi-node
  scheduling, global IPC, forced service colocation or host Docker socket
  access now. Rootless/nested containers need later isolation acceptance.

**Human first operator is a single *identity*, not a globally reused secret.**
The Briareus operator links a verified Rauthy issuer/subject to current
Platform operator authority; equality of email or the presence of
`rauthy_admin` is insufficient alone. Never reuse human/admin passwords for
PostgreSQL, Alembic, Valkey or private API keys. Rauthy v0.37.1 itself owns
empty-provider initial admin bootstrap; user-facing login, MFA and recovery
remain native Control Panel UI through its authenticated BFF. No password
is extracted from startup logs by other services.

## Data plane is independent from management plane

```text
User / MCP client -- Rauthy OAuth --> Gateway ---> Hand/MCP runtime
                                  |                  |
                                  +--> Authorization <--+
                                       (Cedar, PostgreSQL owner grants, Valkey optional)

User browser ---> Gateway /api/* ---> API (management BFF) ---> service-owned APIs
User browser ---> Gateway /panel/ ---> UI (management frontend)
```

- **`services/api` and `services/ui` are purely management/control-plane tools**. Users can configure Rauthy identities, Team/Project membership, Authorization grants and approvals, Resources and Hands through authenticated **owner** APIs. UI presents its own sign-in/MFA/recovery flow, while API manages the upstream Rauthy challenge/session and verified User/Project; neither displays or redirects the browser to upstream hosted login. **Neither API nor UI is a dependency of live MCP requests**. Stopping/rebuilding/removing either may stop management functions, but must not interrupt already running Gateway, Authorization, Hands or execution sessions.
- **`services/external` Rauthy** is the OAuth/OIDC authority: user/service identity, credentials, sessions and JWKS. Gateways/Hands validate required OAuth token identity, audience, expiry and signature with cached trusted provider metadata; the API does not mint its own JWT.
- **`services/authorization`** owns policy and grants; Cedar is a Rust-backed policy evaluator embedded in this service, not another required process. This service reads only its own durable access state from the existing PostgreSQL server, uses real authenticated source-owner APIs for external facts, and may use Valkey for cache/invalidation. It does not call management API to decide.
- **`services/gateway` is the ingress PEP**: it calls Authorization directly for connection/session/coarse MCP admission when required, never via API/UI. It performs transport/routing/streams and does **not** own policies, SQL, approvals or User/Project business data. Per-tool/effect Authorization is enforced again by the actual **Hand PEP**, which sees the real arguments and current grant; a successful Gateway admission is not a blanket permission to execute every tool. This additional Gateway admission check is the owner's new routing choice and supersedes the earlier 'Gateway never asks Authorization' wording, without turning Gateway into the PDP.
- **`hands/<hand>`** are independently deployed, independently configurable MCP/tool providers with their own runtime and credentials. Untrusted Hand executors remain isolated from private DB/Valkey/IdP admin/control networks; users cannot forge headers or self-grant. AgentSession and terminal/execution session have independent lifecycles. On revoke, version/fence checking ensures strict actions cannot rely on stale cached permissions; in-flight effects require their own cancellation.

## Deploy and Watch migration

- For an internal module, use Coolify **Base Directory** `/services/<service>`; for a Hand, `/hands/<hand>`; **Compose location** `/docker-compose.coolify.yaml`. The service's source `build.context` must still resolve to the actual repository root when its Dockerfile `COPY`s under that root; use relative paths derived from the manifest's real folder depth.
- Coolify **Watch Paths** are repository-relative and directory-wide: `services/<service>/**` or `hands/<hand>/**`, **always `services/external/**`** and any imported shared subtrees. External Services updates deliberately trigger each module by owner decision; an API-only change must **not** redeploy Gateway, UI, Authorization or Hands, and docs-only changes must not trigger builds. Do not narrow to individual file lists or generate a per-file import graph. Do not create one Compose project containing API+Gateway+Authorization+Hands; it would couple restarts and deploys.
- Keep the **existing approved 14 Dev Coolify Application UUIDs**, current DNS aliases, public routes and durable state until each cutover succeeds. The old `deploy/<module>` and legacy sources are rollback-only *until proven equivalent*, then retired. Never delete already-used DBs/volumes, move passwords into Git, inspect other Coolify projects/environments, or create a Rauthy Application UUID without explicit allowlisting.
- **Canonical release names** are Docker service/DNS aliases `briareus-control-panel-api:8000` and `briareus-control-panel-ui:8080`, matching their independently owned Compose sources. Gateway must target these exact names in the same coordinated release; it must not retain obsolete `briareus-admin-api/ui` addresses (see the current unresolved Runtime source mismatch in [#536](https://github.com/KobaProduction/briareus/issues/536#issuecomment-6180034198)). The browser paths remain `/api/*` and `/panel/`. Do not claim active Dev routing or signed Rauthy login acceptance solely from these names; keep existing live state until the integration cutover is proven.

## Ownership and acceptance

- Backend: `services/api/`, `services/authorization/`, Platform/Resources where still independently deployed, grants/approvals, owner DTOs.
- Frontend: `services/ui/` and its UI-only Watch. Runtime: `services/gateway/`, **all** `hands/` and final MCP connection/tool enforcement. Deployment: upstream Rauthy `services/external/`, approved Data/runtime infrastructure and resource-scoped Coolify path changes when needed; application owners may configure only their own preapproved Dev apps.
- Orchestrator updates agent tasks and checks folder ownership + handoff; no shared undirected source edits across lanes.
- Validate actual static/native build, required Git checks, scoped Coolify saved Base/Compose/Watch, a real relevant HTTP/MCP operation, and **independent restarts**. Source-only or running health ≠ live OAuth/Authorization acceptance.

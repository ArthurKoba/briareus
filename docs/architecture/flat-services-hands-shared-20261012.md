# Briareus: flat Services, Hands, Shared — owner decision 2026-10-12

**Status: selected target; incremental migration, not evidence of an already deployed cutover.** This is the newest owner decision and overrides the nested `services/control-panel/{api,ui}`, `services/infrastructure/gateway`, `services/platform/<owner>` and `services/hands/<name>` target layouts in older documents. Rauthy + Cedar remains selected. Product/API business semantics, independent service ownership, retention of data, Coolify access scope, and required GitHub checks remain in force.

## Repository root

```text
services/
  api/                   # Python Control Panel management API/BFF; optional to MCP dataplane
  ui/                    # independently deployed Control Panel frontend
  gateway/               # MCP ingress/stream routing and coarse authorization admission
  authorization/         # authoritative grants, AgentSession, approval/revocation, embedded Cedar
  identity/              # Rauthy upstream IdP, OAuth/OIDC sessions/clients/keys; Deployment owner
  platform/              # independent Team/Project owner IF/WHEN retained as a separate deploy
  resources/             # independent Resource Catalog IF/WHEN deployed independently
  data/                  # optional existing PostgreSQL+Valkey Compose owner, only if owned by Deployment
hands/
  files/ terminal/ web/ svc/ infrastructure/ reverse/ ...
shared/
  contracts/             # narrow shared DTO and wire contracts only
  transport/             # optional small reusable protocol helpers
  telemetry/             # optional small reusable observability helpers
  security/              # optional small reusable security *primitives*, no domain permissions

docs/services/{api,ui,gateway,authorization,identity,platform,resources,data}/
docs/hands/<hand>/
docs/shared/<topic>/
```

Each separately deployed module owns its **own** `src/`, `Dockerfile`, `docker-compose.yaml`, `docker-compose.coolify.yaml`, uv/Bun manifest+lock, health/start and **its own migration only when necessary**. No central `deploy/` as the target. Separate documents from deployment-watch directories. No nested layout prefixes just to repeat `control-panel`, `infrastructure` or `platform` when the service has a unique name. Place MCP tools/providers **only** in `hands/`, never mix them into internal `services/`. Common cross-service DTO may live in `shared/contracts/<topic>`, with one selected editor and explicitly narrow consumers. Do not treat a shared package as permission to import owner ORM, database tables or business rules across services.

## Data plane is independent from management plane

```text
User / MCP client -- Rauthy OAuth --> Gateway ---> Hand/MCP runtime
                                  |                  |
                                  +--> Authorization <--+
                                       (Cedar, PostgreSQL owner grants, Valkey optional)

User browser ---> Gateway /api/* ---> API (management BFF) ---> service-owned APIs
User browser ---> Gateway /panel/ ---> UI (management frontend)
```

- **`services/api` and `services/ui` are purely management/control-plane tools**. Users can configure Identity users/groups, Team/Project membership, Authorization grants and approvals, Resources and Hands through authenticated **owner** APIs. **Neither API nor UI is a dependency of live MCP requests**. Stopping/rebuilding/removing either may stop management functions, but must not interrupt already running Gateway, Authorization, Hands or execution sessions.
- **`services/identity` Rauthy** is the OAuth/OIDC authority: user/service identity, credentials, sessions and JWKS. Gateways/Hands validate required OAuth token identity, audience, expiry and signature with cached trusted provider metadata; the API does not mint its own JWT.
- **`services/authorization`** owns policy and grants; Cedar is a Rust-backed policy evaluator embedded in this service, not another required process. This service reads only its own durable access state from the existing PostgreSQL server, uses real authenticated source-owner APIs for external facts, and may use Valkey for cache/invalidation. It does not call management API to decide.
- **`services/gateway` is the ingress PEP**: it calls Authorization directly for connection/session/coarse MCP admission when required, never via API/UI. It performs transport/routing/streams and does **not** own policies, SQL, approvals or User/Project business data. Per-tool/effect Authorization is enforced again by the actual **Hand PEP**, which sees the real arguments and current grant; a successful Gateway admission is not a blanket permission to execute every tool. This additional Gateway admission check is the owner's new routing choice and supersedes the earlier 'Gateway never asks Authorization' wording, without turning Gateway into the PDP.
- **`hands/<hand>`** are independently deployed, independently configurable MCP/tool providers with their own runtime and credentials. Untrusted Hand executors remain isolated from private DB/Valkey/IdP admin/control networks; users cannot forge headers or self-grant. AgentSession and terminal/execution session have independent lifecycles. On revoke, version/fence checking ensures strict actions cannot rely on stale cached permissions; in-flight effects require their own cancellation.

## Deploy and Watch migration

- For an internal module, use Coolify **Base Directory** `/services/<service>`; for a Hand, `/hands/<hand>`; **Compose location** `/docker-compose.coolify.yaml`. The service's source `build.context` must still resolve to the actual repository root when its Dockerfile `COPY`s under that root; use relative paths derived from the manifest's real folder depth.
- Coolify **Watch Paths** are repository-relative, exactly `services/<service>/**` or `hands/<hand>/**` plus only imported shared subtrees. A change to API must **not** redeploy Gateway, UI, Authorization or Hands; docs-only changes must not trigger builds. No generated per-file import graph. Do not create one Compose project containing API+Gateway+Authorization+Hands; it would couple restarts and deploys.
- Keep the **existing approved 14 Dev Coolify Application UUIDs**, current DNS aliases, public routes and durable state until each cutover succeeds. The old `deploy/<module>` and legacy sources are rollback-only *until proven equivalent*, then retired. Never delete already-used DBs/volumes, move passwords into Git, inspect other Coolify projects/environments, or create a Rauthy Application UUID without explicit allowlisting.
- API specifically preserves legacy `briareus-admin-api` Docker service key/alias during the first transition, while its source moves to `services/api/` and its displayed app name becomes Control Panel API. The user-facing path remains `/api/*` (not `/control-panel/api/*`). Rauthy integration replaces legacy auth endpoints **only after** a genuine issuer and user authentication flow have been verified.

## Ownership and acceptance

- Backend: `services/api/`, `services/authorization/`, Platform/Resources where still independently deployed, grants/approvals, owner DTOs.
- Frontend: `services/ui/` and its UI-only Watch. Runtime: `services/gateway/`, **all** `hands/` and final MCP connection/tool enforcement. Deployment: upstream Rauthy `services/identity/`, approved Data/runtime infrastructure and resource-scoped Coolify path changes when needed; application owners may configure only their own preapproved Dev apps.
- Orchestrator updates agent tasks and checks folder ownership + handoff; no shared undirected source edits across lanes.
- Validate actual static/native build, required Git checks, scoped Coolify saved Base/Compose/Watch, a real relevant HTTP/MCP operation, and **independent restarts**. Source-only or running health ≠ live OAuth/Authorization acceptance.

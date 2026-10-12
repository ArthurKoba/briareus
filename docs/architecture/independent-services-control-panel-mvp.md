# Briareus — Independent Service Architecture and MVP Restructure (OWNER DECISION 2026-10-12)

Status: SELECTED ARCHITECTURE; implementation and Dev cutover remain separate from this design publication.

## 0. Explicit owner correction and authority

This document supersedes prior contradictory descriptions of Admin API as a central business/Core service, Gateway as C2 authorization engine, and Python deployment as an AST-derived per-file Watch/COPY graph. The OWNER selected autonomous, folder-contained independent services in a monorepo. Three engineering agents implement and self-build/test/release within their owned areas; Orchestrator accepts retrospectively against these invariants. No pre-implementation microapproval or duplicated review loops. Materially destructive data/security boundary changes require separately established real authority, not invented approval.

Non-negotiable: Briareus MCP / development only for any infrastructure observation/change. Existing live app UUIDs, network, Postgres/Valkey data, database owners, public origin, rollback and approved credentials persist. No accesses to other projects, environments, Shared Environments or secret values.

Current evidence at selection: published Gateway is already a thin HTTP reverse proxy with public / and /panel/; legacy gateway_transport removed from active main. Control Panel API is still displayed as Admin API; independent Identity serves private/internal API. Git files and Coolify Watch/COPY currently enumerate many individual Python sources; previously measured 643 total Watch entries across 14 apps (may change); actual persisted paths sometimes lag Git. Git main must be rechecked before the first source move. A successful healthcheck does not mean User login works.

## 0.1. Mandatory TRY-first delivery rule — owner correction

The owner wants WORKING MVP and SIMPLE service packaging, not another weeks-long architecture review. **TRY -> observe the actual outcome -> fix what broke -> repeat** is the default engineering loop.

- Do NOT demand a new Orchestrator review, user confirmation, source-graph reapproval, giant architecture checklist, preliminary staging report or inter-agent meeting before each routine change. Explicit owner direction in this document is sufficient to begin independently scoped source work now.
- Implement the smallest runnable vertical change, run the minimum native build/check that finds real mistakes, merge with the repository's genuinely enforced Git protection, let scoped Dev Auto Deploy run, check the real affected service and public API, then immediately fix observed regressions.
- Do not re-run huge Ruff/Mypy/e2e suites reflexively across unrelated services, compute exact SHA manifests for every file or duplicate already evidenced CI simply for ceremonial acceptance. Use meaningful targeted checks; if something breaks, diagnose and repair it in the same owner lane.
- Architectural restructuring proceeds autonomously by service and preserves a known-good rollback, but never migrates databases/wipes data, exposes secrets, bypasses authorization or changes other projects/environments. Existing protected controls remain a correctness boundary, NOT a reason to design five more C2 contracts.
- The retrospective Orchestrator may check the integration result at milestones. Agents do not stop each small step for its permission. Record actual status and failures in their existing progress files, and make next design decisions themselves.
- Do not create a new full-system test framework, migration engine, build generator or release-control service just to simplify these directories. Test actual changed service behavior, including an isolated redeploy.

## 1. Independent service model — not a Panel-owned system

### Infrastructure services
Gateway ingress, telemetry/observability plumbing, existing PostgreSQL/Valkey data runtime and any other genuine infrastructure service. Each has a distinct owner, folder, image, deployment, logs and lifecycle. Running infrastructure is not recreated because the Panel UI changes.

### Platform/domain services
Identity (users, credentials, first-user bootstrap, identity status), Authorization (access decisions, grants, AgentSession and revocation), Platform Control (Teams, Projects, membership), Resource Catalog (resource metadata/integration custody) and any further owner domains. Each is a real independent service with its own API, migrations and persistent state ownership when required. The Control Panel does not directly mutate their databases or force-restart them.

Identity answers who the caller is and owns credentials, user state, login and current identity. Authorization answers which actions/resources the authenticated principal can access. Domain owners additionally enforce their resource-specific operations. Do not conflate identity authentication, authorization and gateway routing. A Panel management UI must show a User state but does not own that state.

### External/tool services — Hands (MCP)
Files, Terminal, Web, SVC, Infrastructure, Reverse, and future individually deployable Hands. A Hand is a separately versioned/buildable addressable module, not a hidden subpackage under a giant Panel API. Group GitHub/GitLab logical Hands and existing SVC aggregator based on real deployment/consumer compatibility; never invent extra live apps or split a working provider just for neat naming. Many more Hands will be added. Each Hand owns its own API/MCP runtime, isolation, state or FS permissions, health, metrics and fallback behavior. It may use approved Identity/Authorization decisions but may not inherit a Panel process lifecycle.

### Control Panel — only a management facade
Rename the old visible names Admin API -> Control Panel API; Admin UI -> Control Panel UI. The API is a relatively thin BFF/client/adaptor for operators and ordinary users: UI-facing REST, session handling, input validation, orchestration of explicit calls to independent service APIs, and presentation-friendly aggregate responses. It does not own Identity credentials, Authorization grants, Resource Catalog records, Hands runtime implementations or their SQL tables. If the operator configures Resources, the Panel calls Resources API. If the operator changes access, the Panel calls Identity and/or Authorization with checked permissions. If the operator runs/checks a Hand, the Panel calls that Hand's approved management endpoint. A Panel-only code change redeploys only the Panel API; a Panel UI-only code change redeploys only Control Panel UI. A failure/restart of a backend dependency yields a bounded, honest error and preserves the Panel process.

### Gateway — thin replaceable transport
Traefik may remain upstream as in current Dev. Briareus Gateway has one responsibility: route HTTP/streaming/MCP connections to configured internal destinations and collect bounded, low-cardinality request/routing telemetry. Route rules are static/declarative, not business methods or User/Project/permissions code. Examples: / -> Control Panel UI public assets; /panel/* -> Control Panel UI; /api/* -> Control Panel API with path/method/body/needed headers preserved; auth-server issuer/discovery/token routes -> appropriate independent Authorization/Identity endpoint when actually required by a protocol; /hands/<name>/mcp -> explicit registered Hand target with streaming/SSE/WS semantics and access enforcement OWNED by the destination. Do not invent active routes for Hands that are not live. Gateway does not verify JWT, implement C2, select private Identity methods, own databases or instantiate domain DTOs. Remove dependency on Panel implementations from Gateway; telemetry must not record passwords/tokens or unbounded labels.

A future Go gateway or Traefik-only route set is an optional substitution because route/telemetry config is separate from business logic; NOT a prerequisite for MVP. gRPC also optional and must not become an MVP condition. Bounded HTTP keep-alive/connection pooling is acceptable now; change transport only on measured need.

## 2. Target folder architecture — one deployable box per service

Illustrative target, not a premature command to rename every running path in one commit:

    services/
      infrastructure/
        gateway/
          src/
          Dockerfile
          compose.coolify.yaml
          pyproject.toml
          uv.lock
        telemetry/
        data/
      platform/
        identity/
          src/
          migrations/
          Dockerfile
          compose.coolify.yaml
          pyproject.toml
          uv.lock
        authorization/
        platform-control/
        resources/
      control-panel/
        api/
          src/
          Dockerfile
          compose.coolify.yaml
          pyproject.toml
          uv.lock
        ui/
          src/
          public/
          Dockerfile
          compose.coolify.yaml
          package.json
          bun.lock
      hands/
        files/
        terminal/
        web/
        svc/
        infrastructure/
        reverse/
        github/              # when independently deployed and proven
        gitlab/              # when independently deployed and proven
    shared/
      contracts/
        identity/
        authorization/
        resources/
        platform/
        hands/
      transport/
      telemetry/
      security/              # minimal reusable primitives, no global owner
    docs/architecture/

This is a mono-repository of self-contained services, not Git submodules or mandatory nested .git repositories. A single service directory is the human ownership, Docker/Compose, dependency and Watch boundary. Keep each package's actual runtime startup and migrations together. Services do not import private implementation files of another service. If a contract is common, use a small versioned and owned shared contract/schema at a meaningful namespace; prefer transport DTOs to sharing database ORM models or business state. Some small harmless duplication is preferable to giant transitive shared dependencies.

Infrastructure deployment configuration is service-local rather than a second disjoint deploy/<service> tree. During transition, old deploy/<service> paths remain VALID until a proven safe service-scoped cutover; never delete old working Coolify definitions while rollback depends on them. Make no unreviewed changes to persistent volume mounts or database names. For a Coolify Application retain existing UUID/domain/app ownership and update base directory, Compose location and Watch as one checked unit only at the corresponding migration boundary.

## 3. Single-scope build, simple Watch Paths, selective shared consumers

For each service S use service-directory watch and only actual imported shared subtree watches:

    services/platform/identity/**
    shared/contracts/identity/**
    shared/security/**

Example only; require real path and build-context validation before applying. No list of fifty individual .py inputs. Service-local Dockerfile copies owned service folder plus explicit shared SUBDIRECTORIES; build context may remain repo root to allow shared imports. .dockerignore rejects credentials and generated local files and can exclude other services; don't reconstruct AST transitive import lists to justify every COPY. Avoid repeating the same input set in Dockerfile, Dockerfile.dockerignore, SELECTIVE_UV_SOURCE.json and Compose. One canonical service manifest/lock plus simple Watch config, direct native build; dependency versions pinned by service-local uv/Bun lock.

Changing Control Panel UI -> only UI rebuilt.
Changing Control Panel API -> only API rebuilt.
Changing Identity local code -> only Identity rebuilt (consumers use stable HTTP contract, no reason to restart).
Changing Resources local code -> only Resources rebuilt.
Changing Hands files local code -> only Files Hand rebuilt.
Changing shared/contracts/identity -> rebuild only explicitly consuming services (e.g. Identity and Panel API). A shared library change may intentionally rebuild multiple services; no need to optimize every last restart.
Changing docs/readmes need not restart if separate, but occasional harmless extra Dev rebuild is preferable to fragile per-file graph magic. Avoid general shared/** on all apps; break shared into topical folders. Service dependency at runtime is NOT a deployment dependency: do not use Compose depends_on across independent running apps just because Panel API makes HTTP calls to Identity. Independently deploy API changes must not cascade into Identity and vice versa.

Do not reintroduce a global custom migration manager, per-file SHA/COPY/Watch equality gate or silent code-generation blocker that delays MVP. Minimal checks: native build/import, valid Compose, target inputs present, no leaked secrets, only expected service rebuild for representative changed paths, healthy app and real HTTP/MCP behavior. Read actual persisted Coolify Watch paths as runtime truth and reconcile them only for the approved Dev application.

## 4. Internal requests and security boundary

Use stable private service DNS plus bounded connection pools, timeouts, retries only for clearly idempotent operations, and explicit error translation. HTTP/JSON REST is MVP default. Service-to-service API must be authenticated/authorized at the real owner boundary where access matters; do not blindly trust user-supplied X-* proxy headers or omit original-operation idempotency for non-repeatable effects. Adopt minimum justified internal trust from independently existing verified material; do not invent signer/mTLS/AF_UNIX peer or require five nested permits for login. Browser human session and current User validation belong to Identity/Control Panel API; actual permissions belong to Authorization and each target domain/Hand. First-user bootstrap is a distinct authenticated-operator workflow; never expose a one-use first-admin code in normal public HTTP/logs. If operator binding/key material truly unavailable in approved scope, report EXACT external authority once and keep safe independently feasible source/UX work going.

MVP API path responsibilities:
- Gateway transparently forwards /api/* unchanged to Control Panel API.
- Control Panel API handles /api/auth/register, /api/auth/login, /api/auth/logout and /api/platform/me as a thin HTTP client to Identity over private DNS. It does not copy Identity SQL/credential logic.
- Service management and read operations are explicit stable Control Panel API adapters to the appropriate service/Hand management API, with proper user access checks.
- Identity owns its native internal routes and token/user lifecycle; Authorization owns grant decisions; Resources and Hands own their changes.
- Gateway routes MCP connections to individual Hand endpoints only when actually deployed and registered, preserving streaming and transport semantics.

## 5. Zero-cascade lifecycle and failure acceptance

Concrete mandatory matrix:
- Edit UI styles or component: Frontend UI image+app redeploy only; Admin/Panel API, Identity, Hands unchanged.
- Edit Control Panel API route: API image+app redeploy only; Identity, Resource and Hands container/deploy IDs unchanged.
- Edit Identity password/user implementation: Identity image+app redeploy only; Panel API responds to temporary 502/503 with bounded error/recovery and no container restart.
- Edit Files Hand: Files Hand only; other Hands and Panel API not rebuilt.
- Edit shared identity contract: Identity and only actual consumer(s) rebuilt; unrelated Hands/Gateway untouched.
- Stop Identity for a bounded test: Panel API stays alive, identity-dependent requests fail predictably, unrelated UI and Hand services remain online.
- Stop Panel API: Identity, authorization, resources, individual Hands remain online, independently callable from their permitted internal consumers.
- Failed/missing Hand: Panel management shows that Hand unavailable; no all-service failure or mass redeploy.
- Restart/redeploy: DB volumes/Valkey and owner DBs preserved; no new auth bypass, no secret reveal.

Accept normal single-service brief outages during own redeploy. Never treat an unavailable upstream as a reason to force-restart its consumers; use explicit retry readiness/health status, connection re-establishment and backpressure. Dynamic service discovery and centralized control-plane scheduling are deferred unless a real MVP use case proves necessity.

## 6. MVP first, migration in slices with independent agent ownership

Stage A — Freeze current real baseline and publish contracts; no broad source relocation yet. Record exact Git main and known live Dev HTTP/status and independent data ownership; preserve previous deployment for rollback. Correct existing wrong task assumptions: Gateway not C2, Panel API not global owner, Watch generated per file is retiring architecture.

Stage B — Working signed first User through thin Control Panel API -> Identity with real protected access/credentials; public /panel/ renders, /api/auth POST /me usable for a valid authorized user and safe negative paths, no user data/logging. Do not gate this on rehoming ALL Hands, gRPC, Go or perfect Watch. If first-admin physical operator access is genuinely missing, isolate this gate with exact required proof while other slices continue.

Stage C — Pilot service packaging: select one low-coupling service and make it self-contained source+Docker+Coolify Compose+lock+Watch; prove changing ONLY it triggers ONLY its app and rollback works. Good candidates: Control Panel UI or one stateless Hand, but pilot selection must be made against current source/Dev state and ownership before cutover. No data migration.

Stage D — Move Control Panel API and core owner services one at a time into service-local folders with independent deployments. Preserve existing Coolify apps/UUIDs/domains/databases/roles/migrations; migrate imports and shared DTOs on a small source-by-source boundary. The Panel API rename is both user-visible labels and source architecture, not a mass rename of authorization/Identity. Preserve existing API public routes and support compatibility alias during cutover where clients require it.

Stage E — Move Hands into services/hands/<name>/ and shared contract consumer graph; each Hand adds/removes independently. Preserve physical filesystem access, service accounts, permission fences and data mounts. Only retire legacy paths/AST graph/SELECTIVE_UV_SOURCE and verification machinery AFTER all actual runtime apps build and Watches reconcile; remove dead code instead of retaining two authoritative packaging schemes indefinitely.

Stage F — Integration acceptance and ops UX: observe real zero-cascade Watch cases, real UI login, settings, Identity/Authorization/Resources management and isolated MCP Hand failures; test representative caching/Valkey usage only when a source consumer and cache invalidation model are defined. Keep telemetry by service+route template/destination and avoid high-cardinality credential labels.

Each phase must use focused clean Git branches, reviewer-required CI, agent-owned native build/test and exact Briareus Dev deploy+HTTP/log observation; ONLY independent retrospective Orchestrator accepts SOURCE vs BUILD vs DEV_RUNTIME vs actual USER/MCP product separately. No prepublication sign-off microcycle. Cross-owner message flow through existing agents/<lane>.task.md, agents/<lane>.progress.md and coordination/requests/<lane>.md. User-facing agent chat is short text, NEVER a table. Orchestrator status table is ONLY a three-lane start/stop operator aid.

## 7. Agent ownership and handoff

Backend owns services/platform/* (Identity/Authorization/Platform/Resources where that code is real), services/control-panel/api/*, shared owner-specific DTO/contracts and the first-user pipeline. No cross-domain SQL writes from Control Panel API. Maintain direct service health and owner migrations, fast independent API redeploy; negotiate shared contract namespace with Runtime only once through files.

Runtime owns services/infrastructure/gateway/* and services/hands/* source/runtime, their per-service release/Watch migration and transport/telemetry route config, not Panel API auth. In migration may own moving legacy services/modules/* into Hands and a narrowly scoped shared telemetry/transport area. No Browser User auth in Gateway.

Frontend owns services/control-panel/ui/*, existing admin-web-app source migration, UI design/first-user states and the browser-to-Control-Panel-API contract, plus user-facing rename to Control Panel. Frontend does not build or restart Identity.

For any shared paths that have more than one potential editor, record ONE explicit owner at that migration slice BEFORE both begin. Safe branches from current main, no bulk overlay or workers overwriting a peer's private tree. Integration graph/API route contract must be in THIS decision authority rather than duplicate descriptions in every worker task. Concrete task and progress in existing workspace files, no need to keep asking owner.

## 8. Acceptance gates: what MUST NOT be declared DONE

A. Repo folder layout matches owner: each deployable app has ONE obvious directory containing runtime, Docker/Compose, dependency manifest/lock and owner migration when applicable.
B. Real Python/Frontend builds PASS using owned inputs, with no hidden per-file import manifest required for every edit.
C. Five representative Watch changes validated against actual Coolify Dev persisted Watch (UI, Panel API, Identity, a Hand, one shared); only expected apps deployed.
D. Routes preserve existing public root and Panel; Gateway is business-unaware, stream-safe and collects bounded gateway metrics.
E. Control Panel API is a real authenticated management facade to independent service APIs; service failures bounded and no cascading application redeploy.
F. Identity + Authorization controls remain enforced by real service owners, legitimate bootstrap trusted, no data loss/secret leaks.
G. Existing owner DB schema, volumes and current running isolated Hands are preserved; no hand-waved e2e acceptance from healthcheck.
H. Legacy deploy/module layout and exact-source graph retired only after reference inventory is empty and rollback is credible.

Out of MVP: mandatory Go gateway rewrite, gRPC migration, perfect per-file rebuild selectivity, new universal service registry/control plane, speculative cache layers, broad replacement of existing database ownership/credentials.

## 9. Contradictions resolved

- Previous Gateway preauth/JTI/C2 port duties are superseded: owner services enforce security; Gateway remains transport.
- Previous Admin API as central business/domain owner is superseded: Control Panel API only a UI-facing thin management facade.
- Previous ASGI health-only app as acceptable completed Admin API is superseded: functional /api routes and real user flow required for MVP.
- Previous exact per-file source graph+Coolify Watch is a transitional implementation detail, not target architecture or acceptance requirement.
- Existing per-service isolated domains remain independent. A shared contract change can rebuild the consumers; one service deployment must not redeploy its HTTP callers.
- Infrastructural auth/DB safety, proper actual permission enforcement, protected operator setup and independent owner migration continue to be mandatory. No fictitious relaxed security approval.
- Later Go/gRPC/cache optimizations do not block initial service isolation or first User.

Owner has selected these decisions. Agents do not reopen them by proposing alternate architecture unless physical evidence shows a correctness/security contradiction; at that boundary report exact evidence through coordination files, continue unrelated safe work, and request Orchestrator decision rather than silently reverting to previous complexity.


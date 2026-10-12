# Briareus — independent services, Control Panel, thin Gateway

**Current owner decisions:** owner-decisions-20261012.md.
**Agent program:** ../operations/agent-migration-plan-20261012.md.
No historical ENV-1, global wheel, Gateway C2, privileged Unix bootstrap or per-file Watch requirement is active.

## Runtime topology

Infrastructure has its own runtimes, including thin Gateway, telemetry and Data.
Platform domains are independent: Identity (users, invitations, signing), Authorization (grants), Platform Control (Team/Project), Resources (integrations/catalog).
Control Panel API is a separate management BFF/client of these private service APIs, not an owner of their data or processes; Control Panel UI is a separate browser app.
MCP Hands (Files, Terminal, Web, SVC, Infrastructure, Reverse and future providers) each own their runtime, permissions and deployment. Do not bundle all Hands in a Panel or a Gateway.

Gateway provides only declarative routing, streaming/connection handling and bounded non-secret metrics. Routes for public/UI, unchanged /api/* to Control Panel API, protocol-defined issuer routes and actually registered /hands/<name>/mcp. Identity/Authorization/Hand owners enforce authenticated access; Gateway never verifies Human JWT, Project, C2 or business requests. Go and gRPC are optional future optimizations, not MVP dependencies.

## Monorepo layout

    services/
      infrastructure/gateway/
      platform/identity/
      platform/authorization/
      platform/platform-control/
      platform/resources/
      control-panel/api/
      control-panel/ui/
      hands/files/
      hands/terminal/
      hands/web/
      hands/svc/
      hands/infrastructure/
      hands/reverse/
    shared/contracts/<topic>/
    shared/transport/
    shared/telemetry/
    docs/services/ (mirror of services without runtime source)

Each independent service directory contains its own source, Dockerfile, Compose, dependency manifest and lock, startup, and only its real persistent owner migrations. No required deploy/<name> sibling directory and no nested Git repositories. Documentation stays in separately mirrored docs/services/** and does not trigger service Watch.
Watch patterns: owning service directory/** plus actually consumed thematic shared/topic/**, NOT a list of single Python files; no required AST import/COPY machine registry. A change to one service does not automatically redeploy its callers or other Hands.

## Security and persistence

No new SQL users/roles or databases for MVP. Development currently uses one approved PostgreSQL principal and four separate owner databases; keep existing volumes and owner Alembic. Identity issues system invitation in operator startup logs if and only if count(superuser)<1; after that only superuser issues invitations. Signing keys stable over restarts, appropriate Environment Shared secret reference, no old ADMIN_JWT_SIGNING_KEY. Team Shared owns TZ/OTLP. Secret values never baked into Docker.
The priority isolation risk is untrusted Hands sandbox reaching private owner services, internal DB/Valkey, credentials or other workloads. Constrain runtime network/egress/privileges and enforce permissions in real owner service endpoints, never trust forwarded identity claims.

## Delivery

TRY: change owned source -> native build -> scoped Dev release -> observe real result -> fix if broken. Do not introduce or run new unit/integration/e2e/smoke suites during MVP. Keep actual required GitHub branch protections; Orchestrator reviews once after published service evidence, not before each PR. Keep old Coolify App UUID, runtime aliases, volumes and old source paths until each new service has proven cutover and rollback.

Detailed bootstrap/key/scope and acceptance rules are ONLY in owner-decisions-20261012.md, not duplicated here.

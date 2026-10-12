# Briareus — current AGENTS map (flat Services/Hands/Shared, 2026-10-12)

**LATEST OWNER TOPOLOGY:** docs/architecture/flat-services-hands-shared-20261012.md (flat root `services/`, `hands/`, `shared/`, independent management/data planes).
**IDENTITY/AUTH DESIGN:** docs/architecture/identity-rauthy-cedar-20261012.md (Rauthy + Cedar).
**FOUR OWNERS / HANDOFF:** docs/operations/rauthy-cedar-four-agent-migration-20261012.md.
**Coordination:** docs/operations/AGENT_COORDINATION.md and local workspace coordination/CONTRACTS.md, OWNERSHIP.md, requests/<lane>.md.
**Current agent tasks:** agents/{backend,runtime,frontend,deployment}.task.md; agent reports/evidence in *.progress.md FIRST State.
**Original baseline:** docs/architecture/owner-decisions-20261012.md still governs independent service folders, PostgreSQL/Valkey volumes, sandbox network isolation and TRY-first. Its home-grown Identity/bootstrap/JWT paragraphs are **transitional legacy only**, superseded by the selected Rauthy document.

## Owners
Backend: `services/authorization/` Cedar and grants/AgentSessions/approvals, `services/api/` independent Python management BFF; the BFF is NEVER on live MCP dataplane. Rauthy itself replaces Human Identity/OAuth issuer, not Project Control and not AgentSession grants.
Runtime: `services/gateway/` transport and coarse Authorization admission; `hands/<hand>/` per-effect enforcement and sandbox isolation.
Frontend: `services/ui/` independent management UI with real OIDC + PKCE, truthful approval state.
Deployment: `services/external/` upstream Rauthy alongside Postgres and Valkey/Dev provisioning and real issuer/storage/Admin API contract. It does not duplicate Backend/Cedar/Gateway/UI implementation.

## Autonomous release
TRY: independently owned small real source change -> native build -> protected GitHub PR/reviewer merge -> exact approved Briareus Development app logs/real OAuth/HTTP/MCP outcome -> fix. No new unit/integration/e2e/smoke suites. Orchestrator accepts retrospectively; no prepublication review committee. Agent chats use short emoji TEXT, never tables; Orchestrator-to-owner start/stop TABLE has four lanes only.

## Security / data
Coolify MUST stay inside Briareus MCP project UUID 3xshlpoghb9wcyhjgktlqzzp, development environment UUID naibrku1omovvmw5o0bcnp5c, exact 14 existing allowed app UUIDs in docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md. Forbidden EVEN TO VIEW other projects, non-Dev, Shared Environments, global resources or plaintext secrets. Rauthy must join the existing allowlisted External Services Application; do not create another app. Preserve legacy Identity until independently verified cutover and rollback acceptance. Preserve DB/Valkey/volumes, no fictitious IdP issuer, principal/authorization grant or secret values.
Only Rauthy owns OAuth/JWT User tokens, Authorization owns Cedar policy/grants, Hands enforce resource access, Gateway transports traffic. No unsupported mass cutover or broad private-network access for sandbox executors.

**Cutover precedence:** the flat layout document supersedes all older nested-folder examples. No central deploy/ target, no cross-owner Compose restarts (External vendor stack is explicitly shared), no management API in Gateway→Authorization→Hand execution checks.

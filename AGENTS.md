# Briareus — current AGENTS map (Rauthy + Cedar, 2026-10-12)

**AUTHORITATIVE NEW TARGET:** docs/architecture/identity-rauthy-cedar-20261012.md (selected by owner, PR #472).
**FOUR OWNERS / HANDOFF:** docs/operations/rauthy-cedar-four-agent-migration-20261012.md.
**Coordination:** docs/operations/AGENT_COORDINATION.md and local workspace coordination/CONTRACTS.md, OWNERSHIP.md, requests/<lane>.md.
**Current agent tasks:** agents/{backend,runtime,frontend,deployment}.task.md; agent reports/evidence in *.progress.md FIRST State.
**Original baseline:** docs/architecture/owner-decisions-20261012.md still governs independent service folders, PostgreSQL/Valkey volumes, sandbox network isolation and TRY-first. Its home-grown Identity/bootstrap/JWT paragraphs are **transitional legacy only**, superseded by the selected Rauthy document.

## Owners
Backend: Cedar embedded in independent Briareus Authorization; durable AgentSession/grants/approve/deny/revoke, Control Panel API OIDC/Rauthy Admin BFF. Rauthy itself replaces Human Identity/OAuth issuer, not Project Control and not AgentSession grants.
Runtime: thin declarative Gateway/OIDC route proxy + independently authenticated MCP Hands and sandbox network isolation.
Frontend: independent Control Panel UI with real OIDC + PKCE login, truthfully presenting Authorization approval status.
Deployment: fourth agent REACTIVATED for upstream Rauthy pinned image/Compose/secure Dev provisioning and verified issuer/storage/Admin API contract. It does not duplicate Backend/Cedar/Gateway/UI implementation.

## Autonomous release
TRY: independently owned small real source change -> native build -> protected GitHub PR/reviewer merge -> exact approved Briareus Development app logs/real OAuth/HTTP/MCP outcome -> fix. No new unit/integration/e2e/smoke suites. Orchestrator accepts retrospectively; no prepublication review committee. Agent chats use short emoji TEXT, never tables; Orchestrator-to-owner start/stop TABLE has four lanes only.

## Security / data
Coolify MUST stay inside Briareus MCP project UUID 3xshlpoghb9wcyhjgktlqzzp, development environment UUID naibrku1omovvmw5o0bcnp5c, exact 14 existing allowed app UUIDs in docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md. Forbidden EVEN TO VIEW other projects, non-Dev, Shared Environments, global resources or plaintext secrets. New Rauthy Application UUID is not automatically allowed; establish explicit exact target scope first. Existing Identity cannot be repurposed before real cutover and storage/rollback acceptance. Preserve DB/Valkey/volumes, no fictitious IdP issuer, principal/authorization grant or secret values.
Only Rauthy owns OAuth/JWT User tokens, Authorization owns Cedar policy/grants, Hands enforce resource access, Gateway transports traffic. No unsupported mass cutover or broad private-network access for sandbox executors.

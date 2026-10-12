# Owner selection: Rauthy + Cedar — 12 October 2026

**Status: owner-selected target, not yet implemented or deployed.** This decision supersedes custom Human Identity/JWT/session implementation and standalone non-Cedar authorization-engine plans in `owner-decisions-20261012.md`. Preserve the live implementation until an independently verified cutover. Existing operator security, network isolation, DB/volume retention, Git and scoped Coolify access rules remain mandatory.

## Responsibility boundaries

- **Rauthy (Rust, upstream image)** is the sole Human/Service identity provider: users, credentials, MFA, OIDC/OAuth, SSO/session, refresh/revocation and signing/JWKS, OAuth clients, Groups and coarse IAM admin roles. No local passwords, home-grown authorization code grant or duplicated user-JWT signer. Initial superuser onboarding must still satisfy the owner's one-time operator-only invitation expectation, but implement it via a verified Rauthy bootstrap/provisioning integration; do not assume Rauthy emits the current invitation format. Old Identity startup behavior remains a transitional compatibility boundary until that integration exists.
- **Briareus Platform Control** owns Team, Project and memberships. Rauthy Groups may be synchronized with Team for coarse IdP claims, but neither Rauthy Groups nor IAM Projects are the authoritative Briareus Project graph; do not create one IAM group for every Project. Keep stable external `sub` links, never transfer existing passwords to Briareus.
- **Briareus Authorization (existing independent owner service)** owns grant records, time-limited AgentSession permissions, approval requests, approver identity/proof, revocations, version/freshness, and use of **Cedar** for policy evaluation. Cedar is a library/policy language, NOT an accounts database, permission store, admin API or separate required deployment. Start with `cedarpy` (Rust Cedar via Python bindings) in the existing Python Authorization service; use a separate Rust service only if profiling proves necessary. Pin and review the maintained binding dependency before shipping.
- **PostgreSQL** remains the single existing server/cluster and durable authority for service-owned platform records; Rauthy storage needs an isolated supported namespace and upstream migration contract, **not** an implicit new DB/server/role. Never reuse an existing owner schema blindly or destroy existing data; physical Rauthy database/schema choice must be verified before its runtime deployment.
- **Valkey** is an optional shared accelerator/invalidation bus, never the sole durable grant/revocation authority. Cache keys scope User+AgentSession+Project+Tool+Action+resource+policy version; deny on missing current evidence for sensitive operations.
- **Control Panel API** remains Python BFF, managing Rauthy via scoped upstream Admin REST API and Authorization/Platform/Resources through their own private APIs. **Control Panel UI** is independently deployed; operator only sees Briareus UI. Do not expose Rauthy admin API keys or provider-management endpoints to browsers.
- **Gateway** remains a thin reverse/stream proxy, handling OAuth discovery/token routing and `/api/*`, `/hands/*` where needed; it does not decide JWT/Team/Project/AgentSession permission. Each **Hand/MCP resource server** validates audience/signature/token identity and enforces the corresponding authorization decision before each protected tool operation.
- **Resource Catalog** owns external provider OAuth connection credentials, encrypted external account tokens, workspace resources; Rauthy user login is not a substitute for a GitHub/Google user's delegated OAuth connection. **Execution/Terminal Sessions** own process lifetime independently from Human/OAuth sessions and logical AgentSessions.

## Three session concepts

1. **Human/Service OAuth session**: managed by Rauthy and identified by subject/client/audience; tokens use OIDC/OAuth (authorization code+PKCE for browser; appropriate OAuth flows for MCP clients).
2. **AgentSession**: Briareus owner state for one chat/agent task, linked to User or service identity, Team, Project, allowed Hands/actions/resources, grant constraints and expiry.
3. **Execution Session**: a Hand/Terminal-managed terminal/process lifetime, independently reconnectable; a transport MCP connection is not its durable identity. Revocation stops further protected operations and triggers targeted termination for interruptible active execution where policy requires it.

## Approval, policy and permission lifecycle

- Hand obtains authenticated actor+AgentSession context from verified security inputs; a self-asserted header is never authority.
- Authorization evaluates Cedar PARC (principal, action, resource, context) and durable grant status. `Deny` by default, including invalid/missing session, expired grants, mismatched Project, insufficient scope or unavailable required freshness.
- On absence of rights, return a structured **approval-required** response; Briareus records pending request with requested actions/resources, proposed TTL and initiator. Control Panel presents it; the approver may be Human, elevated agent or service account only when a **separate** existing approval privilege authorizes this exact request and scope. No self-approval or grant beyond approver authority.
- Approve/deny changes are authenticated and idempotent, stored durably. Approved grants are session-scoped, time-bounded and revocable; issue no universally reusable powerful MCP bearer token.
- Revocation commits the authoritative grant state/version and propagates invalidations to Hands/Valkey. A mere TTL or best-effort Pub/Sub is **not** a strict instantaneous-revocation guarantee. High-risk operations require a fresh enough version/fence or fail closed. Report success only after the promised enforcement barrier; in-flight external effects require separate cancellation semantics.
- Adding an MCP/tool declares its resource/action vocabulary and Cedar policy/schema, rather than adding auth code or restarting all services. Policy reload is per owner; never reconfigure unrelated Hands by changing one service.

## Management API contract (target behavior, not proof of deployed endpoints)

- **OIDC sign-in/out/current user**: Control Panel API brokers the browser's standard Rauthy authorization-code/PKCE flow and returns platform `/me` from verified identity and owner memberships. Do not keep independent password/login/JWT issuance in Briareus.
- **Identity administration**: scoped BFF operations for users/groups/roles/invitations call Rauthy Admin REST; sensitive management requires both current operator authority and the provider's least-privilege API credential.
- **Team/Project administration**: Briareus Platform Control private API; roles/membership are authoritative here, optionally projected to Rauthy Groups.
- **Access administration**: BFF presents policies, session grants and pending requests; forwards create/approve/deny/revoke to Authorization's authenticated management API. Live Hand checks call Authorization directly, not through Panel or Gateway.
- Keep a stable public `/api/*` surface and the existing `/panel/` app. Concrete DTO/routes are owned and versioned per Backend/Frontend coordination before publication, not invented as already-live endpoints.

## Rollout constraints and acceptance

1. First verify Rauthy's supported PostgreSQL topology, bootstrap, Admin API, OAuth discovery/issuer, resource audience and key rotation. Existing Development Identity application UUID may be repurposed only by its owner after data/state and route cutover; creating a new app UUID requires an explicit allowlist update. No immediate Dev deployment solely from this design selection.
2. Integrate Cedar within existing Authorization and make deny-on-missing evidence observable; prove a real grant check, a real approval and revoke before replacing current permission path.
3. Reconnect Control Panel login/current-user and platform mappings with Rauthy; avoid duplicating passwords/JWT. Preserve independently deployable service folders, existing protected DB volumes, Gateway routing contract and Hands network sandbox isolation.
4. Only after verified on authorized Briareus Development, retire legacy JWT/bootstrap secret consumers and home-grown auth flows. No artificial users, broad permissions, fake allow decisions, or claims that source/CI proves runtime acceptance.

**Project change note:** Prior A/B/F milestones in `owner-decisions-20261012.md` describe the *currently deployed legacy Identity* only where needed to keep it functioning until cutover. This document owns the *new target*; do not keep extending legacy Human Identity or a competing rule engine merely to satisfy historical milestones.

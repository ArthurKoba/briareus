# Briareus — Authorization and access (current architecture)

Owner selected current contract: owner-decisions-20261012.md.
Current Team/Project/AgentSession product model: target-project-platform.md.
Full historical original source, with outdated Gateway auth and legacy monolithic architecture, is archived outside active docs in local/artifacts/owner-policy-reconciliation-20261012/originals/repo/docs/architecture/authorization-access.md.

## Independent domain ownership

Identity authenticates User, owns credentials, invitations and User signing/JTI. It creates a system invitation and prints its registration URL ONLY on startup with zero superuser; after first superuser, all new ordinary invitations are issued by authenticated superuser. Signing material persists across restarts through the existing scoped environment secret reference.
Authorization is an independent API/domain owner of grants, roles, AgentSession, access expiration/revocation and auditable permission decisions. Platform Control owns Team/Project membership/ownership; Resource Catalog owns integration/credential/resource state; individual MCP Hands own their own operations and runtime isolation.
Control Panel API is an HTTP client for these real owner APIs; Control Panel UI is separate and cannot become a domain owner through UI role rendering. Permission-aware management operations are denied by actual source-owner/Authorization, never by untrusted client-supplied User headers.

## Gateway / MCP

Gateway is ONLY thin routing, connection streaming and bounded metrics, with explicit internal destinations. It must not validate Human User JWT, inspect owner grants or AgentSession state, or contain C2 business clients. OAuth issuer/discovery/token services own their protocol endpoints. Individual MCP Hands implement current authenticated/authorized tool execution with real trusted owners and do not expose private database/control API to a sandbox.
Auth session and AgentSession are distinct; a UUID alone is not authority. Revocation and TTL are evaluated by actual authoritative owner at protected operation time. Valkey may serve fast cache/invalidation, never replaces durable PostgreSQL owner state. Failed Identity/Authorization owner API denies the protected action without taking down unrelated Hands or Panel processes.

## MVP implementation boundaries

- Do not rewrite existing Dev database/roles/volumes: current common PostgreSQL principal and separate owner DBs are accepted for MVP.
- Protect inner service network: untrusted MCP/Terminal/Web execution must not be a peer allowed unrestricted access to private services/Valkey/DB or internal signing materials.
- Follow service-local layouts and scoped Watch, not legacy generic deploy/C2 graph.
- No new unit/integration/e2e/smoke suites in MVP; source native build, actual Dev runtime and protected endpoint behavior are the evidence. Git required checks remain binding.

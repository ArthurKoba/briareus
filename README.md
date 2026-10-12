# Briareus

An independent-service, service-folder monorepo with modular MCP Hands, a thin routing Gateway and separate Control Panel API/UI.

**NEW OWNER TARGET:** [Rauthy + Cedar](docs/architecture/identity-rauthy-cedar-20261012.md).
**Four-agent executable migration:** [Backend / Runtime / Frontend / Deployment](docs/operations/rauthy-cedar-four-agent-migration-20261012.md).
**Root AGENTS map:** [AGENTS.md](AGENTS.md).

Rauthy (upstream OAuth2/OIDC/MFA/SSO IdP) replaces custom Human Identity and homegrown OAuth. Existing Briareus Authorization remains owner of AgentSession grants, approvals/revocation and embeds Cedar PARC evaluation. Platform Control still owns Team and Project. Control Panel API is the independent management BFF for real IdP and other owner APIs; UI uses standard OIDC login. Gateway only forwards declaratively selected HTTP/MCP/issuer paths, preserves streams and collects metrics; each Hand verifies token audience and current Authorization grants before effects.

Own service folder provides Docker/Compose/dependency lock, scoped Watch and native build; docs live outside source in docs/services mirrored structure. Reuse existing DB/Valkey volumes; untrusted Hands sandbox cannot reach private infrastructure and credentials. Native build + scoped Dev observation; no new generic test suites. Legacy Identity is retained as live transition only, not a parallel new OAuth implementation. Exact source and runtime statuses must be verified, not inferred from this documentation.

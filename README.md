# Briareus

Canonical GitHub repository: [KobaProduction/briareus](https://github.com/KobaProduction/briareus).

An independent-service, service-folder monorepo with modular MCP Hands, a thin routing Gateway and separate Control Panel API/UI.

**NEW OWNER LAYOUT:** [Flat Services / Hands / Shared](docs/architecture/flat-services-hands-shared-20261012.md).
**IDENTITY/AUTH TARGET:** [Rauthy + Cedar](docs/architecture/identity-rauthy-cedar-20261012.md).
**Four-agent executable migration:** [Backend / Runtime / Frontend / Deployment](docs/operations/rauthy-cedar-four-agent-migration-20261012.md).
**Root AGENTS map:** [AGENTS.md](AGENTS.md).

Rauthy (upstream OAuth2/OIDC/MFA/SSO IdP) replaces custom Human Identity and homegrown OAuth. Existing Briareus Authorization remains owner of AgentSession grants, approvals/revocation and embeds Cedar PARC evaluation. Platform Control still owns Team and Project. Control Panel API is the independent management BFF for real IdP and other owner APIs; UI uses standard OIDC login. Gateway routes streams and calls Authorization directly for coarse MCP admission; each Hand independently enforces current Authorization grants for actual effects. The management API/UI never sit in the running MCP path.

Own service folder provides Docker/Compose/dependency lock, scoped Watch and native build; docs live outside source in docs/services mirrored structure. Reuse existing DB/Valkey volumes; untrusted Hands sandbox cannot reach private infrastructure and credentials. Native build + scoped Dev observation; no new generic test suites. Legacy Identity is retained as live transition only, not a parallel new OAuth implementation. Exact source and runtime statuses must be verified, not inferred from this documentation.

**Folder rule:** Internal service folders are flat `services/api/`, `services/ui/`, `services/gateway/`, `services/authorization/`, `services/external/` (and other genuinely independent owners); MCP providers live only in root `hands/<hand>/`, shared small DTO/helpers in `shared/`. Each deploys from its OWN folder with its OWN Compose/Docker/lock and folder-only Watch. Legacy `deploy/` stays rollback-only until physical cutover.

The existing External Services Coolify app packages upstream Rauthy with the PostgreSQL and Valkey vendor containers in `services/external/`; Cedar remains embedded in Authorization. Old `deploy/data/` is retired as source only, without deleting its live data.

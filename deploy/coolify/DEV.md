# Isolated Dev deployment

The development environment must be a **separate Coolify resource**, not a mode inside the production resource.

## Purpose

Dev is the integration/acceptance environment for frontend, backend, MCP proxy refactors and browser changes. A broken Dev deployment must not interrupt the production MCP endpoints or their persistent state.

## Source

```text
repository: ArthurKoba/mcp-bridge
branch:     dev
build pack: Docker Compose (Git-backed)
compose:    /docker-compose.yaml
```

Keep `dev` synchronized with accepted `main` changes, then merge feature work into `dev` for integrated testing. Production continues to deploy `main`.

## Isolation requirements

Dev must have its own:

- Coolify application/resource identity;
- generated bootstrap secrets;
- Admin API/auth/workspace/terminal-home/browser-profile volumes;
- Valkey instance;
- public Dev domain;
- GitHub OAuth application/callback identity;
- telemetry environment label (`OTEL_ENVIRONMENT=development`);
- Ghidra/Analysis backend or other explicitly isolated test backend.

Never point Dev `GHIDRA_MCP_URL` at the production Ghidra worker pool while destructive worker/session tests are possible.

## Required external inputs

Coolify generates internal secrets from the Compose contract. Dev still needs externally-issued OAuth values:

```text
GITHUB_OAUTH_CLIENT_ID
GITHUB_OAUTH_CLIENT_SECRET
GITHUB_OAUTH_ALLOWED_USERS
```

For a custom Dev domain, explicitly set:

```text
MCP_PUBLIC_BASE_URL=https://<dev-domain>
MCP_ALLOWED_HOSTS=<dev-domain>
MCP_ALLOWED_ORIGINS=https://<dev-domain>
```

Use a separate GitHub OAuth callback for that Dev base URL.

## Recommended Dev overrides

```text
OTEL_ENVIRONMENT=development
TZ=<deployment timezone>
GHIDRA_MCP_URL=<isolated dev Ghidra bridge URL>
```

Internal MCP locations normally keep their Compose defaults. They are overrideable for split-machine tests without image rebuilds.

## Acceptance before frontend/backend refactor work

- all services healthy in the Dev resource;
- `/mcp` and every dedicated public MCP surface reachable through the Dev gateway;
- Dev OAuth login/refresh/revoke works independently of production;
- Dev Admin API data and browser profile survive a Dev redeploy and are visibly separate from production;
- Dev Analysis reaches only the isolated Dev Ghidra backend;
- Dev telemetry is visible in SigNoz with `deployment.environment.name=development`;
- Coolify inventory tools can list the Dev resource and variable names without exposing values;
- production health is checked after Dev creation to prove no shared-state regression.

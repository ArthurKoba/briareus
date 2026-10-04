# Split Coolify applications

Each file in this directory is one independent Coolify Compose application. The legacy monolith stays
pinned to e41085d9c86124a0f711411314265b36f4c23dea until the split gateway passes acceptance.

One-time topology: create one external Docker network named mcp and set MCP_NETWORK_NAME=mcp.

For the first cutover, reuse the existing legacy persistent volumes:
MCP_WORKSPACE_VOLUME=vaxvdsixzrp87pos3hg0frht_terminal-workspace
MCP_TERMINAL_HOME_VOLUME=vaxvdsixzrp87pos3hg0frht_terminal-home
MCP_BROWSER_VOLUME=vaxvdsixzrp87pos3hg0frht_web-browser
MCP_AUTH_VOLUME=vaxvdsixzrp87pos3hg0frht_auth

Do not run two Web containers against the same browser volume. Stop the legacy runtime before
starting stateful split replacements.

Shared backends use SERVICE_NAMESPACE=MCP, DEPLOYMENT_ENVIRONMENT=production, team OTLP variables,
and the same ADMIN_API_SERVICE_TOKEN used by admin-api. Auth and Gateway also share the same
GITHUB_OAUTH_JWT_SIGNING_KEY and GITHUB_OAUTH_ALLOWED_USERS. Only Auth receives the GitHub OAuth
client ID/secret.

Application -> Compose location:
mcp-valkey -> /deploy/coolify/split/valkey.yaml
mcp-auth -> /deploy/coolify/split/auth.yaml
mcp-github -> /deploy/coolify/split/github.yaml
mcp-gitlab -> /deploy/coolify/split/gitlab.yaml
mcp-files -> /deploy/coolify/split/files.yaml
mcp-web -> /deploy/coolify/split/web.yaml
mcp-terminal -> /deploy/coolify/split/terminal.yaml
mcp-ghidra -> /deploy/coolify/split/ghidra.yaml
mcp-analysis -> /deploy/coolify/split/analysis.yaml
mcp-observability -> /deploy/coolify/split/observability.yaml
mcp-gateway -> /deploy/coolify/split/gateway.yaml
admin-api -> /deploy/coolify/split/admin-api.yaml
admin-ui -> /deploy/coolify/split/admin-ui.yaml

Cutover order:
1. Create network/shared variables and all Applications without starting stateful replacements.
2. Deploy mcp-valkey.
3. Put Admin API on the common network, or temporarily use its public API URL.
4. Stop the legacy monolith for the stateful cutover.
5. Start auth/files/github/gitlab/observability.
6. Start terminal, web, ghidra, analysis.
7. Test every MCP directly.
8. Start gateway last and move the public MCP domain.
9. Validate OAuth and all MCP surfaces through Gateway.
10. Keep legacy stopped but intact until acceptance completes.

Web and Terminal default to 3 CPUs and 6 GiB RAM with no extra swap.

PostgreSQL remains a separate migration wave. Current Admin API settings still derive a SQLite URL
from ADMIN_API_DATABASE_PATH, so a PostgreSQL driver, URL setting and data migration must land first.

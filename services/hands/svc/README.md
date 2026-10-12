# SVC Hand — isolated, fail-closed lifecycle pilot

This service owns its minimal private ASGI process, native uv lock, Docker,
Compose and folder-scoped Watch. It preserves the existing Coolify app UUID
`0tsnkigy4fanthoywmatouig`, internal alias `briareus-svc`, network and
absence of public domain. It has NO database volume and no outbound provider
client. `/health/live` returns a process-only status, while `/mcp` and all
other business HTTP paths return 503; WebSockets close without admission.

The previous runtime deliberately executes `exit 78` before starting, so
GitHub/GitLab FastMCP provider actions are NOT available or accepted here.
Actual secure providers and management endpoints must be migrated and
validated in this SAME directory under an independent trusted caller/owner
authorization contract before any tool activation. DO NOT interpret healthy
container status as working MCP.

Development-only cutover: edit only this SVC app's Base directory to
`/services/hands/svc`, Compose location `/docker-compose.coolify.yaml`, and
Watch Paths to `services/hands/svc/**`, then redeploy and verify private
health vs denied MCP. To rollback, restore its saved old `/deploy/svc`
configuration and exact pre-cutover Watch Paths, then redeploy only SVC.

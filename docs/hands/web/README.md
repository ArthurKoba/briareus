# Web Hand — independent private service

This folder is the target `hands/web/` module. It owns a locked Python
runtime, small ASGI entrypoint, Dockerfile and two Compose manifests.

- Coolify existing application: the original approved Briareus Development
  application. Do not create another application or expose a public domain.
- Base Directory: `/hands/web`
- Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `hands/web/**` and `shared/hand_runtime/**`
- Network service alias: `briareus-web` on the existing internal network.

**Diagnostic MCP transition — not authorized business-tool execution.**
`GET /health/live` reports process liveness; `/health/ready` remains 503.
The internal `/mcp` Streamable HTTP endpoint now implements real MCP
`initialize`, `tools/list`, and two bounded, read-only calls: `hand_status`
and `hand_source_summary`. It does **not** register or call the copied
`services/modules/web` privileged tools; all other private provider HTTP
paths still return 503, and WebSockets are denied. Business tool activation
requires verified Rauthy identity/audience, current Cedar AgentSession
permission for each effect, and appropriate sandbox/network isolation.
See `docs/shared/hand-runtime-capabilities.md` for the exact v1 contract.

Existing `deploy/web/` remains a rollback source. Preserve the existing
resource UUID, networks, DNS, variables, release history, storage and app state.

The prior named volume `briareus-web-v1` is **not deleted or migrated**.
This safety shell intentionally does not mount it or start an untrusted
executor; reattachment requires independently validated sandbox isolation.

Prior Chromium `--no-sandbox` within the shared private network does not
meet the isolation requirement. Do not activate browser execution here.

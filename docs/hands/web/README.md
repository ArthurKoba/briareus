# Web Hand — independent private service

This folder is the target `hands/web/` module. It owns a locked Python
runtime, small ASGI entrypoint, Dockerfile and two Compose manifests.

- Coolify existing application: the original approved Briareus Development
  application. Do not create another application or expose a public domain.
- Base Directory: `/hands/web`
- Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `hands/web/**` and `shared/hand_runtime/**`
- Network service alias: `briareus-web` on the existing internal network.

**This is a deliberately non-privileged, health-only transition, NOT the final
MCP tool implementation.** `/health/live` is liveness only. All other HTTP
routes return HTTP 503 and WebSocket connections are denied. Do not expose
the previous `services/modules/web` tool implementation until it
verifies Rauthy issuer/signature/audience and a fresh Briareus
Authorization/Cedar AgentSession decision per protected action.

Existing `deploy/web/` remains a rollback source. Preserve the existing
resource UUID, networks, DNS, variables, release history, storage and app state.

The prior named volume `briareus-web-v1` is **not deleted or migrated**.
This safety shell intentionally does not mount it or start an untrusted
executor; reattachment requires independently validated sandbox isolation.

Prior Chromium `--no-sandbox` within the shared private network does not
meet the isolation requirement. Do not activate browser execution here.

# Infrastructure Hand — independent private service

This folder is the target `hands/infrastructure/` module. It owns a locked Python
runtime, small ASGI entrypoint, Dockerfile and two Compose manifests.

- Coolify existing application: the original approved Briareus Development
  application. Do not create another application or expose a public domain.
- Base Directory: `/hands/infrastructure`
- Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `hands/infrastructure/**` and `shared/hand_runtime/**`
- Network service alias: `briareus-infrastructure` on the existing internal network.

**This is a deliberately non-privileged, health-only transition, NOT the final
MCP tool implementation.** `/health/live` is liveness only. All other HTTP
routes return HTTP 503 and WebSocket connections are denied. Do not expose
the previous `services/modules/infrastructure` tool implementation until it
verifies Rauthy issuer/signature/audience and a fresh Briareus
Authorization/Cedar AgentSession decision per protected action.

Existing `deploy/infrastructure/` remains a rollback source. Preserve the existing
resource UUID, networks, DNS, variables, release history, storage and app state.

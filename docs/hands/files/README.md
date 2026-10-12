# Files Hand — independent private service

This folder is the target `hands/files/` module. It owns a locked Python
runtime, small ASGI entrypoint, Dockerfile and two Compose manifests.

- Coolify existing application: the original approved Briareus Development
  application. Do not create another application or expose a public domain.
- Base Directory: `/hands/files`
- Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `hands/files/**` and `shared/hand_runtime/**`
- Network service alias: `briareus-files` on the existing internal network.

**This is a deliberately non-privileged, health-only transition, NOT the final
MCP tool implementation.** `/health/live` is liveness only. All other HTTP
routes return HTTP 503 and WebSocket connections are denied. Do not expose
the previous `services/modules/files` tool implementation until it
verifies Rauthy issuer/signature/audience and a fresh Briareus
Authorization/Cedar AgentSession decision per protected action.

Existing `deploy/files/` remains a rollback source. Preserve the existing
resource UUID, networks, DNS, variables, release history, storage and app state.

The prior named volume `briareus-files-v1` is **not deleted or migrated**.
This safety shell intentionally does not mount it or start an untrusted
executor; reattachment requires independently validated sandbox isolation.

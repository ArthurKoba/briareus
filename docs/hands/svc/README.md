# SVC Hand — private GitHub/GitLab module

Owner: Runtime. Application Base Directory `/hands/svc`; isolated Coolify
manifest `/docker-compose.coolify.yaml`, Watch Paths `hands/svc/**` and
`shared/hand_runtime/**`, internal `briareus-svc:8000` alias.

SVC includes copied GitHub/GitLab source implementations but its **only active
MCP tools** are non-privileged `hand_status` and `hand_source_summary` on the
private `/mcp` Streamable HTTP transport. Normal `/health/live` stays 200;
`/health/ready` remains 503; all provider actions remain unregistered and
cannot execute without verified Rauthy/Cedar admission and credential custody.
The legacy service remains a rollback source; no external/public domain or
new volume is created. See `docs/shared/hand-runtime-capabilities.md`.

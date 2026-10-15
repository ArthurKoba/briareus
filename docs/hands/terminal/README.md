# Terminal Hand — independent private service

This folder is the target `hands/terminal/` module. It owns a locked Python
runtime, small ASGI entrypoint, Dockerfile and two Compose manifests.

- Coolify existing application: the original approved Briareus Development
  application. Do not create another application or expose a public domain.
- Base Directory: `/hands/terminal`
- Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `hands/terminal/**` and `shared/hand_runtime/**`
- Network service alias: `briareus-terminal` on the existing internal network.

**Diagnostic MCP transition — not authorized business-tool execution.**
`GET /health/live` reports process liveness; `/health/ready` remains 503.
The internal `/mcp` Streamable HTTP endpoint now implements real MCP
`initialize`, `tools/list`, and two bounded, read-only calls: `hand_status`
and `hand_source_summary`. It does **not** register or call the copied
`services/modules/terminal` privileged tools; all other private provider HTTP
paths still return 503, and WebSockets are denied. Business tool activation
requires verified Rauthy identity/audience, current Cedar AgentSession
permission for each effect, and appropriate sandbox/network isolation.
See `docs/shared/hand-runtime-capabilities.md` for the exact v1 contract.

Existing `deploy/terminal/` remains a rollback source. Preserve the existing
resource UUID, networks, DNS, variables, release history, storage and app state.

The prior named volume `briareus-terminal-v1` is **not deleted or migrated**.
This safety shell intentionally does not mount it or start an untrusted
executor; reattachment requires independently validated sandbox isolation.

## Staged offline executor preflight (source only)

The copied, currently **unmounted** legacy TerminalManager now calls
require_offline_executor() before either terminal_exec or job_start
can inspect workspace policy, contact the old management API, allocate a PTY
or start a subprocess. The check is compiled into hands/terminal/src/ and
cannot be disabled with MCP arguments or environment variables.

The local kernel must report Linux, non-root execution, no effective
capabilities, NoNewPrivs=1, a read-only root filesystem, and **only lo**
on /sys/class/net, IPv4 and IPv6 route tables. Any unreadable/mismatching
fact returns TERMINAL_OFFLINE_EXECUTOR_NOT_ISOLATED before spawning a shell.
This deliberately prevents accidental process execution in the connected
briareus-terminal controller, whose existing Compose still attaches to
briareus-net. The check does not create namespaces, attach networks or
grant authorization; it is an additional fail-closed necessary guard, not
proof of a dedicated worker or an accepted security boundary.

The separately approved future offline executor still requires independently
verified Docker namespace/mount/IPC and non-secret credential exposure,
resource-owner confinement, cgroup/process TTL enforcement, authenticated
controller-to-worker IPC, per-tool Rauthy/Cedar Permit and grant-revoke handling.
These requirements cannot be accepted from mocked local kernel facts. The
current Compose remains unchanged, has no new sidecar, and the old business
tools remain unregistered. Do not move the public Hand onto a loopback-only
network or share protected database/provider sockets with a worker as a
workaround.

## Offline worker candidate — not a deployment

The separate worker candidate Compose is intentionally NOT included in
docker-compose.coolify.yaml. It proposes a container in the Terminal Hand
source, using network_mode none, read-only root, non-root UID, no Linux
capabilities, no new privileges, bounded process and memory resources,
and no secrets, ports or vendor network mounts. The offline_worker
entrypoint rejects startup if kernel prerequisites fail, and then still
exits with authorization unavailable. No command, filesystem or socket
is exposed.

This demonstrates a source-only candidate for separation, not an accepted
worker. Real sandboxing requires independently verified worker namespace,
per-Project mounts/UID, authenticated controller-worker IPC, owner scopes,
current Cedar grants, TTL/revoke/cancel and a real Coolify parser acceptance.
Do not attach this candidate to the existing approved Application UUID or
run it in place of the trusted Terminal controller without Deployment review.

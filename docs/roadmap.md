# Status and remaining work

## Completed

- private SQLite account administration service with encrypted GitHub/GitLab credentials;
- explicit multi-account GitHub/GitLab provider selection;
- self-hosted GitLab account support through per-account base URLs;
- independent GitHub, GitLab, Files, HTTP and Analysis runtime services;
- thin `bridge` gateway and provider-neutral `common` layer;
- capability-oriented GitHub and GitLab clients and tool registrars;
- shared pooled HTTP transport and shared Git branch-policy primitives;
- Pydantic validation at stable module boundaries;
- persistent path-based Files service over the shared workspace filesystem;
- structured curl split into preset, request, execution, response and operation layers;
- schema-driven Analysis facade over the native Ghidra MCP tool catalog;
- Analysis terminology aliases with new names preferred and legacy Ghidra argument names accepted as fallback;
- architecture tests preventing provider-to-provider imports and provider code from leaking into `bridge`/`common`;
- one root `docker-compose.yaml` for shared PostgreSQL/Valkey infrastructure;
- persistent administration, authorization, shared workspace and terminal-home volumes.

## Remaining

### Production acceptance

After the modular stack is deployed, verify every dedicated public surface, persistent
workspace Files reads/uploads, multi-account GitHub operations, self-hosted GitLab
discovery, administration admin/account onboarding, encrypted credential persistence,
HTTP/Files integration, OAuth persistence and Analysis-to-Ghidra connectivity.

### Formatting

Ruff lint is enforced. Repository-wide Ruff formatting remains a separate mechanical
cleanup because existing files predate formatter enforcement.

## Rule

Do not put provider implementation back into `bridge`. Shared code belongs in
`common` only when it is genuinely provider-neutral and reused by multiple modules.

Native Ghidra remains an independent backend. Analysis adapts its live MCP schema and
terminology without modifying or duplicating the Ghidra implementation.

## Upstream-first MCP refactor

The provider/runtime architecture is being re-evaluated around an upstream-first MCP model: Koba owns account routing, authorization, policy, audit and workspace glue, while maintained official/native MCP servers should own provider-domain semantics. See [`docs/refactoring/mcp-upstream-roadmap.md`](refactoring/mcp-upstream-roadmap.md) for the audit, provider decisions and phased migration plan.

## Future architecture — Node Agent and distributed Workspace (deferred)

**Owner decision, 15 October 2026:** stay on a single existing node for
Briareus MVP; do not make a distributed scheduler, remote Node Agent or nested
container runtime a prerequisite for the current User → Project → Cedar →
protected Files Hand development acceptance. The future architecture and
acceptance outline are tracked in [#544](https://github.com/KobaProduction/briareus/issues/544).

After MVP, evaluate a user-space Node Agent that registers a node, advertises
available compute, and places Workspace-associated Files, Terminal and **local
Git** over the same owner-controlled filesystem. GitHub/GitLab provider APIs
stay independent. Investigate shared Git objects/linked worktrees and measured
cache cleanup before assuming branch count is the main disk cost.

Second-stage options are authenticated private RPC to remote nodes, per-Node/
Project/Hand CPU, memory, PID, disk and network policies, and isolated
containerized MCP execution. Rootless or nested Docker/DinD is a candidate,
**not** a selected implementation or a security boundary: privileged DinD and
host Docker socket access must never be assumed to isolate an untrusted Hand.
First prove one local Node Agent/Workspace, then an explicit manually placed
remote Workspace; defer automatic migration/failover until real ownership,
revocation, data durability and OS sandbox acceptance are defined.

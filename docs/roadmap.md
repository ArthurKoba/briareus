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

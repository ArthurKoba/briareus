# Architecture overview

The source architecture separates external OAuth identity, agent access, public routing, administration and provider execution.

```mermaid
flowchart TB
    Client[ChatGPT / MCP clients] --> GW[gateway]

    GW -->|OAuth routes| AU[auth]
    AU --> ADB[(auth DB)]

    GW -->|agent-session validation| AU
    AU --> VK[(Valkey cache)]

    GW --> GH[github]
    GW --> GL[gitlab]
    GW --> FI[files]
    GW --> WEB[web]
    GW --> AN[analysis]
    GW --> TERM[terminal]
    GW --> OBS[observability]

    AN --> GD[ghidra private runtime]

    UI[admin-ui] --> API[admin-api]
    API --> AU
```

## Source ownership

- `auth_service` — local users, OAuth/token state, JWT signing, agent sessions, access elevation, per-MCP controls, account scopes and access security history.
- `bridge` — public gateway, MCP routing, protected-resource metadata, local OAuth token verification and access enforcement middleware.
- `common` — provider-neutral contracts, stable MCP surface IDs and typed settings.
- `admin-api` — administration BFF/realtime surface; it does not own auth persistence.
- `modules.github`, `modules.gitlab`, `modules.files`, `modules.web`, `modules.analysis`, `modules.terminal`, `modules.observability` — provider/domain runtimes.
- `modules.ghidra` — private native analysis backend adapter.

## OAuth model

Auth is one authorization server at `https://mcp.koba-nexus.ru`. Every public MCP URL is an exact protected resource and access-token audience. Gateway publishes protected-resource metadata; auth publishes authorization-server metadata and OAuth operational endpoints.

Auth issues ES256 tokens. The private signing key remains in auth; gateway verifies with the public key/JWKS.

## Agent access model

OAuth identifies the local user/client. Agent sessions independently decide whether a concrete agent context may execute against a concrete MCP surface.

The MVP has automatic read-only sessions and one elevated `full_access` level. Session state is durable in PostgreSQL, with Valkey as a read-through cache. Per-user/per-surface enforcement can be `unrestricted` or `session_enforced`.

See `docs/architecture/authorization-access.md`.

## Public surfaces

```text
/mcp
/github/mcp
/gitlab/mcp
/files/mcp
/web/mcp
/analysis/mcp
/terminal/mcp
/observability/mcp
```

Raw Ghidra is private.

## Deployment isolation

Production uses one Coolify application per Docker target. The legacy monolith stays pinned until split-runtime acceptance. Provider-only changes do not require auth/gateway restarts unless their shared contract changes.

See `docs/deployment.md`.

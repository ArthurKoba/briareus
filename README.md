# mcp-bridge

Modular MCP platform with one public gateway, one central OAuth authorization service,
and independently deployable private provider runtimes.

## Architecture

```text
ChatGPT / MCP clients
        |
        | HTTPS
        v
gateway
  |  \
  |   \-- OAuth routes ----------> auth
  |                                 |
  |                                 +-- GitHub OAuth / DCR / token state
  |
  +-- /github/mcp   -------------> github
  +-- /gitlab/mcp   -------------> gitlab
  +-- /files/mcp    -------------> files
  +-- /web/mcp      -------------> curl
  +-- /analysis/mcp -------------> analysis ---> ghidra (private)
  +-- /admin        -------------> management
```

The public domain is `mcp.koba-nexus.ru`. Gateway is the only process assigned that
public domain. Auth and all provider runtimes remain private on the shared service
network.

## Public MCP surfaces

```text
/mcp
/github/mcp
/gitlab/mcp
/files/mcp
/web/mcp
/analysis/mcp
/admin
```

Native Ghidra is not a public MCP surface. Analysis is the external structured-analysis
contract; Ghidra is an implementation backend.

## OAuth boundary

There is one OAuth authorization server:

```text
https://mcp.koba-nexus.ru
```

and one GitHub OAuth callback:

```text
https://mcp.koba-nexus.ru/auth/callback
```

Every MCP endpoint is an independent RFC 8707 resource audience under that issuer.
Examples:

```text
https://mcp.koba-nexus.ru/mcp
https://mcp.koba-nexus.ru/files/mcp
https://mcp.koba-nexus.ru/analysis/mcp
```

The `auth` runtime owns GitHub OAuth credentials, DCR registrations, authorization
transactions, refresh state and audience-bound FastMCP tokens. Gateway owns only public
routing, protected-resource metadata and token verification through the private auth API.

GitHub OAuth credentials are never configured on provider runtimes or management.

## Repository layout

```text
src/
├── auth_service/
├── bridge/
├── common/
├── management/
└── modules/
    ├── github/
    ├── gitlab/
    ├── files/
    ├── curl/
    ├── analysis/
    └── ghidra/
```

## Deployment isolation

Production is split into independent Coolify applications using Dockerfile targets:
`auth`, `gateway`, `management`, `github`, `gitlab`, `files`, `curl`,
`analysis`, and `ghidra`.

A provider-only source change should rebuild only that provider. Auth and gateway are
stable control-plane services and do not restart for provider changes. Shared
`src/common/**`, Dockerfile or lockfile changes intentionally fan out.

See `deploy/coolify/README.md` for the exact runtime ownership, environment variables,
watch paths and storage mapping.

## Locked Python dependencies

Production and CI install dependencies from committed `uv.lock`:

```text
uv sync --frozen --no-dev --no-install-project
```

This prevents clean deployments from resolving a different dependency graph.

## Files

Files are immutable and content-addressed. Public file identifiers are content IDs;
physical storage paths stay internal. Files, Web/curl and other consumers use the same
canonical object store contract.

## Analysis

Analysis dynamically adapts the internal analysis backend catalog into the project
terminology and validates/normalizes arguments before dispatch. Internal backend naming
is not part of the external ChatGPT contract.

## Management

Management owns provider accounts, encrypted credentials, invocation telemetry, settings,
Files administration and the Admin UI. Provider runtimes resolve account data through the
private management API rather than opening the management database directly.

## License

MIT

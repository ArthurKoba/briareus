# mcp-bridge

Modular MCP platform with one public gateway, one central OAuth authorization service,
and isolated private provider runtimes managed as one Docker Compose stack.

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
  +-- /web/mcp      -------------> web (curl + persistent Chromium)
  +-- /analysis/mcp -------------> analysis ---> ghidra (private)
  +-- /terminal/mcp -------------> terminal
  +-- /admin        -------------> management
```

The public domain is `mcp.koba-nexus.ru`. Gateway is the only process assigned that
public domain. Auth and all provider runtimes remain private on the Compose network.

## Public MCP surfaces

```text
/mcp
/github/mcp
/gitlab/mcp
/files/mcp
/web/mcp
/analysis/mcp
/terminal/mcp
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
transactions, refresh state and audience-bound FastMCP tokens. Gateway owns public
routing, protected-resource metadata and local verification of already-issued signed
tokens. GitHub OAuth credentials are never configured on provider runtimes or management.

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
    ├── ghidra/
    └── terminal/
```

## Runtime and deployment isolation

Production is one Git-backed Coolify Docker Compose application. The Compose file is the
topology authority and starts separate containers for `auth`, `gateway`, `management`,
`github`, `gitlab`, `files`, `curl`, `terminal`, `analysis`, and `ghidra`.

Deployments may rebuild or recreate the stack. Runtime correctness does not depend on
selective-restart scripts. Each service has its own restart policy, and Compose
dependencies exist only where a runtime cannot perform its primary job without another
service: GitHub and GitLab require Management for account resolution, while Analysis
requires Ghidra. Gateway is deliberately not health-gated on provider availability, so
one broken provider does not prevent the remaining MCP surfaces from starting and being
used to repair the system.

The multi-stage Dockerfile keeps rebuilds fast by installing locked dependencies before
copying runtime-specific source trees, so unchanged stages reuse the local Docker cache.

See `deploy/coolify/README.md` for production configuration and failure-isolation rules.

## Locked Python dependencies

Production and CI install dependencies from committed `uv.lock`:

```text
uv sync --frozen --no-dev --no-install-project
```

This prevents clean deployments from resolving a different dependency graph.

## Files

Files is the path-based file manager for the shared persistent `/workspace` filesystem.
Terminal, Files, Web/curl and Management Admin see the same working files immediately.
There is no separate content-addressed file store and no `file_id` storage contract.

## Analysis

Analysis dynamically adapts the internal analysis backend catalog into the project
terminology and validates/normalizes arguments before dispatch. Internal backend naming
is not part of the external ChatGPT contract.

## Management

Management owns provider accounts, encrypted credentials, invocation telemetry, settings,
Files administration and the Admin UI. Provider runtimes resolve account data through the
private management API rather than opening the management database directly. Expensive
workspace statistics and Reverse overview/coverage calculations are refreshed by background
workers into persistent snapshots; Admin pages render the latest cached value with freshness
metadata instead of performing long scans or analyses in the HTTP request path.

## License

MIT


## Terminal

Terminal is a dedicated non-root Linux development runtime exposed at `/terminal/mcp`.
It provides persistent workspaces, bounded shell execution, durable long-running jobs,
interactive PTY input/output and cursor-based incremental logs. Terminal, Files, Curl and
Management Admin share the same mutable `/workspace` volume, so working files are
immediately available by path without import/export copies. System toolchain packages are
installed in the image; normal runtime commands execute as the unprivileged service user.
Terminal command/stdin/output payloads are bounded or omitted in Management MCP-call history.

## Web browser

The Web MCP combines structured curl operations with a persistent Playwright/Chromium
browser profile. Browser cookies and local session state live in a dedicated persistent
volume, while screenshots, uploads and downloads use the shared `/workspace`. Browser
snapshots return bounded page text plus short-lived interactive element refs so agents can
click and fill without serializing full page HTML into model context. Browser page content
and filled values are omitted from Management audit payloads; tool/status metadata remains
observable.

## OAuth sessions

The authorization runtime reports safe OAuth session metadata to Management without
copying access or refresh tokens. Management shows client/resource identity, last use,
refresh activity, token expiry, revocation and the latest authentication error. Refresh
rotation keeps a short bounded replay grace window so concurrent client refresh requests
reuse the same rotated result instead of spuriously forcing a full reauthorization.

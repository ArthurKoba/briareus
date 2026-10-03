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
  +-- /observability/mcp -------> observability (SigNoz + Coolify, read-only)
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
/observability/mcp
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
    ├── web/
    ├── analysis/
    ├── ghidra/
    └── terminal/
```

## Runtime and deployment isolation

Production is one Git-backed Coolify Docker Compose application. The Compose file is the
topology authority and starts separate containers for `auth`, `gateway`, `management`,
`github`, `gitlab`, `files`, `web`, `terminal`, `analysis`, `ghidra`, and `observability`.

Deployments may rebuild or recreate the stack. Runtime correctness does not depend on
selective-restart scripts. Each service has its own restart policy, and Compose
dependencies exist only where a runtime cannot perform its primary job without another
service: GitHub and GitLab require Management for account resolution, while Analysis
requires Ghidra. Gateway is deliberately not health-gated on provider availability, so
one broken provider does not prevent the remaining MCP surfaces from starting and being
used to repair the system. Backend MCP connections are lazy and reused: each public proxy
keeps a small pool of persistent sessions instead of repeating MCP discovery/initialization
for every tool call, while the root bridge keeps one persistent session per backend and caches
backend tool catalogs for 30 seconds. `bridge_tools(..., refresh=true)` bypasses that catalog
cache when an immediate schema refresh is required.

The multi-stage Dockerfile keeps rebuilds fast by installing locked dependencies before
copying runtime-specific source trees, so unchanged stages reuse the local Docker cache.

Valkey is the private shared cache for account resolution and runtime/system settings. It is
not a source of truth: Management remains authoritative, cache failures fall back to Management,
and account/settings mutations invalidate or replace cached values. The production Valkey
container is memory-only (no RDB/AOF volume and no published port). Resolved account entries may
contain provider credentials, so they are short-lived and remain only inside the private Compose
network and process/cache memory.

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
Files administration and the Admin UI. GitHub, GitLab, SigNoz and Coolify can each have
multiple named accounts. SigNoz API keys and Coolify API tokens are encrypted in Management;
they are not deployment environment variables. Provider runtimes resolve the explicitly
selected `account_id`/alias through the private management API rather than opening the
management database directly. Expensive
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

Management `/admin/browser` is the operator surface for the same persistent Chromium
profile. It provides compact shared tabs, per-tab and browser-wide agent access controls,
page-ID copy, Chromium extension management through `chrome://extensions`, docked DevTools
beside the selected application, and an optional separate DevTools tab. Docked DevTools runs
as an internal Chromium target hidden from the normal browser-tab/agent catalog, while both
site and DevTools screencasts remain independently interactive. Chromium is launched as the
persistent process with a remote-debugging endpoint bound only to `127.0.0.1` inside the Web
container, and Playwright attaches to that same process through CDP. This gives the bundled
DevTools frontend a real target transport without publishing a debugging port by Compose. The
operator can also reopen the last closed application tab with `Reopen` or Ctrl+Shift+T. The
Browser Operator page is served with `no-store` headers so
old operator UI versions are not resurrected after deployments. `Clean App`
clears cookies and origin-scoped site data only for the selected HTTP(S) application, while
`Clean browser` is deliberately destructive: it stops Chromium, erases the persistent
profile plus browser cache/config/crash state, starts one clean `about:blank` tab, and leaves
agent access disabled. Browser-operator WebSocket reconnects mint a fresh short-lived Admin
ticket instead of reusing an expired page-load ticket.

The Web surface also mounts Google's official `chrome-devtools-mcp` server (pinned to
`1.10.1`) under the `devtools_` namespace instead of reimplementing Chrome debugging RPCs.
It connects only to the same loopback CDP endpoint used by the persistent browser. Agent
Developer access is a separate browser-wide privilege and defaults to off; privileged calls
require both `Agents: On` and `Developer: On`. Turning either switch off disconnects the
privileged stdio upstream. Full Developer mode intentionally sees all browser targets rather
than honoring per-tab basic-browser locks. The operator UI persists the Developer switch in the
browser policy; a fresh profile starts with Developer access off.

The upstream exposes its native console, network, JavaScript evaluation, DOM/CSS, performance,
memory and extension tools without Koba schema translation. Extension/source filesystem access
is restricted to `/workspace`; file navigations and CrUX URL uploads are disabled. DevTools MCP
arguments and results are omitted from Management audit payloads because they may contain
cookies, authorization headers, JavaScript, request bodies or authenticated page data. Tool
name, status, duration and traces remain observable. The runtime uses normal Chromium
capabilities; it does not add fingerprint spoofing or site-control bypass logic.

## OAuth sessions

The authorization runtime reports safe OAuth session metadata to Management without
copying access or refresh tokens. Management shows client/resource identity, last use,
refresh activity, token expiry, revocation and the latest authentication error. Refresh
rotation keeps a bounded two-minute idempotency window in the encrypted persistent OAuth
store. Concurrent requests and retries that cross an auth-container restart reuse the same
rotated result instead of spending the one-time upstream refresh token again. Client-facing
FastMCP access tokens use a 30-day lifetime; every request still validates the upstream GitHub
session, so upstream expiry/revocation is not extended, while unnecessary daily client refresh
rotation is avoided. Refresh attempts emit token-safe correlation logs for request, replay,
upstream exchange, race recovery and terminal `reauth_required` branches; raw tokens are never
logged. An upstream refresh token that was already invalid before these protections cannot be
reconstructed and requires one fresh user authorization.

## Observability

Observability is one unified read-only MCP surface at `/observability/mcp`. Management keeps
SigNoz and Coolify connections as separate account types because their credentials and APIs are
different, but ChatGPT connects to only this one surface. `observability_sources` lists both
provider types and their aliases; data tools require an explicit account selector.

SigNoz-backed tools provide runtime logs, traces, metrics/query access, service discovery and
field discovery. Coolify-backed tools provide application and deployment state. Coolify runtime
logs, environment variables, secrets and all deploy/restart/mutation operations are deliberately
absent; runtime diagnostics belong to the SigNoz side of the same Observability interface.

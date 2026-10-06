# mcp-bridge

Modular MCP platform with one public gateway, one central OAuth authorization service,
and isolated private provider runtimes managed as one Docker Compose stack.

## Architecture

```text
ChatGPT / MCP clients
   |                    |
   | MCP                | OAuth
   v                    v
gateway             authorization
  |                    |
  |                    +-- local users / OAuth / token state
  |
  |-- agent access ---> authorization (PostgreSQL + Valkey cache)
  |
  +-- /github/mcp   -------------> github
  +-- /gitlab/mcp   -------------> gitlab
  +-- /files/mcp    -------------> files
  +-- /web/mcp      -------------> web (curl + persistent Chromium)
  +-- /analysis/mcp -------------> analysis ---> ghidra (private)
  +-- /terminal/mcp -------------> terminal
  +-- /observability/mcp -------> observability (SigNoz + Coolify, read-only)
  ```

Gateway owns `mcp.koba-nexus.ru`. The authorization runtime is independently public at
`authorization.mcp.koba-nexus.ru`. Provider runtimes remain private.

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
```

Native Ghidra is not a public MCP surface. Analysis is the external structured-analysis
contract; Ghidra is an implementation backend.

## Administration surfaces

```text
https://admin.mcp.koba-nexus.ru/       -> admin-ui
https://api.mcp.koba-nexus.ru/v1/*    -> admin-api
```

Admin UI/Admin API are independent deployment units. Gateway does not proxy their HTTP or
WebSocket routes.

## OAuth and agent-access boundary

There is one local OAuth authorization server:

```text
https://authorization.mcp.koba-nexus.ru
```

Every MCP endpoint under `https://mcp.koba-nexus.ru` is an independent RFC 8707 resource audience. The authorization-server issuer is separate from those MCP resource URLs. The `authorization` runtime owns local users, OAuth clients/codes/sessions, refresh tokens and the private ES256 signing key. Gateway owns public routing and verifies already-issued tokens with the public key/JWKS.

Agent access is a second authorization layer inside the same `authorization` service. In `session_enforced` mode each normal MCP call carries an agent session UID; sessions start read-only and may receive temporary/full access through administration approval. PostgreSQL is durable authority and Valkey is a read-through cache.

Provider accounts remain integrations and are not platform login identities.

## Repository layout

```text
services/
├── authorization/
│   └── access/
├── bridge/
├── common/
├── admin-api/
│   └── src/
│       └── admin_api/
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

Production is migrating from the legacy single Compose resource to independent Coolify
Applications built from the same repository/Dockerfile targets. `admin-ui` and `admin-api` are
already separate deployment units; remaining runtimes move independently. The root Compose file
remains the integration/local topology authority during the cutover.

Deployments may rebuild or recreate the stack. Runtime correctness does not depend on
selective-restart scripts. Each service has its own restart policy, and Compose
dependencies exist only where a runtime cannot perform its primary job without another
service: GitHub and GitLab require Admin API for account resolution, while Analysis
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
not a source of truth: Admin API remains authoritative, cache failures fall back to Admin API,
and account/settings mutations invalidate or replace cached values. The production Valkey
container is memory-only (no RDB/AOF volume and no published port). Resolved account entries may
contain provider credentials, so they are short-lived and remain only inside the private Compose
network and process/cache memory.

See `docs/deployment.md` for production deployment configuration.

## Locked Python dependencies

Production and CI install dependencies from committed `uv.lock`:

```text
uv sync --frozen --no-dev --no-install-project
```

This prevents clean deployments from resolving a different dependency graph.

## Files

Files is the path-based file manager for the shared persistent `/workspace` filesystem.
Terminal, Files, Web/curl and the Admin API see the same working files immediately.
There is no separate content-addressed file store and no `file_id` storage contract.

## Analysis

Analysis dynamically adapts the internal analysis backend catalog into the project
terminology and validates/normalizes arguments before dispatch. Internal backend naming
is not part of the external ChatGPT contract.

## Admin API

Admin API owns provider accounts, encrypted credentials, invocation telemetry, settings,
Files administration and the Admin API/realtime backend. GitHub, GitLab, SigNoz and Coolify can each have
multiple named accounts. SigNoz API keys and Coolify API tokens are encrypted in Admin API;
they are not deployment environment variables. Provider runtimes resolve the explicitly
selected `account_id`/alias through the private Admin API rather than opening the
Admin API database directly. Expensive
workspace statistics and Reverse overview/coverage calculations are refreshed by background
workers into persistent snapshots; the standalone frontend consumes the latest cached value with freshness
metadata instead of performing long scans or analyses in the HTTP request path.

## License

MIT


## Terminal

Terminal is a dedicated non-root Linux development runtime exposed at `/terminal/mcp`.
It provides persistent workspaces, bounded shell execution, durable long-running jobs,
interactive PTY input/output and cursor-based incremental logs. Terminal, Files, Curl and
Admin API file operations share the same mutable `/workspace` volume, so working files are
immediately available by path without import/export copies. System toolchain packages are
installed in the image; normal runtime commands execute as the unprivileged service user.
Terminal command/stdin/output payloads are bounded or omitted in Admin API MCP-call history.

## Web browser

The Web MCP combines structured curl operations with a persistent Playwright/Chromium
browser profile. Browser cookies and local session state live in a dedicated persistent
volume, while screenshots, uploads and downloads use the shared `/workspace`. Browser
snapshots return bounded page text plus short-lived interactive element refs so agents can
click and fill without serializing full page HTML into model context. Browser page content
and filled values are omitted from Admin API audit payloads; tool/status metadata remains
observable.

The standalone Admin UI uses the session-authenticated
`https://api.mcp.koba-nexus.ru/v1/browser/operator/ws` Admin API surface for the same persistent Chromium profile. It shares
tabs, input, agent/developer access controls, DevTools, reopen/cleanup operations and browser
state with the Web runtime. Viewport changes use public `PUT /v1/browser/viewport` on the Admin API origin. The legacy
HTML Browser Operator and ticket-authenticated `/admin/browser/ws` surface have been removed.


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
arguments and results are omitted from Admin API audit payloads because they may contain
cookies, authorization headers, JavaScript, request bodies or authenticated page data. Tool
name, status, duration and traces remain observable. The runtime uses normal Chromium
capabilities; it does not add fingerprint spoofing or site-control bypass logic.

The managed Chromium keeps its existing `browser_*` and privileged `devtools_*` surfaces. An
operator may additionally configure an official Microsoft Playwright MCP server from Admin →
Settings → Browser. Endpoint, per-call timeout, Chrome profile, explicit/idle disconnect policy
and Playwright Extension token are stored as runtime policy in Admin API/PostgreSQL rather than
container environment variables. The token is encrypted at rest and public settings expose only
whether it is configured; a service-authenticated browser-launcher policy endpoint may resolve the
secret when a local Windows launcher needs to populate `PLAYWRIGHT_MCP_EXTENSION_TOKEN`.

External Playwright tools are mounted under the `external_*` namespace and reuse one persistent
upstream MCP session, so one approved browser selection remains active across tool calls until an
explicit disconnect, process loss, policy change, or optional idle timeout. The external browser
path is independent from the managed Chromium and never redirects the managed `devtools_*`
backend.

## OAuth sessions

The `authorization` runtime stores local OAuth users, clients, authorization codes, OAuth sessions and refresh-token state in PostgreSQL. Refresh tokens rotate on use and access tokens are short-lived ES256 JWTs signed only by the authorization runtime; gateway validates them locally with the public key. Provider integrations such as GitHub and GitLab do not participate in platform login or token refresh.

## Observability

Observability is one unified read-only MCP surface at `/observability/mcp`. Admin API keeps
SigNoz and Coolify connections as separate account types because their credentials and APIs are
different, but ChatGPT connects to only this one surface. `observability_sources` lists both
provider types and their aliases; data tools require an explicit account selector.

SigNoz-backed tools provide runtime logs, traces, metrics/query access, service discovery and
field discovery. Coolify-backed tools provide application and deployment state. Coolify runtime
logs, environment variables, secrets and all deploy/restart/mutation operations are deliberately
absent; runtime diagnostics belong to the SigNoz side of the same Observability interface.

Hot-path telemetry distinguishes cache/Admin API access, backend MCP session reuse, provider
HTTP latency and connection-pool wait, and Admin API repository operations. Admin API audit
delivery is batched through a bounded in-memory queue: each MCP call remains an individual audit
record and metric event, while short batches share one internal HTTP request and one SQL
transaction. Sensitive arguments, credentials, authorization headers, full request URLs and
cache keys are not exported as span attributes.

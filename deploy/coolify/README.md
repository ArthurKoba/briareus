# Coolify deployment

Production is being split into independent Git-backed Coolify Applications that use the same
repository and multi-stage Dockerfile. Each application builds only its own target and keeps
Auto Deploy/Watch Paths scoped to that runtime. The root Compose file remains for integration
and migration validation, not as the final production deployment boundary.

## Runtime model

```text
mcp.koba-nexus.ru       -> gateway
admin.mcp.koba-nexus.ru -> admin-ui
api.mcp.koba-nexus.ru   -> admin-api

gateway -> auth / github / gitlab / files / web / terminal / observability / analysis
admin-api -> valkey / files / web / terminal / analysis
analysis -> ghidra
```

`admin-ui` and `admin-api` are public only on their dedicated domains. Provider runtimes,
Valkey and Ghidra remain private.

## Failure isolation

A deployment may rebuild or recreate multiple containers; that is acceptable. Isolation
is a runtime property, not a custom deployment-script property:

- every service has its own `restart: unless-stopped` policy;
- dependencies are declared only for primary runtime requirements;
- GitHub and GitLab require healthy Admin API because account credentials are resolved there;
- Analysis requires healthy Ghidra because Ghidra is its native backend;
- gateway startup does not require provider containers to be healthy;
- an unavailable provider affects only its MCP surface;
- auth is not on the bearer-token request path;
- gateway validates already-issued signed access tokens locally;
- auth is required only for OAuth registration, login, refresh and revocation;
- an auth outage therefore does not invalidate already-issued access tokens.

This is the recovery model: a broken Admin API, GitLab or Analysis container must not
prevent GitHub or other healthy providers from starting and remaining usable.

## OAuth

There is one externally configured authorization-server base URL. For a deployment
whose public base URL is `https://mcp.example.com`, the issuer and callback become:

```text
issuer:   https://mcp.example.com
callback: https://mcp.example.com/auth/callback
```

The application contains no production hostname in runtime defaults. `MCP_PUBLIC_BASE_URL`,
`MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS` are deployment inputs.

Auth owns GitHub OAuth and token issuance. Auth and gateway share the FastMCP JWT signing
key and allowed GitHub user list so gateway can verify bearer tokens locally. GitHub
client ID/secret remain auth-only.

Coolify is now the bootstrap authority for values it can safely generate. The Git-backed
Compose definition uses Coolify `SERVICE_*` generators for internal random values and uses
`${VAR:?}` only for externally-issued values that Coolify cannot invent. Generated values are
stored by Coolify and reused by every service that references the same variable name.

Fresh resources therefore need only these external OAuth inputs before first deployment:

```text
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
GITHUB_OAUTH_ALLOWED_USERS=...
```

The following values are generated automatically unless explicitly overridden:

```text
ADMIN_API_ENCRYPTION_KEY       <- SERVICE_REALBASE64_32_ADMIN_API_ENCRYPTION_KEY
ADMIN_API_SERVICE_TOKEN        <- SERVICE_REALBASE64_64_ADMIN_API_SERVICE_TOKEN
ADMIN_API_USERNAME       <- admin (overrideable)
ADMIN_API_PASSWORD       <- SERVICE_PASSWORD_64_ADMIN_API
ADMIN_API_SESSION_SECRET       <- SERVICE_REALBASE64_64_ADMIN_API_SESSION_SECRET
GITHUB_OAUTH_JWT_SIGNING_KEY    <- SERVICE_REALBASE64_64_GITHUB_OAUTH_JWT_SIGNING_KEY
MCP_PUBLIC_BASE_URL             <- SERVICE_URL_GATEWAY_8000
MCP_ALLOWED_HOSTS               <- SERVICE_FQDN_GATEWAY_8000
MCP_ALLOWED_ORIGINS             <- SERVICE_URL_GATEWAY_8000
```

`SERVICE_REALBASE64_32_*` is suitable for the Admin API Fernet key because it encodes exactly
32 random bytes. Generated secrets are a **new-resource bootstrap** feature, not a migration
mechanism. When attaching an existing Admin API volume/database, always set the original
`ADMIN_API_ENCRYPTION_KEY` explicitly before deployment; replacing it makes previously encrypted
provider credentials unreadable. The same stability rule applies to the JWT signing key and
session secret when continuity of issued tokens/sessions matters.

The `gateway` service explicitly declares `SERVICE_URL_GATEWAY_8000: /`, so a fresh Coolify
resource with a wildcard domain can create routing to gateway port 8000 automatically. A custom
public hostname may override `MCP_PUBLIC_BASE_URL`, `MCP_ALLOWED_HOSTS` and
`MCP_ALLOWED_ORIGINS`; otherwise Coolify's gateway URL/FQDN generator supplies them.

Machine/runtime compatibility inputs are also explicit Compose variables with portable defaults:

```text
TZ=UTC
LANG=C.UTF-8
LC_ALL=C.UTF-8
VALKEY_URL=redis://valkey:6379/0
ADMIN_API_URL=http://admin-api:8000
GITHUB_URL=http://github:8000/mcp
GITLAB_URL=http://gitlab:8000/mcp
FILES_URL=http://files:8000/mcp
WEB_URL=http://web:8000/mcp
ANALYSIS_URL=http://analysis:8000/mcp
GHIDRA_URL=http://ghidra:8000/mcp
TERMINAL_URL=http://terminal:8000/mcp
OBSERVABILITY_URL=http://observability:8000/mcp
GHIDRA_MCP_URL=http://bridge:8081/mcp
```

These defaults still use Compose DNS inside one resource, but exposing them as deployment inputs
lets Dev or a split-machine topology redirect individual private MCPs without rebuilding images.
`TZ` should be set deliberately per deployment when server-side/browser local-time presentation
matters; persistent data and protocol timestamps remain UTC-aware. Browser locale/display/viewport
identity is source-owned for now and is intentionally not duplicated as deployment environment.

Runtime tuning that is not topology/machine-specific remains source-owned. This includes ASGI app
selection, cache TTLs, file limits, provider policy defaults and database/file paths.

`AUTH_SERVICE_TOKEN`, `AUTH_URL` and `AUTH_TIMEOUT_SECONDS` are not used.

## Terminal resource containment

The `terminal` service is an arbitrary-command execution boundary and has hard Docker cgroup
limits in Compose. Defaults are `2g` memory, `2g` memory+swap, `1.5` CPUs, and `256` PIDs.
These limits apply to the complete process tree launched inside Terminal, including Wine,
compilers, Python workloads, and accidental fork storms.

Coolify may override these restart-required infrastructure limits with:

- `TERMINAL_MEMORY_LIMIT` (default `2g`)
- `TERMINAL_MEMORY_SWAP_LIMIT` (default `2g`; equal to memory limit means no extra swap budget)
- `TERMINAL_CPU_LIMIT` (default `1.5`)
- `TERMINAL_PIDS_LIMIT` (default `256`)

Increase these only deliberately for a known workload; do not remove the containment boundary.

## Persistent browser identity

The `web` image runs persistent Chromium headful by default on an internal Xvfb display.
This avoids the explicit `HeadlessChrome` user agent and keeps browser-visible screen metrics
aligned with the configured window size. The profile remains persistent in the `web-browser`
volume and the Browser Operator / DevTools surfaces continue to attach to the same Chromium
process over loopback CDP.

Browser desktop identity is source-owned by `BrowserDesktopProfile`: headful 1440x900,
`ru-RU`, `ru-RU,ru,en-US,en`, `ru_RU.UTF-8`, 24-bit color and Xvfb on `:99`.
Those values are not deployment environment inputs, so they can later move behind Admin API
runtime settings without requiring container configuration changes.

Timezone is the one deployment-owned browser input. Compose passes only `TZ` into the Web
runtime using `${TZ:-UTC}`: an explicit IANA timezone such as `Europe/Moscow` is preserved,
while an unset or blank value falls back to `UTC`. Chromium receives the resolved timezone
together with the internal display and locale values in its process command.

Do not spoof a foreign browser identity by overriding the user agent; use a real headful
Chromium runtime and consistent locale/display/timezone inputs instead.

The Web runtime exposes a non-destructive `browser_restart` tool. It restarts only persistent
Chromium and reconnects CDP/Playwright while preserving `/browser/profile`, cookies, storage and
the internal dev-extension registry. `browser_status` reports process, CDP and context health
separately and includes the browser-observed locale/timezone/WebGL identity for diagnostics.

Unpacked development extensions installed through the upstream `install_extension` tool are
recorded by ID and workspace path under `/browser`. On the next Chromium start their paths are
passed through `--load-extension`, so the normal development loop can use local workspace builds
without GitHub releases. A destructive browser clean clears this registry together with the
credential-bearing profile.

On GPU-less Linux the internal desktop profile selects ANGLE with SwiftShader explicitly. This is
intended to make ordinary WebGL/WebGL2 available under Xvfb without pretending that a hardware GPU
exists.

## Shared Valkey cache

The stack includes a private `valkey/valkey:9.1.2-alpine` service for hot account resolution
and runtime/system settings. It has no public port and no persistent volume; RDB and AOF are
disabled deliberately. Admin API/SQL remains authoritative. Provider runtimes fail open to
Admin API if Valkey is unavailable, with a short local backoff to avoid turning a cache outage
into repeated connection timeouts. Account and settings mutations invalidate or refresh their
shared keys.

## Persistent storage

The Compose stack owns four named volumes with minimal logical names:

```text
admin-api              -> /admin-api
auth               -> /auth
terminal-workspace -> /workspace (shared by Terminal, Files, Curl and Admin API Admin)
terminal-home      -> /home/agent
```

All mount destinations are absolute paths inside containers. No host bind paths are used.
The volumes are ordinary Compose volumes, not `external` volumes with hard-coded Docker
names, so Docker/Coolify keeps them in managed volume storage and they can be backed up
independently of container filesystems.

Production file data lives only in the shared workspace volume. The active project should
therefore contain `<project>_admin-api`, `<project>_auth` and the Terminal
workspace/home volumes. The former `<project>_files` CAS volume is no longer part of the
runtime topology after migration.

## Build and deploy behaviour

Use the standard Coolify Git-backed Docker Compose deployment flow. No custom selective
build/start script, deploy-state volume, GitHub Actions deployment pipeline or external
image registry is required.

Recommended Coolify settings:

```text
Auto Deploy: ON
Preserve Repository: optional
Shallow Clone: default is fine
Disable Build Cache: OFF
Include Source Commit in Build: OFF
Custom Build Command: <empty>
Custom Start Command: <empty>
```

The repository uses one multi-stage Dockerfile and each Compose service selects its own
target. The dependency layer copies only `pyproject.toml` and `uv.lock` and runs
`uv sync --frozen --no-dev --no-install-project` before runtime-specific source is
copied. Normal source changes therefore reuse the server-local dependency cache.

GitHub CI intentionally does not build production container images. CI owns static analysis
and static validation; Coolify owns the single production image build on the deployment host.
This avoids building the same image once on a hosted CI runner and again on the server.

Compose overrides the image healthcheck for deployment responsiveness. The shared runtime
probe uses a 2-second interval and start period, a 1-second timeout, and 10 retries. A healthy
service is therefore released to dependent services quickly while retaining roughly 20 seconds
of failure tolerance. Keeping this override in Compose avoids invalidating Docker image layers
when deployment-health timing is tuned.

A full Compose reconcile may restart healthy containers briefly, but a failure in one
runtime must not cascade into another runtime after startup. Keep orchestration simple
and preserve that failure-isolation contract instead of adding selective-restart state.

## Public routing

Only gateway receives the deployment's public domain. Provider runtimes, auth and
provider runtimes have no public domains. Gateway routes only the public MCP surfaces
to the corresponding private service.

Native Ghidra remains private; ChatGPT uses `/analysis/mcp`.


## OpenTelemetry / OTLP

Telemetry configuration is layered by Coolify scope rather than duplicated per service.

Root Team shared variables:

```text
OTLP_ENDPOINT=<collector base URL>
OTLP_BEARER_TOKEN=<raw bearer token>
```

Project shared variable:

```text
SERVICE_NAMESPACE=MCP
```

Environment shared variable:

```text
DEPLOYMENT_ENVIRONMENT=production
```

Each backend application references those shared values and sets only its own service name:

```text
OTLP_ENDPOINT={{team.OTLP_ENDPOINT}}
OTLP_BEARER_TOKEN={{team.OTLP_BEARER_TOKEN}}
SERVICE_NAMESPACE={{project.SERVICE_NAMESPACE}}
DEPLOYMENT_ENVIRONMENT={{environment.DEPLOYMENT_ENVIRONMENT}}
OTEL_SERVICE_NAME=admin-api
```

The runtime converts `OTLP_BEARER_TOKEN` into the HTTP `Authorization: Bearer ...` header.
Do not store a preformatted authorization header in Coolify. The Admin UI never receives
`OTLP_BEARER_TOKEN`; browser diagnostics are authenticated to Admin API and Admin API exports
them through the shared OTLP transport with `service.name=admin-ui`.

The Python runtime currently exports OTLP/HTTP protobuf and derives the signal URLs from the
base endpoint:

- logs -> `/v1/logs`;
- traces -> `/v1/traces`;
- metrics -> `/v1/metrics`.

`service.namespace`, `service.name`, `deployment.environment.name`, and
`service.instance.id` are emitted as resource attributes. `service.instance.id` defaults to
the container hostname.

`OTEL_EXPORTER_OTLP_*` variables remain accepted only as temporary migration fallbacks for the
legacy monolith. New split applications use the shared contract above.

## Managed SigNoz and Coolify connections

The read-only Observability MCP may inspect Coolify application metadata, safe server/resource
identity/status, and environment-variable **names/flags** for architecture diagnostics. Server IP,
SSH user/port, proxy configuration, Sentinel settings, Coolify `value`/`real_value`, comments, API
tokens, raw Compose bodies and nested configuration objects that may contain credentials are never
returned. For Git-backed Docker Compose applications, agents receive repository/branch/compose
location metadata and should read the source Compose file through the corresponding Git provider
MCP instead of asking Coolify for a rendered Compose body.

SigNoz and Coolify instance credentials are **not** Coolify deployment environment variables
for `mcp-bridge`. Do not add `SIGNOZ_URL`, `SIGNOZ_API_KEY`, `COOLIFY_URL`, or
`COOLIFY_API_TOKEN` to this Compose application. Multiple instances are configured at runtime
through Admin API Admin (`SigNoz Accounts` / `Coolify Accounts`), where credentials are
encrypted with `ADMIN_API_ENCRYPTION_KEY`.

The private `observability` container receives only the normal Admin API service token and
OpenTelemetry bootstrap environment. It resolves the explicitly requested SigNoz or Coolify
account through Admin API. Coolify accounts should use a token with ordinary `Read` permission;
the unified adapter does not expose sensitive log/environment/secret endpoints or any
mutation/deployment action.
## GitHub agent local-first policy

GitHub REST/Git Data mutation is retained as a fallback, but substantial source work should use
the persistent Terminal workspace and ordinary local Git so GitHub API quota is not consumed by
every intermediate file/commit operation. The GitHub MCP publishes this guidance directly in
source-mutation tool descriptions and results.

These controls live in Admin API application settings rather than deployment environment:

- local-first guidance: enabled by default;
- experimental local Git transport: disabled by default until live acceptance;
- legacy remote source/history mutations: enabled by default as a fallback.

Disabling remote source/history mutations blocks direct API source changes (`put_file`, atomic Git
Data commits, branch/tag rewrites, etc.) while keeping PR, issue, review and GitHub Actions
control-plane tools available. `github_checkout_repository mode=git` remains the preferred entry
point. The local Git transport authorizes a workspace/repository/account binding, writes a short-lived
credential into the checkout's `.git` private credential store, configures the ordinary Git
credential helper, and installs a reserved-branch pre-push guard. Agents can then use normal
`git fetch` / `git push` from Terminal. Re-authorize the workspace when the credential expires.

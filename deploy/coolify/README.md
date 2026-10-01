# Coolify deployment

Production uses one Git-backed Docker Compose application named `mcp-bridge`.
All services are separate containers inside that stack. Coolify builds locally on the
server and reuses the local Docker build cache.

## Runtime model

```text
Traefik -> gateway
             |
             +-- auth
             +-- management
             +-- github
             +-- gitlab
             +-- files
             +-- curl
             +-- terminal
             +-- analysis -> ghidra
```

Only gateway is public. All other services communicate over Compose DNS by service name
and port.

## Failure isolation

A deployment may rebuild or recreate multiple containers; that is acceptable. Isolation
is a runtime property, not a custom deployment-script property:

- every service has its own `restart: unless-stopped` policy;
- dependencies are declared only for primary runtime requirements;
- GitHub and GitLab require healthy Management because account credentials are resolved there;
- Analysis requires healthy Ghidra because Ghidra is its native backend;
- gateway startup does not require provider containers to be healthy;
- an unavailable provider affects only its MCP surface;
- auth is not on the bearer-token request path;
- gateway validates already-issued signed access tokens locally;
- auth is required only for OAuth registration, login, refresh and revocation;
- an auth outage therefore does not invalidate already-issued access tokens.

This is the recovery model: a broken Management, GitLab or Analysis container must not
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

All bootstrap credentials are explicit required environment variables on the Coolify
application. Docker Compose declares each one with `${VAR:?}`, so deployment stops
immediately if a required value is missing or empty:

```text
MANAGEMENT_ENCRYPTION_KEY=...
MANAGEMENT_SERVICE_TOKEN=...
MANAGEMENT_ADMIN_USERNAME=...
MANAGEMENT_ADMIN_PASSWORD=...
MANAGEMENT_SESSION_SECRET=...
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
GITHUB_OAUTH_JWT_SIGNING_KEY=...
GITHUB_OAUTH_ALLOWED_USERS=...
MCP_PUBLIC_BASE_URL=https://mcp.example.com
MCP_ALLOWED_HOSTS=mcp.example.com
MCP_ALLOWED_ORIGINS=https://mcp.example.com
```

Coolify `SERVICE_*` magic generators are intentionally not used for this Git-backed
Docker Compose application because they can be materialized as empty application
variables instead of generated values. Internal secrets should be generated once when
provisioning the Coolify resource and then kept stable.

`MANAGEMENT_ENCRYPTION_KEY` must be a valid Fernet key (URL-safe base64 encoding of
32 random bytes). If an existing Management database with encrypted provider credentials
is migrated, preserve its original encryption key; changing it makes those stored
credentials unreadable.

Runtime wiring and tuning are source-owned defaults, not Coolify environment settings.
This includes service-to-service URLs, ASGI app selection, cache TTLs, file limits,
policy defaults and database/file paths. Public OAuth/HTTP identity is deployment-owned:
`MCP_PUBLIC_BASE_URL`, `MCP_ALLOWED_HOSTS` and `MCP_ALLOWED_ORIGINS` are required.
`OAUTH_ENABLED` remains an optional feature flag and defaults to `true` in Compose.

`AUTH_SERVICE_TOKEN`, `AUTH_URL` and `AUTH_TIMEOUT_SECONDS` are not used.

## Persistent storage

The Compose stack owns five named volumes with minimal logical names:

```text
management -> /management
files      -> /files
auth       -> /auth
terminal-workspace -> /workspace (shared by Terminal, Files, Curl and Management Admin)
terminal-home      -> /home/agent
```

All mount destinations are absolute paths inside containers. No host bind paths are used.
The volumes are ordinary Compose volumes, not `external` volumes with hard-coded Docker
names, so Docker/Coolify keeps them in managed volume storage and they can be backed up
independently of container filesystems.

Production has already migrated to the clean logical names. The active project should
therefore contain the core `<project>_management`, `<project>_files`, `<project>_auth` volumes plus the
Terminal workspace/home volumes for this stack.

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

A full Compose reconcile may restart healthy containers briefly, but a failure in one
runtime must not cascade into another runtime after startup. Keep orchestration simple
and preserve that failure-isolation contract instead of adding selective-restart state.

## Public routing

Only gateway receives the deployment's public domain. Provider runtimes, auth and
management have no public domains. Gateway routes the public MCP surfaces and Admin UI
to the corresponding private service.

Native Ghidra remains private; ChatGPT uses `/analysis/mcp`.


## OpenTelemetry / OTLP

Every runtime exports the same service name (`mcp-bridge`) and a distinct
resource scope: `auth`, `gateway`, `management`, `github`, `gitlab`,
`files`, `web`, `terminal`, `analysis`, or `ghidra`.

The runtime uses the official OpenTelemetry Python SDK and exports all three
signals over OTLP/HTTP:

- logs -> `/v1/logs`;
- traces/spans -> `/v1/traces`;
- metrics -> `/v1/metrics`.

With no endpoint configured the exporter is disabled and runtime behavior is
unchanged. A normal Coolify deployment only needs the shared base endpoint and
authorization header:

```text
OTEL_SERVICE_NAME=mcp-bridge
OTEL_EXPORTER_OTLP_ENDPOINT=<otlp-endpoint>
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<token>
OTEL_ENVIRONMENT=production
OTEL_EXPORTER_OTLP_TIMEOUT=10000
```

Optional signal-specific endpoints override the shared base URL:

```text
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=
```

Optional resource/runtime tuning:

```text
OTEL_SERVICE_VERSION=0.1.0
OTEL_SERVICE_INSTANCE_ID=
OTEL_RESOURCE_ATTRIBUTES=
OTEL_METRIC_EXPORT_INTERVAL=30000
OTEL_LOG_LEVEL=INFO
```

When `OTEL_SERVICE_INSTANCE_ID` is empty the container hostname is used.
The exporter records `service.name`, `service.version`,
`service.instance.id`, `deployment.environment.name`, and `mcp.scope`.

MCP tool calls create spans and application exceptions are emitted as ERROR
logs while the span is active. Metrics include runtime starts/up state, tool
call/error counters and tool duration histograms. Invocation arguments,
results, account IDs, credentials and authorization headers are never added to
OpenTelemetry attributes. The Management invocation audit remains a separate,
redacted local operator log under MCP Calls.

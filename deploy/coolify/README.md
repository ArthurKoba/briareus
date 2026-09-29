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

There is one authorization server and one callback:

```text
issuer:   https://mcp.koba-nexus.ru
callback: https://mcp.koba-nexus.ru/auth/callback
```

Auth owns GitHub OAuth and token issuance. Auth and gateway share the FastMCP JWT signing
key and allowed GitHub user list so gateway can verify bearer tokens locally. GitHub
client ID/secret remain auth-only.

Required shared environment:

```text
OAUTH_ENABLED=true
OAUTH_BASE_URL=https://mcp.koba-nexus.ru
GITHUB_OAUTH_JWT_SIGNING_KEY=...
GITHUB_OAUTH_ALLOWED_USERS=ArthurKoba
```

Auth additionally requires:

```text
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
```

`AUTH_SERVICE_TOKEN`, `AUTH_URL` and `AUTH_TIMEOUT_SECONDS` are not used.

## Persistent storage

The Compose stack owns three named volumes with minimal logical names:

```text
management -> /management
files      -> /files
auth       -> /auth
```

All mount destinations are absolute paths inside containers. No host bind paths are used.
The volumes are ordinary Compose volumes, not `external` volumes with hard-coded Docker
names, so Docker/Coolify keeps them in managed volume storage and they can be backed up
independently of container filesystems.

Renaming the existing production volumes is a one-time migration. Do not deploy the
renamed volume contract until the current `<project>_management-data`,
`<project>_files-data` and `<project>_auth-data` contents have been copied into the
new `<project>_management`, `<project>_files` and `<project>_auth` volumes.

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

Only gateway receives `https://mcp.koba-nexus.ru`. Provider runtimes, auth and
management have no public domains. Gateway routes the public MCP surfaces and Admin UI
to the corresponding private service.

Native Ghidra remains private; ChatGPT uses `/analysis/mcp`.

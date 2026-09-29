# Coolify deployment

Production uses one Git-backed Docker Compose application named `mcp-bridge`.
All services are separate containers inside that one stack. Coolify builds locally
on the server and reuses the local Docker build cache.

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

Only gateway is public. All other services communicate over Compose DNS by service
name and port.

## Failure isolation

A deployment may recreate multiple containers; that is acceptable. Runtime failures
must remain isolated:

- provider services have independent restart policies and no health-gated
  `depends_on` relationships;
- gateway startup does not require any provider to be healthy;
- an unavailable provider affects only its MCP surface;
- auth is not on the bearer-token request path;
- gateway validates signed access tokens locally;
- auth is required only for OAuth registration, login, refresh and revocation;
- an auth outage therefore does not invalidate already-issued access tokens.

## OAuth

There is one authorization server and one callback:

```text
issuer:   https://mcp.koba-nexus.ru
callback: https://mcp.koba-nexus.ru/auth/callback
```

Auth owns GitHub OAuth and token issuance. Auth and gateway share only the FastMCP
JWT signing key and the allowed GitHub user list. GitHub client ID/secret remain
auth-only.

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

The Compose stack owns:

```text
management-data -> /management
files-data      -> /files
auth-data       -> /data/fastmcp
```

Do not delete or recreate these volumes during ordinary deployments.

## Selective local deployment

The repository keeps one multi-stage Dockerfile and one Coolify Compose application.
Coolify still performs the build locally on the deployment server, so unchanged Docker
layers stay in the server-local build cache.

Container replacement is selective. Configure the application as follows:

```text
Auto Deploy: ON
Preserve Repository: ON
Shallow Clone: OFF
Disable Build Cache: OFF
Include Source Commit in Build: OFF
Custom Build Command: <empty>
Custom Start Command: bash deploy/coolify/start-selective.sh
```

Set Watch Paths to:

```text
Dockerfile
docker-entrypoint.sh
docker-compose.yaml
pyproject.toml
uv.lock
src/**
deploy/coolify/*.sh
```

Watch Paths prevent documentation/test-only pushes from starting a Coolify deployment.
They do not choose individual Compose services.

The standard Coolify build phase remains unchanged and uses the local Docker cache.
After the build, `start-selective.sh` compares the current Git commit with the last
successfully started commit stored in the Docker volume
`mcp-bridge-deploy-state`. It then runs `docker compose up -d --no-deps --wait`
only for affected services.

Runtime ownership map:

```text
src/auth_service/**       -> auth
src/bridge/**             -> gateway
src/management/**         -> management
src/modules/github/**     -> github
src/modules/gitlab/**     -> gitlab
src/modules/files/**      -> management, files, curl
src/modules/curl/**       -> curl
src/modules/analysis/**   -> analysis
src/modules/ghidra/**     -> ghidra
src/common/**             -> all runtimes
Dockerfile                -> all runtimes
docker-entrypoint.sh      -> all runtimes
docker-compose.yaml       -> all runtimes
pyproject.toml / uv.lock  -> all runtimes
```

If the previous successful commit is unavailable in the preserved Git history, the
script fails safe by selecting all services. The deployment SHA is updated only after
the selected services pass Compose health waiting.

No GitHub Actions deployment pipeline or external image registry is required.

## Build cache boundaries

Dependencies are installed before runtime-specific source code is copied. The dependency
layer copies only `pyproject.toml` and `uv.lock`; documentation changes therefore do
not invalidate `uv sync`.

Keep Coolify build cache enabled and keep Include Source Commit in Build disabled.

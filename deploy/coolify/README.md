# Coolify split deployment

Production runs MCP Bridge as independent Coolify applications. The repository-level
`docker-compose.yaml` remains the local/integration topology only.

The public edge is split into two stable control-plane runtimes:

- `auth` owns OAuth/DCR/GitHub login, the single upstream callback, token storage and
  exact MCP resource audiences.
- `gateway` owns the public MCP domain, protected-resource metadata, routing and the
  Admin reverse proxy.

Provider runtimes remain private and independently deployable.

## Runtime ownership

| Application | Docker target | Internal name | Public | Persistent storage |
| --- | --- | --- | --- | --- |
| auth | `auth` | `auth` | through gateway only | `auth-data:/data/fastmcp` |
| gateway | `gateway` | `gateway` | `mcp.koba-nexus.ru` | none |
| management | `management` | `management` | through gateway `/admin` | `management-data:/management`, `files-data:/files` |
| github | `github` | `github` | no | none |
| gitlab | `gitlab` | `gitlab` | no | none |
| files | `files` | `files` | no | `files-data:/files` |
| curl | `curl` | `curl` | no | `files-data:/files` |
| analysis | `analysis` | `analysis` | no | none |
| ghidra | `ghidra` | `ghidra` | no | none |

All applications join the same Coolify network. Only gateway receives the public
domain. Auth is never assigned its own public domain; gateway forwards the OAuth routes
to it.

The native backend behind the `ghidra` runtime remains private. ChatGPT connects to
`/analysis/mcp`, not to a raw Ghidra surface.

## Public OAuth contract

There is one authorization server:

```text
https://mcp.koba-nexus.ru
```

and one upstream GitHub callback:

```text
https://mcp.koba-nexus.ru/auth/callback
```

The authorization server accepts only the explicit MCP resource allowlist:

```text
https://mcp.koba-nexus.ru/mcp
https://mcp.koba-nexus.ru/github/mcp
https://mcp.koba-nexus.ru/gitlab/mcp
https://mcp.koba-nexus.ru/files/mcp
https://mcp.koba-nexus.ru/web/mcp
https://mcp.koba-nexus.ru/analysis/mcp
```

Every resource publishes RFC 9728 protected-resource metadata pointing back to the same
authorization server. Access and refresh tokens are audience-bound to the exact resource
selected by the client. No path-specific GitHub callback URLs are used.

## Required environment ownership

Auth application:

```text
OAUTH_BASE_URL=https://mcp.koba-nexus.ru
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
GITHUB_OAUTH_JWT_SIGNING_KEY=...
GITHUB_OAUTH_ALLOWED_USERS=ArthurKoba
AUTH_SERVICE_TOKEN=...
```

Gateway application:

```text
OAUTH_ENABLED=true
OAUTH_BASE_URL=https://mcp.koba-nexus.ru
AUTH_URL=http://auth:8000
AUTH_SERVICE_TOKEN=...
MANAGEMENT_URL=http://management:8000
```

`AUTH_SERVICE_TOKEN` is shared only by auth and gateway. GitHub OAuth credentials and
the JWT signing key exist only in auth.

## Watch paths

Every application watches its Docker/runtime authority:

```text
Dockerfile
docker-entrypoint.sh
pyproject.toml
uv.lock
src/common/**
```

Add runtime-specific paths:

```text
auth:
  src/auth_service/**

gateway:
  src/bridge/**

management:
  src/management/**
  src/modules/files/**

github:
  src/modules/github/**

gitlab:
  src/modules/gitlab/**

files:
  src/modules/files/**

curl:
  src/modules/curl/**
  src/modules/files/**

analysis:
  src/modules/analysis/**

ghidra:
  src/modules/ghidra/**
```

A provider-only change therefore rebuilds/restarts only that provider. Auth and gateway
remain untouched. A change to `src/common/**`, Dockerfile or dependency lock is shared
runtime authority and intentionally fans out.

## Availability model

Gateway startup does not require provider containers. Backend catalog/call failures are
isolated to the selected backend.

Gateway token verification depends on the private auth runtime, but auth restart does not
restart gateway. During a short auth outage new requests requiring token verification
return authentication failure; provider processes remain up.

Management restart affects Admin/account resolution only. It does not restart gateway,
auth or unrelated providers.

## Build cache

Third-party dependencies are installed from committed `uv.lock` before source code is
copied:

```text
uv sync --frozen --no-dev --no-install-project
```

Do not enable Coolify "Disable Build Cache" for normal deployments. Keep "Include Source
Commit in Build" disabled unless build metadata is injected through a cache-safe layer.

## Health/readiness

Every runtime image exposes TCP port 8000 and has a TCP healthcheck. Configure Coolify to
honor readiness before replacing the public gateway instance.

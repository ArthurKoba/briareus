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

## Build behaviour

The repository keeps one multi-stage Dockerfile. Each Compose service selects its
own target. Dependencies are installed before service source code is copied, so
normal source changes reuse local dependency layers.

Keep Coolify build cache enabled. Do not enable "Disable Build Cache". Avoid embedding
the source commit into dependency layers.

No custom selective-build script or GitHub Actions deployment pipeline is required.

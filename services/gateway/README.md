# Briareus Gateway — independently deployed service

Owner: Runtime. This folder contains its ASGI source, uv dependency lock,
Dockerfile, Docker build ignore, and both Compose inputs. It never imports
private Control Panel, Identity, Authorization, or Hand implementation source.

The one public origin is `https://briareus.koba-nexus.ru`. Public landing and
Panel static resources are fetched from `briareus-admin-ui:8080` and all
`/api/*` is forwarded unchanged to `briareus-admin-api:8000`. The fixed
public `/auth/v1/*` namespace is transparently proxied to
`briareus-rauthy:8080` without rewriting the issuer, method, path, query,
body, cookies or return status. Gateway sets canonical HTTPS forwarding
headers itself and ignores caller-supplied forwarding claims. Rauthy owns
OAuth/OIDC login and tokens; Backend owns Panel API permissions. Unapproved
`/hands/*`, root `/.well-known/*` and `/oauth/*` paths remain unavailable.

## Scoped Coolify Development cutover

Use only the existing Gateway App UUID `vpuhamswqggqtau3als7siuo` under
Briareus MCP / development. Preserve its domain, network, env references,
Auto Deploy and container identity. After this directory is merged, set:

- Base directory: `/services/gateway`
- Docker Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `services/gateway/**`

The build context remains repository root, but the Dockerfile copies only
this service folder. Native application imports do not require monorepo
runtime source overlays. The TCP healthcheck proves an accepting listener,
not Backend API readiness or authenticated product success.

Rollback (only if this cutover fails): restore the previous Gateway-only
Base directory `/deploy/gateway`, Compose location
`/docker-compose.coolify.yaml`, and prior exact 26 Watch Paths from its
known-good Coolify release, then redeploy only Gateway. Do not touch Panel,
Backend, Hands, secrets or volumes.

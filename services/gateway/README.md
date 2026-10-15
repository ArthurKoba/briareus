# Briareus Gateway — independently deployed service

Owner: Runtime. This folder contains its ASGI source, uv dependency lock,
Dockerfile, Docker build ignore, and both Compose inputs. It never imports
private Control Panel, Identity, Authorization, or Hand implementation source.

The single public origin is `https://briareus.koba-nexus.ru`. Public
landing and Panel static resources come from
`briareus-control-panel-ui:8080`; canonical application `/api/v1/*`
requests are forwarded without changing their URL to
`briareus-control-panel-api:8000`. The historical registered OAuth callback
`GET /api/auth/oidc/callback` is an exact additional exception; other
unversioned API routes, private Core APIs and encoded aliases are closed.
The public `/auth/v1/*` routes use fixed `briareus-rauthy:8080` upstream
with source-verified administrative route/method exclusions. Gateway constructs
canonical Host and provider HTTPS forwarding metadata independently, never
from browser-supplied forwarding assertions. Rauthy owns OAuth/OIDC identity,
Backend owns Panel API permissions. Unapproved `/.well-known/*`, `/oauth/*`
and unknown `/hands/*` paths remain unavailable. Exact allowlisted
`/hands/<hand>/mcp` POST paths require separate coarse admission, not a
blanket proxy.

## Fail-closed MCP connection admission (source, not live Permit acceptance)

The only ingress targets are the six static `hands/<hand>/mcp` paths, where
`hand` is `files`, `terminal`, `web`, `svc`, `infrastructure` or `reverse`.
No arbitrary service name, user-provided upstream or open proxy is allowed.

`POST` requires exactly one `Authorization: Bearer ...` and three required
**untrusted selectors**: `X-Briareus-Project-UUID` (UUIDv4),
`X-Briareus-Agent-Session-UUID` (UUIDv4) and
`X-Briareus-Grant-Revision` (positive integer). A client-provided selector
never establishes identity, grant, membership, authority or a peer identity.
Gateway forwards the original bearer and only `{project_uuid,
agent_session_uuid, action: "mcp.connect", expected_grant_revision}` to
independent `briareus-authorization:8000` via
`POST /internal/v1/authorization/decide`. Only its exact 200
`{"allowed":true}` means coarse access; the Authorization owner is
responsible for independent signed Rauthy identity, authenticated Gateway
service peer, current Platform membership and revisioned Cedar grant.
Gateway never verifies Cedar or constructs a User / AgentSession assertion.

Absent bearer -> 401; absent/malformed selectors -> 400; upstream decision
401/403 -> 401/403; unavailable, unconfigured attestor or unexpected response
-> 503. Any non-Permit response leaves the Hand untouched. Even after coarse
Permit the receiving Hand MUST verify token audience, signed service trust,
current AgentSession grant and each tool/effect itself; Gateway Permit is not
an execution grant. Protected Tools remain unregistered until those invariants
are accepted. Unapproved browser cookies are rejected. Gateway and direct Hand
HTTP independently reject ambiguous Content-Length/Transfer-Encoding and
unsupported body encodings before contacting Cedar or FastMCP; declared length
must equal the bytes received. Fixed Hand routing
preserves protocol-version metadata and streams MCP HTTP (including SSE and
notification 202) without Control Panel API in the data plane. Public Origin
and Host spoof protection still applies. No token or request body is logged.

As of source publication there is no verified Gateway/Hand access-token
resource audience or live signed service-peer attestor. The private
Authorization API defaults to HTTP 503, so **no public positive MCP grant is
claimed**. This change prepares explicit deny semantics only; do not use a
self-asserted header or disabled sandbox as an emergency bypass.

## Scoped Coolify Development cutover

Use only the existing Gateway App UUID `vpuhamswqggqtau3als7siuo` under
Briareus MCP / development. Preserve its domain, network, env references,
Auto Deploy and container identity. After this directory is merged, set:

- Base directory: `/services/gateway`
- Docker Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `services/gateway/**` and `services/external/**` (the
  current owner-mandated External dependency watch)

The build context remains repository root, but the Dockerfile copies only
this service folder. Native application imports do not require monorepo
runtime source overlays. The TCP healthcheck proves an accepting listener,
not Backend API readiness or authenticated product success.

Rollback requires the exact last known-good Gateway-only release SHA and
the independently captured Development Application configuration. Do not
blindly restore historical `/deploy/gateway` or an obsolete Watch Path list:
they are not evidence of the current saved Coolify settings. Verify that the
target image still matches the current Backend API and provider routing before
any scoped rollback. Do not touch Panel, Core, Hands, secrets or volumes.

### Native login stays in Briareus Control Panel

Control Panel owns user-visible login/MFA. Gateway does not serve
Rauthy's hosted SvelteKit UI, and no root-relative /_app or /assets
routes are released for the native login MVP. Opaque /api/* calls
travel only to the fixed Control Panel API owner with original
same-origin cookie/body. Untrusted X-Forwarded-* claims are stripped;
none authenticates a User.

Source regression:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/gateway/src
services/gateway/.venv/bin/python services/gateway/tests/test_native_panel_auth_boundary.py

### Versioned Control Panel Auth API

Browser authentication and session calls belong to /api/v1/auth/*;
Project, AgentSession, approvals, catalogue and Files content operations
belong to sibling /api/v1/* routes. The URL never exposes the upstream
native or oidc implementation names. Gateway
forwards exact v1 URLs unchanged. Retired /api/auth/* application
routes return 404 BEFORE contacting Backend; no redirects or legacy
rewrite. Only GET /api/auth/oidc/callback remains as the precise
registered OAuth provider redirect URI, not a browser application API.
Changing the callback requires coordinated Rauthy-client registration
and Backend verifier changes, never a Gateway URL alias.

The pinned Backend source and promoted typechecked Frontend build must
agree on v1 before the local six-owner native stack can launch. The
source-only transport proof is
services/gateway/tests/test_auth_api_v1_public_contract.py; it
does not create a User, verify credentials or authorize Files.

#### Versioned public API surface

The wildcard /api/* Starlette route is NOT a wildcard upstream access
policy. Only canonical /api/v1/* and the exact provider-registered
GET /api/auth/oidc/callback may reach the fixed Backend owner.
Other API prefixes, private Core endpoints, encoded route aliases
and future unknown API versions are denied by Gateway with 404 before
upstream I/O. This is separate from Cedar and Files authorization.

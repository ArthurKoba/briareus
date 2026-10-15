# Gateway coarse MCP admission — local private transport stage

Gateway remains the thin public /hands/HAND/mcp router, retaining /,
/panel/, canonical /api/v1/*, the registered OAuth callback, and allowed Rauthy paths. It never becomes a policy,
Cedar, token issuer or Control Panel management service.

The source-stage TrustedGatewayDecisionPort is the only permitted path for
a protected mcp.connect decision. It must be supplied by a trusted runtime
supervisor with actual authenticated mTLS/Unix service-peer identity and a
short-lived, replay-protected, body-bound proof accepted by the independent
Authorization owner. Gateway serializes only bounded Project UUIDv4,
AgentSession UUIDv4, action mcp.connect and grant revision into exact JSON
bytes. Neither the caller's Bearer, a private DNS name nor an HTTP header
can manufacture this service identity.
The ingress requires byte-for-byte canonical `/hands/HAND/mcp` raw URL
and an empty query string before the private peer is contacted. Percent-
encoded aliases and synthetic URI parameters are not alternate resources.
Gateway accepts only lowercase canonical UUIDv4 Project/AgentSession
selectors and the exact positive decimal grant revision (no padding or
surrounding whitespace). It refuses noncanonical values before private
Authorization or Hand forwarding; it never normalizes an ambiguous
header into an apparently verified selector.

The default build_app() has no such port. After parsing/validating the
Bearer and selectors, protected admission returns HTTP 503 with no Bearer sent
over unauthenticated private HTTP, and without waiting for an untrusted MCP
request body. With a real adapter, the Gateway now independently performs
strict bounded MCP transport preflight BEFORE calling Authorization:
maximum 1 MiB body, 1024 raw ASGI body events (including empty chunks),
eight-second total input deadline, only UTF-8 JSON objects with unique
keys at every depth, finite JSON numbers and valid Unicode scalar values.
Duplicate or conflicting Content-Length/Transfer-Encoding framing, a mismatched
declared body length, noncanonical decimal Content-Length (including leading
zeros), unwanted Content-Encoding, malformed JSON and batches are
rejected before the PDP. The direct Hand FastMCP boundary independently checks
these HTTP framing invariants, without treating a well-framed request as a grant.
Rejected requests cannot forward the body, bearer or selectors to the Hand.
Accepted request bytes are passed unchanged after current coarse Permit; the
actual Hand separately validates and authorizes each protected effect.

A future real adapter may pass Bearer
only to its independently verified private Authorization ingress. Permit
requires HTTP 200 with the exact typed JSON object {"allowed":true};
integer 1, string "true", duplicate keys, unknown fields, oversized or
malformed bodies all deny. Authenticated 401/403 are propagated; unavailable
PDP or untrusted response maps to 503. Only on proven admission does Gateway
forward the original bearer and canonical selectors to the independent Hand
PEP, which must verify the exact resource and current grant again.

This is SOURCE/LOCAL_NEGATIVE only, not live trusted peer attestation. The
ASGI factory, actual Coolify resource and signed Rauthy audiences do not
yet have an installed trusted adapter. No new certificate material,
allow-by-header switch, unsigned internal principal or network bypass was
introduced. Real Dev validation must establish Authorization's server-side
briareus.verified_private_peer.v1 from a legitimate OS/TLS peer, current
Project membership, Cedar Permit/Deny/Revoke, and the isolated executor.

## Rauthy source-route privacy

A source-reviewed Rauthy v0.37.1 /auth/v1/users administrative route
slice is detailed in docs/services/gateway/rauthy-v0371-public-users.md.
It denies collection/attribute-schema/email-lookup and privileged
single-User mutations before proxying, while preserving upstream login,
registration, password recovery, MFA and self-service. It is NOT a
confirmed block of every Rauthy Admin namespace or a verified Dev
public route result.


The subsequent source-reviewed Rauthy administrative namespace/method
privacy extension is recorded in
[the Rauthy Admin privacy audit](rauthy-v0371-public-admin.md).
It selectively blocks source-confirmed management APIs while retaining
provider-owned OAuth dynamic clients, login/callback, client branding,
registration, account self-service, password recovery, passkeys and MFA.
This remains LOCAL source acceptance, not a live Dev route claim.


The pinned upstream v0.37.1 review subsequently included Backup,
Email, Themes, Terms of Service, PAM, Admin HTML and the OIDC signing
key-rotation route, retaining the signed-in OAuth logout/JWKS and
user/PAM self-service flows. All remain local source gates, not a
replacement for real Development privacy and login checks.

## Native Control Panel authentication (owner correction, 2026-10-14)

Product direction requires native Briareus Control Panel login,
first-factor, challenge/MFA, recovery and logout UI. Browser uses
the scoped Control Panel API BFF as its only credential/challenge
transport; BFF uses Rauthy v0.37.1 session, PoW, CSRF, MFA and signed
token contracts. Public Gateway is a transport layer, NOT hosted Rauthy
login UI, password verifier or alternative provider.

Experimental public root-relative SvelteKit /_app/immutable/* and
/assets/* forwarding for Rauthy hosted UI (commits 13e151a and
31d2709) has been removed from Runtime source. Those paths are not
required for native Panel auth. Prior LOCAL real-asset results are
historical compatibility evidence, NOT a product acceptance gate.

Gateway forwards only canonical public /api/v1/* (and the exact legacy
provider callback) method, body, browser cookie and same-origin Origin to the
fixed Control Panel API owner; it never
mints a User, role, OAuth code or Cedar permission. It strips ALL
client-controlled X-Forwarded-* metadata, including previously
unfiltered X-Forwarded-User, before private forwarding. Rauthy Admin
REST stays filtered and protected MCP still needs an independently
authenticated service peer and current owner resource permission.

services/gateway/tests/test_native_panel_auth_boundary.py verifies
hosted static route removal, BFF-only opaque transport, owner 503
with no synthetic login, untrusted proxy identity metadata stripped,
and hostile Host/Origin rejection. A real native password/MFA BFF,
verified Project, AgentSession, Cedar Permit/Revoke and one Files
effect remain separate not-yet-passed acceptance gates.

### Native challenge transport and cookie fidelity

The Backend-owned native Rauthy initial-session decoder can now parse
the genuine pinned v0.37.1 provider GET /oidc/authorize HTML, two
Host-only Secure provider cookies and a one-use CSRF token in the
disposable LOCAL Rauthy sandbox. Backend alone may escrow those private
cookies and subsequently perform authorized challenge/MFA exchanges.
The Gateway never obtains provider-cookie signing or decides that a
password/CSRF/OTP is valid.

The Gateway's scoped /api/* forwarding preserves the original HTTP
method, exact request bytes, same-origin Origin, browser Cookie and
opaque X-CSRF-Token for the Control Panel API. The API response can
carry multiple independent Set-Cookie headers, a bounded native
challenge response or a 303 back to the same-origin Panel. Gateway
does not merge those cookie headers or generate an authenticated
browser ticket. Every incoming X-Forwarded-* assertion is stripped.
The source ASGI test
services/gateway/tests/test_native_panel_auth_boundary.py verifies
two synthetic Secure challenge-cookie response fields, opaque CSRF
forwarding, a same-origin 303 cookie-clear response, explicit
owner-unavailable failure and origin/host denials. Synthetic fixtures
are transport checks only, not proof of signed Rauthy identity.

A separate local test-only script
local/runtime-rauthy-mvp-20261014/smoke_native_rauthy_init_backend.py
(referenced relative to the persistent Koba workspace, not part of the
release source) verifies real pinned HTTPS Rauthy provider initial
session parsing by Backend with trusted test certificate, including
four malformed-cookie/CSRF/content-type negatives. It never submits
credentials or grants a Platform Project/Cedar permission.

### Native Init and proof-of-work fixed HTTP framing

The Backend owner now exposes real local-only native Rauthy BFF endpoints
POST /api/v1/auth/start (201 with an opaque pending cookie) and
POST /api/v1/auth/pow (200 with a provider challenge, NOT login).
The source Backend validates exact Content-Length: 2 and the exact
application/json body "{}" for each. The Gateway's original streaming
API proxy omitted the browser's declared length and caused HTTPX to
use chunked framing, which the real Backend properly rejected.

Gateway now preserves one syntactically valid, nonconflicting
Content-Length for the fixed Control Panel API owner even while
streaming the original body unmodified. Duplicate, comma-separated,
nondecimal, out-of-range or Transfer-Encoding-conflicting browser
length declarations are rejected before upstream contact. It never
derives a principal or Authorization identity from body framing.
The Rauthy provider and MCP private transport paths remain unchanged.

Native source contract test
services/gateway/tests/test_native_panel_auth_boundary.py covers
owner-shaped Init 201/PoW 200 opaque forwarding, the original "{}"
octets and declared length 2, transactional Secure Set-Cookie
fidelity, all hostile framing negatives, and remaining fail-closed
Host/Origin and unauthorized Files boundaries.

A separate same-host LOCAL integration harness
local/runtime-rauthy-mvp-20261014/smoke_native_bff_start_pow.py
uses REAL Backend 2a803a8 native logic, REAL Valkey NX/expiry, and
REAL pinned Rauthy v0.37.1 behind the actual Gateway and HTTPS local
facade, verifying 201 Init / 200 PoW / 409 replay / 401 expired old
transaction / 401 no User after repeated Init. No password or signed
User login is present; this is source/local pre-first-factor proof.

### Gateway HTTP forwarding helper boundaries

The existing fixed-origin /api and /auth/v1 streaming proxy now keeps
three concerns separate in Runtime-owned source: _api_headers removes
browser-supplied hop/proxy identity (including Connection-listed fields),
_api_declared_length validates one original Control Panel BFF
Content-Length without changing Rauthy framing, and _upstream_headers
adds only Gateway-owned Rauthy canonical Host/Proto assertions. These
functions do not authenticate users, interpret native Rauthy challenges,
authorize Project/AgentSession, or change private MCP transport.
The native-panel source test covers both fixed upstream branches,
exact BFF Init/PoW length+cookies and filtered hostile proxy headers.
Real localhost Backend/Rauthy Init+PoW and six Hand negative tests PASS.

### Management command fidelity and stream teardown

Opaque API forwarding retains Operation-UUID, Idempotency-Key, original
request bytes and the query on exact AgentSession detail reads. Gateway
must not manufacture a new operation ID or silently change the revision
when a caller repeats an uncertain command. The target Backend remains
responsible for idempotency, authorization and current revision.

Response filtering now removes both fixed hop headers and fields named
by the upstream Connection header. Distinct Set-Cookie fields and
Retry-After remain end-to-end metadata unless explicitly hop-scoped.
Targeted transport fixtures verify original command IDs/body on repeat,
exact detail query, owner503, cookies and foreign-Origin denial. These
fixtures do not demonstrate a real granted approval/revoke.

The private ProxyStreamingResponse owns teardown independently of body
iteration. Previously, failure of the first ASGI response-start send left
an upstream response open and a semaphore slot occupied because the body
generator had never entered its finally block. Both API and MCP streaming
now share exactly-once cleanup with a finite upstream-close deadline;
repeated caller cancellation cannot release twice or strand the slot.
Checks cover 80 early/midstream disconnects (beyond the 64-slot pool),
unchanged SSE bytes, repeated cancellation and ASGI2.0 disconnect events.
No private Authorization admission or Hand effect policy is changed.

### Coordinated release source compatibility (15 October 2026)

Runtime consumed Deployment's reviewed local patch from #6184076645.
Fixed UI/API upstreams now use the names actually declared by peer
Compose services: `briareus-control-panel-ui:8080` and
`briareus-control-panel-api:8000`, including the strict API target-host
check. The public Host/origin, paths, cookies, request framing and Rauthy
upstream remain unchanged. The isolated local destination adapter uses
these same fixed names; it still permits only declared loopback ports.

All seven Runtime Coolify manifests now include the owner-selected shared
`services/external/**` Watch input alongside their original owning paths.
Parsed comparison proves no other service, environment, network, volume
or build field changed. This is source configuration, not verification of
Coolify's saved Watch field or Docker DNS at the deployed revision. Apply
as part of the coordinated existing-app release; do not deploy Gateway
alone against an older incompatible UI/API container naming set.


### Parallel shutdown shares stream ownership

Gateway shutdown now drains the same `ProxyStreamingResponse` cleanup
objects as downstream disconnects, rather than directly closing raw
responses in a serial loop. The prior loop stopped on the first close
exception, leaving the remaining responses and client reference uncleared.
Each stream retains its bounded close deadline and releases its pool slot
exactly once; independent streams drain concurrently. Repeated shutdown
cancellation waits for cleanup and then propagates. A slow owner response
arriving after the drain barrier closes immediately instead of registering
a new live stream. Invalid MCP upstream statuses use this same bounded
cleanup, without changing their admission failure result.

Source checks cover failed and delayed closes, concurrent disconnect,
late upstream arrival and all64 slots returning, alongside the existing
80 early/midstream disconnect, raw SSE and ASGI2.0 cases. These are
transport/lifecycle guarantees, not authenticated MCP or Files decisions.


### Pending requests also belong to shutdown

A request waiting for incomplete ASGI input has no upstream response yet.
It previously remained outside the stream registry after drain, retaining
an admission slot. `_proxy_start.PendingProxyStart` now owns the send stage
until response-header handoff; shutdown cancels these owned sends alongside
stream cleanup. A response arriving during cancellation is either handed
to the stream owner once or closed as an orphan. Downstream cancellation
still propagates; service-driven abort retains the route's 502/503 failure.

The initial send has a 60-second TOTAL deadline, including waiting for
client body events and provider response headers. This is not a 60-second
lifetime for an established SSE stream: existing streaming behavior starts
after the handoff and is unchanged. It prevents slowly trickled or empty
input events from indefinitely occupying the 64-slot pool. No body is
interpreted or rewritten, and uncertain mutations are never replayed.
Targeted pending-body, shutdown race and short-deadline fixtures pass,
alongside existing response-stream cancellation and raw-byte checks.

### Server shutdown budget precedes application cleanup

Uvicorn's default graceful-shutdown wait is unbounded and occurs BEFORE
ASGI lifespan shutdown. Thus application drain alone does not guarantee
cleanup within the existing Compose stop_grace_period of 30s while an
upload or SSE connection remains open. Gateway's Dockerfile command now
sets `--timeout-graceful-shutdown 10`, leaving
room for the existing bounded application stream cleanup before the
orchestrator's 30s stop window. Active operation semantics, request-start
60s deadline, routes, identities and runtime limits are otherwise unchanged.

A separate native uv-run process using the declared Uvicorn CLI was sent
SIGTERM during an actual incomplete TCP POST to an owned loopback upstream.
Without a graceful limit it remained waiting. With 10s, source lifespan
completed in 10.19s: pending0, streams0, slots64, client reference cleared.
The upstream destination mapping was fixture-only and no application
command was replayed. This is native process/CLI evidence, NOT a Docker
image build, Coolify stop/restart observation or proof against every type
of uninterruptible transport. No deployed Compose setting was changed.

### Native first-factor and cancellation transport preparation

Backend's next native Control Panel contract adds private
GET /api/v1/auth/capabilities, POST /api/v1/auth/first-factor
and POST /api/v1/auth/cancel to existing Init/PoW owner endpoints.
Gateway remains an opaque same-origin transport: it forwards exact
request bytes, trusted-origin browser cookie, bounded Content-Length
and Gateway-sanitized proxy metadata. It MUST NOT verify passwords,
solve provider PoW, infer Project membership or create browser sessions.

Native ASGI tests now cover an unsupported continuation (409,
authenticated=false, no session cookie), a 204 cookie clear, capability
JSON without signed-in claims, and cancel racing an in-flight
first-factor request. Cancellation can complete before the earlier
request; its late denial adds no cookie, and both responses release
admission slots. These are controlled transport fixtures, NOT signed
Rauthy login, current Valkey state or confirmed release-ready Backend.
The first-factor code is still uncommitted in its owner's worktree;
do not import it into shared production from dirty peer state.

### Core/Execution outage and uncached connection admission

The single-host MVP retains the future Core/Execution boundary: an
independent current Core Authorization decision is required for EACH
new MCP connect. A previously returned coarse mcp.connect Permit cannot
be replayed after Core becomes unavailable, and an injected test-only
positive admission cannot bypass the Hand's separately closed effect
PEP. Gateway tests/test_core_outage_mcp_gate.py exercises Core
unavailable/401/403/503, malformed/duplicate positive replies, bounded
timeout, synthetic admission followed by Hand 503, subsequent Core loss,
and browser cookie substitution. All reject without exposing Files data
or leaking Gateway slots. The test uses controlled private reply fixtures
ONLY; it does not claim genuine service peer identity, Redis nonce store,
Cedar Permit, signed human or an operational multi-node environment.

## Versioned browser Auth API and separately pinned OAuth callback

Owner API direction 2026-10-15: /api/v1/auth is the v1 application
auth namespace. Gateway must NOT rewrite, redirect or silently alias
old /api/auth/native/* or /api/auth/oidc/* application routes. Such
unversioned requests (including encoded spellings, malformed variants
and unexpected methods) return 404 before Backend contact.

The only exception is exact GET /api/auth/oidc/callback: this is the
unchanged Rauthy OAuth client registered redirect URI, NOT an alias.
To move it to v1 the provider client allowlist and Backend expected
callback validation must be changed in one coordinated owner release.
An ingress rewrite cannot make an unregistered redirect safe.

bridge/_api_contract.py enforces this rule. The new /api/v1/auth/* authentication namespace and sibling
/api/v1/* Project/AgentSession/approvals/Files APIs are forwarded
to the fixed Control Panel API byte-for-byte.
test_auth_api_v1_public_contract.py verifies the v1 transport,
retired encoded/ordinary paths denied without leaking a password
body or cookie, exact registered callback GET, no callback POST, and
a denied versioned browser Files content request. It does not
generate a signed token or positive Cedar Permit.

The Runtime local compact stack now invokes
local/runtime-rauthy-mvp-20261014/auth_api_v1_gate.py before starting
any child service. The preflight verifies only SHA-pinned committed
Backend source route decorators (including literal constant prefixes),
the separate provider-registered callback and a promoted Frontend
snapshot with passing typecheck/Vite evidence. It refuses mixed
Backend/Frontend versions, legacy UI route literals and unverified
builds before opening Rauthy, Valkey or any other owned process.
The previously selected B83a4577 and old UI deliberately fail this
check; v1 REAL E2E requires a new jointly committed, verified pair.

### No wildcard Core/private API exposure after v1 migration

Although Starlette structurally uses an /api/{path:path} route, the
Runtime proxy now only forwards raw canonical ASCII /api/v1/* paths
to the fixed Control Panel Backend owner. An exact registered GET
/api/auth/oidc/callback is admitted as a separate OAuth redirect URI.
All other /api/* paths, including /api/internal/*, /api/v2/*,
encoded separators and noncanonical segments, return Gateway 404 with
API_ROUTE_NOT_PUBLIC before contacting Backend. Retired /api/auth/*
retains the explicit AUTH_API_ROUTE_RETIRED denial. New private Backend
routes cannot inadvertently become browser accessible due to a wildcard.

Source ASGI tests and local smoke_v1_two_process.py use two REAL
loopback processes (current committed Backend bed64b0 and Gateway) to
verify v1 transport, rejected private/encoded URLs, the unchanged
registered OAuth callback, and failclosed 503 without a configured
provider. This is no signed login or Cedar/Files permit.

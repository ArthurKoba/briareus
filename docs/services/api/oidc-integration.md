# Control Panel API — Rauthy-only OIDC and Platform BFF

**Owner decision (2026-10-14): clean Briareus Development, no legacy Identity.**
The Control Panel API no longer mounts its old Identity first-user registration,
password/login, bearer/logout or /api/platform/me endpoints. They deliberately
return HTTP 404 instead of forwarding to a retired Identity service.

**Current native implementation:** [native first-factor and cancellation](native-login.md)
owns the latest route/state contract. Earlier Init/PoW/GETDEL notes below are
historical checkpoints, not a statement that first-factor transport is still
absent. OTP/WebAuthn/ToS continuations are still explicitly unavailable.

Only the existing management application and Gateway /api/* route are retained.
Rauthy handles real human OAuth authorization-code+PKCE, issuer keys and
credentials. This BFF owns the opaque secure HttpOnly Valkey browser session,
delegated current Platform User/Team/Project proof, and separate Authorization
management permissions. No OAuth subject alone carries a Briareus role or grant.

Confirmed issuer https://briareus.koba-nexus.ru/auth/v1/ , registered
Panel client briareus-control-panel , exact callback
https://briareus.koba-nexus.ru/api/auth/oidc/callback .
A public authorize 200 or source-only callback does not prove a real human login.
Admin API keys and Valkey credentials remain protected server-only.

The existing provider database briareus_rauthy and its accounts/OAuth clients
are **not** legacy and must be preserved while fresh Briareus owner databases
are prepared. Owner User-link, verified peer and Authorization adapters remain
unconfigured fail-closed 503 until actual Development acceptance; do not
mistake a synthetic local ASGI Permit for real Rauthy/Cedar/MCP access.

## Dedicated service credential for Rauthy management

Rauthy Admin has the key record briareus-panel-api with only Users read,
create, update; Groups read and Roles read. No secret has been created or
installed yet. The operator must generate the API Key secret once and put it
in the approved protected secret store. Configure the existing Control Panel
API application variable RAUTHY_ADMIN_API_KEY as a reference to that secret.
Never put a plaintext key in Git, JavaScript, browser output or logs.

The server-only RauthyAdminClient uses Authorization: API-Key name$secret,
the fixed Docker DNS briareus-rauthy:8080, no redirects, no environment HTTP
proxy and time-limited private requests. GET /auth/v1/users verifies the
Users:read permission without returning any user PII or the credential.
An absent API Key leaves this feature unconfigured; there is no fallback
to the browser administrator session or self-issued Briareus permissions.
No public user-management route is mounted without current operator and
Platform membership verification.

Until operator-generated key material has been bound and the exact live
Rauthy service request has succeeded, this is source-only, not real
service-to-service acceptance. OAuth client_credentials is a separate
service-to-resource identity mechanism, not the Rauthy Admin REST API Key.

## Invalid private service credential must not crash public API

A malformed or missing Rauthy Admin service credential now disables only that
optional private adapter, not the entire Control Panel API application. The
provider itself validates credential content and rights during a private
Users:read request; local validation only rejects unsafe HTTP header bytes.
The server-held state distinguishes unconfigured, invalid_credential and
configured_unverified without exposing secret bytes or a public admin route.
This does NOT establish Rauthy API Key acceptance; it requires a real upstream
probe returning HTTP 200 after the protected shared key resolves.

## Coolify v4.4.6 Compose parser: preserve the Rauthy API Key as a reference

The correct input for both `services/api/docker-compose*.yaml` is the
**simple** `${RAUTHY_ADMIN_API_KEY}` expression, not the optional-default
form `${RAUTHY_ADMIN_API_KEY:-}`. Rauthy requires the original full
service API Key as a protected runtime credential, with the literal dollar
separator. Base64 encoding of its credential format is not required.

The exact upstream Coolify v4.4.6 parser
(`bootstrap/helpers/parsers.php`, `applicationParser` and its legacy
variant) branches on `replaceVariables`: simple `${VAR}` references are
preserved in generated Compose and resolved by Docker from the runtime
`.env`. Defaulted `${VAR:-}` references instead assign the database
value into the generated Compose `environment:` map (lines near 1716 and
3049), then resolve `{{environment.KEY}}` to its plaintext Shared value.
That value can contain `$` and is passed into a subsequent Compose
interpolation, causing a warning that prints the suffix as the missing
variable name and causing truncated credentials at runtime.

Coolify `app/Models/EnvironmentVariable.php` properly surrounds
`is_literal` values with single quotes for the generated `.env` file.
But those quotes cannot protect a separate plaintext copy injected into
the generated Compose YAML. This explains why Literal was enabled yet
insufficient on the defaulted-reference code path. The documented simple
reference avoids the second plaintext YAML injection while retaining the
original credential and ordinary provider authentication.

Production/Preview `RAUTHY_ADMIN_API_KEY` Application bindings stay
runtime-only and refer to the approved protected Shared variable. No key
is ever put in Git or public API output. Past Rauthy Admin API Keys whose
fragments reached deployment logs must be revoked and rotated. Validate
with a new protected key and a real server-side GET `/auth/v1/users`:
HTTP 200 means accepted service-only Users:read; 401/403 is not accepted.
Before redeployment, confirm there are no other raw secret copies or
stale custom generated Compose values. Do not change Rauthy `ENC_KEYS`
or External Services database, volumes, or unrelated credentials.


## Browser OIDC code+PKCE login (Backend source slice)

**Public API routing (current):** `GET /api/v1/auth/me`,
`/session`, `/config` and other login/logout functions use `/api/v1/auth/*`.
Project-bound resource management uses `/api/v1/agent-sessions`,
`/api/v1/approvals`, `/api/v1/catalog` and `/api/v1/files/read`, not a nested
auth segment. Both use the same version root `/api/v1`.
`GET /api/v1/auth/authorize` is the optional code/redirect diagnostic
entry; `POST /api/v1/auth/start` is native Rauthy Init. The **only**
legacy-shaped route is `GET /api/auth/oidc/callback`, pinned to the exact
previously registered OAuth redirect. Rauthy client migration to a future
versioned callback is an independent operator task; do not replace the
registration with a guessed URL or leave a silent redirect fallback.
Frontend must consume the v1 API in the same integration release. A request
to `/api/auth/native/*` or old `/api/auth/oidc/session` will not work.


Routes added under the same public Gateway-managed /api/* path:
- GET /api/v1/auth/authorize: fetch trusted Rauthy discovery, generate S256 PKCE, cryptographic state/nonce, atomically reserve a five-minute private Valkey transaction, set Secure/HttpOnly/Lax __Host transaction cookie, and redirect to the upstream authorization endpoint;
- GET /api/auth/oidc/callback: require exactly one matching state and code, atomically consume state once (GETDEL), exchange authorization_code using private verifier, validate real signed Rauthy ID token/JWKS/issuer/audience/nonce, issue opaque Secure/HttpOnly/Lax session cookie backed by a short-lived Valkey record, then return to /panel/;
- GET /api/v1/auth/session: return only the verified external Rauthy subject, issuer and client, with platform_membership_verified=false and permissions=[]; NEVER substitute for real Platform /me or internal Authorization proof;
- POST /api/v1/auth/logout: same-origin-only, revoke the Valkey session before clearing cookies. This is local BFF logout; provider-wide Rauthy SSO logout requires separate upstream integration.

Callback URL is the confirmed same-origin Gateway route
https://briareus.koba-nexus.ru/api/auth/oidc/callback .
The OAuth client must be a real *public* Rauthy client, configured with the
Authorization Code flow and S256 PKCE, exactly that callback and the actual
registered client ID. Neither dummy credentials nor login-only Rauthy
identity imply Briareus Platform Team/Project membership.

Transactions and sessions use the existing password-protected internal
briareus-valkey:6379 service with key namespace briareus:panel:oidc, atomic
SET NX and GETDEL, 300-second transaction TTL and at most 900-second session
TTL, bounded by signed ID token expiry. No access token or IdP password is
stored in browser cookies. Valkey is never the durable grant/revocation
authority for MCP actions. Logout fails closed when session deletion cannot
be confirmed. Gateway, Rauthy and other stacks remain independently deployed.

The owning Dev Control Panel API adds runtime-only variable
OIDC_SESSION_VALKEY_PASSWORD; this is a **secret** and must be bound to an
operator-owned protected Development Shared reference to the existing Valkey
credential, not copied from Rauthy/Admin or written in Git. The two other
variables OIDC_ISSUER and OIDC_CLIENT_ID are nonsecret; they must be set
*together* only after actual Rauthy client registration. If any dependency
is unavailable, /health/live remains available and new OIDC login endpoints
return 503 (fail closed). The retired legacy first-user API is absent (404);
it is not an authentication fallback.

Source/CI alone does not prove browser sign-in: activation requires a real
OIDC client, runtime Valkey credential, Rauthy authorization_code callback,
valid cookie session and explicit Platform-owned membership integration.

## Existing approved Development configuration drives native-first-factor

The native first-factor and original first-Files resource are selected solely
from the existing configured public Rauthy issuer/client and protected Valkey.
No new operator ENV flags were approved or retained in Compose. Missing
provider/Valkey remains HTTP503; an unregistered Files resource causes a
fail-closed provider denial (no unscoped retry). Public Rauthy requests use
CA-verified HTTPS, exact pinned client/callback and one Host/Origin. The local
self-signed certificate remains a separate explicitly injected test mode.
Deployment must independently qualify the client Files grant, current user,
real HTTPS, owner authorities and allowlisted Dev cutover. See
[native first-factor](native-login.md) for token/MFA/cancel details.

## Resource-bound first-Files credential (local integration)

The optional server-selected resource intent, original PKCE transaction,
private bearer escrow and exact token-purpose checks are defined in
[Resource-bound OIDC](oidc-resource-intent.md). Source-injected identity-only login
remains available without a resource for separately approved local cases. Native Init preserves that same intent,
but no password/MFA endpoint or public Files operation is activated by it.

## Cookie-to-Platform current User: new Backend owner contract (source only)

`GET /api/v1/auth/me?project_uuid=<canonical UUIDv4>` is the exact-current
Project variant. It uses a separately signed Project-bound private delegation,
returns exactly the selected accessible Project and at most its owner Team,
and never falls back to enumerating the first 100 memberships. Duplicate,
unknown or noncanonical query parameters reject with 422. Ordinary `/me`
remains bounded navigation inventory; it is not an unbounded Project listing.
Every Project-scoped AgentSession, approval and Catalog route now uses the
same exact source, including commands decoded from JSON. Adapters must provide
`resolve_project` and `signed_project_delegation`; missing support fails 503
instead of using a subject-only proof or cached browser permission. Current
cookie and owner proof expiry are rechecked after owner I/O. The Platform
owner's [exact Project contract](../platform/README.md#exact-project-membership-without-inventory-enumeration)
owns the SQL and membership semantics.

`GET /api/v1/auth/me` authenticates the existing opaque, Secure/HttpOnly
Rauthy browser cookie. It does **not** read a browser-provided bearer, User UUID
or Rauthy Group as Platform authority. It requires a separately injected
`CurrentPlatformUserSource` that independently resolves the exact signed
issuer+subject into a **current** enabled Briareus User and owner-verified Team/
Project memberships. This source is NOT configured in the default release.

When a current proof exists, HTTP 200 returns:

```json
{
  "authenticated": true,
  "authority": "platform",
  "rauthy": {"issuer": "https://briareus.koba-nexus.ru/auth/v1/", "subject": "<rauthy-sub>"},
  "user": {"id": "<Briareus-User-UUIDv4>", "role": "user", "enabled": true},
  "teams": [{"id": "<Team-UUIDv4>", "version": 1, "owner": false}],
  "projects": [{
    "id": "<Project-UUIDv4>", "version": 1,
    "owner": {"kind": "team", "id": "<Team-UUIDv4>"},
    "permissions": ["use_resources"]
  }],
  "expires_at": "<current-short-lived-proof-expiry>"
}
```

IDs in this example are placeholders, **not fabricated live accounts**.
An operator role is only accepted from a current Platform proof, never from
the Rauthy ID-token or public session. Team members can use resources, but
only current Team owners or verified Platform operators may approve elevated
AgentSession scopes. Project permissions are **not** resource-specific MCP
grant decisions: those are separately enforced by Authorization/Cedar.

Error payload `{"error":{"code":"..."}}` with no-store headers:
- 401: `OIDC_SESSION_REQUIRED`, `OIDC_SESSION_EXPIRED`;
- 403: `PLATFORM_MEMBERSHIP_REQUIRED`, `PLATFORM_MEMBERSHIP_NOT_CURRENT`;
- 503: `OIDC_SESSION_STORE_UNAVAILABLE`,
  `PLATFORM_MEMBERSHIP_SOURCE_UNAVAILABLE`,
  `PLATFORM_MEMBERSHIP_PROOF_INVALID`.

A proof expires within 30 seconds, is issuer/subject-bound, and lists at most
100 Teams and 100 Projects. The actual browser session expiry returned by
`/api/v1/auth/session` and `/me` is bounded by the shorter of the signed
ID-token lifetime and the 900-second Valkey TTL. Old
`GET /api/platform/me` remains the unrelated **legacy bearer** path.

`services/platform/src/projects/_oidc_membership_projection.py` prepares an
independent SQL projection from **only** `briareus_platform`, accepting a
preverified external Rauthy subject→internal User binding. No such durable
binding or authenticated private caller transport is yet provisioned or
mounted. The default returns 503 for a signed-in user instead of granting
self-provisioned privileges. This is a **source-only adapter**: do not show
a working Platform session or approval UX until the genuine Rauthy User link,
provider Admin/Users scope, current Platform proof, and authorized Dev browser
flow are observed.

## Control Panel AgentSession BFF: locally staged, not live owner operations

`services/api/src/control_panel_api/_oidc_approvals.py` defines an
independently injectable `ApprovalManagementPort`; the **default is None**
and never permits management mutations. The BFF shares the same verified
Rauthy browser cookie + ≤30s current Platform User/Team/Project proof as
`GET /api/v1/auth/me`. A response from the upstream OAuth issuer
alone never permits a project operation.

- `GET /api/v1/approvals?project_uuid=UUIDv4`: up to 50
  Authorization-owner-scoped requests, with requester/approver, Project,
  AgentSession, status `pending|approved|rejected`, revision, requested
  operations/resources, expiry and source-confirmed `allowed_actions`.
  Non-approving members see **only their own** request entries.
- `POST /api/v1/approvals`: body
  `{project_uuid,agent_session_uuid,operations:[...],resources:[{hand,tool,action,resource:{kind,id}}],seconds:1..300,expected_grant_revision:int>=1}`;
  returns HTTP 202 only after a real owner request is durably recorded.
- `POST /api/v1/approvals/{approval_uuid}/resolve`: body
  `{project_uuid,approve:boolean,expected_approval_version:int,allowed_operations?:[...]}`;
  current approver rights must be verified again by the Authorization
  owner. No self-approval or expansion beyond the exact request.
- `POST /api/v1/agent-sessions/{session_uuid}/revoke`: body
  `{project_uuid,expected_grant_revision:int}`, returns the next
  confirmed revoked session revision only after an authenticated durable
  Authorization-owner transaction.

Every mutation requires exactly `Origin: https://briareus.koba-nexus.ru`,
`Content-Type: application/json`, and equal canonical UUIDv4 values in
`Operation-UUID` and `Idempotency-Key` headers. The owning
Authorization port must independently check exact signed caller/peer,
Project, session, action/resource, approval eligibility, original idempotency
record and revision: BFF role checks cannot replace those facts.
Rauthy API Keys and OAuth credentials never reach the browser.

Error JSON `{"error":{"code":"..."}}` and no-store:
401 missing/expired OIDC cookie; 403 current Project/role or source-auth denial,
including `APPROVAL_ORIGIN_REQUIRED`; 409
`APPROVAL_REVISION_CONFLICT`; 422 invalid operation identifier/body/scope;
503 `APPROVAL_OWNER_UNAVAILABLE` or invalid owner response. Existing
provider outage and missing authenticated Platform source remain 503.

Current acceptance is **SOURCE/LOCAL_ASGI with synthetic trusted owner
ports only**. The release has no trusted Platform subject-link or
Authorization management transport wired, and must return 503 rather
than invent a real approval. No UI should claim an actual approved or
revoked grant before the owner-backed integration is working.

## Private Platform member source (local integration milestone)

`PrivatePlatformCurrentClient` calls the **fixed** private URL
`http://briareus-platform:8000/internal/v1/platform/oidc/current` using
a connector-injected authenticated transport (`mtls` or `unix-peer`) and
one short-lived signed subject delegation scoped to the independently
verified Rauthy cookie issuer+subject. A plain header from the browser,
an in-network TCP connection or a self-asserted User UUID is not authority.
It rejects redirects, excessive/non-JSON payloads, untrusted peer proof,
foreign Rauthy subject, stale User proof and incorrect Project membership
DTO before returning `ResolvedPlatformUser`. Unlinked users are denied;
unavailable peer/owner credentials fail 503.

The private source and the Platform owner route both **remain unconfigured**
by default. Local synthetic signed-peer ASGI probes are source evidence and
cannot be promoted to real mTLS/Unix peer acceptance. Neither BFF nor browser
reads Platform database tables. Real peer issuance and fresh Rauthy Users
status are independently required before enabling User/Project access.

## Private Access approval listing (local-first read integration)

The server-only PrivateAccessManagementClient now consumes the exact fixed
Authorization route POST /internal/v1/authorization/approvals/list using an
independently injected mTLS/Unix service peer and short-lived signed actor/
Project delegation for audience briareus:access. It never reads Access SQL or
uses Rauthy Admin API credentials from the browser. The upstream owner checks
current Rauthy actor, peer identity and Platform Project membership and emits
only the bounded Project-scoped approvals list. The BFF validates every owner
record's actor/Project scope, versions, expiry and allowed-actions, and refuses
to expose another requester's details to ordinary members.

Backend local two-owner ASGI checks prove that a synthetic trusted Access
peer's current own-DB approval result travels over the private route and
decodes to the public BFF ApprovalSnapshot. A missing writer remains 503.
The lower-level PrivateAccessManagementClient remains read-only; writes
use the separate PrivateAccessManagementWriter through
PrivateAccessManagementBundle, described below. This is not a live read or
write with a real signed Rauthy token or mTLS certificate; the default BFF
still has no trusted Access peer and denies all operations.

## Private Access command client and combined BFF port (local)

PrivateAccessManagementWriter now has fixed private owner paths for request,
resolve and revoke with canonical JSON bodies and matching operation UUID
headers. A separately injected TrustedAccessWritePeerPort signs a fresh
delegation bound to the exact request SHA256, Rauthy actor, current Project,
action, operation UUID, expiry and service audience. No user supplied host,
admin credential, bearer or redirect enters the transport.

PrivateAccessManagementBundle combines existing owner-validated list reads
and mutation writes under the same independently verified private peer.
Every owner response is bounded, strictly parsed, and checked for exact
Project, actor, resource, version and approval/revoke status before any
public BFF success. Unconfigured or unreachable writer responds 503.
The default running Panel still has approval_source=None; no live Access
write claims are made from synthetic source checks.

PrivateAccessManagementWriter now checks response lifecycle and signed input
parity, not just HTTP200: a pending request must have revision 1, no resolver
and no issued session; approved/rejected receipts require a separate current
resolver and revision at least 2; approved MUST have a distinct issued child,
rejected MUST NOT. Original request operations and exact resource-effect scopes
must match the returned request receipt. Resolve requires precisely
`expected_approval_version + 1`; revoke requires precisely
`expected_grant_revision + 1`. Duplicated JSON keys at any nesting depth,
unknown operation/resource vocabularies and wrong actor/Project are unavailable,
not a successful command. All private attestation and HTTP receive work is
bounded by the SAME twelve-second monotonic deadline; if an owner commits but
the reply is lost or late, return 503 and require later state reconciliation
or an explicitly requested replay of the ORIGINAL operation UUID, never an
automatic second command. Original actor, Project and peer proofs must remain
valid throughout. Current regression cases cover contradictory owner receipts,
ambiguous JSON, shifted revisions and both signer/HTTP delays; they exercise
synthetic owner credentials only.

### Rauthy-only write cutover and unconfigured routes

New separate AccessRauthyCommandService accepts the existing BFF request,
approve/deny and revoke DTO without any legacy Identity owner signature,
cross-DB join or copied password. Its trusted actor must be bound by a real
Rauthy+Platform+private peer attestor to the exact Project, action, operation
UUID, short-lived privilege and independent current owner status. The
Authorization owner persists the command under its own SQL idempotency
ledger, with encrypted replay response and transactional audit/outbox.

PrivateAccessManagementWriter carries an independently signed exact JSON
body SHA-256 and canonical operation UUID headers. The combined
PrivateAccessManagementBundle exposes the same typed public management
adapter only when an actual signed peer factory is supplied. No default
credentials, signed actor, or service transport is installed. Public
unconfigured GET/POST approval and revoke paths now consistently respond
HTTP 503 (not a misleading 404) if the provider or browser session store
has not been configured; retired Identity login/register remain 404.

### New normal AgentSession creation (source-only)

POST /api/v1/agent-sessions accepts Project UUID, elevation_policy
fixed/requestable and optional canonical label; it requires a verified OIDC
cookie, current Platform resource membership, Origin/JSON, matching canonical
Operation-UUID/Idempotency-Key and a trusted private Access writer. A real
owner-created session returns HTTP 201 with UUID, revision 1, active status,
24-hour maximum expiry, files.read and project.metadata.read operations,
and NO resource-specific grants. Unconfigured authority returns HTTP 503;
no protected MCP effect follows automatically from opening a session.

### Current AgentSession inventory and revision (local-first DTO)

`GET /api/v1/agent-sessions?project_uuid=<UUIDv4>` returns
`{items:[...]}`, at most 50 owner-confirmed sessions. It requires the
same current Rauthy browser cookie, short-lived current Platform
subject/User/Project proof, and `use_resources` **OR**
`approve_agent_session` rights on that exact Project. A current resource
member can see only their OWN sessions; a separately verified Project
approver may view its Project's sessions. The independent Authorization
owner attestor must recheck the Rauthy User, Project, approver role and
private service peer. The browser's `/api/v1/auth/me` is not itself
Access owner proof.

Each item is typed as:
`{session_uuid,project_uuid,created_by_user_uuid,revision:int>=1,
status:"active"|"expired"|"revoked",is_elevated:boolean,
elevation_policy:"fixed"|"requestable",hard_expires_at:ISO8601,
operations:[...],resources:[{hand,tool,action,resource:{kind,id}}],
allowed_actions:["revoke"]|[]}`. The owner reads current
`briareus_access.sessions.agent_sessions` and returns only a Project-scoped
current grant revision, exact stored operations/resources and expiry.
An expired session remains explicitly `expired`, never falsely
`active`; ordinary members are never told they can revoke, and
`allowed_actions:["revoke"]` requires a current independently attested
Project approver and an unexpired active session. This action hint is NOT
a transferable permission or a substitute for the signed, version-fenced
revoke command. Frontend uses `revision` as the `expected_grant_revision`
selector for request/revoke, and must refresh after any write/conflict.

`GET /api/v1/approvals?project_uuid=<UUIDv4>` now admits
`use_resources` OR `approve_agent_session`, but owner-side filtering
and signed proof still ensure ordinary members see ONLY their own
requests; only verified current approvers see the Project queue. A
requester cannot approve their own request. Unauthenticated cookie=401,
foreign/disabled Project=403, and absent private source/invalid owner
response=503. The release still injects `approval_source=None`;
local synthetic owner ASGI checks are not a deployed current grant read.

## Pinned Rauthy native login response states (SOURCE decoder only)

The owner requests a native Briareus email/password/MFA form without a
hosted Rauthy redirect. Deployment verified upstream sebadob/rauthy
v0.37.1, SHA ce35a70fbc43203b1a6910d3db30389228825f46.
GET /auth/v1/oidc/authorize establishes/reuses provider session and
HTML-supplied CSRF; POST /auth/v1/pow issues one-time proof of work
(upstream solves it with a WASM worker); POST /auth/v1/oidc/authorize
requires the same provider session cookie, CSRF header, solved proof,
exact client, redirect, PKCE, nonce and state. OTP/WebAuthn,
account-update, Terms acceptance, force-MFA and throttling have distinct
branches, not interchangeable successful login states.

control_panel_api._rauthy_native_protocol.interpret_native_authorize
is a PRIVATE pure source-pinned decoder for one such POST response. It
returns oauth_callback_pending for 202 with a fixed Briareus callback
origin, original state and upstream issuer (iss), plus OTP/WebAuthn/ToS
pending, account_update_required, client_mfa_required, rate_limited,
credentials_rejected or request_rejected states. Sensitive OAuth code,
MFA code and ToS continuation are held in SecretStr, not logs.
The decoder rejects duplicate JSON fields, malformed challenge kinds,
ambiguous Location headers, arbitrary redirects, duplicated callback
query parameters, missing/mismatched signed issuer or state, unknown
statuses and invalid rate-limit windows. Pinned Rauthy AuthCode source
builds the callback with three query fields: code (64 alphanumeric),
state and iss (issuer).

202 is NOT an authenticated Briareus session. After Rauthy first factor,
the Backend must atomically consume its original state/PKCE transaction,
redeem the real OAuth code, verify signed ID-token issuer/audience/nonce,
create the private Valkey opaque session, and independently resolve the
current Platform User/Project. MFA and ToS pending must NEVER authorize
a Cedar grant or issue an OIDC session.

This decoder does NOT relay a password or expose a public endpoint.
At this decoder-only checkpoint, the credential route was absent. The current
[native contract](native-login.md) implements first-factor escrow/transport,
replay/cancellation and signed code completion, while unsupported MFA/ToS states
remain unauthenticated. A genuine full native user flow is a separate acceptance
boundary, not supplied by the decoder. Native source probes
classified all expected status branches and rejected more than sixteen
malicious or ambiguous responses; this is parser evidence only.

### Elevation requests require complete scoped resources

POST /api/v1/approvals now rejects request operations unless each
requested Hand action has at least one matching exact resource entry.
For example files.read needs a concrete Files workspace_path selector;
an action-only request has no enforceable Hand resource and responds
HTTP 422 APPROVAL_SCOPE_INVALID. Access owner independently normalizes
and repeats this coverage check at approval, requires an actual short-lived
Resource Catalog owner proof for every resulting scope, and never expands
the approved subset. A private owner 422 is preserved as the public 422,
not concealed as an authorization outage 503. Existing Rauthy/Platform
and session revision checks remain mandatory; this is source-only and
does not enable an elevated effect.

### Control Panel API application/Docker service naming (coordinated release)

Briareus does NOT have a separate management Admin API application. Its
existing approved Coolify application (UUID rf5gaooeijfzyiizgaw9kznr)
is the Control Panel API. The Backend-owned services/api Compose files
now use the canonical service name and Docker network alias
briareus-control-panel-api, without the deprecated
briareus-admin-api alias. The environment key RAUTHY_ADMIN_API_KEY
specifically refers to Rauthy's **private provider** Users/Admin REST API,
not a second Briareus management application; it stays server-side.

**Deployment integration dependency:** Runtime owns Gateway's fixed
upstream and must change both its /api routing and private target
classification to briareus-control-panel-api:8000 simultaneously with this
Backend Compose cutover. The legacy deploy/admin-api source directory
and root deploy/APPLICATIONS.json metadata belong to separate release
owners; neither is an authorization to create a new Coolify app or deploy
Backend service alone. The coordinated release must retain the approved
existing API application UUID, healthy /health/live and unchanged public
/api/* origin. An isolated rename before Gateway changes is explicitly
NOT a safe Dev deploy, even if local Compose parsing succeeds.

### Read-only Catalog metadata on the verified Platform cookie

GET /api/v1/catalog?project_uuid=UUIDv4&kind=integration|variable
is available as a source-typed Control Panel API route. It requires an
existing valid Rauthy cookie and a fresh independently verified Briareus
Platform User/Project use_resources grant, then a second authenticated,
signed and short-lived private Resource Catalog owner read. It returns
the same bounded non-secret {items:[{resource_uuid,kind,owner,key,version}]}
DTO described in docs/services/resources/README.md. BFF rechecks that
every Project resource belongs to that exact Project and every Team
resource belongs to the verified *owning* Team for that Project.
An arbitrary Team membership or injected foreign row cannot substitute.

PrivateCatalogMetadataClient has a FIXED Catalog service destination and
requires an independently authenticated mTLS/Unix peer with a short-lived
Rauthy actor+Project+kind delegation before it returns one metadata row.
The public route is 401 for an absent/expired browser cookie, 403 for a
foreign Project or nonresource user, and 503 for missing private owner
source or malformed/overbroad reply. No cacheable grants are returned.
Default API is unconfigured/503; local two-app ASGI probes with synthetic
trusted owner checked 200 own/Team metadata, 401 missing cookie, 403
foreign Project, and 503 missing/foreign owner. This is NOT a new
permissions endpoint, Resource Catalog writable API, or working
resource-specific elevation picker: the executable Hand selector must
still come from Runtime's exact tool/Resource owner resolver.

### Browser and Platform proof expiry during private owner IO

All cookie-bound Access approval/session routes and the Catalog metadata
route revalidate their effective short-lived caller proof **after** a
potentially slow private owner request and before returning a successful
public response. The Access BFF takes the earlier of actual HttpOnly
browser-session expiry and fresh Platform User proof expiry. Catalog
likewise rechecks both original expiries after bounded source validation.
If either expires while waiting on Access/Catalog SQL or private network,
the response is HTTP 503
PLATFORM_PROOF_EXPIRED / CATALOG_PROOF_EXPIRED, not a stale 200/201/202.
For a mutation this result is deliberately an **uncertain outcome**:
the Authorization owner may have durably committed it before the
browser proof expired. The browser must refresh current session/grant
state and never auto-repeat an ambiguous idempotent write as a new
operation UUID; signed owner CAS/idempotency remain authoritative.

Source-level fake owner tests delayed the private response beyond the
remaining browser-cookie TTL and confirmed neither Access nor Catalog
returned a cached current-user grant. The existing current sessions/
approvals two-owner synthetic ASGI positive/negative probes still pass.
This does not provide a real Rauthy Provider logout/push revocation
feed or a live mTLS/SQL/Dev acceptance claim.

## MVP-first Rauthy Userinfo active-user gate (source code integrated locally)

A real OAuth code+PKCE callback may return a validly signed ID token for
a Rauthy User who was subsequently disabled, deleted or whose access
token was revoked. The BFF now REQUIRES a second server-only current
Rauthy Userinfo check **after** verifying signed issuer/audience/nonce
and **before** creating any Valkey browser cookie:
1. Fetch the verified issuer's OIDC discovery document and require
   authorization, token, JWKS and Userinfo URLs to be the EXACT expected
   Rauthy /auth/v1/oidc/{authorize,token,certs,userinfo} endpoints at the
   SAME trusted HTTPS issuer authority, with no foreign Host, URL
   parameters or redirects.
2. Send the actual upstream access token as a protected server-only
   Bearer to the pinned Userinfo endpoint; no Userinfo token or provider
   PII reaches a browser, Project database or public log.
3. Rauthy **v0.37.1** src/service/src/oidc/userinfo.rs verifies bearer
   claims, checks that the token has NOT been revoked, loads current
   User by its signed sub, and explicitly rejects disabled/expired Users
   even if the bearer has not expired. Require HTTP 200, bounded JSON,
   no duplicate identity fields, and exact sub/id equality with the
   separately verified signed ID-token User. All 401/403 and mismatches
   return 401 without creating any Briareus session; upstream failure
   fails closed 503.
4. Require the Rauthy native callback's exact {code,state,iss} query
   (no missing/duplicate/foreign fields), and compare callback iss
   with independently signed ID-token issuer before saving any cookie.
   A successful userinfo check remains **Rauthy identity only**,
   with Platform membership_verified=false and permissions=[] until
   the separate current Platform User/Team/Project owner proof arrives.

This provides a standards-backed current User verification for a login
callback **without an Admin Users:read API key**. Subsequent Project/me,
signed access-session creation, authorization and revoke still require
a fresh trusted Platform User link and current owner privileges; a
one-time Userinfo check cannot replace that authority, especially if
the User is disabled after login. Source-based local synthetic signed
RSA JWT + mock Rauthy Userinfo callback tests passed 303/200 and
single-use callback 401, rejected disabled Userinfo 401, wrong ID/subject,
duplicate JSON identity field, mismatched callback issuer, and malicious
discovery token endpoint without session issuance. No real Dev user,
provider Users status API scope, physical SQL or mTLS E2E accepted yet.

### Browser-cookie expiry never exceeds OAuth access-token expiry

After fresh provider Userinfo validation, the signed ID-token expiry is
additionally bounded by the upstream token-response expires_in measured from
BEFORE the token request, not restarted after Userinfo/JWKS I/O, before
writing any private Valkey browser session. A resource-bound login is also
bounded by the verified resource access-token exp. The actual browser-cookie
Max-Age is therefore at most the minimum of token lifetimes and the
existing 900-second cap. A short-lived Rauthy user access token cannot
leave a longer-lasting Panel identity cookie. Token material is not
stored in the browser, and silent refresh is not introduced.

## Isolated TLS loopback OAuth callback for disposable native Rauthy

For the FIRST real local user login, the disposable Rauthy sandbox must
NOT register the live existing Development callback for its throwaway
OAuth client. That could redirect sandbox OAuth state/code to a deployed
Dev service. The Backend now supports a test-only source-injected
fixed browser origin:

- Exact local issuer https://localhost:18444/auth/v1/ and
  client briareus-local-panel, both checked against the explicitly
  injected local RauthyOidcAdapter.
- Only accepted test browser origin https://127.0.0.1:18446, injected as
  test_only_local_origin on create_control_panel_api(provider=provider,...).
- Exact redirect/token-exchange URL:
  https://127.0.0.1:18446/api/auth/oidc/callback.
- Exact final panel URL: https://127.0.0.1:18446/panel/.
- Local-only Host: 127.0.0.1:18446 required on OAuth start, callback,
  logout and state-changing AgentSession/approval requests. Origin must
  equal https://127.0.0.1:18446 for same-origin POST writes.
- Existing __Host- Secure/HttpOnly/SameSite=Lax transaction and session
  cookies retain their security properties.

This is a FIXED source-injected constructor argument, NEVER an HTTP
parameter, generic ENV/tenant URL override, wildcard, arbitrary
discovery URL or user-supplied callback. Arbitrary origins, HTTP
downgrade and real Dev issuer/client with local callback fail closed.
The DEFAULT app retains canonical public HTTPS origin
https://briareus.koba-nexus.ru and the existing approved public
callback. The isolated test-only Runtime/TLS listener MUST be bound to
127.0.0.1, preserve exact Host/Origin, route only approved fixed
/api/v1/auth paths to local BFF and /panel to local UI, and never
redirect sandbox tokens to public Dev. Backend DOES NOT mint/provision
a TLS certificate or local Rauthy OAuth client.

SOURCE LOCAL validation: temporary signed RSA JWT + fake Valkey Rauthy
ASGI scenario verified local callback, state/PKCE S256, Userinfo, 303
Panel and 200 identity, callback replay 401 and no Platform grants.
Separate synthetic owner ASGI tested local AgentSession write Origin/
Host positive and wrong Origin/Host 403. Production callback Userinfo/
issuer regression remained green. These are NOT real Rauthy registered
callback, actual TLS browser/MFA, physical PostgreSQL, private peer or
live Development Cedar/Files acceptance.

### Local callback origin also fences session and current-user reads

The fixed disposable 127.0.0.1:18446 HTTPS browser-origin check is
applied to **all** cookie-bearing BFF operations, including GET
/api/v1/auth/session, /me, current AgentSession/approvals/Catalog and
all POSTs. A local Rauthy test identity, even if an opaque ticket is
accidentally presented with a foreign Host, must never cross into the
public Dev Host context. A wrong local-test Host denies with HTTP 403
before any Valkey ticket lookup or Platform SQL proof. This extra
fence applies only to explicitly injected disposable local provider;
the canonical public existing Dev paths retain their original
configured Host/Origin and session semantics.

### Opaque browser session realm pinning across configuration changes

A Valkey browser ticket may outlive a deployment that changes OIDC issuer
or client ID. The browser session route now verifies its stored issuer
and client ID against the CURRENT configured Rauthy adapter, not only
expiry. The separate Platform source path checks the same two fields
BEFORE any private User/Project lookup, covering current-user, Catalog
and all AgentSession/approval requests. A ticket from another issuer
or previous client fails HTTP 401 OIDC_SESSION_REALM_MISMATCH, not a
current User or an Authorization grant. This includes the disposable
local issuer; it does not add a new session or permission.

Source-local tests using the real app factory with a valid-looking stale
cookie and a prior issuer or client returned /session 401 and /me 401,
and triggered ZERO Platform owner calls. Existing signed PKCE/Userinfo
and fixed-TLS callback regressions still pass. This is a bounded
configuration-change/replay fence, not provider revocation acceptance.

### Stale realm cookies are actually revoked, not merely refused

A 401 due to mismatched configured issuer or OAuth client now deletes
the corresponding opaque Valkey session ticket and sends a Secure
host-only cookie expiry to the browser. A rapid rollback from the new
provider configuration to the previous provider cannot silently
reactivate that still-unexpired ticket. If Valkey cannot confirm
deletion, the caller receives fail-closed HTTP 503 rather than a
success or an unsupported revocation claim. This applies to both
OIDC /session and all Platform-backed /me/AgentSession paths.
Source-level four-way regression tests covered prior issuer/client via
both API entrypoints and subsequent configuration rollback with
the same ticket: deletion once, expired browser cookie, no Platform
owner lookup, and replay still 401. A local fake Valkey is not real
IdP logout/revocation propagation; future real source acceptance
must prove the equivalent against current Dev Valkey.

### Fixed browser-origin policy has one source of truth

The canonical Control Panel public HTTPS origin and disposable native
Rauthy test-only callback/Host/client/issuer are centralized in the
private _oidc_origin_policy module. OAuth callback, session, current
Platform User and approval/AgentSession write validation consume the
same fixed source values. No new configurable callback, HTTP credential
mode, tenant override, or unsigned browser Host is introduced.

This avoids future security regressions where a test-only origin change
is applied to callback but silently omitted from a cookie-backed
read/write endpoint. A typed pure source probe rejects arbitrary
loopback URLs, plaintext scheme, production issuer with test callback,
and incorrect OAuth client. Existing local ephemeral signed
code+PKCE/Userinfo callback, Host/Origin write and normal public
callback regression probes remain unchanged and passed. This is
maintenance/source-local evidence, not actual Dev login or provider
credential acceptance.

## Historical Init milestone — local real Rauthy/Valkey

The native login implementation has its own authenticated-control-plane
entrypoint, POST /api/v1/auth/start. It is enabled only by a trusted
source-injected PinnedNativeRauthyInit with the disposable local issuer
https://localhost:18444/auth/v1/, the exact local TLS public certificate,
and an already configured private Valkey. It is NOT enabled by a browser
header, ENV origin override, provider discovery, or the public default app.

Only same-origin POST, the fixed local Host and the literal JSON body {}
are allowed. Rauthy's version-pinned POST /auth/v1/oidc/session is invoked
ONCE for this attempt using a fresh non-shared TLS-verifying HTTP client,
without following redirects or trusting system proxy variables.
The official 201 Init JSON must have state Init, a bounded expiry,
a 32-character CSRF and one __Host-RauthySession Secure+HttpOnly+Lax
cookie. Provider cookies are not forwarded to the browser.

The Backend creates independent S256 PKCE/state/nonce through its
existing signed OIDC adapter and stores issuer, client, verifier,
nonce, CSRF and the exact Rauthy session cookie under a separate
short-lived Valkey native-init key using NX. Its expiry is no longer
than 300 seconds or the provider/OAuth expiration, whichever is earlier.
HTTP 201 returns only
{stage:"first_factor_required", authenticated:false, expires_in:N}
and a Secure HttpOnly __Host-briareus_native_transaction cookie.
NO user identity, MFA grant, Rauthy cookie or token is returned. An
unconfigured app always responds 503. Repeat start invalidates a prior
pending transaction; logout deletes pending native-init state from
Valkey and expires that browser transaction cookie.

This endpoint does NOT yet submit a password, solve provider PoW,
continue OTP/WebAuthn, redeem a native OAuth code or issue a signed
login. Those phases MUST use the same one-time private transaction
and the exact upstream CSRF+PoW+MFA continuation before relying on
existing signed ID-token/Userinfo verification. A native init 201
is not Rauthy User authentication, Platform member or Cedar Permit.

REAL LOCAL validation used the running disposable Rauthy 0.37.1 via
strictly verified localhost TLS and the running password-protected
local Valkey 9.1.2: provider Init201, Backend BFF Init201,
one bound private NX transaction with no secret fields in public
response, pending identity /session401 and logout204 with
server-side transaction deletion. Additional hostile Origin,
malformed body and default-unconfigured failures were verified.
No Dev, physical Platform/Access PostgreSQL, real password/MFA
or protected Files executor has been accepted.

### Native Proof-of-Work challenge after private Init

The second pending-only BFF operation is POST /api/v1/auth/pow with
the same strict localhost Host, Origin, application/json and literal {}
request as native/start. It needs the unexpired Secure HttpOnly
__Host-briareus_native_transaction handle and a matching server-held
Valkey record for the exact issuer and OAuth client. Without current
pending state the endpoint denies 401; wrong Origin/Host/body denies
403. It invokes only the official Rauthy v0.37.1 POST /auth/v1/pow
via a fresh private HTTPS client with pinned test TLS and no proxy.
The one-time public challenge is returned as
{challenge:string,authenticated:false}, no-store. The challenge is not
a solved PoW or password proof; upstream must validate and atomically
consume the client's solved result during the future /oidc/authorize
step. No reusable OAuth code or user grant is emitted.

REAL LOCAL Rauthy HTTP200 and actual password-protected Valkey:
native start201, current session-scoped PoW200, hostile Origin403 and
logout204 with pending key deleted. No first-factor password submit,
OTP/WebAuthn completion, ID token or Platform User was accepted.

### Native Proof-of-Work issuance is single-use per pending transaction

A provider PoW challenge is public but must not be indefinitely
reissued for one unverified native Init session. The scoped
/api/v1/auth/pow BFF now acquires an atomic private Valkey NX
reservation keyed to the original opaque browser transaction before
contacting pinned upstream Rauthy. The reservation is bounded by the
300-second maximum pending transaction window. The owner checks
existing same-issuer/client Init both before and after the reservation
and again after the upstream call, preventing a pending logout/restart
from returning a newly requested challenge. The first accepted call
returns {challenge,authenticated:false}; further same-cookie calls
return HTTP409 NATIVE_POW_ALREADY_RESERVED without making another
provider request. A provider failure burns that attempt's reservation
rather than assuming an unused challenge; the user can explicitly
start a new Init. Starting a new Init invalidates the previous
pending state and reservation; logout deletes both and expires the
pending browser cookie. Once deleted, a request receives HTTP401.

Native unit tests under services/api/tests/test_native_pow.py use
concurrent ASGI calls with a deterministic in-memory Valkey stub:
eight simultaneous callers led to precisely one 200 and seven 409,
one provider call, and cleanup on new Init/deletion. Independent REAL
local Rauthy+password-protected Valkey testing reproduced the same
one-success/seven-conflict result and confirmed post-logout PoW 401.
The PoW challenge still does NOT establish user credentials, solve
the provider's puzzle, bypass MFA, generate an OAuth token or permit
any Platform/Cedar action. Native credential submission remains
disabled until fully verified separately.

### PoW failure/transaction cancellation race regression

A provider timeout/invalid native PoW response burns the Valkey NX
reservation: HTTP503 for the current attempt and HTTP409 on subsequent
same-state PoW calls; the user must start a fresh Init. No assumption
that an upstream challenge was not issued may re-open the reservation.
If the pending state is deleted while the asynchronous provider request
is in flight (for example a concurrent logout), the BFF rechecks the
same issuer/client Init after the await and returns HTTP401 with no
challenge in its response. The native PoW unit suite now includes
explicit deterministic provider-failure and cancellation-during-upstream
race tests in addition to eight-caller concurrency and missing-Init
negative coverage. None of these pre-auth stages issues identity.

### Native pre-auth endpoint readiness is consistent without owner wiring

The source-owned native pre-auth API exposes both POST
/api/v1/auth/start and POST /api/v1/auth/pow as HTTP503 when
the independently injected local Rauthy owner OR protected Valkey
transaction store is absent. A 404 for the PoW route previously
suggested the BFF endpoint was missing or that clients should try
a different, potentially hosted provider endpoint. Neither endpoint
ever treats an absent native owner as a signed login, silently falls
back to hosted Rauthy UI or bypasses the underlying auth source.
Permanent tests exercise an entirely unconfigured default factory
and a source-injected provider lacking its Valkey owner; both entry
points return 503, with no provider credential operation.

### Native challenge decoder contract regression suite (without credentials)

The source-only, version-pinned Rauthy POST /oidc/authorize reply
decoder has permanent tests in
services/api/tests/test_native_challenge_decoder.py. They classify
an exact 202 OAuth redirect for approved same-realm local and Dev
issuer/callback pairs as **oauth_callback_pending** (a provider code
that still requires signed PKCE exchange and Userinfo, NOT an
authenticated Panel session). Exact 200 OTP and WebAuthn challenges,
206 ToS continuation, and valid 429 retry boundaries are explicitly
pending/not authenticated. Negative cases reject foreign or HTTP
callback origins, cross-issuer pairs, duplicated Location headers or
JSON fields, malformed/expired/overlong MFA, and unsupported statuses.
401/403 are never treated as success. No actual password, MFA code,
secret, Rauthy user, bearer or JWT is embedded in these tests.
Combined with native PoW unit tests, the suite tests future BFF
challenge classification while credential submission is still
unimplemented; it cannot serve as real signed-user acceptance.

### Server-private one-time native Init claim (credential continuation prerequisite)

The native Init and PoW transaction has an INTERNAL one-time
OidcBrowserSessionStore.consume_native_init(state, issuer, client_id)
operation. It returns a PrivateNativePending data object with private
SecretStr code verifier, Rauthy CSRF and session cookie. There is no
public route that exposes it and no credential submission or authenticated
User identity is implied.

Valkey GETDEL on the Init key arbitrates concurrent consumers; only one
may read the provider-held session and PKCE material. The PoW reservation
is deleted. An invalid issuer/client, malformed value or missing record
returns no pending proof and burns the transaction, not a reusable login.
The next credential handler must independently verify provider PoW,
CSRF, MFA and the resulting signed ID-token/Userinfo and Platform authority.

Permanent local source tests simulate eight concurrent callers (exactly
one winner) plus wrong-issuer claim and replay denial; secret contents
remain masked in repr. Attempted verification of the new GETDEL method
against the running protected local Valkey was blocked by the tool, so
it is NOT claimed as live Valkey acceptance. Earlier native Init+PoW
real-Rauthy/Valkey HTTP checks remain independently valid.

### Native continuation claim requires a previously issued PoW challenge

The internal one-time native Init claim now requires a separately
reserved native-pow marker from the current transaction. Merely
starting a Rauthy provider Init is NOT proof that the browser has
requested a one-use provider challenge. Both private Init and
reservation are consumed with Valkey GETDEL, so skipping /native/pow
burns the pending session rather than handing CSRF, original
provider cookie or PKCE to a continuation handler. This marker
proves only that PoW was ISSUED; the official Rauthy service must
still validate the client's solved challenge during first-factor
authentication. A missing marker, wrong issuer/client, replay or
expired Init yields no authenticated identity. No credential
submission API or Session Permit is created by this safety gate.

The permanent local suite includes distinct cases for concurrent
one-winner claim, wrong-issuer burned state, Init claim without an
issued PoW marker, provider failure 503/409, and pending logout
during upstream request. Fourteen tests passed, including the
existing challenge decoder. The current new GETDEL claim remains
validated only by local stub execution, not physical Valkey.

## Exact AgentSession refresh and mutation reconciliation

`GET /api/v1/agent-sessions/{session_uuid}?project_uuid=<UUIDv4>`
returns one **flat** current-session object with exactly the same fields as
an item from the existing session list: session/project/creator UUID,
revision, status, is_elevated, elevation_policy, hard_expires_at,
operations, resources and allowed_actions. It performs an exact owner
lookup; absence from the most recent 50 list entries is NOT absence from
Authorization. No pagination scan, guessed revision or cookie-only grant
is used. The shared single/list serializer applies the same bounds,
creator/Project visibility, grant scope and state checks to both APIs.

The browser needs a valid Rauthy-backed opaque cookie and fresh Platform
Project `use_resources` OR `approve_agent_session` permission. Authorization
independently verifies its private peer and current actor: an ordinary
member can read only their own session; a current approver can read Project
sessions. An exact scoped absent/hidden session returns 404
`AGENT_SESSION_NOT_FOUND`, with no distinction between nonexistence and
another member's hidden record. Foreign Project permission is 403,
missing authentication is 401, malformed selector is 422, missing owner
or malformed/overbroad response is 503. An unmounted private route's generic
404 is deliberately a BFF 503, never evidence that a session was deleted.
Every successful/semantic-missing public response is no-store.

After a write with an uncertain result (transport loss, expiry during the
reply, or HTTP503), refresh the exact known session to reconcile current
revision/status. Do NOT infer failure merely from the lost response or
increment a cached revision locally. Retrying the **same** operation must
preserve the original Operation-UUID/Idempotency-Key and entire original
body, including its original expected revision. A changed body under that
key conflicts. A new user decision uses a new operation key and the newly
confirmed revision. For a creation whose session UUID was never received,
this GET cannot discover the result: reuse the original idempotent create
request after refreshing authority, rather than allocating another key.

Approval responses also remain owner-bound: ordinary members cannot see an
overbroader owner's foreign-request list, duplicate requests are rejected,
and pending/approved/rejected resolver/issued-session fields must be
consistent. A resolved receipt must name the current resolver and increment
exactly the submitted approval version. JSON approval decisions must be
actual booleans; revisions and lifetimes must be actual bounded integers,
not strings, booleans or fractional numbers coerced by a DTO parser.

Source integration tests traverse actual BFF -> fixed private client ->
Authorization routers and SQLAlchemy selectors with synthetic peer/User
proofs and an in-memory SQL fixture. They verify exact lookup beyond the
first 50, own/approver visibility, 401/403/404/503 separation, expired state
and current revoked revisions. A second test runs the actual Access revoke
service, encrypted idempotency executor and Cedar evaluator on that fixture:
a dropped reply after the revoke produces BFF503; exact GET returns revoked
revision; parent and approved child both deny afterwards; identical replay
returns the same receipt without duplicate audit/outbox, changed payload409,
and revoked approver authority403. This is **SOURCE/ASGI** validation, not
physical PostgreSQL atomicity, authenticated Rauthy/mTLS, or a Files effect.

### Native Init winner retains its own PoW reservation

A `GETDEL(native-init)` winner can be waiting for its network response while
a losing consumer observes no Init. Previously the losing consumer still
removed the PoW marker, leaving both consumers unable to continue. Only the
caller that actually obtained Init may now consume the PoW marker. A
controlled delayed-response regression reproduced the old failure and
passes with one winner after the fix. This changes no credential route,
provider permission, MFA or signed-login state; it protects the prerequisite
for a future native continuation.

### Pending approval receipts must confirm the exact submitted scope

A successful-looking 202 does not by itself establish that Authorization stored
the intended request. The BFF verifies that the pending receipt names the original
operation UUID, current actor, AgentSession, revision 1, exact requested operations
and exact resource tuples. Resource ordering may be normalized by the owner, but
substitution, omission, expansion or duplicate scope entries are rejected with
503 rather than reported as a confirmed pending request. Input duplicate tuples
are rejected before the owner call. As with a lost write reply, an invalid receipt
is an uncertain result: retain the original idempotency key/body and reconcile
through the owner instead of silently allocating another operation.

The first-Files Runtime resource selector is now source-agreed as a compact,
Project-bound `project-path-v1` identifier. Authorization validates it without
reconstructing a path. This is not permission for the browser to manufacture a
selector, submit arbitrary filesystem paths or reuse Catalog record IDs. The
read-only exact AgentSession endpoint supplies a current revision for subsequent
verified operations; it does not enable a Files read or replace the missing
signed User/Project and actual Files-owner integration.

### Auth-state storage cannot use an evicting cache policy

The separate native Init and one-time PoW reservation keys are authentication
state, not expendable cache entries. Evicting only the reservation while retaining
Init can reopen challenge issuance. Deployment owns the shared Valkey policy and
has selected `noeviction`; a local test using that policy does not establish that
the same policy has reached Development. Keep runtime policy verification in the
coordinated rollout, not an automatic global CONFIG change in the Backend.

Under noeviction, allocation can fail. Backend catches the actual Valkey client's
OutOfMemoryError through its existing ValkeyError boundary and returns503. A failed
Init write must not set a pending browser cookie; a failed PoW reservation must
not request or return a provider challenge. The targeted native-route regression
uses the real client exception type with a controlled store and verifies both
paths. No live memory pressure, key deletion or vendor configuration was performed
by this test. Authentication readiness is not inferred from a successful cache ping.

## Browser-safe Files content contract (source only)

[Control Panel Files content read](files-content-read.md) now defines
`POST /api/v1/files/read` with a strict current Project-scoped cookie,
resource bearer held only server-side, exact AgentSession grant revision,
canonical path/byte limit and unpredictable server-generated operation ID.
Only an independently authenticated private Files/Access owner may return
content after before/after current Cedar/mapping/FD checks. The BFF rechecks
cookie/token expiry and revocation after IO, then constructs the same four
bounded fields used by the Frontend preview decoder. **No trusted Files
owner port is configured by default, so the real API returns HTTP503.**
This is neither MCP tool registration nor product evidence of a real read.

# Authorization → Gateway / Hands: private Cedar decision API

**Status: source API staged, not live Rauthy authorization.** The independent `services/authorization` runtime mounts `POST /internal/v1/authorization/decide` but ships with `decision_service=None`. It therefore **always responds 503**, rather than allowing a user, agent or service to self-assert an identity or permission. It has no public Gateway route or Coolify-generated FQDN. The control-panel API/UI is absent from the execution path.

### Private request

```json
{
  "project_uuid": "<UUIDv4>",
  "agent_session_uuid": "<UUIDv4>",
  "action": "mcp.connect",
  "expected_grant_revision": 1
}
```

`action="mcp.connect"` is **Gateway-only coarse session admission**, checking that the caller has a real active session with nonempty operations and that Cedar admits the connection. It is **not** permission for any tool execution. For a Hand, `action` must instead be the exact already approved scope (e.g. `files.read`, `terminal.execute`), and the Hand must perform its additional resource/argument-specific authorization before each side effect. Unsupported actions deny. Stored active grant, actor/project/session match, exact current revision, expiry, and elevation are evaluated from Authorization's own PostgreSQL `briareus_access` under a transaction, with the Rust-backed Cedar policy embedded via `cedarpy`.

**Response semantics:** HTTP 200 `{"allowed":true}` only after all verified evidence and a current Cedar Permit; 401 when a configured verifier rejects caller authentication, 403 for a real Deny or verified scope mismatch, 503 for absent trusted identity/session peer adapter or authoritative data. Request bodies cannot specify trusted User IDs, proof issuers or verified peer attributes. No unsigned `X-Actor-Id`/`X-User-Id` or flat internal network may substitute for authentication. Other 4xx are boundary format errors. No bearer, grant or reason leakage in success.

### Actual activation requirements

The Backend/Deployment/Runtime handoff must supply an independently reviewed implementation of `TrustedDecisionAttestor`: real Rauthy access-token issuer/JWKS/signature/expiry/audience validation, service-peer authentication for the Gateway or particular Hand, canonical stable subject → internal User link, **fresh** Platform Project/member/active status, and a bounded expiry. A trusted factory must also inject `AuthorizationDecisionReader(PlatformDatabase(OwnerDatabaseSettings(owner="access")))` as the owner-local SQL authority. Never fabricate an issuer, client key or caller just to make this API return Allow. The deployed default remains unconfigured until those inputs exist; an API or UI outage must not become an Authorization dependency.

No automated suites are added in the MVP. Native import, compiled Cedar, fail-closed local ASGI requests and release image source-closure checks prove only source behavior. Real Dev acceptance uses the existing owner-approved Authorization Application UUID `95podguiawtnf2tvlemvk3ef` in Briareus Development; it still requires the reviewed code actually deployed, live peer/OAuth/Project attestation and an allow → deny → revoke sequence at a protected Hand. See issue #490. Retain existing PostgreSQL data and the legacy compose as rollback until runtime acceptance.

## Service-local decision lifecycle binding (source only)

The Authorization factory now accepts explicit trusted ingress and Rauthy/service-peer/Platform attestor adapters. Only after the existing Access owner lifespan successfully migrates/verifies its own database and ingress does it open an additional **owner-local** verified SQL reader pool for decisions; that pool is closed on shutdown. No other owner DB, schema or service is touched. The default release supplies neither adapter and continues to deny with HTTP 503. This is a prepared source integration, not a live OAuth Permit or a claim that authenticated grants are accepted.

## Verified Rauthy signature and Project trust composition (source-only)

The Authorization private verifier module now checks Rauthy JWT signatures
against independently trusted issuer signing keys, limiting algorithms
to supported RSA/EdDSA families, enforcing the verified HTTPS issuer,
resource audience distinct from browser OAuth client ID, key ID and expiry.
It rejects unsigned, mismatched and token-directed key references.
Key-set origin and rotation are still verified separately by the provider owner.

The decision attestor composes that verified bearer with two required
independently trusted ports: the authenticated service transport verifier and
the current Platform User/Project membership resolver. It checks the peer's
exact Hand action family, permits Gateway only for coarse mcp.connect, and
bounds proof expiry by the shortest upstream/peer/Project lifetime. The
Access owner SQL + Cedar policy must still verify the current durable grant.
Without actual trusted provider enrollment, peer and Platform ports, the
runtime default remains 503 fail-closed; no real Permit is claimed.

## Access-token purpose is mandatory before owner resolution

`RauthyJwksVerifier` requires signed `typ=Bearer`, nonempty `azp` and `jti`,
strict integer `iat`, `nbf` and `exp`, and the current resource audience.
An ID/Refresh token, missing purpose, malformed lifetime, duplicate audience,
or a `cnf`-bound token without its required proof is not a Bearer credential.
These reject with 401 before private peer/Platform/Access SQL resolution.
A default-unconfigured authority still returns 503, never a permissive fallback.
Public JWKS containing private signing material is rejected.

This closes a reproduced source defect: a controlled signed JWT with the correct
resource audience but `typ=Id` or `typ=Refresh` previously reached Cedar Permit.
The negative cases now stop before SQL. Generic MCP admission is deliberately
not pinned to the Control Panel client: another genuinely issuer-authorized
OAuth client can present the same User's resource-audience Bearer, but current
Project membership, peer, AgentSession and exact grant checks remain mandatory.
The BFF's stricter original browser-client/resource binding is a separate
[OIDC credential contract](../api/oidc-resource-intent.md), not a global client allowlist.

The claim vocabulary was checked in upstream `sebadob/rauthy` v0.37.1
`src/jwt/src/claims.rs` and `src/service/src/token_set.rs`. Native tests use
actual ephemeral JWT signatures, the private router and Cedar, with synthetic
peer/Platform/SQL fixtures; no deployed authentication finding is inferred.

## Trusted issuer key-source refresh (source only)

`_rauthy_issuer_keys.py` loads the actual discovered JWKS using the
operator-reviewed HTTPS issuer, system CA validation, strict same-origin
`jwks_uri`, disabled redirects, bounded JSON responses and a short refresh TTL.
Refresh never follows token-supplied key locations. An expired key cache is
invalidated before refresh; an upstream outage therefore denies new decisions
rather than extending expired trust. The decision attestor accepts this
refreshed source as well as the original injected static verifier. A provider
key-fetch outage maps to 503 authority unavailable, not an authentication
denial or grace Permit. Native validation exercised actual public Rauthy
issuer/JWKS retrieval (four keys), key rotation, hostile JWKS origin and
refresh outage. This is SOURCE validation, not proof of deployment-network
reachability, a provisioned OAuth client or any live authenticated permit.

## Resource-scoped Hand decision protocol (local-first Backend source extension)

For `action=mcp.connect`, Gateway sends exactly the original
Project/AgentSession/revision selectors with **no Hand fields**. Every Hand
effect must additionally provide an exact, **server-resolved** selector:

```json
{
  "project_uuid": "<Project-UUIDv4>",
  "agent_session_uuid": "<AgentSession-UUIDv4>",
  "action": "files.read",
  "expected_grant_revision": 1,
  "hand": "files",
  "tool": "read_file",
  "resource": {"kind": "workspace_path", "id": "<resolved-workspace-path>"}
}
```

The actual Hand implementation resolves `tool` and `resource` from the
executed MCP tool and its canonical arguments, **not** a user-provided header.
The independently authenticated service-peer attestor must bind the exact
same canonical effect identity and Rauthy subject to current Platform
Project membership. Project UUID/session/revision and JSON resource fields
are only selectors; none authenticate the caller or confer a grant.

Known resource kinds are explicit per Hand:
`files.workspace_path`, `terminal.workspace/job`,
`web.browser_session/origin`, `svc.repository`,
`reverse.analysis_project/artifact` and
`infrastructure.application`. IDs are bounded canonical opaque names,
not arbitrary strings that may be interpreted with a different path,
URL or ownership resolution. Unknown kinds/tools and ambiguous resource
mapping reject; no wildcard resource permission is inferred.

Only an active Access-owned `sessions.agent_sessions` row with current
`version`, non-expired `hard_expires_at`, active creator/Project and
exact `grants.operations` **plus** an exact durable matching entry in
`grants.resources` can pass HandResource Cedar. Each resource entry has
`{hand,tool,action,resource:{kind,id}}`; the request and signed peer effect
must match that same entry. Old action-only grants never authorize an
arbitrary resource. Gateway admission is still only coarse `mcp.connect`
and does **not** authorize any effect.

Owner-only approval sources may carry these scoped entries through
request/elevation/approve into an elevated AgentSession **only** if an
independently preattested, short-lived, current resource owner proof matches
the exact Project/action/effect and the requested scope. Validation of that
proof is synchronous (no remote network calls under SQL row locks). The
approval may never expand beyond the requested actions/resources. Missing
Resource Catalog proof denies; real Resource owner transport and user-facing
approval BFF endpoints are NOT yet wired.

HTTP 200 `{"allowed":true}` is allowed only on real signed actor+peer,
current Platform Project proof, current durable grant and Cedar Permit.
Malformed or missing Hand effect selectors reject with 422; authenticated
Cedar denial is 403; missing provider/peer/owner attestor remains 503.
The default Authorization runtime has no trusted peer/Platform attestor
and therefore **still fails closed 503**. Source-level positive probes
against synthetic trusted proofs are NOT live signed MCP acceptance.

## Private Approval read source (local-first integrated slice)

`services/authorization/_approval_read_api.py` adds
`POST /internal/v1/authorization/approvals/list` with
`{project_uuid:UUIDv4,limit:1..50}`. The query is a **selector**, not a
grant. An explicit `TrustedApprovalListAttestor` must independently verify
the signed Rauthy actor, authenticated private service peer, active current
Platform Project membership, and the exact Project approval privilege before
the Access owner reads any rows.

The Access reader queries ONLY its own
`sessions.approvals` in `briareus_access` with a bounded deterministic
order. Ordinary members receive only their own requests; a separately
attested approver may read the Project's pending/resolved requests. SQL and
response guards reject foreign Project/requester rows, invalid UUID/status/
versions, malformed operations, unapproved resource grants and expired
caller proof. Valid owner response `{items:[...]}` contains the same
status/requester/resource/revision and `allowed_actions` fields as the
BFF typed adapter. No actor UUID or role is accepted from JSON or headers.

A missing token maps to 401, a verified Project scope mismatch to 403,
and unavailable authority, invalid stored state or absent attestor to 503.
The Authorization app constructs the own-DB read pool only after trusted
ingress and either trusted decision or approval attestation has been
explicitly injected and verified. The **default release has neither**
and continues to return 503 for the private approval route.

Local ASGI probes demonstrate no-token 401, synthetic signed-peer/own-row 200,
and default-unconfigured 503. No actual Rauthy OAuth subject, network peer
certificate, Platform owner membership, PostgreSQL table query or Dev request
was authenticated as part of those source probes. Approve/deny/revoke writes
still require real signed OwnerCommandDTO/proofs and independent owner
IdempotentCommandExecutor; BFF route declarations alone do not activate them.

## Independently verified Gateway/Hand peer binding (local-first V2)

The Authorization source now includes
authorization._decision_peer_transport.TransportAuthenticatedDecisionPeerResolver.
It does **not** create or sign a private service identity. It consumes an
internal ASGI scope object named briareus.verified_private_peer.v1 which must
be inserted exclusively by an independently trusted mTLS or Unix-peer
transport adapter **after** authenticating the service certificate/OS peer
and the owner-resolved Hand/tool/resource being executed. No HTTP header,
OAuth actor claim, caller-supplied Project UUID or resource field may set
this scope or act as peer proof.

The server-side verified object binds:
- transport mtls|unix-peer; consumer gateway|hand; exact source audience
  (gateway/files/terminal/web/svc/reverse/infrastructure), destination
  briareus:access, and a previously verified immutable Hand effect key;
- SHA-256 of the exact received JSON HTTP request body (not a rewritten
  object), UTC attestation time and maximum 15-second proof lifetime;
- a cryptographically unpredictable lowercase hex nonce of 16–32 bytes
  which the injected shared replay authority consumes atomically across
  all Authorization replicas. A replay guard outage fails 503, reuse or
  digest mismatch denies. No in-process-only allow cache is sufficient.

After successful transport proof, RauthyDecisionAttestor additionally
verifies a real Rauthy access token's signature, issuer, expiry and
**separate MCP resource audience**, the current Platform Project User
membership, the fixed Hand action family and exact canonical effect key.
Access PostgreSQL then verifies the current revocable AgentSession resource
grant and Cedar policy. Only that full composition may respond HTTP 200
{"allowed":true}. Unauthenticated external connection, no ASGI peer
extension, missing attestor, stale/duplicated/mismatched proof or missing
Resource owner proof cannot become a Permit.

This is a **source-level contract**, not a deployed mTLS listener or signing
authority. Runtime owns actual Hand resolvers, transport and requests;
Deployment owns verified upstream client/audiences and scoped Dev trust
configuration. Until those independent owners provide real verified
adapters, Authorization's factory retains its default 503 outcome. Local
ASGI probes with synthetic transport objects show missing peer 503, one
correct digest/nonce acceptance, same-nonce replay denied, changed HTTP
body denied and no resource attestation denied; synthetic proof is not a
real certificate or hardware/Dev acceptance.

### Shared replay backing source

ValkeyPeerReplayGuard in authorization._decision_peer_replay adds a concrete
distributed, atomic set-if-absent nonce consumer. A separately approved
private Valkey client must be injected by Authorization owner startup;
the helper NEVER constructs a connection from a request, routes a provider
admin credential, or treats a local in-memory cache as authorization.
The namespace stores only SHA-256 of the service audience/nonce as key and
the request-body digest as value. NX with a 30-second expiry prevents one
verified service assertion being consumed twice across replicas. Valkey
timeout, unexpected reply or unavailable credential fails 503; replay denies.
Signed Rauthy token, current SQL/Cedar revision/revoke and actual Hand resource
proof remain independently mandatory on EVERY effect.

Only local synthetic Valkey/ASGI probes have run. There is no verified
real private peer certificate, secure listener, distributed Valkey
connectivity or signed MCP access token configured yet.

## Rauthy-only Authorization owner mutations (local-first)

The new AccessRauthyCommandService and private route adapter replace the
Identity-proof-dependent write path after greenfield cutover. An injected,
independently authenticated TrustedAccessCommandAttestor must verify the
current signed Rauthy actor, service peer, Project privileges and exact
action/operation UUID/expiry before Access SQL can change anything.

Private POST /internal/v1/authorization/approvals/request accepts Project,
AgentSession, expected revision, requested operations/resources, TTL and
operation UUID. Requesting actor must own an active base session; a
revision-locked owner transaction records an approval and audit/outbox.

Private POST /internal/v1/authorization/approvals/resolve accepts Project,
approval UUID, expected approval revision, approve flag, allowed operation
subset and idempotent operation UUID. Approval requires current independent
approver rights, cannot be self-approved or broaden a requested scope.
Lock acquisition is base AgentSession before approval. Elevated child
lifetime never exceeds the original base expiry, requested approval expiry
or five minutes. Actual resource grants also demand a current signed
Resource Catalog owner proof, unavailable by default.

Private POST /internal/v1/authorization/sessions/revoke receives Project,
session UUID, expected grant revision and operation UUID. Current approver
permission and revision are mandatory. Revoking a base atomically revokes
each issued elevated child referenced by a durable approved request within
the same Access SQL transaction, incrementing each version. Missing or
inconsistent child ownership aborts the entire transaction, never a
partial success or asynchronous best-effort invalidation.

All commands require a single private bearer, no cookie/Origin, JSON media
type and matching canonical Operation-UUID and Idempotency-Key headers. The
signed attestor must independently bind those selectors to the authenticated
actor. The Access IdempotentCommandExecutor provides a durable encrypted
response and keyed fingerprint under one transaction; errors preserve
401/403/409/422/503 semantics. No default signing key/peer/command port is
installed, so default service writes still return 503.

Local synthetic-owner checks cover pending 202, idempotent replay,
self-approval deny, separately authorized approve, stale revision deny,
parent+child revoke and TTL bound. These are SOURCE/ASGI tests, not real
Rauthy mTLS/Access PostgreSQL acceptance.

### New normal AgentSession opening (source-only)

POST /internal/v1/authorization/sessions/open accepts Project UUID,
operation UUID, fixed/requestable policy and optional label with an
independently attested current Rauthy User/Project and private peer. Access
persists one normal AgentSession, audit/outbox, and encrypted idempotent
response under its own transaction. Basic operations files.read and
project.metadata.read do not include resource grants and cannot authorize
protected Hand effects. Synthetic local checks show 201 and exact replay
without duplicate sessions; actual Rauthy/Platform/SQL trust remains gated.

## Current Platform project membership for Cedar decisions (source integration)

The separate Platform owner now defines private
POST /internal/v1/platform/oidc/project-member with
{issuer,subject,project_uuid}. Only an independently authenticated Access
service peer/delegation may query it; the body alone is never proof of
the Rauthy User. The Platform owner checks issuer/subject and project
against its current active, Rauthy-status-verified User link and private
Team/Project SQL projection, denying missing or inactive membership.
A match returns {issuer,subject,actor_uuid,project_uuid,expires_at},
bounded by current signed peer and provider status; absent membership
returns 403 and unavailable provider/SQL/attestor returns 503.

Access uses PlatformCurrentProjectResolver behind the existing
CurrentProjectMembershipResolver port. This resolver requires a signed
short-lived issuer+subject+Project delegation, a privately authenticated
fixed-destination Platform service response, and matching current User ID,
Project and expiry before providing any VerifiedProjectMembership to the
RauthyDecisionAttestor. The Authorization attestor now passes the
**actual verified JWT issuer** as well as signed subject, blocking
issuer-crossing same-sub collisions. It never queries the Platform DB
directly nor derives User UUID from JWT claims. Default owner trust is
still unconfigured and denies.

Local two-owner ASGI HTTP with synthetic independently attested service
delegation verified the exact current Project response, unrelated
Project/member denial and absent-owner failure. This is not live signed
Rauthy token, physical PostgreSQL, mTLS or working MCP Permit evidence.

### Standalone source-only Authorization import and Hand namespace verification

Native release verification must use the **actual Authorization Docker
source set**: services/authorization/*.py and services/common/*.py,
without copying historical Identity or Resource business packages.
The RauthyDecisionAttestor and TransportAuthenticatedDecisionPeerResolver
must import only the narrow owner-local _action_audiences vocabulary,
not the legacy ServiceIdentityAuthority module which imports
identity._domain and projects._resource_domain. An isolated copied-source
native Python import is a stronger check than an import from the entire
monorepo, where stale packages can mask missing Docker sources.

A verified Hand service certificate/audience MUST match the exact hand
element in its [hand,tool,kind,id] effect tuple. Even for actions shared
between Svc and Infrastructure, cross-Hand service impersonation denies
before replay-nonce consumption. The high-level signed Rauthy attestor
independently enforces the same constraint before any current Platform
membership or Access SQL read. This is source/ASGI evidence, not a live
mTLS/Hand executable permit.

### Current AgentSession inventory (read-only Access owner)

The Access service adds private
`POST /internal/v1/authorization/sessions/list` with the existing
bounded `{project_uuid:UUIDv4,limit:1..50}` command.
`TrustedApprovalListAttestor` independently verifies a current Rauthy
User/Platform Project, private service peer and Project approver status
before the service reads its own `briareus_access` SQL. This is not a
browser bearer or raw UUID authorization. Ordinary users receive only
sessions whose `created_by_principal_id` equals their current verified
User UUID; approvers may view other sessions in the same Project.
The SQL predicate AND final per-row authority check enforce this again.
Each row is strictly validated against exact Project/User UUIDs, current
grant version, active/revoked/expired status, bounded operation list and
exact resource grant scopes; malformed data or owner outages fail 503.
A limited status hint `allowed_actions:["revoke"]` is returned ONLY for
an approver viewing a currently active, unexpired session. A separate
idempotent owner write with expected revision is always required to revoke.

Source-level isolated BFF→Authorization ASGI test covers 401 missing
cookie, 200 own sessions with revisions, no visibility of foreign User,
expired session without revoke, 200 approver-only queue and session
visibility, foreign Project 403 and default unconfigured owner 503.
No actual provider identity, database or service transport was accepted.

### Exact V2 Hand/action vocabulary (source-aligned with Runtime)

The private V2 Hand decision is NOT a generic action-string API.
authorization._action_audiences.HAND_EFFECT_ACTIONS now exactly matches
the six current Runtime Hand PEPs:

- Files: files.read, files.write;
- Terminal: terminal.execute;
- Web: web.access;
- Svc: integrations.use, variables.use;
- Reverse: analysis.import;
- Infrastructure: integrations.use, variables.use.

Gateway may request ONLY coarse mcp.connect (without any Hand effect
fields). Every protected Hand effect requires exact Hand, tool and canonical
resource selector, and action MUST belong to its source Hand. Impossible
legacy project.metadata.read/agents.manage Gateway-only actions, and
reserved integrations.manage/variables.manage operations, are not valid
V2 Hand effects and now reject with 422 instead of appearing as usable
Cedar permissions. The same validation applies when normalizing stored
resource grants, matching stored grants, accepting fresh Resource owner
proofs and checking signed Rauthy service-peer audiences. Normal
AgentSession bootstrap may contain project.metadata.read as a non-effect
operation, but this does not authorize a protected Hand tool.

Native verification parses Runtime peer shared/hand_runtime/_effect_auth.py
read-only and confirms identical six-Hand action maps, with nine positive
Hand/action combinations and six impossible combinations rejected at
source. No new effect permission, public route, bearer or Dev configuration
is introduced by this change.

### Elevated scope coverage is mandatory (Rauthy-only mutation)

The new Access Rauthy-only request-elevation DTO requires every requested
protected Hand action to appear in at least one explicit canonical
{hand,tool,action,resource:{kind,id}} selector and no selector to exceed
the requested operation list. Action-only elevation (for example files.read
without a concrete Files owner resource), legacy project.metadata.read,
agents.manage and reserved manage actions are invalid as Hand elevation.
These cases reject HTTP 422 rather than creating an apparently approved
session with no enforceable V2 resource. This rule is checked both when the
request is validated and again at approval before an elevated child row can
be created. The current Resource Catalog owner still must independently
verify every granted scope; having syntactically valid JSON is never proof.

Normal AgentSession opening remains unchanged: basic operations may be
listed with resources:[] but cannot authorize protected Hand effects.
Rejecting an unsupported elevated scope is NOT a role denial or Cedar
decision. The private Access owner returns 422, the signed BFF writer
preserves that status instead of hiding it as 503, and the public cookie
route checks missing per-action resource coverage before calling owner.
A manager can still reject a pending bad/stale historical request, but
cannot approve it into a new grant. Source-only test verified positive
request+approved child with one exact current Files resource proof, and
negative no-resource, wrong-Hand, wrong-action and unsupported management
requests. No live owner database or runtime effect was accepted.

### Signed proof expiry while waiting for owner SQL

The Rauthy actor/peer/Platform Project proof is short-lived. A request may
block on PostgreSQL row locks or a slow owner read after the proof was
validated at ingress. AccessRauthyCommandService therefore checks the
current absolute expiration again AFTER obtaining the base/approval/child
locks and immediately before each business mutation, not only before the
idempotency transaction begins. Expiration aborts the entire Access
transaction (including cascading parent+child revoke) with no partial
audit/grant commit. AuthorizationDecisionReader likewise rechecks the
signed proof after returning from the owner SQL query and before Cedar
can issue Permit. A previously valid proof never gets extended by lock
contention or a slow query.

Local asynchronous fake-DB probes deliberately delayed row reads longer
than the attested proof TTL: elevation was denied with zero writes and a
coarse Gateway decision returned Deny, even though the query otherwise
returned a valid-looking session. This demonstrates source timing fences,
not a real Dev PostgreSQL/issuer/revocation experiment.

## Exact current session read for Control Panel reconciliation

Private `POST /internal/v1/authorization/sessions/get` accepts
`{project_uuid: UUIDv4, session_uuid: UUIDv4, limit: 1}` (limit may be omitted).
It reuses the independently attested Project read authority and the session
inventory's row validation; SQL includes both exact session and Project,
and creator equality for a nonapprover, with LIMIT 1. Only briareus_access
is read. The result is `{item: <current-session-inventory-item>}`. A scoped
missing/hidden row is HTTP404 with `detail="AgentSession not found"` and
no-store; a malformed/mismatched/overbroad row remains503. There is no
fallback to a different Project, unchecked page scan, browser-supplied
actor or synthesized grant. The BFF maps only this exact owner 404 shape;
a generic missing endpoint cannot masquerade as a deleted session.

All current list/detail readers enforce the requested bound and refresh
expiry classification after SQL returns. The signed actor proof is bounded
to 30 seconds and must still be live before returning. DTO revision and
approval/lifetime fields are strict integers/booleans on both public BFF
and private mutation boundaries; normal JSON UUID strings remain supported.
The read route does not authorize revoke or an MCP effect: writes use
independent signed actor/body binding, expected revisions and idempotency;
Cedar still evaluates current grants for each protected effect.

Focused integration checks in services/authorization/tests use the real
read/write routers, BFF private client, command executor, and Cedar library,
but synthetic trust and SQL fixtures. They include a simulated dropped
successful revoke response, current detail recovery, parent/child denial,
encrypted receipt replay without duplicate effects, altered-body conflict
and loss of actor authority before replay. Run with the API source added to
PYTHONPATH and the existing locked Authorization Python runner plus httpx.
No physical SQL, live service identity or product-readiness claim follows.

## Versioned first-Files selector and Project binding

For the first Runtime `read_file` effect (`hand=files`, `action=files.read`,
`resource.kind=workspace_path`), Runtime's owner-resolved canonical selector is
`project-path-v1:<canonical lower-case Project UUIDv4>:<64 lower-case hex digest>`.
It is exactly 117 ASCII characters, within the existing resource.id limit.
Runtime alone computes the digest using its existing A6 path_fingerprint:
SHA-256 of the bytes `files-project-relative-v1` followed by NUL followed by
the UTF-8 canonical NFC relative path. The actual path and bounded max_bytes
remain separate immutable execution arguments. No path is truncated, case-folded
or normalized again by Authorization, and no Catalog record UUID becomes a path.
The current Runtime ProjectRootRegistry has one Files namespace per Project;
root incarnation/version and ownership remain independently attested facts.

Authorization reserves the `project-path-` namespace for that versioned Files
selector, checks UUIDv4/canonical spelling/digest length, rejects unknown versions
or use on another Hand/resource kind, and compares the embedded Project with the
current request or owner Project. The check is applied to V2 decisions, Rauthy
approval requests, approval-time scope normalization, current resource owner
proofs, Access inventory/detail reads and Cedar's stored-grant match. A broken
stored row cannot permit an exact matching selector embedded with a foreign
Project. Other independently defined resource namespaces retain their existing
exact-scope semantics; this change does not invent or resolve an owner resource.
The decision revision is also a strict positive signed-64-bit integer, not a
coerced JSON string, float or boolean.

The deterministic selector is NOT an A6 signed FilesReadPermit, server-created
ProjectInvocation, Rauthy resource audience or private service identity. A future
Files tool still needs current verified User/Project/AgentSession, exact canonical
execution arguments, a separately verified Files resource-owner revision, current
Access/Cedar decision, and existing filesystem/read fences. No MCP tool or Files
browser route is mounted by this Backend change.

Local checks executed Runtime's unmounted encoder read-only for a short path,
Unicode path and a 3399-byte relative path; all matched its existing A6 hash and
117-character wire format. Backend tests use those public fixture vectors and
verify decision/request/owner/Cedar rejection on foreign Project, malformed ID,
wrong path and revoked grant. A controlled current synthetic row can pass the
real Cedar evaluator only for its exact allowed selector. This is source-level
cross-lane compatibility plus local policy execution, NOT a signed live Files
operation or physical PostgreSQL acceptance.

The Files decision regression also runs the actual Rauthy JWT verifier and
`RauthyDecisionAttestor` before the real private `/decide` router and Cedar
library. Ephemeral test RSA keys are generated only in memory, and the issuer,
User/Project, peer identity and SQL are fixtures. An exact signed resource-audience
token plus matching peer effect and current granted row yields the controlled
positive decision; revoked row, OAuth client audience in place of resource
audience, wrong issuer, expired token, foreign peer Hand/effect and mismatched
Project membership deny. This does not establish that the real Rauthy client has
that audience registered or that a live authenticated Files peer exists.

## First native Files read without legacy Identity epochs

The dedicated [Files read-decision contract](files-read-decision.md) adds private
before/after checks bound to the same original operation, compact Files selector,
byte limit and grant/resource revisions. It reuses current Rauthy/Platform/Access
verification and requires independent Files-owner evidence; no A6/Identity fence
is fabricated. `/decide` retains its existing minimal `{allowed:true}` shape.
Both use one current-grant reader, which now checks proof expiry after SQL
transaction exit as well as after the query. Neither route provisions Files
storage or removes Runtime's descriptor/path and final-release checks.

## Strict private authority JSON and bounded preparse effect requests

The current source-owned private Authorization boundaries now reject JSON
property duplication **at every nested object level** and nonstandard
`NaN`/`Infinity` before typed owner/JWKS interpretation. This applies to
`PlatformCurrentProjectResolver`'s independently authenticated Project
response and public Rauthy HTTPS discovery/JWKS material. `Rauthy` v0.37.1
signs the stable 24-ASCII-alphanumeric User ID as `sub`; an otherwise
cryptographically signed resource bearer with another subject shape denies
before privileged Platform/Access SQL. This is a source-owned provider-format
constraint, not a browser-asserted identity or a new user database.

`TrustedRauthyIssuerKeys` still requires the explicit reviewed Rauthy HTTPS
issuer, CA hostname checks, matching discovery `issuer`, same-origin JWKS
location, approved signing algorithms and bounded refresh TTL. Its HTTPS
metadata fetch now **disables ambient process proxy configuration** as well
as redirects; no platform proxy or caller-selected hostname is permitted to
interpose the signing-key authority. No Rauthy private key or arbitrary URL
is consumed by these readers.

The `POST /internal/v1/authorization/decide` and
`POST /internal/v1/authorization/files/read-decision` endpoints accept only a
**single** `Content-Type: application/json` and an exact single decimal
`Content-Length` of at most **8192 actual bytes**. `Transfer-Encoding`,
`Content-Encoding`, duplicate headers, missing/mismatched declared lengths
and oversized ASGI bodies are rejected with uncached 413/422 **BEFORE**
FastAPI/Pydantic body parsing, bearer/peer lookup, replay-guard nonce
consumption, owner/Platform SQL or Cedar. Actual body reception has a
five-second deadline. This is source-level protection against malformed
HTTP or forged small `Content-Length`, not proof of network ingress
segmentation. Runtime/Gateway must send exact bounded JSON framing; there
is NO legacy fallback route or independent unbounded parser.

The digest verifier receives a fresh Request over exactly the same bounded
original bytes, reusing the original server-owned ASGI scope. No scope
attribute, certificate, User token or resource-effect key is generated by
this reconstruction. The original body SHA-256/one-use nonce and current
Rauthy/Platform/Access/Cedar enforcement still decide the result. Both
private decisions have a separate twelve-second deadline for the attested
peer, current Project and owner/Cedar work after receiving the bounded body.
Timeout/outage yields an uncached 503, not Allow or a cached grant. All 200
`{allowed:true}` and 401/403/413/422/503 decision responses include
`Cache-Control:no-store` and `Pragma:no-cache`, and never expose bearer,
filename, filesystem root, signing key or provider error bodies.

Tests within the existing Authorization Files selector and native Files
read-decision suites now exercise approved in-memory RSA/JWT and synthetic
mTLS/Platform/replay authority together with the real routers, Cedar and
independent deterministic negatives: nested-duplicate issuer/Project/JWKS,
nonfinite values, noncanonical signed subjects, ambient proxy refusal,
invalid/duplicate transfer headers, spoofed two-byte length plus excessive
ASGI body, malformed JSON, and post-attestation timeout. Correct signed
fixture decisions still pass, but there is **NO** deployed authenticated
Hand peer, actual Rauthy resource-client grant, real Platform/current User,
physical PostgreSQL/Cedar effect or live Files business-tool acceptance
implied by these unit/ASGI checks.

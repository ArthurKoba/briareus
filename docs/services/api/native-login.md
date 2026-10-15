# Native Rauthy first factor and cancelable completion

Status: local implementation. Password-first-factor transport and signed
code/PKCE completion are implemented; OTP/WebAuthn/ToS/account-update
continuations remain explicitly unavailable, not authenticated fallbacks.
No public Files tool, Platform membership or Cedar grant is created by login.

## Configured capabilities and browser contract

The trusted local factory must inject the pinned Rauthy provider, protected
Valkey store and `PinnedNativeRauthyInit` with the actual localhost certificate.
The exact local issuer/client/origin remain those of the existing
[OIDC resource-intent contract](oidc-resource-intent.md). Arbitrary URLs,
HTTP downgrade, browser identity headers and provider Admin keys are not inputs.
No new configuration flag opens this on the default public factory.

`GET /api/v1/auth/capabilities` returns the configured implementation:
`{protocol:"rauthy-native-v1",first_factor:"password",pow:"client-solved",
cancel:true,continuations:[]}`. This is not a health probe or authenticated
identity. A missing owner returns 503; an older server may lack this route.
Frontend must not enable a credential form from Init 201 alone.

Existing `POST /api/v1/auth/start` and `/pow` retain their response shapes.
The browser creates Init with `{}`, obtains one public PoW challenge with `{}`,
solves it in a client worker, then calls:

`POST /api/v1/auth/first-factor`

`{email:string,password:string,pow:string}`

Only these three fields are accepted. Input is bounded to 8192 bytes; password
is 1..256 characters, email 3..320 and solved PoW 2..128 with the upstream alphabet.
The actual Rauthy validator remains authoritative for email/password/PoW.
Duplicate JSON keys, incorrect types, oversized bodies, extra OAuth selectors
and duplicate pending cookies are rejected without echoing submitted values.
Even for `{}` Init/PoW, `Content-Length: 2` is not accepted as proof that
only two bytes will arrive: the BFF streams at most two actual request bytes
under a five-second deadline and rejects mismatched or oversized ASGI input
before any provider Init or PoW reservation. Unsupported transfer-encoding,
Authorization headers and hostile Origin/Host are rejected early.
Requests require the exact local Host/Origin, application/json and a bounded
Content-Length; no browser Authorization header or query is accepted. Body
reception is bounded to 5 seconds and the claim/provider/completion sequence to 30 seconds.

A completed login returns 200:
`{stage:"authenticated",authenticated:true,authority:"rauthy",
platform_membership_verified:false,permissions:[]}`

Only the opaque Secure/HttpOnly session cookie is set. There is no browser
redirect, authorization code, provider session cookie, CSRF, password or bearer
in the response. The current Platform User/Project must still be fetched and
independently verified through the existing scoped `/me` owner API.

`POST /api/v1/auth/cancel` with `{}` cancels the current pending attempt,
in-flight claim, or its linked completed BFF session, then returns 204. It does
not revoke unrelated browser sessions or provide provider-wide SSO logout.
Ordinary `/api/v1/auth/logout` also cancels native state before clearing the
current identity cookie. Canceling an absent valid handle is idempotent;
ambiguous/invalid presented handles cannot produce a cancellation success.

## Versioned public API boundary — v1

The Control Panel uses **`/api/v1`** as its versioned management API root.
Only authentication and current-identity routes live under **`/api/v1/auth/*`**.
The old `/api/auth/native/*` routes have no aliases. Resource APIs are
separate: `/api/v1/agent-sessions`, `/api/v1/approvals`, `/api/v1/catalog`
and `/api/v1/files/read` (default owner unavailable). Current scoped
`GET /api/v1/auth/me?project_uuid=...` remains an identity/Project proof,
not an AgentSession or filesystem permission.
`POST /api/v1/auth/start` starts the in-panel Rauthy flow;
`GET /api/v1/auth/authorize` is a separately named diagnostic hosted-code
redirect; `/session`, `/logout`, `/capabilities`, `/pow`, `/first-factor`,
`/cancel` are unambiguous by method and name.

**Provider registration exception:** The actual Rauthy public client and
existing disposable local client currently register the exact redirect
`GET /api/auth/oidc/callback`. This single old route remains a tightly
validated provider return boundary and is **not** a second browser API or a
fallback login UI. Its full `redirect_uri` must match the original PKCE
request and token exchange. Do not silently change it to
`/api/v1/auth/callback` until Deployment independently qualifies and
coordinates the existing client's redirect allowlist update. All other old
unversioned public Auth requests return 404; no transparent rewrite or
user-supplied alternative origin is allowed. The next release must stage
Frontend and Gateway BFF together to avoid breaking old clients.

## Existing Development activation boundary (SOURCE only)

The independently deployed Control Panel API now has TWO fixed native Rauthy
transports. The disposable local integration uses the exact localhost issuer,
S256 client, loopback origin and explicitly source-injected localhost TLS
certificate. The existing Development source mode uses ONLY the approved public
issuer `https://briareus.koba-nexus.ru/auth/v1/`, public OAuth client
`briareus-control-panel` and same-origin callback
`https://briareus.koba-nexus.ru/api/auth/oidc/callback`. Its private BFF→Rauthy
requests use the system CA-verified HTTPS certificate, hostname verification,
no redirects and no environment proxy. It does NOT post credentials over
private Docker HTTP or accept arbitrary issuer/client/host selections. Gateway
must preserve the fixed public `Host`/`Origin` required by all native browser
POSTs; the current Gateway source forwards the public Host for the BFF API.

The two proposed `OIDC_NATIVE_FIRST_FACTOR` / `OIDC_FILES_RESOURCE`
operator flags were removed after Deployment found they were not part of the
approved Coolify variable contract (#536, issuecomment-6186624567). Product
mode derives exclusively from the already-approved `OIDC_ISSUER`,
`OIDC_CLIENT_ID` and protected `OIDC_SESSION_VALKEY_PASSWORD`. When issuer and
client exactly identify the public existing Rauthy realm, the BFF mounts the
native first-factor only while the existing Valkey credential is available.
Missing/mismatched provider or Valkey continues returning HTTP503, without
credential fallback to another IdP.

That same pinned public issuer/client always uses the exact source-owned
Files resource `https://briareus.koba-nexus.ru/hands/files/mcp` from the
ORIGINAL authorization-code request, and verifies its access JWT after signing.
An unregistered resource returns upstream `invalid_target` and MUST block
login, rather than silently issue an unscoped identity that appears entitled
to Files. A provider administrator must separately verify/approve the existing
client's `allowed_resources` before this release is activated in Dev. A
localhost source-injected test provider may still intentionally run identity-
only with resource=None; it does not configure the public service.

This source change requires NO new Coolify ENV, application UUID, secret,
container or provider Admin key. It does not permit an unattended Dev cutover:
Deployment must verify provider client enrollment, credentials, live HTTPS,
current User and a controlled rollback. Do not touch `ENC_KEYS`, existing
users, databases, volumes or runtime-only authorizations for this preparation.

Mock upstream HTTP/RSA/Valkey exercises the actual configured application
factory with the existing issuer/client/Valkey settings, checks the exact
Files audience and native code/PKCE/Userinfo/cancel, hostile Host/Origin and
provider `invalid_target`. This is synthetic signed-source acceptance, not
real provider registration, genuine User login or MFA acceptance.

## Errors and unavailable continuations

All native responses are no-store. Credential/request rejection, missing or
spent Init, original realm changes, expiry and canceled completion yield 401.
Malformed input yields 422. Provider throttling yields 429 with the validated
`retry_not_before` Unix timestamp. Unavailable provider/Valkey/key sources or
unconfirmed cancellation yield 503. Do not automatically resubmit a consumed
attempt or reinterpret a timeout as successful login; start a new attempt.

A verified provider OTP/WebAuthn/ToS/account-update/client-MFA requirement yields 409:
`{stage:<provider-state>,authenticated:false,continuation_available:false,
restart_required:true}`.

The states are `otp_pending`, `webauthn_pending`, `tos_pending`,
`account_update_required`, and `client_mfa_required`. No token exchange occurs,
no challenge secret is forwarded and the local claim is retired. Frontend must
show the unavailable branch, not silently bypass it, accept terms, re-prompt a
password indefinitely, or redirect to the hosted provider as the final design.

## Pinned upstream protocol

Reviewed source: `sebadob/rauthy` v0.37.1, commit
`ce35a70fbc43203b1a6910d3db30389228825f46`:
`src/api/src/oidc.rs`, `src/service/src/oidc/authorize.rs`,
`src/api/src/lib.rs`, `src/api_types/src/oidc.rs`, and the principal/CSRF middleware.

Rauthy's `POST /auth/v1/oidc/session` explicitly supports an independent UI.
The first-factor request uses `POST /auth/v1/oidc/authorize` with that same
private session and `x-csrf-token`, the solved upstream PoW, and the original
server-held client/redirect/scopes/state/nonce/PKCE/resource. Upstream checks
session/CSRF, validates and consumes PoW, checks credentials and account/client
policy, and decides the continuation. This is NOT the OAuth password grant.
The BFF uses fresh isolated HTTPS clients with certificate/hostname validation,
no redirects and no environment proxy; private response cookies are not reused
across attempts or passed to the browser. Upstream `POST /oidc/session` (Init)
replies are streamed under an 8192-byte cap; `POST /pow` replies are streamed
under a 128-byte cap. The fixed response bounds are applied BEFORE buffering
the full upstream body or parsing provider cookies. Excessive responses fail
closed with no newly issued Briareus cookie or PoW challenge.

The exact 202 callback goes through the existing signed ID-token nonce/issuer/
client, current Userinfo and optional resource-JWT verification before any
session write. The original resource intent and all token deadlines remain
unchanged. Unknown statuses, non-JSON challenges and duplicated response headers
do not become login success. Provider body reads are bounded to 8192 bytes.

A corrected decoder detail: `WebauthnLoginResponse.exp` is a DURATION from
`req_exp.as_secs()`, not a Unix timestamp. It must be a strict 1..600 second
integer; the decoder derives an absolute deadline from the request start.
This classification correction does not implement a WebAuthn ceremony.
The upstream PoW worker calls `pow_work_wasm` from its sPoW WASM module;
Frontend owns bundling a pinned supported solver, not the BFF.

## Atomic Valkey lifecycle and cancellation

The existing native-init key now transitions `init -> claimed -> complete`.
A PoW reservation first says `reserved`; ONLY after successful upstream issuance
is it atomically changed to `issued` while the same Init is current. A failed
request keeps the reservation spent, without pretending a challenge was issued.
A first-factor claim requires `issued`, removes the PoW marker and replaces
Init with a secret-free claim marker. Concurrent consumers have one winner;
losers never remove the winner's state. The original absolute expiry is checked
by both the application and Valkey server time.

Completion checks the exact random claim and deadline, then links the attempt
to one newly allocated session key and writes the verified identity/optional
resource credential. Both operations are one Lua execution on the existing
single-node owner. Collision checks precede linking; no existing session can
be adopted or deleted by cancellation. Because Lua runtime errors do not undo
prior writes, linkage precedes session allocation and allocation failure does
not issue a cookie. No live/global Valkey policy change is made by Backend.

The complete linkage lasts as long as the new session, not merely the remaining
Init TTL. If cancellation wins first, completion cannot create a session. If
completion wins but its reply is late, cancellation deletes the linked session;
a later cookie cannot restore it. The existing short native cookie is retained
on successful first factor for that cancellation window. Starting a new Init
retires the prior attempt and its linked session, if any. Completed linkage
expires automatically; it is not a reusable permission or second bearer store.

Explicit cancellation and repeated task cancellation use bounded drained cleanup.
Actual downstream disconnect is checked after provider work and around completion;
no detached task is promised to continue signing a user in. A disconnect can be
noticed only at an enforcement boundary, not retroactively. BFF cancellation does
not claim upstream token revocation or instantaneous distributed logout.
Old pending records without the new stage/deadline format must restart; established
browser-session records remain compatible. No database reset is required.

## Evidence boundary

Tests exercise the actual native provider transport code, route validation,
real ephemeral JWT signatures/PKCE/Userinfo checks, state transitions, races and
unsupported branches with a synthetic Rauthy HTTP peer. The same native route
cases also run with actual password-protected Valkey 9.1.2 on an isolated private
Unix socket, executing the real Lua. Separate checks cover expiry, wrong claim/
realm, collision, completion-vs-cancel and noeviction OOM; final known test state
is removed. Real loopback TCP disconnects are exercised through Uvicorn, with
synthetic credentials only. These tests are not a genuine Rauthy password/MFA
login, browser UI acceptance or Platform/Access PostgreSQL acceptance.

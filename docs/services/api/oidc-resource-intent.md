# Original OAuth resource intent and private Files credential

Status: local source/cryptographic integration. Neither a registered provider
resource nor a genuine signed Files operation is established by this contract.
The default BFF remains identity-only unless its trusted launcher explicitly
constructs `RauthyOidcAdapter(resource_audience=...)`. No browser parameter or
unreviewed environment switch selects a resource or enables a Hand.

## Fixed realm and original request

The first supported resource pairs are deliberately exact:

- Disposable local: issuer `https://localhost:18444/auth/v1/`, client
  `briareus-local-panel`, callback `https://127.0.0.1:18446/api/auth/oidc/callback`,
  resource `https://127.0.0.1:18446/hands/files/mcp`.
- Existing Development: issuer `https://briareus.koba-nexus.ru/auth/v1/`, client
  `briareus-control-panel`, callback `https://briareus.koba-nexus.ru/api/auth/oidc/callback`,
  resource `https://briareus.koba-nexus.ru/hands/files/mcp`.

A URI match is a source boundary, not proof of provider registration. Upstream
Rauthy v0.37.1 requires an authorized client resource grant. `LoginRequest.resource`
and `TokenRequest.resource` are defined in `src/api_types/src/oidc.rs`; the
`src/service/src/oidc/grant_types/authorization_code.rs` implementation forbids
introducing or widening a resource during code redemption. The request therefore
includes the resource during original authorization, before any code is issued,
and repeats the same value at the token endpoint. Cross-realm or arbitrary URLs
are rejected. No automatic client update, database mutation or permission bypass
is implemented when the provider returns `invalid_target`.

Normal and native Init escrow retain issuer, client, resource intent, nonce,
PKCE verifier and an absolute deadline. The normal callback consumes its original
transaction once, checks these bindings and verifies signed ID-token nonce/client,
callback issuer and current Userinfo subject. Native Init stores the same intent
and its one-use claim preserves it for the future first-factor continuation.
Init alone does not send a password, solve MFA or create a browser identity.
The [native first-factor handler](native-login.md) now consumes the bound attempt
and completes a supported password-only provider response through the same
signed PKCE/Userinfo verifier. Unsupported MFA/ToS cannot issue a session.
Old pending transactions without the new binding/deadline fail closed and must
restart; established unscoped identity sessions remain readable.

## Independent resource-token verification

For a resource-bound login the BFF additionally verifies the access token against
the same trusted Rauthy issuer/JWKS, never a token-provided key URL. Upstream
`src/service/src/token_set.rs` emits a resource token audience containing the
client and the granted resource. This first-Files BFF accepts exactly those two
unique entries, in either order, and rejects additional audiences. It requires
the same signed subject and authorized client as the ID token, `typ=Bearer`,
strict lifetime claims, and a bounded token ID. DPoP/`cnf`-bound or delegated
`act` credentials are unsupported here and cannot silently become Bearer.

The session deadline is the minimum of signed ID expiry, signed access-token
expiry, the token response's expires_in measured BEFORE its HTTP request, and
the BFF's 900-second cap. Slow Userinfo or JWKS requests cannot restart that TTL.
Duplicate token-response JSON fields reject. Both verification paths share the
same pinned-provider key loader while retaining their separate token purposes.

## One private session record, no public bearer

`create_session(identity, resource=credential)` stores the verified identity and
optional private resource bearer in ONE password-protected Valkey session record.
An opaque Secure/HttpOnly cookie is the only browser handle. `/session`, `/me`,
callback responses and UI DTOs contain no token or provider session secret.
Default unscoped login stores identity only and has no Files credential.

`get_resource_credential` is an internal escrow read, NOT an authorization API.
Logout deletes the same record holding both identity and bearer, so a second
credential key cannot survive identity deletion. This is BFF-local logout, not
provider-wide token revocation, cancellation of an already copied bearer, or a
claim of provider-wide instantaneous logout. Native completion now uses the
cancelable atomic state/linkage described in the native contract: canceled
attempts cannot recreate a live BFF session after a late completion reply.

A future trusted caller must still independently validate the actual resource
JWT, current Platform User/Project, private peer identity and current Access/Cedar
AgentSession grants for every operation. Possession of the escrow entry alone
never supplies those facts. No public Files listing/read route or new MCP tool is
registered by this BFF package, and it does not make BFF a live MCP dependency.

## Local evidence

Focused tests use real ephemeral RSA signatures and the actual BFF code/PKCE,
callback, Userinfo decoder and session store, with an explicitly synthetic IdP
HTTP transport and in-memory Valkey. They cover successful scoped and unscoped
flows; wrong subject/client/audience/purpose; unsupported bound/delegated tokens;
intent mismatch; duplicate token fields; resource registration failure; expired
Userinfo completion; one-use transaction replay; private-only credential output;
and joint session/credential logout. Native Init is checked through its actual
`POST /api/v1/auth/start` router. This is not genuine Rauthy first-factor/MFA,
physical Valkey persistence, real client enrollment or product acceptance.

## Existing Development source mode (no new operator variables)

The existing configured `OIDC_ISSUER=https://briareus.koba-nexus.ru/auth/v1/`
and `OIDC_CLIENT_ID=briareus-control-panel` deterministically select one
source-owned Files resource. Its URI cannot come from a browser or ENV value;
the same fixed realm selects native first-factor transport when the protected
existing Valkey dependency is present. The formerly proposed feature flags
were removed to honor Deployment's approved operator-variable boundary.
The real Rauthy client must already have the resource in its allowed list;
an upstream `invalid_target` is a deliberate fail-closed release blocker,
not grounds to silently retry with no Files audience. Local source-injected
identity-only tests do not change the public product contract. Real issuer,
MFA, User, Project and Access grants still require independent verification.

# Control Panel API — Rauthy transition

**State: source-ready for controlled existing-App cutover, not proof of running Coolify migration.** The independently buildable Python Control Panel API preserves the existing Compose service key/Docker DNS `briareus-admin-api` as a transitional Gateway compatibility alias; it also declares `briareus-control-panel-api`. Keep the legacy `services/admin-api` and `deploy/admin-api` on Git as rollback until proven Dev cutover. Never start a second container claiming either alias.

`GET /api/auth/oidc/config` obtains and validates the actual upstream Rauthy OpenID Connect discovery document (strict issuer comparison, HTTPS endpoints, Authorization Code and PKCE S256) and returns only public client settings. It caches the metadata for 5 minutes; unavailable/unconfigured issuer fails with 503. `GET /health/live` remains local when the identity service is unavailable. No password, client secret, token, registration or grant is accepted by this route.

Config supplied by the Rauthy owner: canonical public `OIDC_ISSUER` and public `OIDC_CLIENT_ID`, as protected/approved environment-scoped references or nonsecret app settings as applicable. The concrete public issuer and OAuth client ID are not known until the other agent publishes and verifies them. Avoid inventing an issuer URL or exposing client secrets to the browser.

**Remaining integration:** verified authorization-code+PKCE callback and session storage with anti-CSRF state/nonce; token and JWKS verification; scoped Rauthy Admin REST adapter once verified upstream API permissions and contract are available; authenticated `/api/platform/me` by real Platform owner membership; Authorization/Cedar grant/approval/revocation owner ports; production routes and service-local folder Cutover with existing Coolify UUID and Gateway alias. Do not conflate OAuth UserSession, AgentSession or persistent Terminal execution session. Do not make a new JWT issuer inside Control Panel API.

## Existing application cutover contract

Keep the existing approved Coolify Control Panel API Application UUID. Set its Base directory to `/services/api` and Compose location to `/docker-compose.coolify.yaml`, then persist repository-relative Watch Paths `services/api/**`. Preserve the old service name `briareus-admin-api` until Gateway selects `briareus-control-panel-api` by a separately verified Runtime release. Do NOT delete `deploy/admin-api/` or old app state before the new folder is actually serving /api. Never set an OIDC issuer/client ID to a fabricated value. Until Deployment verifies the real Rauthy issuer, optional empty `OIDC_ISSUER`/`OIDC_CLIENT_ID` keep legacy first-user routes operational and public OIDC config returns 503.

The new folder includes a **transitional copy** of precisely the four legacy first-user routes: `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/platform/me`. They use the same private Identity service DNS, bounded request/response, original-operation-id headers, origin and bearer validation. A successful `/health/live` alone is NOT sufficient; compare real pre- and post-cutover HTTP routes including denial modes and schema, plus independent service restart/Watch. Retire transitional first-user code only once Rauthy OAuth sign-in/current User works end-to-end.

**Public ingress:** this private Compose must never declare `SERVICE_URL_BRIAREUS_ADMIN_API_8000` or a generated Coolify domain. All public `/api/*` traffic terminates at Gateway. During the flat-folder Base Directory migration the old magic variable briefly created an unintended default sslip.io domain; it was removed from the scoped Development Application's Domains configuration before deploying the new API. Do not reintroduce it on reparse.


## Authorization code + PKCE (source-only)

The existing Rauthy discovery adapter can now create an upstream OAuth2
authorization request with cryptographically random state, nonce and S256 PKCE
challenge. The code verifier stays inside a server-side SecretStr. An
operator-approved HTTPS redirect URI is injected by a trusted controller, not
derived from incoming Host or query arguments. The adapter exchanges a valid
one-time code against the verified Rauthy token endpoint without inventing a
client secret, and returns explicitly UNVERIFIED SecretStr token values.

No public callback route is mounted yet: a real registered Rauthy OAuth
client, trusted one-time state storage, signature/issuer/audience/nonce checks,
current Platform memberships and an authenticated session writer are required
for secure product login. An exchanged bearer or ID token is never itself a
Briareus AgentSession or a Cedar permission. The legacy first-user route
remains operational until real sign-in is accepted.


## Verified upstream ID-token identity (source-only)

After a trusted, single-use PKCE/state callback has exchanged its code, the
Control Panel API provider adapter now verifies the returned Rauthy ID token
against HTTPS discovery-pinned issuer/JWKS, with no redirect or token-header
key URL, allowed RSA/EdDSA signatures, exact browser OAuth client audience,
bounded issued/expiry times and constant-time nonce matching. The result is
a signed external Rauthy subject only. Neither ID-token identity nor Group
claims are current Team/Project membership or an authenticated AgentSession.

The callback/session route remains unmounted until owner-approved OAuth
client enrollment, one-time state store and current Platform User/membership
resolution are integrated. Unsupported/expired/mismatched ID tokens always
deny; do not fall back to legacy Identity JWT issuer or grant fake access.


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

Routes added under the same public Gateway-managed /api/* path:
- GET /api/auth/oidc/start: fetch trusted Rauthy discovery, generate S256 PKCE, cryptographic state/nonce, atomically reserve a five-minute private Valkey transaction, set Secure/HttpOnly/Lax __Host transaction cookie, and redirect to the upstream authorization endpoint;
- GET /api/auth/oidc/callback: require exactly one matching state and code, atomically consume state once (GETDEL), exchange authorization_code using private verifier, validate real signed Rauthy ID token/JWKS/issuer/audience/nonce, issue opaque Secure/HttpOnly/Lax session cookie backed by a short-lived Valkey record, then return to /panel/;
- GET /api/auth/oidc/session: return only the verified external Rauthy subject, issuer and client, with platform_membership_verified=false and permissions=[]; NEVER substitute for real Platform /me or internal Authorization proof;
- POST /api/auth/oidc/logout: same-origin-only, revoke the Valkey session before clearing cookies. This is local BFF logout; provider-wide Rauthy SSO logout requires separate upstream integration.

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
is unavailable, existing /health/live and legacy first-user API continue
running and new OIDC login endpoints return 503 (fail closed).

Source/CI alone does not prove browser sign-in: activation requires a real
OIDC client, runtime Valkey credential, Rauthy authorization_code callback,
valid cookie session and explicit Platform-owned membership integration.

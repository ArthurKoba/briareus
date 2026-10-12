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

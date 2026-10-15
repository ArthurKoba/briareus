# Rauthy v0.37.1 — browser/OIDC and privileged REST route boundary

This is an **upstream source-derived** reference for Runtime's eventual
Gateway public-path allowlist, not an implemented Gateway configuration.
Reference checkout: upstream `sebadob/rauthy` tag `v0.37.1`, Git commit
`ce35a70fbc43203b1a6910d3db30389228825f46`. Source files:
`src/bin/src/server.rs`, `src/api/src/oidc.rs`, `users.rs`, `clients.rs`,
`generic.rs`, `html.rs`, and the corresponding Svelte login frontend.
All listed API paths are underneath the deployed `/auth/v1` prefix.
Runtime is sole editor of `services/gateway/**`.

**Owner override 2026-10-14:** the target Briareus login interface is
implemented **entirely inside Control Panel UI**; its API must use Rauthy as
the upstream identity/challenge/credential/MFA authority. Users MUST NOT be
navigated/redirected to Gateway or Rauthy's SvelteKit hosted login page. This
reference describes vendor protocol/legacy compatibility only; it is NOT an
order to expose Rauthy HTML/JS/assets as an MVP dependency. Do not promote
hosted page 200, its Svelte asset 200 or a PKCE authorization redirect into
acceptance of the custom Control Panel sign-in.

## Upstream protocol routes — assess for Control Panel BFF integration

| Method | Relative path | Purpose / boundary |
| --- | --- | --- |
| POST | `/oidc/session` | Documented native/custom-login Init session creation; returns Rauthy cookie and one-time CSRF for subsequent validated steps |
| GET | `/oidc/authorize` | Validates client+redirect, creates/resumes Rauthy session and CSRF; returns login HTML |
| POST | `/oidc/authorize` | Email/password+PKCE challenge, CSRF, fresh PoW; returns auth-code redirect or MFA next step |
| POST | `/oidc/authorize/refresh` | Refreshes already authenticated Rauthy browser session for new client |
| POST | `/pow` | Anti-automation proof challenge for login and recovery; not a password token endpoint |
| GET | `/.well-known/openid-configuration` | OIDC discovery |
| GET | `/oidc/certs` and `/oidc/certs/{kid}` | Signing public keys |
| POST | `/oidc/token` | OAuth code+PKCE exchange; must enforce per-client proof |
| GET, POST | `/oidc/logout` | Upstream signout; independent from Briareus opaque BFF cookie logout |
| GET, POST | `/oidc/userinfo` | Scoped access-token identity; public OAuth endpoint not a public user list |
| GET | `/oidc/sessioninfo`, `/oidc/sessioninfo/xsrf` | Rauthy session helper; requires upstream own authentication |
| GET | `/clients/{id}/logo`, `/clients/{id}/favicon` | Public brand assets for registered OIDC clients |
| GET | UI-owned HTML/assets/theme routes | Exact paths must be derived from Rauthy renderer and browser requests; do NOT generalize to entire prefix |

**Caution:** `GET /oidc/authorize` may directly return Rauthy HTML with
client-provided redirect and provider cookies; its successful `200` is not a
completed login or access-token issue. Native password login requires
Rauthy-owned session+CSRF and a fresh solved PoW. After first factor, `200`
means OTP/WebAuthn MFA challenge, not authenticated User. Svelte upstream
currently handles `202` redirect, `205` profile update, `206` terms-of-service
acceptance, `406` missing mandatory MFA and `429` rate limiting.

## User enrollment, recovery and MFA (mixed user REST namespace)

| Method | Relative path | Class / prerequisite |
| --- | --- | --- |
| GET | `/users/{id}` | **Mixed upstream route**: `Users:read` API key/group admin OR Rauthy session reading **its own** user ID; public exposure is not required by native Panel |
| GET, POST | `/users/register` | Optional unauthenticated signup; upstream handler returns 404 GET / Forbidden POST if `OPEN_USER_REG=false`. Not needed for invite-only login |
| POST | `/users/request_reset` | User-triggered password reset request, with PoW |
| GET | `/users/{id}/reset/{reset_id}` | One-time password setup/reset link rendered for legitimate user |
| PUT | `/users/{id}/reset` | Completes password reset, with upstream proof checks |
| GET | `/users/{id}/email_confirm/{confirm_id}` | One-time email verification/activation |
| GET | `/users/{id}/revoke/{code}` | User-triggered revocation link |
| POST | `/users/otp_start`, `/users/otp_resend`, `/users/otp_finish` | Hosted login OTP challenge |
| POST | `/users/webauthn_start`, `/users/webauthn_finish` | Hosted passkey login challenge |
| POST | `/users/{id}/webauthn/auth/start`, `/users/{id}/webauthn/auth/finish` | Session-guarded user WebAuthn authentication |
| POST | `/users/{id}/webauthn/register/start`, `/users/{id}/webauthn/register/finish` | Authenticated account enrollment, **not** public account creation |

The `/users/**` tree **cannot** be blocked wholesale without breaking
upstream user recovery and MFA. But also must **not** be publicly forwarded
wholesale: collection GET `/users`, collection POST `/users`, GET
`/users/email/{email}`, mutations at `/users/{id}`, `/users/attr*` and
most privileged/user account management are not login prerequisites and expose
private server API surface even if unauthenticated requests return 401.
Gateway must gate with *exact method + normalized path*, accounting for
encoded aliases, trailing slashes and future vendor route changes. **GET
`/users/{id}` is dual-use** in the pinned Rust handler: it first tries
privileged Users:read, but otherwise calls `validate_session_auth()` and
`is_user(&id)` for authenticated self-access. A blanket upstream block
would break Rauthy's own hosted account UI, but that UI is not the native
Control Panel contract. A closed public route is acceptable while the BFF
retains the necessary private provider operations; do not force public
exposure simply to satisfy a hosted-UI probe. Paths with user ID/reset code are
security-sensitive operations; source allowlisting does not replace
upstream session, principal and CSRF validation.

## Privileged boundaries in otherwise public prefixes

- **POST `/oidc/rotate_jwk`** is administrative despite `/oidc/*` appearing
  to be a public standard OAuth namespace. Don't allow all `/oidc/*`.
- **GET/POST `/clients`**, GET/PUT/DELETE `/clients/{id}` and client
  secret/registration endpoints are not browser login resources; provider
  administration belongs to private `http://briareus-rauthy:8080`.
- Dynamic OAuth client registration/CIMD is explicitly disabled at source
  (`ENABLE_DYN_CLIENT_REG=false`, `ENABLE_EPHEMERAL_CLIENTS=false`). Do not
  enable globally to work around the absence of a registered MCP resource.
- Default signup disabled at source is not a proof of current deployed ENV.
  Public `/users/register` GET 404 alone is not proof that every recovery,
  registration, admin or alternative POST path is correctly gated.

## Native UI compatibility boundary

The upstream `POST /oidc/authorize` endpoint **exists**, but an independent
Briareus UI is **not** automatically a safe replacement for upstream's
SvelteKit authentication orchestrator. It must retain server-issued session
cookies and `x-csrf-token`, solve fresh `/pow` proofs, process time/OTP/passkey
conditions, support correct `code`, `state`, `nonce`, `redirect_uri`, PKCE S256,
prevent cross-session mixups and delegate all password verification to Rauthy.
It must not turn into Resource Owner Password Credentials, a local JWT issuer,
or a browser-exposed privileged Rauthy API key. An owner-approved, fully tested
provider-version-specific Backend adapter is required before enabling native
credential submission. Hosted Rauthy login is **not** an approved final/fallback Briareus UX after
the owner's native Control Panel decision. If the Backend cannot securely
implement the upstream provider challenge protocol, report a clear product
blocker and keep native password submission unavailable; do not silently
redirect to Rauthy/Gateway or invent a second credential/token authority.

**Validation state:** Source review is exact pinned-upstream evidence only.
Local source, lints and public negative OIDC probes are available; real
password+MFA login, administrative credential scopes, volume restart
persistence and restricted MCP `aud` remain unverified. Public Gateway admin
privacy must fail closed until Runtime releases and independently accepts its
exact route filters.

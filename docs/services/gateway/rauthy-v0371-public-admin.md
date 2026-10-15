# Rauthy v0.37.1 Admin REST privacy: source-confirmed route slice

**Status:** Runtime source/local security hardening, not a deployed Rauthy
login or proof of a complete publicly inaccessible Admin API. This file
extends [the Users-specific audit](rauthy-v0371-public-users.md).

**Pinned evidence:** sebadob/rauthy tag v0.37.1, Git tree
ce35a70fbc43203b1a6910d3db30389228825f46. Inspected real Rust
handlers in src/api/src/{api_keys,atproto,auth_providers,backup,blacklist,
clients,email,events,fed_cm,generic,groups,html,kv,oidc,pam,roles,scopes,
sessions,swagger_ui,themes,tos,users}.rs, available at
https://github.com/sebadob/rauthy/tree/v0.37.1/src/api/src.
The upstream Rust principal-validation calls, not guessed path names, are
the basis for this limited privacy decision.

The public Gateway sends 404 before contacting the private provider for
the following confirmed management API routes. The Control Panel BFF
remains responsible for its independently authenticated direct private
Rauthy Admin client; it does not use these public management routes.

- **Whole Admin/group-management namespaces:** /admin/** (Rauthy's own
  administrative HTML UI), /api_keys/**, /backup/**, /blacklist/**,
  /email/**, /events/**, /groups/**, /roles/**, /scopes/** and
  /sessions/**. The HTML handlers serve the provider's Admin interface;
  the management REST handlers use an API key or a validated
  Admin/Group-Admin principal, including Events SSE, session removal,
  API-key secret rotation and API-key introspection. No public login
  handlers are declared in these namespaces in the pinned source.
  The provider's API-key self-introspection method is intentionally
  included in the public block: any genuine independent API-key consumer
  needing it through Gateway requires an explicit owner-approved,
  narrowly audited transport contract, not an implicit Admin bypass.
- **Administrative KV:** /kv/ns/**, whose namespace, access and value
  operations require an Admin session. This is NOT a blanket KV denial:
  /kv/pub/**, /kv/keys/** and /kv/values are separately public or
  Access-Key-authorized upstream APIs and remain routed.
- **OIDC client management:** GET/POST /clients, GET/PUT/DELETE
  /clients/{id}, /clients/{id}/secret and PUT/DELETE on
  /clients/{id}/logo or /favicon. Client configuration requires
  privileged Clients rights. GET branding resources, OAuth Forward
  Auth/callback and POST /clients/validate_uri are NOT blocked.
- **OIDC dynamic clients:** /clients_dyn is NOT confused with /clients.
  Upstream separately implements dynamic client registration and its
  scoped registration-token or rate-limit requirements. Gateway does
  not override provider policy or assert it is enabled.
- **External identity-provider management:** POST /providers (admin
  provider list), POST /providers/create, POST /providers/lookup,
  PUT/DELETE /providers/{id}, GET /providers/{id}/delete_safe,
  and non-GET /providers/{id}/img. The same upstream module also owns
  external login, callback, provider image GET, self-service
  linking/unlinking and /providers/minimal; those remain routable.
- **Confirmed one-off Admin endpoints:** /auth_check_admin,
  /search, /login_time, /password_hash_times, /encryption/keys,
  /encryption/migrate, POST /oidc/rotate_jwk and non-GET
  /password_policy. JWK rotation requires Rauthy Secrets.Update, and
  is not an ordinary OAuth/JWKS publication operation.
  Authenticated users can still GET their current password policy,
  perform GET/POST /oidc/logout, use JWKS and standard OIDC grants.
- **Branded themes:** POST/PUT/DELETE /theme/{client_id} require
  privileged Theme rights, while GET /theme/{client_id}/{timestamp}
  supplies public OIDC login CSS and remains routable.
- **Terms of Service:** GET/POST /tos and GET /tos/user/{id} are
  Admin-managed ToS listing/publishing/acceptance inspection.
  GET /tos/latest and POST /tos/accept or /deny belong to hosted
  login and are preserved for real User flows.
- **Privileged Access Management (PAM):** Admin-only /pam/groups/**,
  /pam/emails_unlinked, /pam/hosts collection/configuration and
  host-secret mutation, and /pam/users collection/user administration
  are blocked. PAM host-scoped login, MFA, preflight, account self
  operations, user-host access checks and authorized-key self-service
  remain routed; Rauthy enforces its own host/session secret proofs.

This extends the earlier source-reviewed User collection, attribute
schema, arbitrary-email lookup and privileged direct User mutations.
Login, self-service, registration, reset, MFA, passkeys and OIDC
protocols still route to their real provider owner. A Gateway route
denial is not a replacement for upstream session/role validation.
Malformed, encoded-slashed, double-encoded and dot-segment paths are
rejected before constructing an upstream request.

## Scope limitations and local evidence

The local source-map checker compared **210 actual Rust-declared HTTP
method entries across 21 upstream modules** against the Gateway
classifier, in addition to the separate Users-specific audit.
Representative native local ASGI/httpx MockTransport probes confirmed
112 Admin UI/API denials (no upstream request), 81 preserved
protocol/user forwards and seven rejected encoded/traversal aliases.
Forwarded HTTP 200 from MockTransport is synthetic, not a Rauthy
service response.

Conditional and development-only upstream routes, non-decorator
middleware handlers, source-to-running-image version parity, and
unknown future Admin endpoints have NOT been comprehensively
accepted by this audit. The filter is intentionally not a blanket
deny of /auth/v1/**, which would break hosted login, OIDC metadata,
dynamic client registration, account self-service and MFA.

Before product acceptance, Deployment must verify the exact Development
Rauthy routes and genuine signed-in OAuth login, PKCE, MFA, recovery and
Admin endpoint public non-reachability AFTER reviewed merge and approved
scoped Dev deployment. No live Dev request, DB/volume operation, OAuth
resource token provision or real Cedar Permit is evidenced here.

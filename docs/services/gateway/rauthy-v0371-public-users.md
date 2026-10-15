# Rauthy v0.37.1 User API: public Gateway privacy slice

**Runtime source-only review, 2026-10-14. NOT a full public Admin ACL or live Dev proof.**

Upstream fact source: sebadob/rauthy tag v0.37.1, Git tree
ce35a70fbc43203b1a6910d3db30389228825f46,
src/api/src/users.rs:
https://github.com/sebadob/rauthy/blob/v0.37.1/src/api/src/users.rs

Rauthy shares the /auth/v1/users namespace between interactive Human
flows and administrative management APIs. A blanket /users/** block
would break legitimate hosted registration, recovery and account/MFA
sessions. The Gateway therefore performs a **limited source-reviewed
route/method classifier** in services/gateway/src/bridge/_rauthy_admin_privacy.py.
The following routes return a public 404 BEFORE the private provider
transport is contacted, regardless of supplied cookies or Bearer:

- Entire /auth/v1/users collection, all methods: upstream GET and POST
  are authenticated list/create management (Rust lines 94 and 158);
  they are NOT the configured /users/register flow.
- /auth/v1/users/attr and children, all methods: the top-level custom
  attribute schema management GET/POST/PUT/DELETE requires Admin/API
  privileges (Rust lines 218, 240, 265 and 310).
- /auth/v1/users/email and children, all methods: lookup of arbitrary
  users by address requires privileged Users.Read (Rust line 2358).
- PUT/PATCH/DELETE on exactly /auth/v1/users/{id}: these directly
  mutate other users and are privileged management (Rust lines 2391,
  2446 and 2901). No pattern matching beyond exactly one ID component.

The following are deliberately NOT blocked by this particular slice:

- GET /users/{id}: Rauthy's handler independently admits the current
  authenticated User to its own account (Rust line 582).
- GET/POST /users/register, GET/PUT /users/{id}/reset, and the other
  user confirmation/revocation/forgot-password endpoints: upstream
  interactive recovery/enrollment, with the provider's real registration
  configuration still authoritative (Rust lines 378, 403, 1183, 1266,
  1145, 1304, 2306).
- GET/POST self-service, picture, OTP and WebAuthn routes and all OIDC
  protocol endpoints. Signed-in account settings and MFA are owned by
  the provider, not administered through the public Briareus BFF.

For every Rauthy path the classifier rejects double-encoding (%25),
percent-encoded separators/backslashes, NULs, malformed percent
escapes, repeated slashes and literal/percent-encoded dot segments
before path normalization or upstream HTTP. Valid single-encoded path
aliases (e.g. %75sers, %61ttr) are classified using one strict decode.

**Boundary of this finding:** A subsequent source-reviewed, narrowly
scoped extension now covers confirmed privileged routes in Clients,
API Keys, Groups, Roles, Scopes, Events, Blacklist, Sessions, external
Providers, administrative KV and selected one-off Admin methods. See
[the Admin privacy extension](rauthy-v0371-public-admin.md) for exact
evidence and preserved protocol routes. Neither slice proves the entire
Rauthy Admin API unavailable on the public Gateway. The protected
Control Panel BFF still requires independently authenticated, scoped
Admin access via direct private provider transport.

Native LOCAL evidence: direct route classification plus bounded ASGI
Gateway/httpx MockTransport for 12 denied User admin routes, 17 preserved
login/self-service routes and 6 encoded/dot-segment attacks. MockTransport
HTTP 200 means only that forwarding code was reached; it is NOT a live
Rauthy response. Real Development acceptance needs the approved provider
route audit, hosted login/signup/reset/MFA navigation and public admin
denial after the reviewed merge and scoped deploy.

# Rauthy 0.37.1 — operator-owned provider contract

Owner: Deployment, `BR-20261014-D-OIDC-01`. Applies **only** to the existing
Briareus MCP **development** Coolify Application `pdx35bwnh9tjeopx30jslrb9`.
This document is a nonsecret deployment/acceptance contract, **not** a command
to reprovision an active provider or rotate an existing key.

## Boundary and source policy

Briareus has exactly **one Control Panel API** (Backend-owned BFF) and
one independent **Control Panel UI**. No other Briareus control-plane API/UI
application exists. This vendor stack runs upstream Rauthy identity/OIDC;
its *privileged Rauthy operator REST* is an internal upstream capability
consumed server-to-server by authorized Control Panel API/Platform owners.
It must not be exposed directly or routed as another public Briareus API.

Three vendor services run in the *same approved Compose application*: PostgreSQL
(`briareus-postgres:5432`), Valkey (`briareus-valkey:6379`) and upstream Rauthy
(`briareus-rauthy:8080`). Only Gateway is the public HTTPS ingress. No host
port, additional OAuth issuer, separate Rauthy application, Cedar replica or
new PostgreSQL server is authorized. Preserve current application UUID,
`briareus-net`, encryption references and three durable volume keys:
`postgres-data`, `valkey-data`, `rauthy-data`. No wipe, `down -v`, database
stamp, rekey, secret reveal or silent schema migration during this cutover.

The default Git-backed Coolify Watch Paths remain `services/external/**`.
Avoid unnecessary per-file watch lists. The saved Watch Paths in the
existing Development application are separate runtime state and must
be checked during the coordinated release without changing its UUID.

The Compose contract explicitly disables user self-registration
(`OPEN_USER_REG=false`) and public-registration open redirects
(`USER_REG_OPEN_REDIRECT=false`). Open dynamic registration
(`ENABLE_DYN_CLIENT_REG`) and unauthenticated CIMD/ephemeral lookup
(`ENABLE_EPHEMERAL_CLIENTS`) also remain disabled until a versioned, narrowly
approved client/resource policy exists. These switches do **not** disable
operator-created Rauthy Users or *static* operator-created OAuth clients.
A source declaration is not proof that the currently deployed process uses it;
verify only on the exact accepted Dev application after the final large PR.

PostgreSQL's Compose readiness now requires BOTH real `pg_isready` and a
**provider-specific** `/run/briareus-rauthy-db-ready` marker proving the
Rauthy logical database exists and is owned by the scoped PostgreSQL role.
Rauthy's intra-Compose `depends_on: service_healthy` does not wait for
unrelated Access/Platform/Resources DBs or their owner migrations. A
**separate** `/run/briareus-owner-databases-ready` marker records successful
reconciliation of all four DB names/owners. If one domain DB is missing or
owned by an unrelated role, Postgres remains physically available and Rauthy
can still start *when its own protected DB is intact*; that failing domain
service must reject startup until its separate owner issue is resolved.
Missing, foreign-owned or disappeared Rauthy state instead keeps provider
health false. The healthcheck now runs the dedicated **read-only live catalog
probe** `provider-db-health.sh` after the initial provider-ready marker and
`pg_isready`, so a database removed or reassigned while the physical server
keeps running does NOT leave that marker as a false permanently green result.
It uses only the existing scoped PostgreSQL credentials, never prints the
password, never mutates the catalog or owner schemas, and does not require
another container, operator ENV or new role. The probe is **not** verification
that Rauthy's own schema, first operator, OIDC endpoints or user data actually
work. Verify effective healthchecks and service behavior on approved Coolify
Dev before acceptance.

## Valkey memory policy for native login

The shared Valkey deployment definition uses `maxmemory-policy noeviction`. Native Init,
its one-use PoW reservation and browser sessions are not disposable cache
entries. With `allkeys-lru`, memory pressure can remove the reservation while
keeping Init, allowing a second challenge reservation on the same attempt.
This was reproduced with native Valkey 9.1.2 and the actual Backend store.
`noeviction` retains existing keys and refuses allocations when full; Backend
must return a bounded unavailable response, not retry as a new identity or
assume writes succeeded. The existing 128 MB data limit, AOF, volume and
credential references are unchanged. This does not prove crash durability,
replace PostgreSQL grant authority, or configure the already running Dev
container; effective runtime policy must be checked at coordinated cutover.

An isolated test of this Compose shell command and the real Backend session
store also survived an owned Valkey process SIGKILL: pending Init+PoW remained,
consumed Init was not resurrected, and expired Init stayed expired after AOF
replay. This is **process-crash** evidence only. The observed `appendfsync`
policy is `everysec`; host power loss, storage failure and actual Coolify
volume recovery are not proven by a kill that leaves the kernel running.

The four-database bootstrap orders Rauthy first on a genuinely fresh
cluster. Otherwise, interruption after creating an earlier domain database
makes the next run look like a populated cluster with missing provider data
and correctly trips the protective guard. Ordering creation fixes that
fresh-install dead end without changing the guard: an existing populated
cluster missing Rauthy still requires an explicit recovery decision, never
an automatically manufactured replacement identity database. Native
PostgreSQL 18.6 checks covered partial first install, replay with preserved
provider fixture/OIDs, missing-provider refusal and foreign-owner refusal;
these are isolated local databases, not actual Coolify volumes or users.

## First Rauthy operator is provider-owned, not a shared migration password

The same human should operate Rauthy and Briareus, but the identity contract
is the verified **Rauthy issuer+subject** linked to a distinct Platform
operator authorization. Matching account e-mail or the upstream
`rauthy_admin` role does not automatically grant Project/AgentSession rights.
**Never** copy a human password into PostgreSQL/Valkey, owner Alembic, a
Bootstrap service, or the Briareus Control Panel database. Do not scrape or
log first-login passwords as a provisioning mechanism.

Pinned upstream Rauthy v0.37.1
`src/data/src/migration/bootstrap/mod.rs::migrate_init_prod()` initializes
its own FIRST empty production DB: the provider updates the initial admin,
initializes signing JWKs and its bootstrap records. Its
`src/data/src/migration/bootstrap/rauthy_admin.rs` and
`book/src/config/bootstrap.md` support an owner-controlled initial email
and a protected **Argon2id password hash** by optional
`BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD_ARGON2ID` *for this
first empty provider initialization only*. Without that explicit choice,
Rauthy generates its initial random password and prints it only once in its
operator logs. DO NOT retrieve those logs via automation or reuse a password
found there. Do not set `BOOTSTRAP_ADMIN_PASSWORD_PLAIN` in Dev configuration;
no new privileged operator ENV/secret is introduced by this decision.

The upstream first-init path itself is **not transactionally atomic**: after
JWKs exist, a later bootstrap failure does not automatically rerun that
first-init on restart. A truncated, pre-existing or wrong-owner Rauthy DB is
an incident requiring separately approved provider-owned recovery, NOT a
signal for the Briareus coordinator to create a new empty issuer, delete
provider state or replay account setup. Always distinguish DB *existence*
(reconciled by External PostgreSQL), upstream Rauthy's own schema/setup
migration, and independently versioned Platform/Authorization/Resources
migrations. These are three different authorities with different restart
lifecycles. Backend owns the first verified issuer+subject → Platform
operator link only after real upstream authentication and owner access proof.

## Native Control Panel authentication UI — owner decision 2026-10-14

The complete human-facing login, MFA/step-up, password recovery and session
UX belongs to **Briareus Control Panel UI**, backed by its **Control Panel
API**. The browser must NOT navigate to Gateway or to Rauthy's hosted login
HTML/SvelteKit interface. Gateway can still act as a fixed same-origin
transport where necessary but is not an authentication frontend; it must
not render/redirect users to upstream login pages. Upstream Rauthy remains
the sole authority for credential validation, session/MFA state, OIDC code,
token signing and revocation. Control Panel does not store an alternate
password database or mint identity tokens.

The upstream Rauthy **v0.37.1 pinned source** explicitly documents
`POST /auth/v1/oidc/session` as the initializer for a custom user-facing
login UI (see `src/api/src/oidc.rs::post_session`): it returns an Init
provider session, Rauthy cookie and a one-time CSRF token. **Do not
repeat** `POST /oidc/session` to check or refresh that Init session: pinned
`Session::is_valid()` intentionally excludes `/oidc/session` from its Init
path allowlist, so even a request containing the valid cookie **and**
`x-csrf-token` creates another Init (`201`), replacing the client's session
binding. This was reproduced against disposable local Rauthy under verified
TLS. Keep the original provider session+CSRF server-side and advance only
through its permitted authorize/MFA continuations; do not infer lost cookies
or authentication success from repeated Init responses. Other relevant
versioned handlers include `POST /auth/v1/pow`,
`POST /auth/v1/oidc/authorize`, token exchange and separate OTP/WebAuthn,
Terms-of-Service, recovery and mandatory-MFA flows. This is **evidence of
protocol building blocks**, not proof that a complete secure native BFF
integration exists. The Backend must hold the provider session/cookie,
CSRF, challenge, PKCE state and sensitive responses within a bounded,
version-pinned, independently tested protocol boundary; do not expose
Rauthy operator API keys or use a password-to-token shortcut. Frontend
receives narrowly scoped challenge states, never unverified identity
privileges. After real provider identity, Platform independently checks
User/Project and Authorization checks Cedar before a Hand effect.

Consequently, a Rauthy authorize HTML `200` or loading
`/_app/immutable/*` or `/assets/rauthy_*.svg` is **not** native
Control Panel login readiness. No Deployment or Runtime login acceptance
may depend on forwarding those hosted SvelteKit files. Keep read-only
issuer/client/redirect metadata evidence distinct from native credentialed
login, verified User/Project and protected MCP execution.

## Existing Control Panel client: verified Dev public metadata

- Issuer: `https://briareus.koba-nexus.ru/auth/v1/`
- Discovery: `/auth/v1/.well-known/openid-configuration`
- Authorization: `/auth/v1/oidc/authorize`
- Token: `/auth/v1/oidc/token`
- JWKS: `/auth/v1/oidc/certs`
- Public client ID: `briareus-control-panel`
- Exact approved callback: `https://briareus.koba-nexus.ru/api/auth/oidc/callback`
- Authorization-code + PKCE **S256**, requested scopes `openid profile email`.

A read-only unauthenticated authorize probe for this client/callback
returned provider HTML `200`, while an unknown client got `404` and a wrong
callback got `400`. This is **provider client/redirect metadata only**,
not the approved browser UX, native credential submission or a successful
login. The Control Panel BFF owns server-held session/CSRF/PKCE state and
provider verification; never put operator API keys or human passwords in
public JavaScript responses or generic logs.

## Supported invitation / identity administration

With self-registration closed, an authorized provider operator
creates Users through the **upstream Rauthy operator interface**. Initial password setup/reset
email requires working SMTP. Supported Rauthy API keys are created/rotated by
an operator in the upstream Rauthy management interface, not by anonymous callers. Distinct scoped
permissions are required for a server-side integration:

- User lookup/status: `Users:read`, and specific `Users:create` / `Users:update`
  only if the BFF actually implements those operations. Deletion is not a
  default requirement; Rauthy API keys never grant Briareus Project authority.
- Client inventory/provisioning: `Clients:read` plus narrowly authorized
  `Clients:create`/`Clients:update` only for the operator's provisioning
  principal, **not** an ordinary browser/BFF User-reading API key.
- Rauthy API keys cannot themselves manage API keys. Their actual permission
  grants and credential validity must be verified with an authorized
  server-side, sanitized operation; never retrieve or print the key value to
  check whether one exists.

After upstream login, Backend separately binds the authenticated Rauthy `sub`
to a **real** Briareus User/Team/Project owner record and Cedar AgentSession.
No Rauthy role/group automatically creates Platform Project membership.

## MCP resource audience and native Control Panel

Use the provider's authorization-code + S256 resource-indicator flow, not a
Panel ID token or a manufactured service identity. Pinned Rauthy v0.37.1
`Client::validate_resource_request` checks exact `allowed_resources` values;
`finish_authorize` binds the selected resource to the issued code. The native
BFF must carry the server-selected resource through its protected transaction
and real password/MFA flow. Adding `resource` for the first time during token
exchange is rejected: the token request may repeat the same code-bound value
or omit it and inherit that value, but may never introduce another target.

For the disposable LOCAL stand, Runtime confirmed:
- issuer `https://localhost:18444/auth/v1/`;
- existing public/S256 client `briareus-local-panel`;
- callback `https://127.0.0.1:18446/api/auth/oidc/callback`;
- Files resource `https://127.0.0.1:18446/hands/files/mcp`;
- bootstrap scopes `openid profile email` and RS256 token-signing configuration.

These source/owner facts do **not** mean the provider has granted the resource
or issued a token. The Dev resource is separately
`https://briareus.koba-nexus.ru/hands/files/mcp`; never silently accept the
local issuer/audience in Dev or replace the resource with the Panel client ID.
OAuth scopes are not Cedar `files.read` grants, Project membership or Files
root authority. The current public client does not need a new client secret
for this authorization-code flow.

**Bootstrap limitation:** v0.37.1's
`src/data/src/migration/bootstrap/types.rs::Client` has neither
`allowed_resources` nor `default_aud`; `bootstrap/clients.rs` also omits those
columns from its INSERT. Adding the fields to `bootstrap/clients.json` is not
resource provisioning. Do not reset an existing provider to retry bootstrap.
Use an authorized exact-client `GET /auth/v1/clients/{id}` and
`PUT /auth/v1/clients/{id}` with `Clients:read` and `Clients:update`, preserving
current required `UpdateClientRequest` settings. A Users:read key is not
sufficient. For the minimal flow, do not add always-on `default_aud` values
or enable DCR/CIMD; confirm the one exact allowed resource after the update.
No operator credential or provider database write is authorized by this guide.

**Important v0.37.1 update hazard:**
`src/api/src/clients.rs::put_clients` accepts a *full*
`UpdateClientRequest` and validates `Clients:Update`; this is not a PATCH or a
narrow `allowed_resources` setter. Pinned
`src/service/src/client.rs::update_client` overwrites name, confidential
client mode, redirect/logout URIs, scopes, PKCE challenges, signing algorithms,
MFA, custom claims, allowed origins, `allowed_resources` and `default_aud`
from that complete request. Changing `confidential` can generate/remove a
client secret; **omitting `scim` deletes an existing SCIM client integration**.
An operator must therefore obtain a protected current exact-client snapshot,
confirm whether SCIM is configured and be able to preserve its private token
via the provider's approved operator-only workflow. Never log, export to a
regular issue, or copy a secret-bearing GET response into ordinary artifacts.
If the existing SCIM config or another mandatory field cannot be preserved
safely, **stop** instead of submitting a minimal PUT. The authorized payload
must preserve all other current fields, add only the one reviewed Files URI to
`allowed_resources`, leave `default_aud` unchanged, preserve the exact known
callback and S256 flows, and verify the provider's sanitized reply/re-read
without a bearer or client-secret reveal. Review and record a rollback before
the first write; do not assume a bulk provider update is reversible merely
because HTTP returned 200. This source contract does not approve or perform
that write in Development.

`TokenSet::access_token` includes the client ID and granted resource in the
signed `aud`, normally `[client_id, resource_uri]`; the verifier must require
the exact resource as a member, not require a single-string audience. The
ID token remains a client-login proof, never a Files bearer. Actual Backend
verifier checks with ephemeral synthetic signatures accept the client+Files
array and reject client-only, another Hand and a trailing-slash mismatch;
that is parser/cryptographic contract evidence, **not** a Rauthy-issued token.
The BFF must hold any genuine access token server-side with verified
issuer/subject/expiry and bind it to the current human session; the existing
identity-only `PanelOidcSession` fields cannot reconstruct a resource token.
Platform, private peer and before/after Files Cedar checks remain independent.

RFC 8693 token exchange is a separate confidential-client, explicit-flow
feature that needs an existing valid access token. It is not a shortcut from
an opaque Panel cookie or ID token and is not the minimal current integration.
Client provisioning and a genuine native code/MFA/token exchange remain
explicit pending acceptance; no public login HTML status proves either.

## Public route privacy and real acceptance

The current Dev Gateway passes administrative collection GET
`/auth/v1/users` to Rauthy: upstream unauthenticated `401` means that
private collection REST is **internet-routable**, not network-private.
Runtime owns public OIDC/login routes and must deny privileged-only Users
collection/attributes and Clients management before upstream. **However**,
Rauthy v0.37.1 GET `/users/{id}` is a *mixed* route: a privileged Users:read
API key/group admin can read users, while a normal authenticated Rauthy
session may read only **its own** ID. That describes the upstream handler,
not a requirement to expose its account UI publicly. With native Control
Panel, the BFF supplies the human-facing account contract and the provider
self-profile route may remain private. Gateway `404` is therefore not a
native-login failure; `401`/`403` are also valid anonymous rejections if a
compatibility route remains. Neither result proves authenticated profile
access or where a denial originated. No browser operator key is permitted;
Deployment does not change Runtime's route policy.
The internal Rauthy origin `http://briareus-rauthy:8080` remains only for
trusted app-to-app Rauthy management REST and provider runtime.

From an approved **local** Python environment, run
`python services/external/provider_contract.py` to verify source config;
append `--public` only for bounded, noncredential **OIDC discovery/JWKS
and protected route** checks against the fixed public Dev origin. The
native Control Panel does not use a hosted Rauthy sign-in page: this
verifier therefore does **not** request `GET /oidc/authorize`, does not
create browser Init sessions, and does not require that Gateway renders
Rauthy login HTML. Client/redirect registration is a separate trusted
provider-operator/BFF integration check (`registered_client_redirect` remains
`NOT_PROVEN_NO_PRIVATE_CLIENT_PROOF`). The verifier prints **no** cookies,
passwords, tokens, private keys, email addresses or user records. Its separate
self-lookup probe uses a fresh random 24-character ID-shaped path from the
pinned upstream `new_store_id()` contract, NEVER actual Users data. An
anonymous `401`, `403` or `404` on GET `/users/{id}` is a rejection,
not an Admin privacy failure. Native Panel does not require this upstream
profile route to be publicly reachable; success, redirect or server failure
must not pass that check. Privileged-only collection/configuration GET
endpoints still require `404` and independent Gateway-policy acceptance.
No anonymous status proves a real authenticated self-profile read.
It intentionally reports
`signup_disabled_everywhere=NOT_PROVEN_BY_PUBLIC_GET`,
`valid_user_code_flow=NOT_PROVEN_NO_USER_CREDENTIALS` and
`resource_token_audience=NOT_PROVEN_NO_SIGNED_MCP_TOKEN` and
`native_control_panel_login=NOT_PROVEN_NO_NATIVE_BFF_CHALLENGE_FLOW`
until a real owner-authorized product flow is independently accepted. The
noncredential public OIDC checks cannot accept the native login UX.

A true Dev acceptance must *also* establish registered client parameters,
operator API-key permission outcomes (status only), Postgres/Valkey ready,
correct Rauthy signing state, a persisted account/client after an approved
restart and separate real MCP resource access-token issuance. Runtime/Backend
then accept authenticated User/Project/grant and scoped tool execution in
their own lanes. Never infer persisted volumes from an empty Coolify storage
metadata list; corroborate actual allowed application-only mounts and stable
state before declaring durability.

Reference: Rauthy upstream
[configuration](https://sebadob.github.io/rauthy/config/config.html),
[API keys](https://sebadob.github.io/rauthy/work/api_keys.html),
[bootstrap](https://sebadob.github.io/rauthy/config/bootstrap.html),
[RFC 8707](https://www.rfc-editor.org/rfc/rfc8707.html).

## Owner-approved clean Dev domain databases (source staged; no live DDL)

On 2026-10-14 the owner explicitly authorized a clean **Briareus
Development-only** service-owner database reset without carrying retired
Identity schema/migrations forward. This does NOT authorize a drop of Rauthy
identity or its persistent signing/encryption state: existing provider Users,
OAuth clients, signing keys, `briareus_rauthy` PostgreSQL and `rauthy-data`
are still required for real existing-user login.

The External PostgreSQL bootstrap now *idempotently creates/verifies only*
`briareus_access`, `briareus_platform`, `briareus_resources` and
`briareus_rauthy`; the first three are product owners, the last is the
untouchable upstream identity provider. It no longer creates
`briareus_identity`. New fail-closed bootstrap guard distinguishes a truly
fresh PostgreSQL installation (no known Briareus databases) from a populated
cluster where `briareus_rauthy` has disappeared. It permits creating the
provider DB only in the former case; in the latter, bootstrap stops with a
nonsecret recovery error **before any owner database CREATE**, leaving the
physical PostgreSQL server running but the owner readiness marker absent.
An existing Rauthy DB remains untouched; no migration, reset or owner takeover.
Initial PostgreSQL `POSTGRES_DB` is the standard
`postgres`, not the old unused `briareus_dev`. The PostgreSQL entrypoint,
network/DNS, existing owner credential reference and named data volumes are
preserved. **No reset/drop is embedded in bootstrap**. An absent Rauthy
database at an existing populated installation is an incident to investigate,
not permission to provision a replacement identity and accept new users.

### Target-qualified release order

1. **Release fence:** validate current approved Briareus
   MCP/development UUIDs, required GitHub/Reviewer merge SHA and owner branches.
   Backend Platform/Resources migrations must use the same fresh baseline as
   their model registry; Runtime must retire or disable latent Identity
   business imports before any protected Hand execution. This source change is
   not permission to deploy ahead of those owners.
2. **Nonsecret inventory:** through the *existing allowed External Services
   application's* provider-scoped terminal only, inspect the exact names,
   owners and active sessions for PostgreSQL databases and the presence of the
   registered Rauthy OAuth client. The non-startup source
   services/external/owner-readiness.psql is a SELECT-only query scoped to ten
   known Briareus database names; it reports DB existence, current-role owner
   match and active connection counts, without inspecting application tables.
   The same file is copied read-only into the existing PostgreSQL image at
   /usr/local/share/briareus/owner-readiness.psql; it is NOT executed by
   entrypoint or healthchecks. Run it ONLY from an approved operator terminal
   inside the existing External Services Application, never through a global
   host or a credential dump.
   Do not dump tables, credentials, private
   JWKs, users, provider encryption secrets or other projects. A file in Git
   and a successful Coolify build are not evidence of existing databases.
3. **Recovery fence:** obtain independently verified restorable backups of
   precisely selected domain databases **and** protected
   `briareus_rauthy`/Rauthy durable signing state under the existing
   privileged operator process. Verify backup identity and a recovery
   procedure before any destructive action. Do not treat `Coolify storages=0`
   as evidence that a Docker named volume is absent. Never prune
   `postgres-data`, `valkey-data` or `rauthy-data` globally.
4. **Stop just the affected product owners** on their authorized existing
   Application UUIDs, and verify active domain connections have quiesced.
   Rauthy, PostgreSQL and Valkey remain operating; no vendor-stack teardown
   or encryption rotation. Do not blindly stop every Briareus application
   or modify unknown containers. Confirm that public Gateway/Hands cannot
   issue new writes to databases selected for replacement.
5. **Exact database set:** for a clean Platform/Resources baseline,
   `briareus_platform` and `briareus_resources` need explicit, separately
   qualified empty schemas/databases. Include `briareus_access`,
   `briareus_files`, `briareus_runtime`, `briareus_reverse` or
   `briareus_ingest` **only if their owning current release explicitly
   requires an incompatible fresh baseline and the operator accepts the
   corresponding data loss**. `briareus_identity` and `briareus_dev`
   are candidate retired databases, not automatic deletion targets: first
   verify that *no* remaining service consumes them. Never use a
   broad `briareus_%` drop, SQL `CASCADE` against unknown objects, or
   general Docker-volume cleanup. Exclude `briareus_rauthy` unconditionally.
6. **Controlled activation:** only after approved exact target selection and
   real provider/database backups may the authorized operator perform the
   owner-specific database recreation. Source bootstrap itself contains no
   destructive DDL; starting a new image without first coordinating the
   selected owner schema may fail closed. Check each Alembic head and owner
   readiness separately; do not stamp around incompatible migrations.
7. **Consumer acceptance and rollback:** verify that Rauthy issuer/JWKS and
   existing `briareus-control-panel` registered client survive unchanged
   (prefer comparing the public keyset before/after), PostgreSQL/Valkey probes
   pass, new Platform/Resources migrations match their clean baselines,
   authenticated subject→Platform User binding is re-enrolled through the
   approved operator path, and denied permissions remain denied. Rollback
   an incompatible product owner against *its own* backed-up DB; never roll
   back provider secrets/clients by restoring an unrelated domain snapshot.

All of the above is a **plan/checklist**, NOT live DB reset confirmation.
The source-only verifier `services/external/provider_contract.py` checks
that current Git still preserves the provider and contains no reset SQL.
The old repository-level static gate `deploy/verify_deploy_static.py`
references five databases including Identity and requires updating by its
designated editor in the coordinated large release; Deployment will not
silently take ownership of that cross-lane path.

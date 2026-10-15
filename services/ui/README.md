# Briareus Control Panel UI

This is one independently deployable **Vue 3 / TypeScript / Bun** frontend service.
Source, local dependency lock, Dockerfile, Docker-specific ignore, Nginx and
Coolify Compose are all in `services/ui/`. It owns no SQL data,
Identity credentials, Authorization grants or MCP Hand runtimes.

## Public paths

- `GET /` — static, indexable Briareus project landing from `public/_site/index.html`.
- `GET /robots.txt` and `/sitemap.xml` — public landing crawler files.
- `GET /panel/` and `/panel/assets/*` — Control Panel UI SPA, `noindex,nofollow`.
- `/api/*` — same-origin browser requests to the separate **Control Panel API**,
  NOT to Identity directly. Gateway routes API and Hands separately.

The browser calls **only same-origin Control Panel API** routes under
`/api/*`, never the provider Admin API or individual MCP Hands directly.
The canonical API revision is **`/api/v1`**. Identity operations (native
Init/capabilities/PoW/cancel, session/config/logout and current Platform
User/Project `me`) belong under `/api/v1/auth/*`. Resource APIs use their
own paths: `/api/v1/agent-sessions`, `/api/v1/approvals`,
`/api/v1/catalog` and `/api/v1/files/read`. The unversioned browser routes
are retired, with no rewrite, silent fallback or hosted-provider link.
The only exception is the **private OAuth return endpoint**
`GET /api/auth/oidc/callback`, pinned to Rauthy's existing registered
redirect URI and not called by the Frontend. Changing that callback requires
an independently coordinated Backend/Deployment OAuth client update.
Production `src/app/App.vue` now mounts exactly **one** login and Platform
composition, `OidcPanelPage`, instead of branching into the unreachable legacy
`PlatformPort` UI. The full verified User/Project workspace still requires
current BFF owner proof. That main workspace loads as an asynchronous JS
module; the initial static shell shows a localized, noninteractive status
until it is available. If the module asset fails during a Development
rollout, a bounded read-only error screen offers an **explicit reload**;
missing JS does not open a guest, old Identity or hosted-Rauthy path, and
there is no background retry of POST/authentication commands. Protected
AgentSession, Catalog, MCP module, Dashboard and Settings bundles are also
lazy-loaded **only when the parent has a current BFF User+Project proof**;
they provide their own noninteractive pending/failed states and manual reload.
A missing protected-section script is a presentation failure, never an
authorization fallback. Only an explicitly DEV-built source can load the
isolated local design preview; the production entry has no guest/legacy
Identity fallback or hosted-provider login action.

The default `/panel/` screen is now the **Briareus sign-in form inside
the permanent Control Panel sidebar/header**. Anonymous navigation does not
open a guest MCP preview; direct protected hashes return to the sign-in
route. Current Rauthy OIDC session is checked read-only, with stable
in-place loader/status UI. The earlier custom Identity client/form has been
removed from this Frontend source.

**Current native sign-in boundary:** owner decision #536 supersedes the
hosted Rauthy login page. Briareus owns the sign-in UI and must add its
own MFA continuation once Backend supports it; Rauthy remains the sole
credential, OTP and token authority. The
Frontend uses the actual Backend POST `/api/v1/auth/start` (201,
`first_factor_required`) via the same HTTPS Control Panel origin, only when
the user explicitly checks preparation. Backend now exposes `GET /api/v1/auth/capabilities` and the locally
implemented `/api/v1/auth/first-factor` and `/api/v1/auth/cancel`.
Only the **exact capabilities GET** is consumed before each UI Init; it must
report the supported `rauthy-native-v1` first-factor/PoW/cancel shape. The UI
can explicitly cancel a pending Init, and requires HTTP204 to claim a confirmed
cancel. A request timeout is not cleanup success. The Backend POST
`/api/v1/auth/pow` reserves a one-use challenge; the UI still MUST NOT
consume it before a verified credential+official sPoW worker can submit the
first factor. The credential form remains disabled, since its integration is
not accepted. These are unauthenticated precredential steps. The UI never
renders a PoW challenge as a User identity or stores a provider token/CSRF;
it shows unavailable when the exact native capability is absent or invalid.
Although Backend exposes the first-factor API, the UI's credential submit,
MFA and signed-session continuation remain disabled pending independent
end-to-end acceptance. The official upstream Rauthy 0.37.1 browser solver
(sPoW 0.7.0, fixed SHA-256 and Apache-2.0 license) is now vendored under
`features/platform/vendor/spow` and runs only inside
`features/platform/model/rauthy-pow.worker.ts`. It accepts a bounded public
one-use challenge, has no password, provider cookie, CSRF, private bearer or
Cedar role, and is cancellable. Its isolated browser test validates actual
SHA-256 work at 1440/390px. It is **not called by Control Panel** and
satisfying PoW is neither Rauthy authentication nor Platform ownership.
No public challenge is fetched ahead of actual first-factor submission. Disabled credential placeholders have no
Vue-bound username/password state or password-manager autocomplete; while a
native Init is pending, UI repeat submission is disabled until its server-
reported TTL expires. A native Init response with unexpected fields is rejected.
No browser redirect to Rauthy's hosted login UI is an accepted sign-in path. The former PKCE callback remains private
Backend plumbing, not an external login UI.
Native Init lifetime is measured from request start, not extended by a delayed
response. Monotonic round-trip time also counts when the wall clock pauses.
Cancelled or already-expired replies cannot publish a prepared state.
The page clears a completed preparation on identity changes, shows expiry
explicitly, and rechecks both wall-clock and monotonic deadlines on return to
the foreground; no background retry or premature PoW request is added.


The login status panel follows RauthySignIn's existing state event.
When the parent OidcPanelPage supplies a freshly checked Rauthy
session snapshot, the child adopts it without a second session/config
GET, timer poll or tab-visibility refresh; the parent retains all
session and Platform-membership revalidation. If standalone, the
RauthySignIn component still owns its own refresh and logout.
On confirmed logout, uncertain logout or expired current-user proof,
the parent invalidates the cached login snapshot so a newly mounted
sign-in screen cannot display a stale `signed_in` state. The UI must never
submit credentials through the retired Identity route, use OAuth ROPC,
invent a Rauthy login endpoint, or store passwords/tokens in JS storage.
Backend+Deployment own the actual native first-factor/MFA session-completion contract.

A child component echoing the same provider snapshot is not a new auth event.
A real logout or changed identity invalidates older owner reads before their
late response can restore the previous User. Starting logout removes action
widgets immediately rather than leaving them active while the cookie is being
revoked. An unconfirmed logout is unavailable, never still signed in.

`GET /api/v1/auth/me` is the independent short-lived (maximum 30s),
cookie-bound, Rauthy issuer/subject-bound **Briareus User/Team/Project proof**.
Once the real Backend owner adapter answers positively, `OidcPanelPage`
opens the full Briareus sidebar/dashboard/MCP layout and read-only
Team/Project identity views, preserving deep links. The UI revalidates
membership before expiry and on return to the browser. The selected Project
is shared across Home, Projects, AgentSessions, Integrations and Variables,
kept only while the same verified User retains the relevant permission, and
reset immediately when Rauthy changes principal or owner rights are revoked.
Catalog never treats that UI selection as an execution grant. Signed-out, denied,
invalid, expired or unreachable owner state returns to the login screen
without opening operations. **Sidebar visibility is presentation only** and
never a Cedar decision.

For the **first MVP landing screen**, the server-confirmed User/Team/Project
view is followed by one direct **Open AgentSessions** action instead of
placing an unavailable observability dashboard into the login-success
path. The button appears only for a Project with owner-reported
`use_resources` or `approve_agent_session`; it is disabled without those
rights. This is *visibility only*: each session, approval, creation or revoke
request still checks the current Project/owner action independently through
the BFF, and no rights or records are manufactured in Frontend. Advanced
dashboard/observability remains on its dedicated navigation route.

The Integrations and Variables navigation screens now consume the actual
LOCAL Backend `GET /api/v1/catalog?project_uuid=UUIDv4&kind=integration|variable`
read-only route for verified Resource Catalog nonsecret metadata. They show
only `resource_uuid`, `kind`, `owner`, canonical display `key` and
`version`, after a fresh Rauthy-bound Platform Project `use_resources`
proof. Team ownership is matched against both current Team membership and
selected Project owner. Strict shape checks reject foreign/overbroad rows
or any returned secret/credential/value field; no writes, credential leases,
variable values or invented MCP resource permits. Local DEV preview never
requests the Catalog BFF. The Resource owner source must still be deployed
with trusted peer verification before this view can show actual data.

Normal AgentSession creation, current Project-scoped session inventory,
approval queue and server-authorized revocation use their *own* same-origin
BFF routes and fresh membership checks. The per-session inspector consumes
`GET /api/v1/agent-sessions/{session_uuid}?project_uuid=...` using the
same owner-bound DTO validation as the inventory. It clears old content on
failed refresh, permission change, expired proof or a mismatched response.
Revoke uses the version from this exact-session GET, independent approver
proof and a canonical idempotency UUID, then confirms the exact session again.
A capped list, missing endpoint or absent row never proves that revoke succeeded. On passive deadline expiry, only the
elapsed active row is hidden from that owner's current snapshot; unaffected
sessions and historical records remain visible. This is presentation only,
not a browser-authored expiration/revocation decision.
A known canonical session UUID can be opened independently of the capped list.
Only HTTP404 with `AGENT_SESSION_NOT_FOUND` means a scoped missing/hidden
record; a generic missing route remains unavailable. After an ambiguous revoke
reply, one exact read may show the current state, but the UI labels that as an
observation, not as confirmation of the missing command receipt. No POST is
replayed. The original session remains directly inspectable when reconciliation
is unavailable.

No optimistic success, invented grant revision or client-made permit exists.
Session and approval responses also validate the six exact Runtime Hand
action/resource-kind pairings and deny forged, duplicate or incomplete
elevated effects. The live owner adapters still require independent
acceptance and source-backed resource picker DTOs before elevation requests. Reserved Files
`project-path-v1:<Project UUIDv4>:<path fingerprint>` selectors must belong to
the selected Project on every session/approval/elevation read or write.
Malformed/reserved aliases and cross-Hand use are rejected; the browser never
constructs these selectors from arbitrary paths or treats a digest as ownership. Legacy
`PlatformPort` remains fail-closed until complete per-service management
permissions and CRUD/streaming DTOs can be installed independently.
No UI-local claim or Rauthy subject creates a Project, grant or privilege.

### Operation continuity and upcoming Files integration

Normal-session creation is prepared as an immutable in-memory request intent.
If the response is lost, invalid or HTTP503, the Panel retains the original
serialized body and Operation-UUID/Idempotency-Key instead of starting another
creation. The explicit **Retry original request** action revalidates current
User/Project permission and resends precisely that intent. Pending parameters
and the new-create action are locked; navigating between tabs or Panel routes
does not replace the pending key. Receipt recovery is labelled as the result of
the original creation, not a new session or a current grant. Recovery stops
at the normal 24-hour session lifetime, before the owner's seven-day deduplication
retention boundary. A closed page, logout or different identity clears this
memory; there is no credential or request journal in browser storage.
The recovery limit uses both wall and monotonic clocks and latches expiry:
restoring the clock cannot revive an elapsed request. The shared command
orchestrator snapshots User/Project identity before verification, retains an
interrupted dispatch for its original owner, and does not erase an earlier
uncertain creation when a later retry is denied.
A creation/recovery receipt can open the exact current-session inspector
without another POST. This distinguishes the original creation from a later
revoked/changed session. Approved requests likewise link to their issued child
session through the same owner-checked point-read API. That read does not reuse
an approval as a grant; lost Project visibility or invalidated parent records
closes the inspector and discards its data.
Request details are also readable without approver privileges: initiator,
current request revision, exact operations/resources and resolution references
come from the current list response. Non-approvers only see their own requests;
an overbroad owner reply is rejected instead of being silently filtered.
Inspecting a request never starts a decision or an elevation request.

Refreshing a still-current `/me` proof for the same User/Project does not reset
a confirmed normal-session result or abort create/revoke/approval POSTs.
Changing the User, Project or required permission invalidates the old command;
expiry is still enforced independently. An open approval/revoke confirmation
survives a same-scope proof refresh only while its row and revision remain
current. Confirmation is disabled during revalidation and closes on a changed
revision, revoked action, failed read or lost owner scope. Approval decisions revalidate current
membership and re-read the exact approval revision before one idempotent POST,
then confirm status/revision/resolver through a fresh GET. A resolution must
advance exactly one submitted revision and preserve the original requested
effects. Pending receipts contain neither a resolver nor an issued session;
approved receipts name a different resolver and child session, while rejected
receipts cannot claim a child grant. A newly requested approval's returned UUID
must match its operation UUID. The final GET must also preserve the exact
requested effects and the issued child session from the receipt, not merely
its status and resolver. A lost response or server 5xx causes one read-only
reconciliation, never another POST. If the exact original request is present,
its state is labelled as observed, not as a confirmed command result. Absence
from the capped list, substituted effects or inconsistent revisions leave the
outcome uncertain and discard stale actionable rows.

The source-backed `requestSessionElevation` client prepares the actual
`POST /api/v1/approvals` contract: bounded exact Hand/resource tuples,
1–300 seconds, current grant revision and one operation/idempotency UUID.
It accepts only a matching `202 pending` result, not an elevated grant. No
component mounts this action until a genuine resource picker and fresh
User/Project checks exist. Local contract tests do not prove resource ownership.

Files navigation on both direct and nested MCP routes links to AgentSessions
only for the currently verified resource-capable Project. Upload, download,
write and read execution remain disabled without their BFF/Hand integration.
`FilePreviewPane` can decode a future owner `readResult` matching Runtime's
unpublished Files-read adapter (`path`, `size_bytes`, `sha256`,
`content_base64`). It bounds 262,144 bytes, verifies canonical relative paths,
base64 length/padding and SHA-256, distinguishes strict UTF-8 from binary, and
renders escaped text only. The complete accepted text is browsable in bounded
8,192-character fragments rather than silently ending at the first 64KiB.
Fragment boundaries preserve Unicode pairs and CRLF; literal case-sensitive
search covers the bounded input, with at most 500 retained match positions.
Binary data displays byte count and checksum metadata without rendering as text.
A new input, denial or invalid response clears previous content and search state. The checksum verifies byte consistency, not a
signature, resource ownership or a Cedar decision. No Files network endpoint
is invented or enabled by the preview; changing input/scope discards old data.
Raw `content` strings are accepted only in the DEV-only design workbench;
production file preview requires a checksum-validated owner response.

The Files screen now verifies the selected Project through exact
`GET /api/v1/auth/me?project_uuid=...`, then reads the existing bounded
AgentSession inventory. It displays only active, nonexpired `files.read` /
`read_file` resource tuples from parsed owner records, with source
session UUID, revision and opaque resource identifier. An action-only normal
session has no Files resource scope. The list may be capped at 50 sessions;
absence is not evidence of revocation or deletion. Losing Project permissions,
changed Project ownership/version, expired server proof or an aborted read
clears stale scope. Individual Files-session rows expire independently:
one elapsed row must not remove an unrelated still-current read-only row. This screen
never passes those opaque resource selectors to a Hand or claims Cedar Permit.
Backend now defines a **source-only** `POST /api/v1/files/read` facade with
bounded input `{project_uuid,agent_session_uuid,expected_grant_revision,
path,max_bytes}` and owner-verified `{path,size_bytes,sha256,content_base64}`
output. The typed Frontend client exists in
`features/files-preview/api/files-content.ts`, but is **not exported to or
invoked by the product UI**. The reader streams at most 384KiB of success
JSON, caps error JSON at 4KiB and cancels stalled body reads promptly upon
AbortSignal; oversized/error replies never enter unbounded `response.json()`.
It requires one exact current session, an owner-
supplied canonical Project-relative path matching a current
`files.read/read_file/workspace_path` selector, and it caps raw response bytes
before verifying SHA-256. A digest-only selector cannot be reversed to a path
in the browser. The Backend's trusted Files content owner is not yet wired,
so this endpoint correctly returns 503; no speculative file path field or
read button is enabled. BFF and Files Hand must independently recheck signed
Rauthy identity, Project, session revision, Cedar, mapping and expiry both
before and after filesystem IO. No browser-supplied Permit or private Hand URL
is accepted.

Local browser evidence must identify the served build. The Runtime integration
harness may serve its own pinned copy rather than this worktree's latest `dist`.
A successful rebuild alone does not update that copy. Candidate-static browser
fixtures and the actual Gateway-served UI are separate validation levels; API
fixtures must never be reported as authenticated Rauthy/Platform/Cedar acceptance.

Appearance preferences are RU/EN, dark/light, density, Graphite/Indigo/Amber
accents and sidebar state; these are display-only, never authorization.
Shadcn-vue's generated Reka UI primitives own the shared Button/Card/Input/
Sidebar/Tabs/Table/Popover/Select/Switch/Dialog/Badge components. FSD
navigation, module operations and the composite shell are owned by distinct
features/widgets with public imports; no module server operation is enabled
until a real scope-bound API exists.

## Local UI design workbench (development only)

To compare the Control Panel visual states without an identity service, run:

```sh
bun install --frozen-lockfile
bun run dev -- --port 43197 --strictPort
```

Open `http://127.0.0.1:43197/panel/?ui-preview=1#platform/mcp`.
This Vite **DEV-only** workbench allows navigation through module and settings
layouts, direct links such as `#platform/mcp/files/settings`, and explicit
loading/empty/denied/unavailable presentations. The
`#platform/sessions` route previews the shadcn tabbed Current sessions /
Approvals / Create session workspace, including server-shaped empty, loading,
denied and unavailable views, without fabricated users, records or grants.
The `#platform/mcp/web` preview has local-only sample browser tabs; the
`#platform/mcp/files` preview accepts a bounded browser-local text file and
never uploads its contents. It never installs a
`PlatformPort`, fabricates a User, enables tool calls, writes approvals or
issues auth tokens. Production bundles have no preview route.

Use a real browser at mobile and desktop viewports for UX acceptance. The
native build and an HTTP response alone are not screenshot/click acceptance.
`/panel/` without the dev query stays on the real sign-in screen.

## Native localhost HTTP workflow (default development path)

**No Docker or HTTPS is required to build, view, iterate on, or visually test
the Control Panel UI.** The default `bun run dev` and `bun run preview`
both listen only on `127.0.0.1` and do not connect to a Backend without an
explicit opt-in. For read-only and source-authorized same-origin API checks
against the already-running LOCAL Runtime Gateway, opt in to the fixed
API-only Vite proxy:

```sh
cd services/ui
BRIAREUS_LOCAL_HTTP_API_PROXY=gateway bun run dev -- --port 43198 --strictPort
# HTTP browser UI: http://127.0.0.1:43198/panel/
# GET /api/v1/auth/config and /session now reach ONLY native
# Gateway http://127.0.0.1:18925 via fixed Host allowlist.
```

This is purely Vite **dev/preview tooling**. It never adds public
upstreams, Docker DNS, Authorization grants, test identities, TLS trust
exceptions or OAuth fixture code to the production bundle. Only the
`/api/` prefix is proxied to the exact `127.0.0.1:18925` Runtime-owned
native Gateway with its canonical fixed Host; no Rauthy operator/Admin
REST or Hand transport is proxied. Passing actual GET /config200,
session401 and /me401 confirms only safe HTTP routing, not sign-in.

Current native authentication uses secure `__Host-` cookies. HTTP localhost
remains useful for ordinary UI and read-only API iteration; native prelogin
requires the Runtime-owned HTTPS origin. The UI does not offer hosted Rauthy
navigation or weaken the provider's cookie, Origin, PKCE or Userinfo checks.

## Local integration acceptance

Identify the exact served UI bundle before a browser run. The Runtime-owned
Gateway may serve a pinned UI copy rather than the latest `services/ui/dist`.
Do not restart Runtime's processes or silently substitute their source.

`tests/fixtures/peer-management-wire.py` launches the actual selected Backend
membership/management/Catalog routers on a dynamically allocated loopback port.
Run it with the Backend Python environment, an explicit `--backend-source`
path to its `services/api/src`, and an explicit `--bun` executable. Its sibling
TypeScript file calls the actual Frontend clients over HTTP: exact Project,
creation and idempotent recovery, session list/detail, elevation request,
approve/deny, revoke, Catalog and denied/conflicting/missing responses.
The fixture injects temporary in-memory session and owner sources. It is a
wire-contract check, not Rauthy, SQL or Cedar acceptance; it makes no writes
to those systems and stops its own server and child process afterward.
Neither file is imported by the application or creates a product route.

The retained `scripts/local-stack-readiness.py` and `local-oidc-start.py` are
**historical transport diagnostics**, not the current native-login acceptance
contract. They preserve exact former issuer/client and callback checks for
explicit investigation, but hosted authorize HTML or an old successful
checkpoint must not be interpreted as native first-factor/MFA readiness.
The current native UI contract is described at the top of this document.

## Standalone native build

From this directory:

```sh
bun install --frozen-lockfile
bun run build
bun run test  # persistent OIDC, current-session/revoke and approval contract tests
```

`dist/` is disposable generated output, never source-controlled. The source
has one Vite build with `/panel/` asset base and separate public files; no
extra Gateway HTML engine, Jinja or SSR service is installed.

## Coolify Development service

Existing Briareus Development application UUID:
`pxv5fbwcogun3va4vygnejd4` — rename display to **Control Panel UI**, but
reuse the SAME application (not a new instance).

- Base directory: `/services/ui`
- Compose file: `/docker-compose.coolify.yaml`
- Service-local Dockerfile: `services/ui/Dockerfile`
- Default Watch paths: `services/ui/**` **and** `services/external/**`.
  The latter is the owner-required directory-wide default for **all** services,
  not a manually curated list of vendor files. It does not add SQL migrations
  to UI or grant permission to edit the External stack.
- Existing private `briareus-net` remains. Canonical UI DNS is
  `briareus-control-panel-ui:8080`; Runtime/Gateway owns the atomic migration
  from any compatibility alias. Do not create a second UI or remove an active
  Gateway route before Runtime confirms the local DNS switch.
- Only Gateway owns the public `briareus.koba-nexus.ru` origin.

A UI-only edit must not build Control Panel API, Identity or the Hands.
Do not add SQL migrations, credentials, additional unapproved shared watches or public UI
secrets. Observe real Coolify deployment and `/`, `/panel/`, assets, sitemap,
then separately report any still-unavailable backend-authenticated API.

## MCP module migration

The legacy Browser, Files, Terminal, GitHub/GitLab, Analysis, Calls, OAuth,
Observability and service-tool **interface inventory** is preserved as
separate modules with nested settings **behind verified Platform access**.
File preview, repository grouping and observability provider panels show
honest unavailable states until read/write BFF DTOs and current grants exist.
Global display preferences are functional; backend module settings require
verified, provider-agnostic Control Panel API DTOs.
See `docs/services/ui/mcp-module-migration.md` for the evidence and missing
BFF contracts.

The small `tests/fixtures/files-preview.entry.ts` bundles only the existing
Files component for isolated local browser acceptance. It is not imported by
`src/main.ts`, adds no product route and makes no product API call. Building
that fixture separately allows browser validation without a concurrent Vite
server in a process-constrained workspace.

### Scoped inspection and lifecycle ownership

Catalog integrations and variables expose only the existing nonsecret metadata
GET. Project/Team owner filters and text search operate on the returned records;
the 50-record cap is explicit and no pagination endpoint or secret read is
invented. Record details follow the latest accepted list revision, survive a
same-scope proof renewal, and close when the record, identity or permission is
no longer present. A filter miss is distinct from an empty source response.

Catalog, session lists, approvals and creation share a small local proof-lifetime
primitive. The **parent Controller** additionally binds the current Rauthy
identity and User/Project owner proof to independent monotonic lifetimes, so
a wall-clock rollback cannot extend protected navigation/commands while an
asynchronous BFF renewal is stalled. Fresh owner reads acquire new bounded
leases; losing or changing identity clears both immediately. This guard
cancels expired presentation even with unchanged parent props, checks the
foreground deadline and never turns a local clock observation into Cedar
Permit. It is a UI invalidation guard, not a server permission.
The session and approval inventories now age individual actionable records:
one elapsed AgentSession or pending approval is removed from its current
presentation snapshot and any matching open confirmation is closed, while
unrelated still-current entries and owner-returned resolved history remain.
When every actionable record has elapsed the list becomes stale until a
fresh owner read. No browser expiration is converted into a server status,
permit or command receipt. In-flight commands keep their own exact-source
reconciliation lifecycle rather than being aborted solely because another
listed record's deadline elapsed.
The exact-session inspector uses the same guard for Project access and for
an active session's own expiry. When the latter elapses, the snapshot is
hidden as stale; only a fresh owner read can display the current terminal
state. This local deadline never writes an expired/revoked status to the owner.


The main OIDC controller owns logout from both verified and identity-only views.
A child requests that operation rather than racing a separate POST against the
parent's membership read. The controller hides prior state immediately, cancels
older reads and records only the current logout result. Standalone identity
widgets retain their own logout behavior without refreshing over an in-flight
logout. `tests/fixtures/proof-lifetime.entry.ts` is an isolated component-only
acceptance entry; it adds no application route or authentication provider.

Before a Project command, the UI now reads the source-backed
`GET /api/v1/auth/me?project_uuid=<canonical UUIDv4>` contract, verifying one
exact returned Project and at most its owner Team. The ordinary `/me` remains
navigation inventory only. No fallback to an inventory scan, another Project
or client-inferred membership is used on denied/unavailable point reads.

The Project scope selector can request an exact known Project even when it is
absent from the capped navigation inventory. A point proof is shown separately,
never merged into the inventory. The selected scope survives view changes and
proof renewal; command checks remain bound to that same Project. Switching
unmounts old action widgets before the owner lookup. A denied point lookup does
not silently choose another Project. Returning to the inventory cancels a
pending lookup and rejects its late response. Logout or a different Rauthy
issuer/subject/client clears the scoped selection, including after an outage.

# Control Panel MCP modules — functional migration boundary

**Owner:** Frontend; canonical Git `KobaProduction/briareus`.

**Source baseline:** pre-cutover `admin-web-app/src` at `e41085d`. Do not
revive the old `admin-web-app` deploy tree, `ant-design-vue` dependency, native
password session, global event bus, or direct MCP/Hand requests in the browser.
The current source and both Compose files live in `services/ui/`.

## Design parity checkpoint — baseline e41085d

Source-compared to actual historical `admin-web-app/src` at commit `e41085d`
(not to an assumed screenshot). Its `app/App.vue` and
`shared/ui/SidebarNav.vue` established a compact permanent left sidebar,
sticky header and nested GitHub/GitLab, SigNoz/Coolify and settings entries.
Its `pages/dashboard/DashboardPage.vue` grouped MCP calls and latency,
integrations and OAuth, analysis jobs and workers, and workspace storage.
Its BrowserPage used page/session IDs, capability-driven controls and a
reconnecting WebSocket, while FilesPage exposed paginated folder operations,
uploads/downloads and deletion confirmation through the retired pre-Control-Panel management API.

Locally restored so far: shadcn-vue/reka-ui persistent sidebar/header and
module deep-link submenu; neutral dark graphite and configurable accent;
dashboard group/card density with explicit unavailable/empty/loading states;
shadcn tabs, table, buttons, accessible select/switch, FilePreviewPane, repository
groups and SigNoz/Coolify source panels. No legacy pre-Control-Panel management API,
`ant-design-vue`, WebSocket endpoints, password store, or optimistic
privilege grants were copied.

A DEVELOPMENT-ONLY design workbench is available via
`/panel/?ui-preview=1#platform/mcp` on the local Vite dev server. It permits
safe navigation and bounded browser-local text-file preview; no sessions,
privileged actions or mock grants. The workbench code is excluded from the
production build by `import.meta.env.DEV`. Browser screenshot and mobile
interaction acceptance remain separate from build/HTTP/source validation.

Shadcn-vue migration continued through the read-only MCP operation panels:
`widgets/mcp-modules/ui/ModuleOperationsPanel.vue` now composes generated
Card/Content, Input, Badge, Button and Table primitives for Browser, Terminal,
Files and provider Git operations. It owns no credentials, socket, terminal
process, or fake server state; every operation lacking a real versioned
Backend DTO stays `disabled`. Historical BrowserPage's managed tab bar,
navigation/address box, screenshot and DevTools controls remain visible but
inert; the optional external-browser disclosure cannot create sessions.
The Terminal output uses the current semantic color tokens (no hardcoded
old dark-navy background). A page no longer imports another page: the
module workspace imports its FSD widget through `widgets/mcp-modules/index.ts`.

Local Chromium at 390px and 1440px navigated Web, Terminal and GitHub
with all unsupported operations disabled; zero app JavaScript errors,
no POST attempts and no horizontal overflow. This is design/layout
acceptance with an isolated DEV preview, **not** real MCP operation
acceptance or credential/permission verification.

Still requiring actual Backend BFF source/authorization for product parity:
browser tab/session inventory and streaming/reconnect, real files workspace
listing and download/preview, terminal execution and output, provider Git
groups/repository mutation, SigNoz/Coolify telemetry, and current AgentSession
approval/revoke. Disabled interface controls must remain disabled until
server contract and scope proofs are accepted.

## Rauthy-verified user shell (presentation, not authorization)

A fresh `GET /api/auth/oidc/session` confirms only the Rauthy subject;
`GET /api/auth/oidc/config` pins its issuer and client. Independently, an
actual `GET /api/auth/oidc/me` with the same HttpOnly browser cookie MUST
return a current, enabled Briareus User, an identical issuer/subject, bounded
30-second expiry and strictly validated Team/Project scope/ownership.
Only then does `pages/platform/OidcPanelPage.vue` open the normal Briareus
sidebar and read-only presentation pages, preserving
`#platform/mcp/{module}/{overview|settings|global}` deep links.
No anonymous or identity-only session can see the protected layout.

OIDC presentation routes explicitly **do not install PlatformPort or grant
Cedar capabilities**. Static module descriptions/drafts, honest unavailable
dashboard/analytics, local appearance settings and Project/Team IDs from
the verified current-user DTO are available as read-only views. Normal
AgentSession POST and approval list/resolve require their own server-side
permission gates and fresh Project proof; unavailable owners return 503,
never a simulated permit. Logout clears the local presentation only after
confirmed HTTP 204 from the server. Periodic expiry and tab-visibility
revalidation fail closed without keeping a stale privileged shell open.

Local Chromium/Playwright browser tests now cover positive mocked Rauthy
identity plus matching owner `/me` (full sidebar, deep links, normal session
503, logout 204), independent negative 401/403/503 and proof-expiry
fallback, and desktop/mobile responsive shadcn controls. **Only local
synthetic BFF fixtures were used; no real Rauthy user sign-in, Cedar
decision, database reset, GitHub CI or deployed Dev source was verified.**
Native persistent Bun tests separately cover identity/owner DTO rejection,
approval idempotency and normal-session result freshness.

## Module inventory and interface status

| Historical interface | New Control Panel module | UI shell / settings | Live data/action readiness |
| --- | --- | --- | --- |
| BrowserPage + old browser WebSocket | Web Browser (managed/external) | Preview, nested browser settings, tab/session empty state | Blocked: BFF WebSocket/session/capability/viewport/navigation/DevTools contract absent |
| FilesPage | Files | Preview, nested listing/overwrite/preview settings | Blocked: authorized BFF file list/transfer/delete contract absent |
| TerminalPage | Terminal | Preview, nested timeouts and shell settings | Blocked: authorized BFF workspace/job/interactive session contract absent |
| GitPage + VCS policy | GitHub, GitLab | Separate provider modules, account/repository settings | Blocked: authorized BFF account/repo/PR/check/action/credential lifecycle absent |
| AnalysisPage | Analysis | Preview and task settings | Blocked: authorized BFF project/program/import/analysis contract absent |
| CallsPage | MCP Calls | Preview and journal retention settings | Blocked: authorized BFF call history/details/realtime contract absent |
| OAuthPage | OAuth & Sessions | Preview and session-scope settings | Blocked: provider-agnostic BFF user/session contract absent |
| ObservabilityPage | Observability | Preview and time-range settings | Blocked: authorized BFF trace/log/metrics/deploy contract absent |
| General old settings | Global settings | Functional RU/EN, theme, density, display TZ | Local display preferences only; backend settings remain owner API |
| Teams/Projects/Users/AgentSessions | Server-proof owner views plus legacy greenfield source | Verified Team/Project IDs and source-backed normal Session/approval BFF clients | Source/local tests only; requires trusted owner adapters, live user and accepted authorization |

The module inventory is now reachable only through authenticated Control
Panel navigation; the former anonymous module-preview entry has been removed
at the owner's request. The login screen is first at /panel/, not a guest
catalog. The module UI is still explicitly fail-closed until BFF permissions
are available; it is not a simulated account or permission. No synthetic backend
results, fake websocket states or fake successful saves are provided. Local
module form drafts cannot write or persist privileged server settings. Global
UI display preferences do operate in the browser because they need no grant.

## Mandatory BFF contract handoff

Before replacing these disabled states with production operations, Backend
must provide source-backed, versioned, scoped **Control Panel API `/api/*`**
contracts with real routing to owning services and Hands. At minimum:

1. **Current User and scopes:** verified session start/end/current actor,
   audience, effective permissions, Project/Team access, CSRF and auth failure
   semantics. Rauthy is internal; no upstream auth URLs, admin token or browser
   provider console.
2. **Managed/external Web:** authorized session inventory, tab CRUD, navigation,
   viewport/theme, screenshot stream, live WebSocket proxy from browser to
   Control Panel API, reconnect and revocation behavior. Historical
   `/api/browser/operator/ws` is *evidence of old functionality*, not an
   accepted endpoint in the new API.
3. **Files/Terminal/Analysis/SVC:** scoped list/pagination/details and operation
   status, approved command ids, safe upload/download, console stream,
   cancellation/reconciliation and explicit refusal/permissions.
4. **GitHub/GitLab:** source-authorized identities, allowlisted repositories,
   PR/MR, branches, workflows/jobs and provider-specific settings/actions;
   backend holds all credentials and consent. Keep tokens out of UI state.
5. **Calls/Observability/OAuth:** authorized read/list/filter/detail/stream,
   backend time-range and retention policies with accurate data provenance.

Each module must receive its **own nested settings** from its owner via BFF;
interface-wide language/theme/density/TZ belong to **Briareus global settings**.
A settings draft cannot be submitted until the BFF publishes a verified
configuration DTO, update operation, permission proof and reconciliation path.

## Local-first HTTP UI and Backend preflight

Owner priority (2026-10-14): native, fixed-loopback HTTP replaces Docker
or a duplicate local HTTPS stack for daily UI/functional preflight.
`BRIAREUS_LOCAL_HTTP_API_PROXY=gateway bun run dev -- --port 43198
--strictPort` serves real Vite UI on `http://127.0.0.1:43198/panel/`
and proxies ONLY same-origin `/api/` to native Runtime Gateway
`127.0.0.1:18925` with a pinned exact canonical Host.
No remote proxy address is configurable; without the explicit opt-in
there is no API proxy. Current actual GET `/api/auth/oidc/config`
HTTP200 and anonymous `/session`/`me` HTTP401 through this local
HTTP Vite route are transport smoke, not positive identity.

The native HTTP Control Panel **does not initiate the legacy secure
hosted-login redirect** until Backend/Runtime approve a test-only
HTTP browser callback and session-cookie contract. This protects
disposable credentials from being redirected to the public Development
callback. Only the localhost OAuth link is paused: actual HTTPS
Control Panel continues using hosted code+PKCE. Neither the UI nor
Vite builds a fake User/Project/Cedar decision, and production assets
retain no local proxy path or secret.

This local HTTP path allows rapid shadcn/Project/AgentSession module
browser work independently of the separate TLS acceptance gate.
Production/Development deployment eventually requires real HTTPS and
secure-cookie verification, but no longer blocks day-to-day
Frontend functionality or safe HTTP preflight. Backend and Runtime
own any *temporary* insecure session-mode implementation exclusively.

## OIDC local-sandbox versus Development issuer separation

The **native local test stack** now has a working disposable Rauthy v0.37.1
issuer at `https://localhost:18444/auth/v1/` and a local test OAuth
client `briareus-local-panel`. This is deliberately distinct from the
existing Dev public issuer `https://briareus.koba-nexus.ru/auth/v1/`
with client `briareus-control-panel`. Frontend readiness has exact
endpoint + client pins for each profile and selects one only via explicit
`--profile dev|local-sandbox`. Ten dependency-free Python tests enforce
that one profile cannot pass using the other's provider endpoints.

Actual local HTTP now confirms UI/asset forwarding, Rauthy health/JWKS,
BFF config200, and correctly denied unauthenticated BFF session/me401:
the **nine-step local-sandbox precredential readiness gate passes**.
A separate real BFF `/api/auth/oidc/start` GET returns HTTP302 with
proper Secure/HttpOnly/SameSite=Lax transaction cookie, state/nonce and
PKCE S256, but its authorize URL uses the Backend canonical public
`https://briareus.koba-nexus.ru/api/auth/oidc/callback`. The disposable
provider's local OAuth client has a different registered callback and
originally returned HTTP400 for this generated authorize URL. Runtime
has since reconfigured its disposable provider and a repeated real
credential-free Rauthy authorize GET now returns HTTP200.
The Frontend also exercised a real Chromium 390px/1440px browser flow
through the actual Gateway and Rauthy with a **test-only local proxy
that rejects all outbound public callback requests**: the hosted sign-in
page loads and the exact one-time `__Host-briareus_oidc_transaction`
Secure/HttpOnly cookie is present, with no browser JS error or credential
submission. This establishes ONLY the browser precredential entry; a
genuine signed Userinfo/token and callback have not been exercised.
Backend's subsequently committed local source `b8e09d1` and
`386b49d` explicitly allow ONLY the pinned test-only
`https://127.0.0.1:18446/api/auth/oidc/callback` when source-injected
with exact disposable issuer/client; current real Dev/production callback
is unchanged. Runtime still owns the separate fixed loopback TLS 18446
listener, exact provider client registration and Gateway forwarding
to the test-only source. A valid sandbox authorize200 is not proof
the safe callback listener is running. The Frontend
`scripts/local-oidc-start.py --source isolated-tls --probe-provider-entry`
checks real 302, cookie state, Rauthy HTML200, isolated /panel/200
and anonymous /session401, and deliberately returns exit 2 until ALL
sources are independently accepted. A legacy Gateway precredential probe
may only run with explicit `--source gateway-legacy` and can NEVER
turn a publicly routed callback into test acceptance. No credential,
bearer or signed-user response has been produced by Frontend. **Do not** add a
throwaway sandbox client redirect to a live Dev endpoint without proof
that its entire callback roundtrip is isolated locally. No signed-user
token exchange or Cedar/Files Permit is accepted yet.

## Native multi-service preflight and release boundary

A user-visible Briareus Control Panel UI is now hosted **locally only**
on `127.0.0.1:18929`, while the Runtime owner exposes a bounded
local Gateway on `127.0.0.1:18925` and the Backend owner exposes
the real Control Panel API on `127.0.0.1:18928`.
Current native five-process smoke (including pinned disposable Rauthy and
Files Hand) confirms UI HTTP200 through Gateway with byte-identical JS,
provider Health/JWKS200, public OIDC configuration with exact existing
Briareus Dev issuer/client, Gateway private provider URL404 and
unsigned Files401. The private Valkey session/Platform owner still
returns HTTP503; no completed signed test-user login or Cedar Permit.
The acceptance gate `services/ui/scripts/local-stack-readiness.py`
therefore intentionally exits 2 with separate per-hop reasons, instead
of allowing a fabricated successful auth state.

The Frontend Compose's private DNS is only
`briareus-control-panel-ui:8080`. Current Runtime Gateway source still
references the older compatibility destination; coordinated source
fan-in MUST atomically switch the Gateway's fixed UI/API destinations
and allowlist in the same reviewed release. Running localhost's test
adapter can still use its previous names until the Runtime owner
switches its local mapping. Do not deploy the UI alias removal alone.
Existing approved Development application UUIDs and public paths are
unchanged; the native ports and Rauthy throwaway user accounts are
NOT a Development deployment.

## Read-only Resource Catalog metadata — independent owner scope

The Backend peer commit `1e96bf0` introduces a **LOCAL-only**
`GET /api/auth/oidc/catalog?project_uuid=UUIDv4&kind=integration|variable`
route backed by an authenticated private Resource Catalog reader. It returns
`{items:[{resource_uuid,kind,owner:{kind:"team"|"project",id},key,version}]}`,
maximum 50. No token, integration credential, variable value, secret field,
provider API key, lease or executable Hand scope is returned. The owning
service independently authenticates the browser's current Rauthy-linked
Platform Project `use_resources` right and its own signed private peer.

Frontend `features/catalog/api/current-metadata.ts` enforces canonical
UUIDv4, exact response keys (rejects extra secret-bearing fields),
owner Project/Team membership binding, canonical 1..128 display key,
positive integer version, no duplicates, <=50 results, current short
Platform proof, and same-origin cookie GET with no-store. The shadcn
`widgets/catalog/ui/CatalogWorkspace.vue` shows only permitted names,
identifiers, ownership and revisions, with Project selector, search, reload
and honest empty/loading/403/503/malformed states; no mutation buttons or
secret-value reveal actions. Native tests and Chromium fixtures enforce that
foreign Project/team rows do not appear and that DEV preview makes no BFF
calls. All Catalog rows are *metadata*, not hand-effect resource selectors.
A separate independently validated ResourceOwner catalog/exact selector
contract is still required before an elevated AgentSession request can be
safely constructed and sent.

Validation level is SOURCE/BUILD plus LOCAL CHROMIUM with synthetic trusted
BFF/owner responses; no real Dev Resource Catalog read, Token/API Key or
production authorization acceptance is asserted.

## AgentSession approval UX — local source-backed integration

The Backend peer's **LOCAL, unreleased** `services/api/src/control_panel_api/
_oidc_approvals.py` contract defines cookie-authenticated
`GET /api/auth/oidc/approvals?project_uuid=UUIDv4`, returning at most 50
records with current request status/version, requested actor/AgentSession,
operation/resource scopes, expiry and server-computed `allowed_actions`.
The Frontend `features/approvals/api/control-panel.ts` validates this DTO
strictly (UUIDs, allowed operations, scopes, expiry, duplicate IDs and
unexpected action grants), and the shadcn `ApprovalQueue` renders filters,
search, scoped details and empty/loading/forbidden/unavailable states.
The list is fetched ONLY after a Rauthy-bound, short-lived, server-verified
Platform Project proof with `use_resources` OR `approve_agent_session`, per the
Backend's current peer `1e5be95` source. The DEV design fixture never
fetches it or constructs an invented Platform User.

An approver's approve/deny action requires a fresh independent
`GET /api/auth/oidc/me` check, correct Project
`approve_agent_session` rights and non-self-approval, followed by the
real source-defined `POST /api/auth/oidc/approvals/{uuid}/resolve`
contract with exact canonical UUIDv4 `Operation-UUID` and
`Idempotency-Key`, JSON/Origin and `expected_approval_version`.
No optimistic `approved` state is shown; success requires verified
server response AND a fresh approval-list read. 401 expired, 403 denied,
409 revision conflict, 503 owner unavailable and uncertain network
completion remain distinct. A current grant revision is NOT part of the
current-user DTO, but it is now supplied by the independent server-owned
AgentSession inventory for that exact Project. Revocation is implemented
in a separate version-fenced UI flow; elevation requests remain disabled
until a validated scoped effect/resource selection source is accepted.
No arbitrary revision or wildcard resource is fabricated.

### Normal (non-elevated) AgentSession creation

New Backend peer **LOCAL-only** source at `d885a2b` adds
`POST /api/auth/oidc/agent-sessions`: an authenticated, Project-scoped,
version-fenced owner mutation with body `{project_uuid,elevation_policy:
"fixed"|"requestable",label:null|string}` and canonical equal UUIDv4
`Operation-UUID`/`Idempotency-Key` headers. The typed Frontend
`features/agent-sessions/api/open-normal.ts` requires an exact HTTP 201
result bound to that Project, `revision=1`, `status=active`,
`is_elevated=false`, bounded timezone-aware expiry, operations exactly
`["files.read","project.metadata.read"]`, and no resources.
`widgets/platform-context/ui/OpenNormalSession.vue` checks fresh
server user/Project `use_resources` proof before issuing any POST.

This is a *new normal session*, **not** a permission elevation. A confirmed
response is displayed in memory only with the returned server revision
and expiration; the UI does not persist it across reloads. A fresh, separate
Project-scoped inventory read is available from the Current sessions tab. A successful server response to a POST
without a valid DTO, or a network timeout, is **uncertain** and must not
automatically repeat the request. A real owner adapter and reauthorization
are still required before opening sessions succeeds in Development. This
read-only DEV-only visual preview never calls the API and never produces
a fabricated AgentSession.

### Current AgentSession inventory and versioned revocation

Backend peer local commit `1e5be9565b92dc7e44383b0856b1a565c9c5c37d`
adds `GET /api/auth/oidc/agent-sessions?project_uuid=UUIDv4`.
It returns a maximum of 50 server-current records, with original actor,
revision, state `active|revoked|expired`, elevation status/policy,
timezone-aware hard expiry, operations, bounded scope details, and optional
server-computed `allowed_actions:["revoke"]`. Read visibility is
`use_resources OR approve_agent_session`; a non-approver receives only
their own records and never a Revoke action. All of this is checked by the
independent Authorization owner behind the BFF, NOT inferred from a Rauthy
claim. The Frontend `features/agent-sessions/api/current-sessions.ts`
strictly checks UUIDv4 values, actor/Project ownership, operations,
scopes, duplicate sessions, version, expiry and allowed-action constraints
before showing them. Unsupported responses fail closed.

`widgets/platform-context/ui/CurrentAgentSessions.vue` uses shadcn
Table/Card/Input/Badge and an explicit confirmation Dialog. Before a
Revoke POST it reads a *fresh* `/api/auth/oidc/me` approver proof, then
re-fetches the current session and compares the original
`session_uuid/project_uuid/status/revision/allowed_actions`. Only after
matching does it send `POST /api/auth/oidc/agent-sessions/{uuid}/revoke`
with `{project_uuid,expected_grant_revision}` and exact canonical UUIDv4
`Operation-UUID=Idempotency-Key`. A 200 must return the exact current
session and a **higher** revoked revision, AND a subsequent list GET must
independently confirm the revoked state. HTTP 401/403/409/503, stale rows,
unknown outcomes and network errors never become optimistic success and
cannot trigger automatic repeated writes.

### Source-pinned exact Hand effect validation (2026-10-14)

Backend's local `9921b3b` and `1e1288c` enforce Runtime V2's six
Hand-specific action vocabularies and exact resource-owner scope coverage.
The Frontend `shared/lib/hand-effect-scope.ts` mirrors ONLY the **response
validation** subset (not Cedar permission creation):

- Files: `files.read`/`files.write`, `workspace_path`
- Terminal: `terminal.execute`, `workspace` or `job`
- Web: `web.access`, `browser_session` or `origin`
- SVC: `integrations.use`/`variables.use`, `repository`
- Reverse: `analysis.import`, `analysis_project` or `artifact`
- Infrastructure: `integrations.use`/`variables.use`, `application`

`project.metadata.read`, `agents.manage` and reserved
`integrations.manage`/`variables.manage` are not MCP Hand effects.
An existing normal Session's coarse operation listing is still valid and
does NOT imply a Hand Permit. A returned resource scope must have exact
four keys, canonical tool name, exact kind for that Hand, NFC untrimmed
resource ID with no controls, a matching supported action, and no duplicate
scope. Pending elevated approvals without resource coverage for **every**
requested action are rejected in the UI instead of offered for execution.

These checks never replace independent Authorization/ResourceOwner proof;
the UI does not construct selectors from an unverified free-text path,
browser origin, repository or database record. Such elevation creation is
still disabled pending an accepted trusted resource-selector catalog.
Native tests include invalid Hand/action combinations, wrong kinds,
duplicate selectors, malformed Unicode and all six valid source pairings.

A compact shadcn Tabs layout makes Current sessions the first visible
surface, with Approvals and Create session as separate on-demand tabs.
Users with `approve_agent_session` only may browse/resolve/revoke
according to server-listed actions but cannot create a normal session;
`use_resources` without approver rights cannot revoke. Switching
tabs does not invent records or bypass BFF scope checks. A request for
elevated operations remains blocked until independently authorized
resource/effect selectors exist; a free-form scope string is not allowed.

Local Bun tests cover positive/negative current-session DTO, version-fenced
revoke idempotency and no-retry after ambiguous POST. Local Chromium
with synthetic (not live) BFF responses validated desktop/mobile,
approver-only, a single Revoke POST followed by GET reconciliation,
shadcn Tabs and 503 fail-closed. The Backend owner routes remain local
source and physical Authorization/Platform integration is a separate gate.

The Backend factory currently defaults its current Platform and approval
owner ports to **unconfigured/503** in LOCAL source. No signed-in human
approval, production grant change, release, Dev deploy or full
product authorization acceptance is claimed from the Vue build.

## Validation level

`vue-tsc` + Vite build and UI route/preview acceptance establish source/browser
UI shell coverage, NOT MCP tool execution, signed OAuth, live WebSocket,
server settings persistence or full historical feature parity. The former
Historical pre-Control-Panel UI is a behavioral reference, not a permitted runtime auth shortcut.


## OIDC transition: real Rauthy sign-in panel

ControlPanelAccessPage embeds the independently controlled RauthySignIn
feature; the legacy first-user password proxy has been removed from
Frontend. Native Briareus username/password remains disabled until the
exact Rauthy challenge/MFA BFF protocol receives independent validation. The feature reads only same-origin
GET /api/auth/oidc/config and GET /api/auth/oidc/session. The
signed-out state is exposed only when public provider config responds
successfully and the mounted session route returns HTTP 401.
While provider/client/session storage are missing, the UI accurately
shows an unavailable message and does not present a dead login button.

Once ready, login navigation uses the fixed Backend-controlled
/api/auth/oidc/start Authorization Code + PKCE flow; never accepts
credentials or client secrets in frontend JavaScript. Identity is shown
only when the typed Backend session returns a signed upstream subject
with platform_membership_verified=false and empty permissions.
It does not unlock Projects/Teams/Hands. Same-origin POST logout is
reported successful only on BFF HTTP 204 (private session revocation).
OIDC backend and user/provider installation are separate runtime gates.

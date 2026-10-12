# Control Panel MCP modules — functional migration boundary

**Owner:** Frontend; canonical Git `KobaProduction/briareus`.

**Source baseline:** pre-cutover `admin-web-app/src` at `e41085d`. Do not
revive the old `admin-web-app` deploy tree, `ant-design-vue` dependency, native
password session, global event bus, or direct MCP/Hand requests in the browser.
The current source and both Compose files live in `services/ui/`.

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
| Teams/Projects/Users/AgentSessions | Existing greenfield Platform components | Original guarded source views remain, no invented records | Blocked: real current User and owner BFF DTOs |

The module preview is deliberately *unauthenticated read-only interface
inspection*, not a simulated account or permission. No synthetic backend
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

## Validation level

`vue-tsc` + Vite build and UI route/preview acceptance establish source/browser
UI shell coverage, NOT MCP tool execution, signed OAuth, live WebSocket,
server settings persistence or full historical feature parity. The former
Admin UI is a behavioral reference, not a permitted runtime auth shortcut.

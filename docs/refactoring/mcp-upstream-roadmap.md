# Upstream-first MCP refactoring roadmap

Status: architecture audit / migration roadmap  
Audit date: 2026-10-03  
Scope: public/provider MCP surfaces in `mcp-bridge`; this document does not redesign the frontend or choose a long-term SQL database.

## Executive decision

`mcp-bridge` should stop owning provider-domain implementations when a maintained upstream MCP already owns that domain.

The target product is a **policy-aware MCP bridge**, not a collection of parallel GitHub, GitLab, browser, observability and filesystem implementations.

The bridge should own:

- public OAuth/resource boundaries and ChatGPT-facing endpoints;
- account selection and multi-account routing;
- credential resolution and safe credential injection;
- authorization and Koba-specific policy;
- tool allow/deny policy and privileged feature gates;
- audit/redaction/telemetry;
- connection/session pooling and catalog caching;
- shared-workspace glue that an upstream server cannot provide;
- a small set of explicitly documented Koba extensions.

The upstream MCP should own:

- provider API semantics;
- provider tool schemas and descriptions;
- pagination and provider-specific errors;
- provider API version changes;
- ordinary repository / browser / observability domain operations;
- provider-specific resources and prompts where available.

This is the main architectural direction for the planned clean/DDD refactor.

## Important clarification: "agents already know this MCP"

There is no safe architectural assumption that a model has a hidden preference for a package merely because it is popular. The useful advantage of an official or established MCP is more concrete:

1. stable and recognizable tool names and schemas;
2. public documentation and examples that agent authors and clients can target;
3. upstream compatibility testing across MCP hosts;
4. upstream protocol/API/security maintenance;
5. less Koba-specific schema context for the model to learn;
6. less provider-domain code for us to maintain.

Therefore the goal is **schema/ecosystem interoperability and reduced ownership**, not an assumed model-weight optimization.

## Current inventory

Measured from the repository during this audit:

| Surface/module | Live tools | Python files | Approx. Python LOC | Current shape |
| --- | ---: | ---: | ---: | --- |
| GitHub | 96 | 38 | 6,437 | custom GitHub REST/GraphQL + custom MCP tools |
| GitLab | 35 | 19 | 2,141 | custom GitLab REST + custom MCP tools |
| Files | 12 | 6 | 663 | custom shared-workspace filesystem server |
| Web | 68 | 15 | 3,437 | custom curl + custom Playwright browser + official DevTools proxy |
| Analysis | 247 | 6 | 1,697 | dynamic schema/terminology facade over Ghidra MCP |
| Ghidra private adapter | 247 | 2 | 26 | thin MCP proxy; already correct direction |
| Terminal | 16 | 4 | 1,120 | custom persistent workspace/process/job runtime |
| Observability facade | 14 | 2 | 199 | custom SigNoz/Coolify composition |
| SigNoz implementation | included above | 2 | 263 | custom direct HTTP client |
| Coolify implementation | included above | 2 | 187 | custom direct HTTP client |

The largest duplicated provider-domain ownership is GitHub, Web, GitLab and Analysis. SigNoz/Coolify are smaller in LOC but have especially strong upstream replacements.

## Target architecture

```text
ChatGPT / MCP client
        |
        v
+---------------------------+
| Public gateway / OAuth    |        Koba-owned
+---------------------------+
        |
        v
+-----------------------------------------------+
| AccountScopedMcpProxy / Provider Proxy Port   |  Koba-owned
|-----------------------------------------------|
| account_id -> credential/base URL             |
| auth header/env injection                     |
| Koba policy + tool allow/deny                 |
| schema extension (only when unavoidable)      |
| audit/redaction/tracing                       |
| session pool + catalog cache                  |
+-----------------------------------------------+
        |
        +-------------------+------------------+------------------+
        v                   v                  v                  v
 official GitHub MCP   native GitLab MCP   official SigNoz MCP  native Coolify MCP
        |
        +---------------------------------------------------------+
                                  |
                                  v
                          provider APIs/services
```

For local capabilities:

```text
/web/mcp
  +-- Playwright MCP upstream --------> existing persistent Chromium via CDP
  +-- Chrome DevTools MCP upstream ---> same Chromium via CDP
  +-- Koba browser policy/operator ----> access gating/control plane only
  +-- Koba raw HTTP extension --------> exact request/download/stream cases

/analysis/mcp
  +-- transparent Ghidra MCP proxy ----> ghidra-mcp
  +-- small Koba extensions ----------> workspace transfer / catalog helpers only
```

### Generic account-scoped proxy is the key reusable primitive

Provider replacement should not produce a new hand-written wrapper for every upstream. Introduce one generic application port capable of:

- resolving `account_id` through Management/Valkey;
- selecting an upstream URL or process configuration;
- injecting `Authorization`, provider headers or process environment without exposing secrets to the model;
- adding an explicit `account_id` parameter to upstream tools when the public surface is multi-account;
- filtering upstream tools by Koba policy;
- preserving upstream names, descriptions, input schemas, output schemas, resources and prompts wherever possible;
- pooling upstream sessions and caching catalogs;
- invalidating sessions/catalogs when account credentials or upstream version/configuration change;
- applying audit redaction without transforming provider semantics;
- exposing upstream/version/capability diagnostics.

This component belongs in the application/infrastructure boundary of the future clean architecture. Provider-specific code should become configuration plus small extensions rather than thousands of lines of API clients.

## Provider-by-provider decision matrix

| Surface | Upstream candidate | Maturity / evidence | Decision | Koba code that remains |
| --- | --- | --- | --- | --- |
| GitHub | `github/github-mcp-server` | official GitHub server; HTTP + stdio; toolsets/tools/exclusions, read-only, lockdown, scope filtering; HTTP accepts per-request bearer credentials | **Migrate, high priority** | multi-account selection, account credential injection, branch/review policy, writer/reviewer identity contract, shared-workspace checkout, Koba-only maintenance operations |
| GitLab | native `https://<gitlab>/api/v4/mcp` | GitLab-native; Beta; GitLab.com/Self-Managed/Dedicated; OAuth DCR; toolsets and tool prefix support | **Migrate with capability/version/auth gate** | multi-instance/account routing, OAuth/credential mediation, protected-branch policy, shared-workspace checkout; temporary legacy fallback for unsupported GitLab versions/tools |
| SigNoz | `SigNoz/signoz-mcp-server` | official SigNoz server; self-hosted binary/Docker; HTTP mode; much broader logs/traces/metrics/alerts/dashboard coverage | **Replace custom HTTP client, very high priority** | account routing; per-account upstream process/config cache; read/write policy; audit/redaction |
| Coolify | native `<coolify>/mcp` | native Streamable HTTP; team-scoped bearer auth; tools/resources/prompts; broad infra/deployment coverage | **Replace custom HTTP client, very high priority** | account/team routing, read-only tool policy, token injection, safe audit/redaction |
| Browser | `microsoft/playwright-mcp` | official Microsoft project; can attach to existing browser using CDP; snapshot/actions/upload/screenshot supported | **Prototype then migrate custom `browser_*`** | Browser Operator, persistent browser lifecycle if still needed, Agents/Developer policy, per-tab access enforcement, download/workspace policy |
| DevTools | `ChromeDevTools/chrome-devtools-mcp` | official Chrome DevTools project; already proxied | **Keep current upstream model** | privilege gate, browser lifecycle hook, audit redaction, version pin/upgrade testing |
| Analysis | existing private `ghidra-mcp` | already an MCP upstream; bridge currently rewrites a large live catalog | **Simplify to near-transparent proxy** | project/workspace glue, explicit filtering, catalog search helpers only if upstream lacks them; remove semantic rewrites unless a product requirement proves their value |
| Ghidra adapter | existing `ghidra-mcp` | private adapter is only ~26 LOC and uses MCP proxying | **Keep** | auth boundary / internal routing only |
| Files | MCP steering-group Filesystem reference server | familiar reference schema; file operations and access controls; repository explicitly says reference servers are not production-ready | **Evaluate / partial standardization, not blind replacement** | attachment ingest, hard workspace root, byte/hash limits, audit, hardened production security; consider upstream-compatible naming/schema |
| Raw HTTP / curl | MCP Fetch reference server + built-in host web tools | Fetch handles ordinary web content, but reference servers are explicitly educational and Fetch does not replace exact HTTP/download/stream semantics | **Keep only narrow raw-HTTP extension** | arbitrary method/header/body, bounded binary download, SSE/chunk stream capture; ordinary browsing should use host web/search or optional Fetch upstream |
| Terminal | no steering-group production terminal server; Desktop Commander is established community software | broad process/filesystem features, but community security semantics differ; terminal commands can bypass its file `allowedDirectories` policy | **Keep current runtime for now; run a separate upstream evaluation spike** | non-root isolation, persistent workspaces, durable jobs/log cursors, PTY, process-group cancellation, bounded output/retention |
| Local Git | `mcp-server-git` reference server | official reference, early development; reference repo warns it is not production-ready and has published security advisories | **Do not replace production Git/workspace flows now** | current controlled Git workflow/policies until a production-grade upstream passes threat review |

## Detailed findings

### 1. GitHub: largest avoidable custom provider implementation

Current GitHub is approximately 6.4k Python LOC and implements repository contents, refs, commits, PRs, review threads, issues, Actions, GraphQL helpers, policies and tool registration itself.

GitHub now maintains the official `github-mcp-server`. Its HTTP mode is explicitly designed for reverse-proxy/container use and accepts an `Authorization: Bearer ...` credential per request. It supports toolsets, individual tool selection, exclusions, read-only mode, lockdown mode and permission/scope filtering.

That maps well to our multi-account architecture: Management remains the credential authority, while a generic proxy injects the selected account's bearer credential into the upstream HTTP request. We do **not** need the upstream stdio server's own login flow for this deployment model.

Do not delete all Koba GitHub code. Keep extensions whose semantics are ours rather than GitHub's:

- writer vs reviewer identity separation;
- mandatory branch/PR/reviewer gates;
- protected/reserved branch policy and expected-head CAS checks;
- local checkout into the shared workspace;
- any history identity rewriting / reserved-branch maintenance that is deliberately narrower than ordinary GitHub operations;
- account/capability inspection specific to Management.

The migration objective is to delete ordinary GitHub API plumbing and preserve policy orchestration.

### 2. GitLab: native MCP should become the primary provider path

GitLab exposes a native MCP endpoint at `/api/v4/mcp`. It supports GitLab.com, Self-Managed and Dedicated, OAuth 2 DCR, toolset selection and optional tool-name prefixes.

The important constraint is maturity/versioning: the server is still documented as **Beta**, and MCP/toolset support landed progressively across GitLab releases. Our self-hosted multi-account support means an account may point to an older instance.

Migration therefore needs a provider capability/auth probe:

1. resolve account/base URL;
2. probe native MCP capability/version;
3. validate that the stored account credential model can authenticate to that instance MCP endpoint (GitLab documents OAuth/DCR as the primary flow; do not assume every existing legacy token is MCP-compatible);
4. use native MCP when compatible;
5. temporarily route to the legacy adapter only for unsupported accounts/auth modes;
6. remove legacy REST code after all managed instances satisfy the native MCP acceptance contract.

This avoids making one old self-hosted GitLab instance block the architecture cleanup.

### 3. SigNoz: custom direct API client is now unnecessary

Our SigNoz implementation directly owns Query Builder v5 requests, log/trace queries, service discovery and field discovery. The official SigNoz MCP server now covers metrics, traces, logs, services, alerts, dashboards, saved views, documentation and more. It supports self-hosted deployment and HTTP mode.

This should be an early migration because:

- upstream domain coverage is substantially broader than ours;
- SigNoz API/query-model changes become upstream responsibility;
- our custom client is not adding strategic semantics beyond account selection/read policy.

The official self-hosted server is configured by `SIGNOZ_URL` / API key, so multi-account operation should use an **on-demand per-account upstream instance/process cache** or another isolated account-scoped transport. Credential changes must invalidate/restart that upstream instance. Also version-gate it: SigNoz documents that each MCP server release targets the latest SigNoz release and is not tested against older releases.

### 4. Coolify: native MCP replaces our thin API projection

Coolify exposes Streamable HTTP MCP at `/mcp`. Authentication is a bearer API token bound to a team. It already has tools/resources/prompts for applications, servers, projects, databases, services, deployments, logs, environment/storage metadata, integrations and automation.

Our custom client currently projects only teams, applications and deployments. Maintaining those REST projections is no longer justified.

The Koba Observability surface should proxy native Coolify MCP and enforce our desired read-only contract. Prefer both:

- a credential with read-only capability where Coolify permits it;
- a Koba tool allowlist/denylist so mutation tools are not advertised on `/observability/mcp`.

Do not rely only on tool failure after authorization; catalog filtering is better for safety and model tool selection.

### 5. Browser: official Playwright MCP can replace most basic browser actions

Our custom browser stack implements its own page IDs, snapshots, interactive refs, clicks, fills, selects, uploads, downloads, screenshots, waits and navigation. Microsoft now maintains `playwright-mcp` with accessibility snapshots and browser actions, and it can attach to an already-running Chromium through a CDP endpoint.

This matches our existing architecture unusually well: the persistent browser already exposes loopback CDP at `127.0.0.1:9222` for Chrome DevTools MCP. We can point Playwright MCP to the same browser instead of launching a second profile.

This is **not** a blind drop-in replacement because the Koba Browser Operator has product-specific policy:

- browser-wide Agents access;
- per-tab agent access;
- operator-owned tab labels/page identity;
- shared human/agent control;
- destructive Clean App/Clean browser lifecycle;
- workspace-constrained upload/download behavior.

Prototype an `OfficialPlaywrightProxyRuntime` next to the current browser tools. The acceptance gate is that all current access restrictions can be enforced without forking Playwright MCP. If per-tab policy cannot be enforced safely, retain only the minimum custom policy adapter around the upstream tool calls; do not reimplement browser actions.

Chrome DevTools MCP is already implemented exactly in the desired style and should be the template for this migration.

### 6. Analysis: proxy, do not translate the entire domain unless translation is product value

The private `ghidra` runtime is already correct: it is a tiny FastMCP proxy to native `ghidra-mcp`.

The public `analysis` runtime is much heavier. It dynamically:

- reads the entire upstream schema;
- renames tools;
- rewrites descriptions/schema references;
- normalizes arguments;
- adapts results;
- publishes a separate vocabulary;
- adds catalog helper tools.

This creates schema drift and forces agents to learn a Koba vocabulary instead of the upstream contract. Unless that semantic translation is an explicit product requirement with measurable benefit, it should be removed.

Preferred future state:

- preserve upstream tool names/schema/descriptions;
- add `project_id`/routing only where the upstream truly requires bridge context;
- filter unsafe/internal tools without rewriting unrelated schemas;
- keep workspace artifact transfer as a small extension;
- keep `search_tools` / `check_tools` only if the upstream catalog is too large and the upstream server has no equivalent discovery facility.

This also makes Ghidra upgrades much cheaper: catalog changes flow through automatically instead of requiring terminology adaptation.

### 7. Files: standardize carefully; reference does not mean production-grade

The steering-group Filesystem MCP server overlaps strongly with our 12 tools. However the MCP servers repository explicitly labels its servers as **reference implementations, not production-ready solutions**. The 2026-07-28 MCP specification also deprecated Roots for new implementations, so our design should not become newly dependent on dynamic Roots.

Useful direction:

- compare and align ordinary read/list/info/write/mkdir/move/search semantics with the familiar filesystem contract;
- if we run the reference server, use an explicit fixed `/workspace` server configuration and a pinned version after threat review, rather than relying on Roots;
- retain Koba-only attachment ingestion (`openai/fileParams`), hash verification, bounded binary chunks and hard workspace confinement as extensions;
- retain our audit/redaction and symlink/path-escape rules unless the upstream contract is proven equivalent.

This is a lower-priority refactor than GitHub/GitLab/SigNoz/Coolify because our Files implementation is already small and security-sensitive.

### 8. Raw HTTP: retain only what is actually transport-specific

The MCP reference Fetch server is useful for ordinary URL retrieval and HTML-to-model-friendly content. It does not replace our exact HTTP use cases:

- arbitrary methods/headers/cookies/body;
- byte-exact downloads to `/workspace`;
- bounded SSE/MJPEG/chunk capture;
- request diagnostics.

The workflow already says ordinary public web research should use the host's built-in browser/search path. Therefore do not grow the custom curl surface into a web browser. Keep it as a narrow raw-HTTP transport extension. Optionally mount Fetch for generic MCP clients that do not have host web search, but the reference-server production warning still applies.

### 9. Terminal: custom implementation is currently justified

There is no production steering-group terminal server equivalent to our contract. Desktop Commander is a widely used community server with process interaction and filesystem tooling, but its own documentation warns that `allowedDirectories` restricts its file tools while terminal commands can still access paths outside those directories. Its security/persistence semantics therefore are not a drop-in match for our infrastructure boundary.

Our Terminal has concrete Koba requirements:

- non-root container isolation;
- persistent named workspaces;
- durable jobs independent from a single request;
- cursor-based output logs;
- interactive PTY input and resize;
- process-group cancellation;
- bounded command/output/runtime;
- retained job metadata and cleanup policy.

Keep it for now. Open a separate evaluation spike comparing Desktop Commander and other real-PTY MCP servers against this acceptance contract. Replacement is allowed only if those semantics can be preserved by a thin adapter without weakening isolation.

### 10. Local Git reference server: not a current production migration target

`mcp-server-git` is useful as a schema/reference source, but the official reference repository states that these implementations are educational rather than production-ready. The Git server is additionally documented as early development and the repository has published Git-server security advisories.

Do not replace protected Koba Git/workspace workflows merely to reduce LOC. Reevaluate when a production-supported Git MCP with a matching path/branch threat model is available.

## Observability surface after refactor

Keep `/observability/mcp` as a useful unified product surface, but make it a composition point rather than an API reimplementation:

```text
observability_sources / observability_connection  # Koba account control plane
signoz_*                                           # official SigNoz upstream catalog
coolify_*                                          # native Coolify upstream catalog, read-only filtered
```

If explicit `account_id` is required for every call, add it generically at proxy time. Do not hand-write a second set of SigNoz/Coolify tool schemas.

## Proposed clean/DDD ownership

### Domain

Own concepts that are actually Koba domain rules:

- Account / ProviderAccount;
- ProviderCapability / AccountCapability;
- AccessPolicy / ToolPolicy;
- Workspace identity;
- AgentRole (writer/reviewer/operator where applicable);
- Audit policy;
- Browser access policy.

Provider concepts such as GitHub pull-request JSON or Coolify deployment JSON should **not** be domain entities unless Koba has a real business rule around them.

### Application

Use cases/ports:

- `ResolveProviderAccount`;
- `OpenUpstreamMcpSession`;
- `ListFilteredUpstreamTools`;
- `CallUpstreamTool`;
- `ApplyToolPolicy`;
- `RecordInvocation`;
- `MaterializeWorkspaceArtifact`;
- Koba-specific Git/review workflows.

### Infrastructure

Adapters:

- HTTP/stdio MCP transports;
- GitHub official MCP adapter;
- GitLab native MCP adapter;
- SigNoz MCP process adapter;
- Coolify MCP HTTP adapter;
- Playwright/DevTools stdio adapters;
- Ghidra HTTP adapter;
- Valkey;
- SQL persistence;
- filesystem/terminal process runtime where still owned.

### Presentation

- public MCP resources/endpoints;
- Management API;
- frontend/admin API;
- operator WebSockets.

This decomposition lets backend/frontend separation happen without coupling the frontend to provider API clients.

## Migration phases

### Phase 0 — generic proxy foundation

Build the reusable account-scoped MCP proxy before replacing any provider.

Acceptance:

- per-call explicit account selection;
- secret never appears in public tool args/results/audit;
- HTTP and stdio upstream support;
- headers/environment created from resolved account only at transport boundary;
- tool catalog pass-through with optional generic `account_id` extension;
- allow/deny policy without provider response rewriting;
- session pooling/catalog cache with deterministic invalidation;
- resources/prompts pass-through where supported;
- upstream health/version diagnostics;
- golden test proving an upstream schema is unchanged except documented bridge fields.

### Phase 1 — low-risk official/native observability upstreams

1. SigNoz official MCP.
2. Coolify native MCP.

Run old and new implementations side-by-side in shadow/acceptance tests. Compare representative queries and permissions. Remove custom API clients only after production acceptance.

### Phase 2 — browser and Analysis proxy simplification

1. mount Playwright MCP against the existing Chromium CDP endpoint;
2. prove Browser Operator access policy on the upstream calls;
3. migrate browser actions;
4. simplify Analysis toward transparent Ghidra pass-through;
5. keep Chrome DevTools and private Ghidra proxy as known-good examples.

### Phase 3 — GitLab native MCP

- capability probe per account/instance;
- native `/api/v4/mcp` path for supported instances;
- legacy adapter fallback while required;
- tool coverage and mutation-policy parity tests;
- remove legacy REST implementation once no managed account needs it.

### Phase 4 — GitHub official MCP

This has the biggest deletion payoff but also the most Koba-specific policy.

- start official GitHub HTTP server privately;
- inject selected account credential per request;
- use official toolsets/exclusions/read-only/lockdown facilities rather than duplicating them;
- preserve writer/reviewer policy and workspace checkout as extensions;
- create a coverage matrix for all 96 existing public tools;
- classify each existing tool as `upstream`, `Koba extension`, `obsolete`, or `merge into workflow`;
- migrate names to official names unless a compatibility alias is temporarily needed;
- delete custom provider API layers after parity/production acceptance.

### Phase 5 — Files/Terminal evaluation

Do these after the high-value provider migrations. They are local privileged infrastructure and deserve a stricter threat review than ordinary provider APIs.

## Migration rules

1. **Upstream name wins.** Do not rename official tool names merely to preserve our old vocabulary. Temporary aliases need a removal date.
2. **No response reshaping by default.** Preserve structured upstream content unless redaction/policy requires a transformation.
3. **Policy is allowed; domain duplication is not.** A branch-safety check is Koba policy. Reimplementing GitHub branch APIs is not.
4. **No hidden account state.** Keep account selection explicit unless the public endpoint itself is account-scoped.
5. **Pin upstream versions.** Upgrade intentionally with catalog diff + acceptance tests.
6. **Catalog diffs are CI artifacts.** An upstream version change must show added/removed/changed tool schemas.
7. **Keep old path during migration.** Run compatibility/shadow tests and delete the legacy provider only after runtime acceptance.
8. **Security beats standardization.** A reference/community MCP is not automatically safer than our small hardened implementation.
9. **Prefer upstream resources/prompts as well as tools.** Do not flatten MCP back into tools-only wrappers when the upstream exposes richer protocol primitives.
10. **Do not couple the frontend to upstream provider schemas.** Management/frontend use Koba control-plane APIs; provider MCP catalogs are agent-facing.

## Acceptance metrics for the refactor

Track these per migrated provider:

- custom provider LOC removed;
- custom provider tests removed/replaced by upstream integration tests;
- upstream version and catalog hash;
- public tool count and schema-diff count;
- p50/p95 `tools/list` and tool-call bridge overhead;
- MCP session reuse rate;
- account-cache hit rate;
- error rate by `bridge` vs `upstream` ownership;
- number of Koba extension tools remaining;
- credential exposure/redaction tests;
- permission/policy parity tests.

Do **not** treat lower LOC alone as success. The migration is successful when ownership is clearer, security policy remains enforceable, and runtime behavior is at least as reliable.

## Expected deletion / simplification impact

Directional, not a promised exact LOC target:

- GitHub: most of ~6.4k LOC becomes upstream + a much smaller policy/extension layer.
- GitLab: most of ~2.1k LOC becomes native MCP proxy after compatibility fallback is retired.
- SigNoz/Coolify: direct provider clients should disappear almost entirely.
- Browser: most interaction/action code can potentially disappear if Playwright policy acceptance succeeds.
- Analysis: a large part of schema/terminology transformation can disappear if transparent upstream names are accepted.
- Files/Terminal: little or no immediate deletion until production/security parity is demonstrated.

This should also lower maintenance CPU/build/test burden indirectly, but the primary gain is **ownership and compatibility**, not a guaranteed runtime CPU percentage.

## Known documentation debt discovered by this audit

Current architecture docs are already stale in several places and should be corrected as part of the clean-architecture documentation pass:

- `docs/architecture/overview.md` references an obsolete `CU` node while the runtime is `web`;
- the overview/public-surface list omits Terminal and Observability;
- `docs/architecture/components.md` calls Files "immutable storage" although the current implementation is a mutable shared workspace;
- `docs/roadmap.md` describes several now-completed migration states as if they were current work.

Do not use those stale sections as future architecture authority without updating them.

## Upstream evidence / references

Primary sources checked for this audit:

- GitHub official MCP: https://github.com/github/github-mcp-server
- GitHub HTTP server / reverse-proxy mode: https://github.com/github/github-mcp-server/blob/main/docs/streamable-http.md
- GitHub server configuration/tool filtering: https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md
- GitHub App auth (stdio-specific): https://github.com/github/github-mcp-server/blob/main/docs/github-app-auth.md
- GitLab native MCP: https://docs.gitlab.com/user/model_context_protocol/mcp_server/
- Microsoft Playwright MCP: https://github.com/microsoft/playwright-mcp
- Chrome DevTools MCP: https://github.com/ChromeDevTools/chrome-devtools-mcp
- SigNoz MCP: https://github.com/SigNoz/signoz-mcp-server
- SigNoz MCP docs: https://signoz.io/docs/ai/signoz-mcp-server/
- Coolify MCP: https://coolify.io/docs/mcp/how-mcp-works
- Coolify MCP capabilities: https://coolify.io/docs/mcp/capabilities/overview
- MCP reference servers: https://github.com/modelcontextprotocol/servers
- Filesystem reference server: https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem
- Git reference server: https://github.com/modelcontextprotocol/servers/tree/main/src/git
- MCP reference-server security notice: https://github.com/modelcontextprotocol/servers/blob/main/SECURITY.md
- Desktop Commander community terminal MCP: https://github.com/wonderwhy-er/DesktopCommanderMCP

## Immediate next decision

Implement Phase 0 as the first code slice of the larger clean-architecture refactor, then use **SigNoz** as the first real provider migrated through it. SigNoz is the best proof because the upstream is official, the custom implementation is non-strategic, and the current public read operations are easy to compare side-by-side.

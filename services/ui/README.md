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

The browser only calls **same-origin Control Panel API** endpoints under
`/api/*`. It never talks directly to the identity provider, Authorization,
Platform or individual MCP Hands, and does not embed provider secrets, issuer
configuration or admin credentials. The public, unauthenticated access screen
checks only `GET /api/platform/me` to distinguish signed-out, denied, unknown
and unavailable responses. A 200/401/403 alone is **not a verified signed-in
User**. Login/registration actions remain explicitly disabled until Backend
publishes a real, provider-agnostic session-start/callback/current User contract.
The separate authenticated `PlatformPort` remains closed until a verified
permission-bearing Control Panel API adapter is installed; the UI cannot
infer Team, Project or AgentSession access from local state.

Unauthenticated access supports English/Russian and light/dark preferences;
those display preferences never grant permissions, select an IdP, or reveal
credentials. A timed, bounded read-only connectivity probe cannot trigger
any account mutation.

## Standalone native build

From this directory:

```sh
bun install --frozen-lockfile
bun run build
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
- Single Watch path: `services/ui/**`
- Existing private `briareus-net` remains; keep `briareus-admin-ui` as a
  temporary internal network alias for the published Gateway, while also
  advertising `briareus-control-panel-ui`.
- Only Gateway owns the public `briareus.koba-nexus.ru` origin.

A UI-only edit must not build Control Panel API, Identity or the Hands.
Do not add SQL migrations, credentials, broad shared watches or public UI
secrets. Observe real Coolify deployment and `/`, `/panel/`, assets, sitemap,
then separately report any still-unavailable backend-authenticated API.

## MCP module migration

The legacy Browser, Files, Terminal, GitHub/GitLab, Analysis, Calls, OAuth,
Observability and service-tool **interface inventory** is preserved as
separate modules with nested settings. An explicit anonymous module-preview
mode shows that layout without presenting fabricated server data, permissions
or fake successful saves. Global display preferences are functional; backend
module settings require verified, provider-agnostic Control Panel API DTOs.
See `docs/services/ui/mcp-module-migration.md` for the evidence and missing
BFF contracts.

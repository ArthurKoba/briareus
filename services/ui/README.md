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

The browser-only first-user client sends the original matching UUIDv4
`Operation-UUID` and `Idempotency-Key` on each POST, keeps a signed bearer
in memory only, re-verifies `/api/platform/me` and never replays uncertain
first-user registration. The broader privileged `PlatformPort` stays closed
until owner-authenticated server permissions are actually available. The
interface never derives auth or project access from the landing page.

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

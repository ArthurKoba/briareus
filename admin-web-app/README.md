# Briareus Admin UI

Vue 3, TypeScript, Vite and the Briareus Project-scoped administration views.
The old MCP Bridge operator UI is not part of this application entrypoint.

## Build

- `bun install --frozen-lockfile`
- `bun run typecheck`
- `bun run build`

Local dev and Vite preview bind to `127.0.0.1` only. There is no automatic
legacy Admin API proxy, `admin.*` hostname rewriting, public CORS assumption,
mock login or preview bypass. The built HTML has no runtime-config injection.

## Authentication and production routing

The Briareus `PlatformPort` remains **uninstalled** until an independently
accepted C1-B2/C2 same-origin HTTPS and current-User authentication contract
is available. Without it the UI fails closed and shows the unavailable state.
The UI has **no operator-editable ENV variables** at this stage. Backend
credentials, JWTs, database/Valkey passwords and service signing keys do not
belong in the browser image or browser runtime config.

Deployment owns the service Dockerfile and Compose cleanup, and must remove
the obsolete `runtime-config.template.js` and `docker-entrypoint.d` COPYs
before deleting those source placeholders. Publication and external TLS
routing require separate orchestrator review.

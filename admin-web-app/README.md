# Admin UI

Standalone Vue 3 + TypeScript + Vite + Tailwind CSS administration frontend.

## Production contract

- UI: `https://admin.mcp.koba-nexus.ru/`
- Admin API: `https://api.mcp.koba-nexus.ru/v1`
- Realtime: `wss://api.mcp.koba-nexus.ru/v1/realtime`
- Browser Operator: `wss://api.mcp.koba-nexus.ru/v1/browser/operator/ws`

The Admin UI is served from `/`. It does not use the MCP Gateway as an HTTP proxy.

Runtime variables:

```text
ADMIN_UI_PREVIEW=false
ADMIN_API_BASE_URL=https://api.mcp.koba-nexus.ru/v1
ADMIN_UI_TELEMETRY_ENABLED=true
ADMIN_UI_TELEMETRY_SAMPLE_RATE=1
ADMIN_UI_EVENTS_MODE=websocket
```

If `ADMIN_API_BASE_URL` is empty, the browser derives it from an `admin.<zone>` hostname by
replacing `admin.` with `api.` and appending `/v1`.

Cross-origin Admin API requests use `credentials: include`. The Admin API must allow the
configured `ADMIN_UI_ORIGIN` and keep the session cookie HttpOnly.

The browser never receives the upstream OTLP bearer credential.

## Local preview

Set `ADMIN_UI_PREVIEW=true` to render preview state without Admin API requests.

## Build

```text
bun install --frozen-lockfile
bun run --bun typecheck
bun run --bun build
```

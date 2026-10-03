# Management UI

Standalone Vue 3 + TypeScript + Vite + Tailwind CSS management frontend.

## Isolation boundary

The frontend container is built with `frontend/` as its Docker build context. The build cannot read or copy the Python backend, root `Dockerfile`, `src/`, `uv.lock`, or the backend Compose topology.

For a standalone Coolify application use:

- branch: `dev`;
- base/build directory: `frontend`;
- Dockerfile: `Dockerfile`;
- container port: `8080`.

No backend container is required to build or start the frontend.

## Runtime modes

### Preview

Set `MANAGEMENT_UI_PREVIEW=true`. The UI renders using local preview state and makes no management API requests. Use this only when the backend is intentionally unavailable.

### Connected

Connected mode is the default. Set:

- `MANAGEMENT_BACKEND_ORIGIN=https://<management-backend-origin>`.

`MANAGEMENT_UI_PREVIEW=false` is already the default.

The nginx runtime proxies browser requests from `/api/*` to the backend `/admin/api/*`. The SPA itself is unchanged, so switching backend endpoints does not require rebuilding the image.

## Architecture boundaries

- `app/` - composition root and global design tokens;
- `pages/` - route-level screens;
- `widgets/` - large reusable regions;
- `features/` - user-facing capabilities;
- `shared/api/` - typed backend transport;
- `shared/ui/` - repository-owned shadcn-style primitives;
- `shared/lib/` - framework-independent helpers and browser-local UI preferences.

Only visual preferences belong in localStorage. Operational state, credentials and authorization remain backend-owned.

## Interactive platform contracts

The frontend is organized by domain slices under `src/pages/<domain>/` and reusable feature code under `src/features/`. Cross-cutting browser infrastructure lives under `src/shared/`.

Current frontend infrastructure includes:

- `shared/i18n/` — RU/EN locale catalogs and persisted language preference;
- `shared/notifications/` — application-wide toast/notification bus;
- `shared/telemetry/` — sanitized browser telemetry facade and local diagnostic buffer;
- `shared/events/` — one topic subscription manager with mock, compatibility and future WebSocket transports;
- `shared/settings/` — typed helpers for preserving full backend settings while domain pages edit only owned values;
- `shared/ui/DataTable.vue` — Ant Design Vue dense table wrapper with virtual scrolling and an end-of-scroll signal.

### Frontend telemetry contract

The browser must never receive an OTLP/Bearer secret. When telemetry is enabled it sends sanitized events to the same-origin endpoint configured by `MANAGEMENT_UI_TELEMETRY_ENDPOINT` (default `/api/telemetry`) using the existing authenticated browser session.

The management backend authenticates the browser session and forwards accepted telemetry to the infrastructure telemetry endpoint using server-owned authorization. Passwords, cookies, authorization headers, account credentials, request bodies and other sensitive payload fields are filtered by the frontend telemetry facade and must also be rejected/redacted server-side.

Runtime variables:

- `MANAGEMENT_UI_TELEMETRY_ENABLED=true`;
- `MANAGEMENT_UI_TELEMETRY_ENDPOINT=/api/telemetry`;
- `MANAGEMENT_UI_TELEMETRY_SAMPLE_RATE=1`;
- `MANAGEMENT_UI_EVENTS_MODE=hybrid` (`mock`, `hybrid`, or `websocket`);
- `MANAGEMENT_UI_EVENTS_URL=/api/realtime`.

`hybrid` uses the unified management WebSocket as the primary transport and retains the existing MCP Calls SSE stream only as a compatibility fallback during migration. Deployment may switch to `websocket` after the fallback is no longer required.

The implementation roadmap and backend follow-ups are tracked in GitHub issue #233.

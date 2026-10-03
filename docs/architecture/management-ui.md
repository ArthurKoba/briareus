# Management UI architecture

## Decision

Management is split into independent delivery units:

- the existing Python management backend stays in the MCP backend stack;
- the new management frontend is a standalone Vue 3 application with its own Docker build context.

The frontend lives in `frontend/`. Its container build must not require or copy `src/`, Python dependencies, the root Dockerfile, or the backend Compose topology.

## Branch and rollout contract

The new management UI is developed on `dev` through feature branches. It must not be merged into `main` until the user explicitly promotes the completed migration.

The existing Starlette Admin remains mounted at `/admin` and remains the authoritative UI until the Vue application reaches feature parity.

## Backend migration contract

New browser-facing FastAPI contracts are added alongside the legacy admin under `/admin/api/*`. Adding an API does not require switching the production UI.

The legacy admin must not be removed, relocated, or made dependent on the new frontend during the migration.

## Standalone frontend deployment

The frontend is deployed as an independent application from the `frontend/` build context.

It supports two runtime modes:

- preview mode: no backend is required; the UI renders with local preview state for design and interaction work;
- connected mode: nginx proxies `/api/*` to a configured management backend origin.

Runtime connection settings are supplied through container environment variables. Changing the API upstream must not require rebuilding the SPA.

## Frontend boundaries

- `app/` - composition root and design tokens;
- `pages/` - route-level screens;
- `widgets/` - reusable large screen regions;
- `features/` - interactive user capabilities;
- `shared/api/` - typed HTTP/WebSocket clients;
- `shared/ui/` - local shadcn-style components;
- `shared/lib/` - helpers and UI preferences.

Only presentation preferences belong in `localStorage`. Credentials, authorization and operational state remain backend-owned.

## Realtime direction

MCP calls, browser activity and other live operational surfaces should receive explicit WebSocket/SSE contracts instead of polling full pages.

## References

ChatGPT Booster is the local reference for Vue 3, TypeScript, Vite, Tailwind and shadcn-vue component ownership. Its environment-neutral separation and browser-local UI preference model are reused conceptually.

The requested NTSG Technologies Intel Web App reference was not identifiable through the currently authorized repository set, so no repository-specific assumptions from it are included.

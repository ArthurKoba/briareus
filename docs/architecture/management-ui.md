# Management UI architecture

## Decision

Management is split into two independently buildable delivery units:

- Python management backend: FastAPI application, domain/application/infrastructure layers and typed HTTP/WebSocket contracts.
- Browser management frontend: Vue 3 SPA built with TypeScript, Vite, Tailwind CSS and repository-owned shadcn-vue compatible components.

The frontend lives at the repository root in `frontend/` rather than under `src/`. It is not a Python module and has its own dependency/build boundary.

## Branch and rollout contract

The new management UI is developed on `dev` through feature branches. It must not be merged into `main` or replace the production admin until the user explicitly promotes the completed migration.

The legacy Starlette Admin remains available throughout development.

## Migration strategy

Public routing in the dev environment:

- `/admin` and `/admin/*` -> management-ui SPA;
- `/admin/api` and `/admin/api/*` -> FastAPI management backend;
- `/admin/browser/ws` -> existing browser-operator WebSocket backend;
- `/admin/legacy` and `/admin/legacy/*` -> Starlette Admin fallback.

Starlette Admin is removed only after all required management capabilities have typed API contracts and equivalent Vue screens.

## Frontend boundaries

- `app/` - composition root and design tokens;
- `pages/` - route-level screens;
- `widgets/` - reusable large screen regions;
- `features/` - interactive user capabilities added during migration;
- `shared/api/` - typed HTTP/WebSocket clients;
- `shared/ui/` - local shadcn-style components;
- `shared/lib/` - helpers and UI preferences.

Only presentation preferences belong in `localStorage`. Credentials, authorization and operational state remain backend-owned.

## Backend boundaries

Presentation adapters call application services. New Vue endpoints must not query SQLAlchemy models directly from route handlers.

The existing `/internal` API remains service-to-service and bearer-token protected. Browser endpoints under `/admin/api` use the management session cookie and same-origin checks for mutation.

Future realtime surfaces such as MCP Calls, browser activity and runtime events should use explicit WebSocket/SSE contracts rather than polling whole pages.

## Deployment

`management-ui` is a dedicated container. The build stage produces static assets; the runtime stage serves them with nginx. Gateway remains the only public ingress.

## References

ChatGPT Booster is used as the local reference for Vue 3, TypeScript, Vite, Tailwind and shadcn-vue component ownership. Its environment-neutral separation and browser-local UI preference model are reused conceptually.

The requested NTSG Technologies Intel Web App reference was not identifiable through the currently authorized GitHub repository set or public repository search, so no repository-specific assumptions from it were introduced.

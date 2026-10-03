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

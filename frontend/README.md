# Management UI

Vue 3 + TypeScript + Vite + Tailwind CSS with a shadcn-vue-compatible local component layer.

Architecture boundaries:

- `app/` — composition root and global design tokens;
- `pages/` — route-level screens;
- `widgets/` — large reusable regions;
- `shared/api/` — typed backend transport;
- `shared/ui/` — repository-owned shadcn-style primitives;
- `shared/lib/` — framework-independent helpers and browser-local UI preferences.

Only visual preferences belong in `localStorage`. Operational state, credentials and authorization remain backend-owned.

The SPA is introduced through a strangler migration. `/admin/legacy` remains available until the Vue surface reaches feature parity with the Starlette Admin console.

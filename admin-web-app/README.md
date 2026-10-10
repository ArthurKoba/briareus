# Briareus Admin UI

Standalone Vue 3 + TypeScript + Vite application for Briareus Users, Teams,
Projects, AgentIdentity, AgentSessions and source-authorized resources.
The old MCP Bridge operator UI, cookie REST client, telemetry and global
realtime components have been **removed from this product source**.

## Source layout

- `src/app/` — Briareus application entry, navigation and styles.
- `src/features/platform/` — typed platform API boundary, scoped state,
  revocation-safe commands and reusable components.
- `src/pages/platform/` — User/Team/Project/Agent/Session and resource screens.
- `src/shared/` — small standalone UI primitives, locale and non-secret UI
  preferences (stored under `briareus:ui:v1`).

The accepted Backend A9 source OpenAPI defines **60 routes,
68 operations and 68 schemas**, unchanged from A8. `src/features/platform/api/draft/` is a
strictly typed, **uninstalled** source consumer; it is not a public API SDK.
The only source-origin input of its development constructor must pass same-
origin and HTTPS validation. **No** public REST adapter, HTTP proxy, OAuth
principal, WebSocket or generated service keys are activated on page load.

## Build

- `bun install --frozen-lockfile`
- `bun run typecheck`
- `bun run build`

The build embeds **only** the source `package.json` version through a Vite
compile-time constant. This is not a deployed service version, source commit
hash or current deployment environment/Authorization readiness.

## Browser diagnostic privacy and time

Briareus contains a first-party browser diagnostics recorder under
`src/features/platform/model/browser-telemetry.ts`. It is **opt-in and off
by default**; pre-B14 UI preferences do not silently authorize collection.
Consent is a standalone boolean (`briareus:diagnostics-consent:v1`). At most
64 fixed-schema records / 16 KiB / 24 events per minute are kept **only in
memory** for up to five minutes; no URLs, query strings, raw exception text,
credentials, token values or User/Team/Project IDs are read or recorded.
Events are purged on scope/principal changes, logout, disconnect, pagehide,
consent revocation and expiration. Server delivery is **disabled** pending
an A10 authenticated same-origin telemetry relay; this code contains no
collector endpoint or Team `OTLP_BEARER_TOKEN` and sends NOTHING to SigNoz.

All accepted server instants are UTC-aware ISO-8601; display can use UTC or
viewer device time in Settings, not a fabricated Team/deployment `TZ`.
Native `datetime-local` inputs are device-local and convert to explicit UTC
before a write, rejecting missing/duplicated DST wall-clock values.
Browser `clientObservedAtUtc` diagnostic times and deadline displays are NOT
backend audit timestamps or Authorization schema readiness evidence.

Production images are defined in the **separately owned**
`deploy/admin-ui/Dockerfile` and its portable/Coolify Compose files.
Only the Briareus source and existing static Nginx assets are copied.
Vite development and preview bind `127.0.0.1`; there is no old API proxy
or hostname-based service inference. No runtime-config JS or operator ENV
flags are consumed.

## Authentication and deployment boundary

`PlatformPort` remains **non-installable** until C1-B2-PUBLIC/C2 approve
actual mounted TLS-origin/authentication, current User and Team/Project
permissions, Bearer/cookie policy, revocation, command reconciliation and
scoped realtime transport. Until that contract exists the UI explicitly
shows that the Admin API is unavailable; it never simulates login or
falls back to the old product. The first-superuser setup route is also
blocked until Backend and Deployment approve an authenticated operator-only
channel. During an Authorization migration or outage, a backend 503 is shown
as service-unavailable-or-possibly-upgrading; Briareus does not run migrations
or infer readiness from Data container health. No DB/JWT/encryption/service private keys belong in browser source,
Vue build args or stored browser preferences.

Live Coolify deployments, image publication and restricted DEV acceptance
belong to the infrastructure owner; a successful static build is not
real authentication or runtime acceptance.

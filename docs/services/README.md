# Service documentation map

Documentation is separate from each service's runtime and mirrors its directory category:

- docs/services/infrastructure/<service>/ — e.g. Gateway routing/transport.
- docs/services/platform/<service>/ — Identity, Authorization, Platform Control, Resources.
- docs/services/api/ and docs/services/ui/ — independent Control Panel API and UI services.
- docs/services/hands/<service>/ — independent MCP Hand runtime, access and isolation.

Code/Compose/Dockerfile/locks belong exclusively under their actual owning service directory under `services/`. Docs do NOT appear in Coolify Watch and should not cause redeploy. Keep canonical cross-service meaning only in docs/architecture/owner-decisions-20261012.md, not duplicated in every service doc. Current identity/authorization migration: docs/operations/rauthy-cedar-four-agent-migration-20261012.md.

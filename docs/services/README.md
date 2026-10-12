# Service documentation map

Documentation is separate from each service's runtime and mirrors its directory category:

- docs/services/infrastructure/<service>/ — e.g. Gateway routing/transport.
- docs/services/platform/<service>/ — Identity, Authorization, Platform Control, Resources.
- docs/services/control-panel/api/ and docs/services/control-panel/ui/.
- docs/services/hands/<service>/ — independent MCP Hand runtime, access and isolation.

Code/Compose/Dockerfile/locks belong exclusively under services/<same category>/<service>/. Docs do NOT appear in Coolify Watch and should not cause redeploy. Keep canonical cross-service meaning only in docs/architecture/owner-decisions-20261012.md, not duplicated in every service doc. Execution program: docs/operations/agent-migration-plan-20261012.md.

# Briareus deployment — current guide

Selected owner contract: architecture/owner-decisions-20261012.md.
Transitional instructions: operations/service-layout-transition.md.
Agent execution: operations/agent-migration-plan-20261012.md.

Current running Dev Coolify resources can still use legacy deploy/<name> Base/Compose/Watch until each independently owned service is migrated. This is NOT an architectural standard. Target: each services/<category>/<name> has its runtime, source, Dockerfile, Compose, uv/Bun lock and native build; docs in docs/services/<same category>/<name> outside Watch. Watch service folder/** and narrow consumed shared/**.

One Development PostgreSQL principal and four logical DBs stay for MVP. Team Shared TZ/OTLP, Environment Shared DB/Valkey/Identity signing material. Real secret values not in Git/Docker image/Compose. No new roles/DBs, no data volume reset, no global migrator. Gateway is thin transport without JWT/C2 business logic. Authorized inner service endpoints and Hands isolation are essential.

Only three service-owning agents implement TRY-first with their allowed Briareus MCP/development applications: build -> Git PR/required checks -> deploy -> observe -> fix. No unit/integration/e2e/smoke suites during MVP. Orchestrator independent review AFTER publication.

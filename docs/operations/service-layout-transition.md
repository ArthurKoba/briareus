# Per-service migration from legacy deploy tree

Current owner contract: ../architecture/owner-decisions-20261012.md.
Agent tasks: agent-migration-plan-20261012.md.

Current live Coolify Dev may still use deploy/<module> and code under services/bridge, services/modules, services/projects and admin-web-app; this is a TRANSITIONAL reality, not desired design.

For ONE owner service at a time: inspect current main, source dependencies, actual Coolify app UUID/base/Compose/Watch and rollback; move own source, runtime, Dockerfile, Compose, uv/Bun lock and own migrations into services/<category>/<name>/; move shared DTOs only to small shared/topic/ under one editor; add mirror docs/services/<category>/<name>/ outside source; set Watch to own service/** and actual consumed shared/topic/**; native build and permitted Git PR/merge; update only matching existing Briareus Dev App; inspect runtime logs/HTTP; fix failures before removing legacy files. No changes to unrelated app deployments.

Do not create a second app to rename Admin API/UI; rename to Control Panel API/UI while preserving existing UUID, public routes and compatibility until actual rollout. An API-only edit never restarts Identity; changing one Hand never restarts other Hands. Shared contracts rebuild only their declared consumers.

During MVP do not add unit/integration/e2e/smoke test suites, global wheel generator, per-file AST manifest, new PostgreSQL SQL roles/DBs or network-wide mTLS/C2 approval chain. Actual build, live Dev response and safety isolation of untrusted Hands are the acceptance evidence.

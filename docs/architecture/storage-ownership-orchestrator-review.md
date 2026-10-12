# Historical storage redesign proposal — not current MVP authority

This former proposal about new owner SQL roles, DB provision and migration gates is RETIRED for the current Development MVP. Existing Development uses the already approved shared PostgreSQL principal and four owner logical databases without introducing new roles, global migrations or data moves. Preserve existing PostgreSQL/Valkey volumes.

Current source of truth: owner-decisions-20261012.md. Current rollout: ../operations/agent-migration-plan-20261012.md. This file is a historical locator only, not permission to split schema or change SQL grants. The full prior text is archived in local/artifacts/owner-policy-reconciliation-20261012/originals/repo/docs/architecture/storage-ownership-orchestrator-review.md.

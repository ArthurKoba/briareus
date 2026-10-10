# MCP Bridge — local engineering map

This repository checkout belongs to the persistent Koba Terminal workspace
`mcp-bridge-platform` (`/workspace/projects/mcp-bridge-platform/repo`).

## Authority and navigation

- Current target: `docs/architecture/target-project-platform.md` (still DRAFT for unresolved matters).
- ONLY active implementation tracker: ArthurKoba/mcp-bridge issue #390 (all slices and future implementation). Issue #391 is a separate POST-REFACTOR INDEPENDENT AUDIT, not a worker task, activated only after stable implementation. Do not create slice issues.
- Current application code is historical implementation evidence, not accepted target state.
- Read the root `README.md` for the old runtime map and load relevant workflow-library skills before changing a domain.
- Admin UI/API refactor is a cross-cutting part of #390; use architecture §14 and the project-scoped API contracts. Post-refactor acceptance belongs to #391 only.
- Identity/Team/Project/Agent/Authorization are separate logical domains; one domain does not imply one container.

## Work contract

- Edit ONLY this local checkout for active tasks. Scratch, temporary Alembic revisions,
  local runtime state and logs belong in `../local/`, outside this Git repository.
- Never import legacy users/sessions/files/provider data into the new greenfield platform.
- Follow async FastAPI/Pydantic/Pydantic Settings/SQLAlchemy, explicit transaction and idempotency contracts.
- Keep REST/OpenAPI as default inter-runtime API, FastMCP for agents, and leave gRPC/GraphQL optional.
- Do not create Git commits, push, open PRs, or merge during individual task slices.
  Maintain a recoverable working tree; one intentional publication/review cycle after slice integration.
- Owner decision (2026-10-09): Backend owns source-tracked approved Alembic baseline/revisions and automatic startup migration in Authorization; this supersedes the earlier prohibition of migration files in Git. No manual one-shot schema init, create_all, schema sidecar or legacy-data migration. See architecture §5.3 and coordination MIGRATION-AUTO.
- Do not add/run unit/integration/e2e/CI suites or write test-policy files.
  Local app configuration, builds, runtime investigation, and isolated schema migration application are allowed.
- Do not modify production containers/databases or wipe existing infrastructure from this checkout.
- Stop at architectural/security contradictions and record them before coding across that boundary.

## Orchestrator repeatable handoff

When the human requests acceptance of A/B/C, reread current progress files,
exact owned source deltas using coordination hash snapshots, current contracts
and tasks; independently review source/security/static/build levels, then
integrate only accepted changes into central `repo/`, refresh all worktrees,
write next large tasks in `agents/<lane>.task.md`, reset their first progress
`State:` to READY, and update the same #390 issue. The human can then say
`Продолжай работу` in each agent's existing chat; each lane's own AGENTS.md
routes this short command to its current task, ownership and contracts.

Never claim that a source/static/build check is a live auth or product
acceptance. Keep #391 as separate later post-refactor audit; do not run
forbidden unit/integration/e2e/smoke tests or create intermediate Git
commits/pushes/PRs/issues.

## Compact #390 tracker rule after EACH independent acceptance

The owner wants issue #390 SHORT. Keep at its top: general progress, the
conceptual MVP checklist, six implementation slices, actual blockers and one
compact accepted-waves table. **Do not add acceptance checklists**, large
per-wave sections or repeat the agent progress report in issue comments.

After an independent acceptance: (1) verify the lane's source and evidence,
(2) mark only genuinely completed conceptual/slice checklist items and leave
PUBLIC/LIVE/OS/DB/security gates open, (3) edit the relevant row in the
three-lane accepted-wave summary and current A/B/C states, (4) mention only
NEW material blockers, and (5) update the existing #390 BODY and verify it.
The complete detailed evidence belongs in `agents/<lane>.progress.md` and
coordination request/contract files, not duplicated as GitHub checklists.

Accepted means the specified SOURCE/STATIC/BUILD work was implemented and
integrated locally, **never** automatically deployed into production. F1–F7
remain deferred outside MVP. Do not treat checked-box totals as a product
completion percentage. Preserve the original historical issue snapshot in
Koba Files `mcp-bridge-platform/review-archives/issue-390-original-2026-10-09.md`.
Do not edit active agent worktrees, create new issues/commits/push/PRs, or
run forbidden test suites as part of tracker maintenance.

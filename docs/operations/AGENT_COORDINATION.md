# Briareus — four worker lanes, file handoff and retrospective audit

Current architecture: ../architecture/identity-rauthy-cedar-20261012.md.
Four-agent program: rauthy-cedar-four-agent-migration-20261012.md.

## Who reports what
Worker chats (Backend, Runtime, Frontend, Deployment): **3–5 short readable text lines with emoji**, NO Markdown tables, no copied full tasks/test logs. Each gives FIRST State, NEW result, own native build/Dev observation and actual blocker/next action. Only Orchestrator-to-owner management status gives ONE small FOUR-ROW table: agent | FIRST State | start/stop? | short reason. No forgotten fourth lane.

## Files, not cross-chat forwarding
- Orchestrator task/correction -> agents/{backend,runtime,frontend,deployment}.task.md TOP in persistent workspace.
- Worker results, exact PR/main SHA, real build/Dev observation -> agents/<lane>.progress.md; FIRST State is operational. Agents already IN_PROGRESS continue, not forced READY by doc edits.
- Cross-owner DTO/route/issuer/infra requests and responses -> coordination/requests/<lane>.md with FROM/TO/WAVE/REF/REQUIRED ACTION/STATE. One writer for shared changes.
- Normative shared source: coordination/CONTRACTS.md + repo/docs/architecture/identity-rauthy-cedar-20261012.md. No old separate homemade Identity/JWT or Gateway C2 contract.
- Worker creates own clean Git PR, waits actual required checks/reviewer merge, watches only own approved Briareus Development application(s), fixes real failures. READY_FOR_AUDIT is already merged and observed; Orchestrator writes scoped ACCEPTED/CHANGES_REQUESTED retrospectively via progress files. No routine Orchestrator pre-build/approval.
- TRY-first and owner instruction: no new unit/integration/e2e/smoke suites. Native build/import, Dev runtime/browser/real OAuth/permission result are the necessary product observation, not generic test-suite work.

## Scope/security
Only Coolify Briareus MCP project UUID 3xshlpoghb9wcyhjgktlqzzp, development environment UUID naibrku1omovvmw5o0bcnp5c and existing approved exact UUIDs in BRIAREUS_DEV_ACCESS_SCOPE.md. No even viewing other projects/Shared Environments/global resources/plaintext secret values. A new Rauthy app requires exact scoped authorization before creation/inspection. Preserve data/volumes, legacy Identity until valid Rauthy cutover, and real Authorization grants; no fabricated policy allow/JWT/issuer.

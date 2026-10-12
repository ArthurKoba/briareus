# Briareus — агентский обмен и приёмка

Current owner authority: ../architecture/owner-decisions-20261012.md
Concrete agent work: agent-migration-plan-20261012.md
Active workspace: mcp-bridge-platform.

## Worker chat format
Only short readable text (3–5 lines): emoji + lane/wave/FIRST State, NEW achievement, real native build/Dev HTTP observation, next action, genuine blocker if any. NO Markdown table, no giant test/check inventory and no chat-to-chat instructions. Only Orchestrator-to-owner management reports use a three-row table Backend/Runtime/Frontend with Start/Stop and simple command.

## File exchange (not user chat)
- Orchestrator writes CURRENT task into agents/<lane>.task.md, worker reads on Continue.
- Agent records FIRST State, current branch/SHA, own build, required GitHub checks, Dev app/HTTP/log result and blockers in agents/<lane>.progress.md.
- Agent sends cross-owner request from coordination/requests/<lane>.md with FROM/TO/WAVE/REF/REQUIRED ACTION/STATE; Orchestrator returns response to recipient task/inbox file. Historic requests are archived, not current.
- coord/CONTRACTS.md (workspace coordination/CONTRACTS.md) holds ONLY one current contract; repo/docs/architecture/owner-decisions-20261012.md owns architecture and selected product choices.
- GitHub writer produces clean-branch PR; real protected checks and independent Reviewer merge must pass. Worker observes its own Briareus Dev release and immediately fixes failures.
- READY_FOR_AUDIT = already published exact SHA + true evidence in progress file, independent retrospective Orchestrator ACCEPTED/CHANGES_REQUESTED is returned by files. Orchestrator is not prepublication build/test gate.

## TRY-first — no test suites now
Work in safe slices, native uv/Bun compile/build, publish/Dev deploy/observe actual response, fix. NO creation or running unit/integration/e2e/smoke suites and nonrequired CI test suites until owner changes policy. Existing mandatory GitHub protection not bypassed. Healthcheck alone never proves a signed login or actual Hand permission.

## Ownership and access
Backend = Control Panel API + Identity/Authorization/Platform/Resources; Runtime = Gateway + independent Hands/infrastructure runtime/sandbox isolation; Frontend = Control Panel UI. Source/runtime/docker/Compose and local lock inside a service directory; docs/services mirror outside source; Watch on folder/** and actual shared. Use one editor per shared subtree and no cross-owner tree overwrite.
Coolify: ONLY Briareus MCP UUID 3xshlpoghb9wcyhjgktlqzzp, environment development UUID naibrku1omovvmw5o0bcnp5c and exact app allowlist BRIAREUS_DEV_ACCESS_SCOPE.md. Forbidden even viewing other projects/environments, Shared Environments/global/team secret settings, secret plaintext or host-wide resources. Preserve PG/Valkey volumes and actual data.

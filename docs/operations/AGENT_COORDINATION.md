# Briareus — CHAT-REPORT-V2: tables, file handoffs, Orchestrator acceptance

**Owner decision 2026-10-12.** Canonical agent workflow for workspace mcp-bridge-platform. Supersedes historical CHAT-REPORT-V1, plain-text/no-table V2, pasted НА ПРИЁМКУ and all conflicting older agent instructions. Applies to Backend, Frontend, Runtime workers and Orchestrator.

## 1. Two DIFFERENT formats: worker chat text vs. Orchestrator control table

### Agent chat: STRICTLY NO TABLES

Backend, Frontend, Runtime worker chats must send a **short, readable text update**, NOT a Markdown table. This is a direct owner correction: long six-column tables wrap vertically and make worker chats unusable. Worker answers should normally contain 3–5 short lines, no giant markdown table, no fenced log dump, no agent-to-agent commands, no repeated achievements. Actual evidence stays in progress.md.

Example for an individual worker:

🟡 Backend A19 — OBSERVING
Сделано: исправлен Docker COPY и опубликован PR #455.
Проверка: собственная сборка PASS; Identity Dev запущен; реальный login ещё недоступен.
Дальше: подключить доверенный Identity-канал; повторно проверить вход.
Блокер: проверенная подпись/сервисный peer не предоставлены. (Only if materially true.)

Use the exact FIRST State in agents/<lane>.progress.md; truthful one new result, own build/test/CI/Dev evidence, one or two next actions and only a real blocker. Emojis are for the status, not decorative lists. No Markdown TABLE in worker chat even on "отчёт" unless owner explicitly asks a particular worker for a table.

### Orchestrator chat with OWNER: concise AGENT-CONTROL TABLE only

The **Orchestrator**, and ONLY the Orchestrator, gives the OWNER a compact table to decide WHICH of the three worker chats to start or leave stopped. This is a management table, NOT the worker reporting template. Maximum four short columns:

| Агент | State | Запускать? | Команда или причина |
| --- | --- | --- | --- |
| 🟡 Backend | OBSERVING | ⏸️ Нет | Уже наблюдает; не перезапускать |
| 🔵 Runtime | WAITING | ⏸️ Нет | Нет нового задания |
| 🟣 Frontend | READY | ▶️ Да | Продолжай работу |

These rows are an EXAMPLE, not current state. On every answer read real FIRST States from the shared progress files, inspect the latest assigned work and do not invent active sessions. There are EXACTLY THREE agents to display: Backend, Runtime, Frontend. Do not add inactive historical lanes. Provide one command per agent only when launch is actually needed; for IN_PROGRESS/RELEASING/OBSERVING do NOT reflexively tell owner to send "Продолжай". Avoid excessive technical details in table cells. The Orchestrator may provide a short plain-language summary before or after the management table when genuinely useful.

If owner asks the Orchestrator to inspect a specific technical issue or write task corrections, do that in files; the agent-control table is most useful for management/status/launch requests, not mandatory for unrelated general conversation.

## 2. Commands and replies are FILE-BASED, not chat-based

Worker chats report short status TEXT only; only the Orchestrator-to-owner launch/status summary uses the compact management table. Tasks, change requests, cross-agent answers, acceptance decisions and full evidence are exchanged in existing shared workspace files. No forwarding command payloads between worker chats by a human.

| File | Who writes | Who reads | What lives there |
| --- | --- | --- | --- |
| agents/<lane>.task.md | Orchestrator | Owning agent | CURRENT executable task and correction AT TOP, acceptance criteria, exact scope; historical blocks are not active |
| agents/<lane>.progress.md | Agent; Orchestrator appends explicitly attributed audit | Agent / Orchestrator | FIRST State, own diff, builds/tests, CI, published main SHA, scoped Dev deployment/logs/HTTP, blockers, READY_FOR_AUDIT handoff |
| coordination/requests/<lane>.md | Agent: outgoing request; Orchestrator: incoming response/decision | Orchestrator / owning agent | Cross-owner request and answer, explicit recipient and required action |
| coordination/requests/orchestrator.md | Requesting agent / Orchestrator | Orchestrator | Conflicts or cross-lane decisions that require coordinating owner |
| coordination/CONTRACTS.md | Orchestrator | All agents | Approved durable shared contract and link to this authoritative handoff protocol |
| GitHub PR and scoped Coolify Dev release | Agent/authorized GitHub Reviewer | Orchestrator | Published artifacts, required checks and actual Dev evidence; NOT task/acceptance messages |

Cross-lane request metadata: FROM, TO, WAVE, REF/PR, REQUIRED ACTION, STATE (OPEN/ANSWERED/CLOSED). Agent writes request in its OWN coordination/requests/<lane>.md; Orchestrator routes its answer/command through the relevant recipient request/task file; no direct edit of another agent's task or source by a worker. Update the latest related thread, do not endlessly append identical requests.

Read order on every resume: FIRST State in own progress -> own task TOP -> incoming latest requests/answers -> accepted contract -> live Git main and own scoped source. Chat summaries, old stale task paragraphs and issue #390 chronology do not supersede files.

## 3. Implementers build, test, deploy and verify THEMSELVES

Backend, Frontend and Runtime implement only owned paths, preserve dirty known-good checkout, release from a clean published-main-based branch, independently run relevant native uv/Bun builds, lint/type/targeted tests, then push PR/required GitHub CI and permitted Reviewer merge. The agent itself inspects its exact approved Briareus MCP/development application Coolify deploy, logs, real HTTP/browser and diagnoses or repatches failures within the SAME wave. Do NOT ask Orchestrator to repeat routine builds/CI, push or inspect logs on the agent's behalf. Keep real build results distinct from placeholder test/docker CI.

When own scope and release evidence are ready for independent acceptance, agent sets FIRST State READY_FOR_AUDIT in progress and records exact published merged main SHA, relevant changed paths, tests/CI, Dev image/deploy result, live HTTP and remaining explicit unknowns. This FILE IS the handoff: no pasted НА ПРИЁМКУ block to user. Agent does not mark itself ACCEPTED. Genuine external blockers may remain named even when source/Dev release is ready for partial acceptance.

Dev-only hard allowlist: docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md. Agents may manage their OWN Briareus Dev app Watch Paths/nonsecret settings independently;  Forbidden even viewing other projects, environments, Shared Environments, Shared Variables/secret values, global Coolify/host data. Never wipe DB/Valkey or invent privileged Identity/JTI/Service peer or bypass C2.

## 4. Independent ACCEPTANCE is Orchestrator's exclusive action

Orchestrator takes READY_FOR_AUDIT file handoff, reads exact published diff/main SHA, PR/CI evidence, app logs/HTTP and cross-owner contracts, checks critical correctness/security/architecture with focused verification (NOT blindly repeating every agent build/test). Then Orchestrator writes scoped ACCEPTED (SOURCE, BUILD, DEV_RUNTIME, AUTH_PRODUCT as actually evidenced), or CHANGES_REQUESTED with specific findings, to the owning agents/<lane>.progress.md; actionable changes to agents/<lane>.task.md TOP; cross-owner dependencies to coordination/requests/<lane>.md.

On CHANGES_REQUESTED, agent revises the same wave, performs self-build/test/PR/deploy and returns READY_FOR_AUDIT through files. On ACCEPTED, Orchestrator may set READY with a distinct next task or WAITING if there is none; do not leave a false active task. GitHub Reviewer merge and protected checks are separate from Orchestrator product/source acceptance. Orchestrator reports to the owner with the compact THREE-AGENT LAUNCH/STOP management table only for status/management requests; workers never receive that table as their reporting format.

## 5. Current first-user acceptance boundary

Public / and /panel/ have reached real HTTP 200 in scoped Dev. Real registration/login and GET /api/platform/me still require actual trusted Backend Identity/Admin signer, service peer, current User/JTI and Gateway activation; protected Hands remain closed. Always reread current Dev evidence before reporting state. Git repo: ArthurKoba/briareus; issue #390 is compact tracking summary, not a chat command bus.

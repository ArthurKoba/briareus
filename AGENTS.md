# Briareus — AGENTS.md (рабочая карта)

Перед любой substantial задачей: прочитать это, current task/progress и выборочный skill из ArthurKoba/ai-agent-workflow. Source authority — актуальный опубликованный GitHub main; локальная central repo может быть старой или содержать незавершённый dirty-код.

**ЕДИНСТВЕННОЕ действующее владельческое ТЗ:** docs/architecture/owner-decisions-20261012.md.
**Исполнимый план трёх агентов:** docs/operations/agent-migration-plan-20261012.md.
**Процедура файлового обмена:** docs/operations/AGENT_COORDINATION.md.
**Локальные workspace paths:** agents/backend.task.md, agents/runtime.task.md, agents/frontend.task.md, их *.progress.md, coordination/CONTRACTS.md, coordination/OWNERSHIP.md, coordination/requests/<lane>.md. Не выполнять исторические задания/примеры из архива.

## Владелец и работа
Backend — самостоятельные Identity/Authorization/Platform/Resources и Control Panel API; Runtime — тонкий Gateway, инфраструктурный runtime и Hands/MCP; Frontend — отдельный Control Panel UI. Общие контракты только через согласованные тематические shared папки. Код, Compose, uv/Bun lock и Watch каждого сервиса — внутри его собственной папки; docs отдельно в docs/services аналогичной структуры.

TRY-first: агент сам меняет только принадлежащий ему сервис, native compile/build, PR + реально обязательные GitHub checks, Reviewer merge, реальный Briareus Development app deploy/логи/HTTP, оперативное исправление. **Не писать/запускать unit/integration/e2e/smoke suites и необязательные CI тесты.** Обязательные Git protection/checks не обходить. Оркестратор проводит независимую проверку ПОСЛЕ публикации, не делает рутинный билд за агента.

Worker чат: короткий текстовый статус, 3–5 строк с emoji, НИКОГДА не таблица. Таблица только от Оркестратора владельцу для трёх агентов (запускать/не запускать). Новые задачи и замечания идут ЧЕРЕЗ файлы, без переписывания в чате. FIRST State сохраняет смысл; не сбрасывать реально работающего агента при правках документации.

## Жёсткие ограничения
Coolify читать/изменять ТОЛЬКО проект Briareus MCP UUID 3xshlpoghb9wcyhjgktlqzzp, environment development UUID naibrku1omovvmw5o0bcnp5c, и точные одобренные приложения docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md. Запрещён ДАЖЕ ПРОСМОТР других проектов, environments, Shared Environments, глобальных страниц, Shared secret values/host-wide данных. Не раскрывать credentials, не удалять или мигрировать существующие PG/Valkey volumes, не делать фиктивный User/JWT/право доступа, не давать sandbox Hands свободный egress во внутреннюю сеть.

Gateway исключительно transport/маршруты/метрики, независимо от Identity бизнес-логики; Control Panel API — управляющий BFF-клиент независимых owner API. System invitation в операторских startup logs только при count(superuser)<1; дальше invitations через superuser. Постоянный Identity signing key, Team Shared TZ/OTLP, Environment Shared DB/Valkey/Identity secrets, нет старого ADMIN_JWT_SIGNING_KEY. Только uv per-service, никакого общего wheel/пофайлового AST manifest как нормы.

Исторические PACKAGING-V1, ENV-1, C2 в Gateway, старые README и READY_FOR_REVIEW не являются приказами. Архив, если нужен для расследования: local/artifacts/owner-policy-reconciliation-20261012/originals/. **Нет других обязательных длинных стартовых карт.**

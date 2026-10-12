# Briareus — предметная модель и MVP (только действующие решения)

Детальная текущая архитектура, bootstrap, secrets, Dev scope и процесс: owner-decisions-20261012.md.
Этот документ теперь фиксирует только продуктовые домены/сценарии. Прежний полный текст с отменёнными Gateway JWT, startup при существующем superuser, общим Authorization migrator, отдельным deploy/<module> и запретами/обязательными проверками сохранён в локальном историческом архиве; НЕ применять его как ТЗ.

## Платформа

User — локальный человек с уникальной идентичностью, настройками учётной записи, login/password и статусом enabled/suspended. Identity владеет User, credentials, приглашениями, login и подписью сеансов. Authorization отдельно владеет grants/AgentSession/access/revoke. Control Panel API — тонкий HTTP-клиент owner API, не business owner и не SQL-owner; Control Panel UI — отдельный браузер.

Team — группа пользователей, имеет одного User-owner и TeamMembership. Project принадлежит ровно одному User либо Team. Персональный Project не даёт доступа другим людям; для совместного Project переносится в Team. Доступ членов Team к проектам/ресурсам определяется актуальными owner grants; MVP допускает полный доступ активных членов Team ко всем Team-owned Project без мелкозернистых индивидуальных ACL. Superuser — глобальная роль после подтверждённого логина, не способ анонимного обхода Identity.

IntegrationConnection и ScopedVariable принадлежат либо Team, либо одному Project, не любому глобальному сервису; нужный актуальный Project context определяет доступ. AgentIdentity, AgentSession, RuntimeSession и RuntimeJob различаются. AgentSession содержит UUIDv4 session_uuid, Project, grant/TTL и не заменяет самого факта аутентификации. Browser/Terminal runtime состояния принадлежат Project/владельцу Hand, а не chat или OAuth-сессии.

При удалении User не терять принадлежащие ему Team/Project/Files: сначала переназначить ownership с реальными owner разрешениями. Last superuser deletion guard допустим; при фактическом отсутствии хоть одного superuser восстановительный startup bootstrap должен работать.

## Регистрация, первый superuser

Публичной свободной регистрации нет: пользователь получает одноразовое приглашение. **Во время каждого запуска Identity, если count(User.role=superuser)<1, создать/подготовить системную регистрацию и вывести полную ссылку в operator startup logs Identity.** Первый успешный регистрационный commit после отсутствия superuser создаёт ровно одного superuser, при параллельных запросах только одна транзакция получает эту роль. Прочие системы/логи/трассировки/Gateway не получают этот код. Вход защищён Identity.

**Когда хотя бы один superuser уже есть, системная ссылка ни при каком обычном restart не выдаётся и в logs не печатается.** Все новые ссылки обычным пользователям создаются **через существующего authenticated superuser**. Обычное приглашение никогда не присваивает superuser. При исчезновении всех superuser начальная логика по count<1 снова активируется. Старый once-ever bootstrap flag не блокирует это восстановление.

User session подписывается устойчивым Identity signing key, сохраняющим действительность токенов на обычном restart Identity. Secret source — правильная Environment Shared ссылка с проверенным именем/форматом; прежний ADMIN_JWT_SIGNING_KEY не каноничен для Identity. Отзыв/expiry/current User проверяются настоящим Identity, Access/Resource права — соответствующими owner services. Нет Gateway JWT/User C2. Системный код печатается только в operator startup logs Identity при count<1; запрещено копировать в публичные страницы/общее OTLP/MCP logs.

Сброс пользовательского пароля, suspend, выдача приглашений superuser, права пользователей и управление Team/Project — последующие API действия с явной реальной проверкой владельца. После начального superuser не появляется автоматический поток приглашений при каждом запуске.

## Independent domains и MCP

Identity: User/регистрация/login/current/credentials.
Authorization: actor permissions, agent grants/revocation.
Platform Control: Team/Project/membership/owner revisions.
Resource Catalog: resource metadata, integrated provider accounts and scoped variables.
Control Panel API: собственные UI-facing /api/* и приватные вызовы доменных APIs; не владеет чужими SQL и не перезапускает владельцев.
Control Panel UI: отдельный Vue/Bun браузер с / и /panel/.
Gateway: исключительно маршрутизация/streaming/метрики, forward всего /api/* без изменений к Control Panel API; OAuth issuer и Hands MCP маршруты к настоящему service owner. Не проводит authorizations, user identity, session grants, business routing.
Hands: самостоятельные Files, Terminal, Web, SVC, Infrastructure, Reverse и новые MCP runtime; один независимый сервис/папка/приложение по реально существующей deployment topology, FastMCP остаётся протоколом agent tools.

Внутренний HTTP/typed REST достаточно для MVP. Go/gRPC/GraphQL/WebRTC — исключительно по доказанной необходимости после MVP, не обязательный foundation. Валkey для реальных realtime/cache/invalidation сценариев, но PostgreSQL — долговременная истина grants и owner state.

## Сервисное размещение и данные

Одна monorepo, отдельные services/platform/<name>, services/infrastructure/<name>, services/control-panel/{api,ui}, services/hands/<hand>. В каждой папке собственный runtime, Dockerfile, Compose, локальные uv/Bun dependencies/lock и owner DB migrations при необходимости. Несколько мелких shared/topic/* контрактов с явными потребителями. Документы отдельно в docs/services/ с аналогичной категорией, не в service source. Folder-based Watch и один независимый redeploy по сервису, нет универсального wheel/AST-per-file manifests/постоянной отдельной папки deploy.

Development сохраняет уже принятую **одну общую PostgreSQL учётную запись с повышенными правами, четыре логические owner DB**, существующие volumes, per-owner Alembic. Не проводить новых SQL-ролей или global migration ради MVP. Угроза — недоверенный MCP/Terminal/Web sandbox с сетевым доступом к private API/DB/secrets; ограничить network/egress/UID/capabilities у runtime и проверять реальный actor в owner endpoint. Не считать Docker DNS доверенным actor.

Team Shared TZ и OTLP/telemetry, Environment Shared PostgreSQL/Valkey и environment-specific секреты Identity. Секретные значения не должны храниться в Docker images/Compose/Git/открытом Application env. Coolify доступ только к Briareus MCP/development allowlisted apps.

## Приоритет MVP и цикл реализации

Сначала реальный initial User через startup invitation, стабильная подпись Identity и работающий /api/login/current. Далее собственные service boxes и folder Watches, самоизолированные Hands, UI/control operations. Не строить заранее full Go/gRPC, новые SQL-roles, cache fabric и новые тестовые комплексы.

TRY: агент делает узкий runnable change, собирает, публикует с обязательной GitHub защитой, деплоит в разрешённом Dev, смотрит фактический результат и исправляет. **Unit/integration/e2e/smoke suites на текущей стадии отключены.** Не обходить базовые privacy/auth/db invariants. Оркестратор проверяет после работающего релиза, не выдумывает предварительные шаги.

Подробная история прежнего ТЗ не является нормативной. Для расследования предыдущая версия хранится только как historical snapshot local/artifacts/owner-policy-reconciliation-20261012/originals/repo/docs/architecture/target-project-platform.md.

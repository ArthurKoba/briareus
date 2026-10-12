# Briareus — исполнимые задачи Backend / Runtime / Frontend, 12.10.2026

**Новая команда владельца 12.10.2026:** целевая архитектура [Rauthy + Cedar](../architecture/identity-rauthy-cedar-20261012.md). Приостановить расширение старой собственной Human Identity/JWT и заменить первоначальные Backend Identity/bootstrap milestones на Rauthy OIDC/Admin API adapter и Cedar Authorization integration. Сохранять рабочий legacy runtime до проверенного переключения, не выполнять разрушительный cutover. Python Control Panel API сохраняется; Gateway не становится PDP. Очередность, согласования и приёмка — по новому решению. Новая сеть/приложение Rauthy требует проверки существующего разрешённого Dev app UUID и защищённой конфигурации.

**Основа:** docs/architecture/owner-decisions-20261012.md — прочитать целиком. Это не отдельный архитектурный консилиум; решения владельца закрыты. Исторические ENV-1, PACKAGING-V1, per-file AST graph и Gateway C2 не могут использоваться как основания для нового блокирования. При невозможности безопасной конкретной операции агент фиксирует факт, делает оставшуюся независимую работу и не возвращается к прежней архитектуре.

**Процесс:** TRY → правка одного принадлежащего сервисного среза → native compile/build (не новая тестовая suite) → PR/обязательные GitHub checks/Reviewer merge → Coolify Dev наблюдение своего app и публичного HTTP → исправление обнаруженного. Никаких новых unit/integration/e2e/smoke suites, никаких длинных приёмочных остановок. Данные, тома, секреты, Git protection и запрет смотреть другие Coolify projects/Shared Environments сохраняются. При переносе каталогов не трогать работающий старый deploy до проверки нового. После публикации отправить READY_FOR_AUDIT через progress, Оркестратор ревизует раздельно.

## Backend — P0: Identity/bootstrap; затем Control Panel API и Platform

**Первый срез, не ждать переноса всех сервисов:** в нынешнем Identity устранить отклонение от продукта: при startup COUNT всех role=superuser в реальной Identity базе; если 0 — атомарно создать/обновить системное приглашение, выдать ровно первую роль superuser по успешной регистрации и вывести системную ссылку в OPERATOR startup logs. Если count>=1 — никогда не печатать системные ссылки; приглашения выдаёт только действующий аутентифицированный superuser через Identity API. Не оставлять дополнительного Unix-оператора как обязательную предпосылку. Не переносить токен в MCP/Gateway/OTLP traces, tool responses или публичный API. Один корректный User при конкурентных операциях; безопасная повторная попытка установки. Нельзя считать древний once-ever boolean достаточным основанием для отказа при count=0.

**Второй срез:** существующая уже согласовываемая Identity signing key (НЕ ADMIN_JWT_SIGNING_KEY) с правильным алгоритмом и форматом из Identity источника. Устойчивый защищённый Environment Shared reference; при рестарте JWT валиден до нормального TTL/revocation, без самовольной смены signing key. Если значение действительно отсутствует, вывести только имя требуемой переменной/scope и состояние ready-not-ready; никогда не создавать бессрочную бессвязную замену или print key. Псевдонимы старого имени не добавлять.

**Третий срез:** Control Panel API настоящий независимый клиент Identity HTTP для /api/auth/register/login/logout и /api/platform/me, остаётся жив при перезапуске Identity (достоверная ошибка, без перезапуска самого API). Реальные role/permission решения у Identity/Authorization/Resources, не Gateway. Публичные endpoints 401/403/405/429/503 адекватны запросу; не принимать forged x-user или service headers. Оператор UI обращается только к Control Panel API. Внутренние Hand API защищаются реальным Authorization/owner; не изобретать международную цепочку C2.

**Четвёртый срез:** перенос собственного кода в services/control-panel/api/ и services/platform/{identity,authorization,platform-control,resources}/, у каждого Dockerfile+Compose+собственный uv manifest/lock и migrations. Перенести только реальные DTO в shared/contracts/<owner>/. Согласовать одного владельца каждого shared пути и передать Runtime/Frontend только небольшой HTTP контракт. Документация по соответствующим путям docs/services/platform/<owner>/, docs/services/control-panel/api/. Docker image получает только каталог сервиса и используемый shared/**; Watch folder/**. Удалять устаревшие exact-graph/COPY/старый deploy/<module> после работающего независимого переноса данного App, сохранив Coolify UUID/DB/volume/rollback. НЕ делать новые SQL-роли и глобальные миграции.

**Результат Backend:** сохранившийся JWT после Identity restart; bootstrap link лишь при count(superuser)<1; обычные invitations лишь от superuser; реальные /api маршруты; изменение Control Panel API не деплоит Identity или Hands. Evidence: SHA, собственный build, Dev runtime/log и путь HTTP, отсутствие лишнего rebuild. Не требовать unit/e2e suite.

## Runtime — P0: изолированная внутренняя сеть Hands; затем Gateway и упаковка

**Первый срез:** изучить реальную сеть и исполнение только РАЗРЕШЁННЫХ Briareus Dev Hands/Terminal/Web и другие разрешённые конкретные Apps. Проверить, какие процессы реально исполняют непроверенный/пользовательский код и может ли эта sandbox-среда по сети обращаться к Control Panel API, Identity, Authorization, PostgreSQL/Valkey/открытым Hands и управлять чужими credentials. Не предполагать, что docker briareus-net уже защищён. Сформулировать конкретные ограниченные изменения network attachment/egress, container UID/capabilities/FS и service owner authenticated ingress, чтобы недоверенный исполнитель не мог свободно бродить по внутренней сети. Не трогать другие проекты/host/global/сами значения секретов; не ломать реальные volume mount и shared DB. Изоляция capability важнее множества C2 hops.

**Второй срез:** Gateway только декларативный reverse proxy: static public/Panel -> Control Panel UI, /api/* -> Control Panel API с оригинальным path/method/body и нужными headers, настоящие issuer/token/discovery -> соответствующий независимый auth service там, где действительно требуется, /hands/<name>/mcp -> соответствующий настоящий Hand с MCP streaming/SSE/WS; поддерживать соединения и собирать только безопасную маршрутную телеметрию. Не возвращать Gateway JWT/C2/User/Project/approval бизнес-классы. Частное имя цели не берётся из клиентского запроса. Go/gRPC не включать в MVP.

**Третий срез:** отдельно располагать services/infrastructure/gateway/ и services/hands/{files,terminal,web,svc,infrastructure,reverse,...}/. Все Hands независимые runtime и наборы модулей; каждый service folder сам содержит Dockerfile, Compose, uv manifest/lock и настройки. Документы в docs/services/hands/<name>/ и docs/services/infrastructure/gateway/. Watch только собственная service/** плюс потреблённые маленькие shared/**. Проверить одну первую маленькую миграцию от current main, затем без лишних согласований повторить для остальных реальных сервисов. Не объявлять новые физические Hand приложения без потребности; логический GitHub/GitLab внутри SVC можно оставить пока независимое развертывание не нужно.

**Четвёртый срез:** убедиться на реальном Dev, что изменение одного Hand не перезапускает другие, UI, Gateway и Identity; изолированный отказ одного Hand не валит остальные. Владелец Hand проверяет Actor/Authorization реальными service endpoints, а не ждёт C2 Gateway. Отказ 503/401 там, где реального доступа нет, остаётся честным.

**Результат Runtime:** реальная sandbox network containment, независимые Hands и Gateway как routing+metrics, реальный folder Watch и отсутствие каскадных rebuild. Native build, Dev logs/HTTP/MCP наблюдение; без новых тестовых framework.

## Frontend — P0: Control Panel UI independent release

**Первый срез:** зафиксировать уже работающие публичный сайт / и /panel/ — не ломать мобильную/десктопную B21 форму, RU/EN, доступность, SEO/noindex и idempotency POST. Сохранять реальные ошибки Identity API и не утверждать, что регистрация прошла без реального User.
**Второй срез:** Control Panel UI — самостоятельно развёртываемый services/control-panel/ui/ с Vue/Bun source, assets, Nginx, Dockerfile/Compose/Bun lock; только UI-folder/** Watch + реальный тематический frontend shared. Документы в docs/services/control-panel/ui/, не в runtime каталоге. Перейти на имя Control Panel UI в интерфейсе/документах, сохранив существующий Coolify App UUID, публичный origin и маршрут.
**Третий срез:** фронтенд обращается только к same-origin /api/* Control Panel API (не напрямую в Identity/Hands и не через спец-C2 Gateway), User и роли отображаются из реального /me, приглашения обычных User появляются только через аутентифицированные superuser операции. UI не должен обещать регистрацию всем подряд после bootstrap и не должен выводить системную ссылку.
**Четвёртый срез:** изменение CSS/UI вызывает только UI build/deploy, не запускает Identity, Control Panel API, Gateway или Hands. Проверить браузер/HTTP после реального Dev Auto Deploy; исправить при поломке в том же PR/slice.

**Результат Frontend:** собственный folder runtime, переименование, пользовательский API-клиент с работающим состоянием первого User, Watch isolation и готовый дизайн. Нативная Bun production build/реальное браузерное наблюдение, без новой тестовой suite.

## Обмен ответами и остановки

- Автором Backend identity JWT/signing и API contract остаётся Backend; Runtime владеет Sandbox/Gateway/Hands; Frontend только UI. Общие поля/DTO передавать через coordination/requests/<lane>.md и один владелец shared.
- Реальный внешний blocker сообщать один раз через requests с ТОЧНЫМ названием потребности, не ссылкой на старые мёртвые ENV-1/Gateway-C2 решения. Любую другую работу продолжать.
- При отчёте агент пишет 3–5 коротких строк текста с emoji, не Markdown-таблицу. Подробные результаты только в progress.md. Оркестратор показывает владельцу таблицу «Backend / Runtime / Frontend — запускать или нет»; другие направления не выводит.

## Приёмочные вопросы Оркестратора

- Соответствует ли конкретная изменённая функция явному owner-decisions контракту?
- Не пересобрались ли другие приложения из-за одного изменения?
- Не проскочила ли ссылка в общие OTLP traces/metrics/MCP logs?
- Остались ли действительные JWT после Identity restart, но не после штатной revocation?
- Не получили ли untrusted Hands сеть/секреты/SQL доступ?
- Не пропали ли DB/volumes/existing Coolify app identity?
- Реальный принятый login и изменения через UI подтверждены HTTP/сервисом, а не health-only?

Это проверка после релиза и по конкретной зоне риска, а не требование создавать отдельный долгий тестовый цикл.

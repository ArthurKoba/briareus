# Briareus

Модульная платформа с независимыми инфраструктурными, доменными и MCP Hands-сервисами. Контрольная панель — два отдельных сервиса: Control Panel API (тонкий управляющий REST-BFF) и Control Panel UI (браузер). Gateway — простой маршрутизатор/stream proxy с безопасной телеметрией.

**Текущий продуктовый и архитектурный контракт:** [Решение владельца](docs/architecture/owner-decisions-20261012.md).

**План реализации:** [Backend / Runtime / Frontend](docs/operations/agent-migration-plan-20261012.md).

**Правила агентов:** [AGENTS.md](AGENTS.md), [Файловая координация](docs/operations/AGENT_COORDINATION.md).

**Операционный переход:** [Сервисный layout](docs/operations/service-layout-transition.md).

В целевой монорепе один каталог на независимо развёртываемый сервис: services/platform/**, services/infrastructure/**, services/hands/**, services/control-panel/**, небольшие shared/**, а отдельно от исходников зеркальные docs/services/**. Каждый сервис имеет собственный Dockerfile, Compose, uv/Bun lock и локальный Watch; изменение одного не запускает остальных.

Реальные запущенные Dev-приложения пока используют старые deploy/<name> и исходные пути, пока их агент отдельно не перенёс с сохранением состояния/отката. Состояние конкретной функции проверять по опубликованному GitHub main и реальному Briareus Development, не по устаревшему README, сборке или /health/live.

Особенности MVP: первый bootstrap system invitation показывается в операторских startup logs Identity только когда в базе нет ни одного superuser; после этого приглашения создаёт superuser. Identity signing key устойчив к restart. JWT/права не проверяются Gateway: ответственность настоящих owner-сервисов. Самый важный изоляционный риск — sandbox MCP Hands и её сетевой доступ к приватной инфраструктуре.

До отдельного решения не добавляем тестовые suite, глобальный wheel, gRPC/Go как обязательный стек или новые SQL-роли/БД. Агенты используют TRY → сборка → Dev → исправление, соблюдая действующие Git permissions и безопасность данных.

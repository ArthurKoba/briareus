# Единый доступ MCP: Gateway PEP + Authorization/Cedar + Hand SDK

**Статус:** решение владельца 16.10.2026, согласованный план миграции; `source-only` до независимой сквозной проверки.
**Основной Issue:** [#536](https://github.com/KobaProduction/briareus/issues/536). **Runtime work_id:** `BR-20261014-R-MCP-01`.
**Границы:** уже существующие `services/gateway`, `services/authorization`, `shared/hand_runtime`, шесть `hands/*`, `services/api`, `services/ui`, Rauthy и Platform. **Нового Authorization-сервиса нет.**

## 1. Зафиксированное решение владельца

Gateway **остаётся единой публичной точкой допуска MCP**: проверяет реальную подписанную личность и **предварительное право на конкретный MCP tool** через существующий Authorization. Gateway не владеет ролями, политиками, Cedar PARC, ресурсами, списком прав пользователя или реализацией инструментов. Он не грузит исполняемые политики MCP-сервисов и не выполняет Cedar локально. Самостоятельные функции Gateway: фиксированная маршрутизация шести разрешённых Hands, ограниченное распознавание вида MCP-вызова и имени инструмента, вызов доверенного Authorization, сохранение исходного тела/заголовков и обезличенная трассировка.

Authorization/Cedar **единственный авторитет** по политикам, возможностям, текущему Actor/Project/AgentSession, выдаче, отзыву и срокам разрешений. Каждая Hand исполняет инструмент, определяет **настоящий ресурс** по каноническим аргументам/владельцу и через **общий Runtime SDK** получает точечное независимое Permit/Deny от того же Authorization. Не копировать Cedar, JWT issuer, роль-парсер, grant CRUD или правила в шесть Hands.

Взаимодействие:

```text
MCP client with provider-issued resource Bearer
       |
       v
Gateway: fixed registered /hands/{hand}/mcp, signed identity,
         current mcp.connect, tool-intent preflight by Authorization
       |                                |
       |                         Authorization/Cedar
       |                         (signed User, Project,
       |                          AgentSession, grants,
       |                          catalog, revocation)
       v                                ^
Hand: immutable tool binding + current canonical owner resource |
       |                                |
       +---- shared Hand SDK --> exact effect Permit/Deny -+
       |
       v
isolated, owner-bound execution ONLY after current Permit
```

Два разрешения служат **разным целям**, но приходят из **одного PDP**: (а) Gateway отказывает в запрещённом tool до отправки запроса в Hand; (б) Hand не допускает подмену действительного Project/файла/сессии/репозитория после предварительного разрешения. Gateway не интерпретирует аргументы бизнес-инструмента, Hand не хранит собственные политики.

## 2. Подтверждённое состояние исходников (не приёмка продукта)

- [`services/authorization/_decision_api.py`](../../../services/authorization/_decision_api.py): существующий `POST /internal/v1/authorization/decide`, `DecisionCommand`; допускает `mcp.connect` **без** hand/tool/resource и per-effect вызов **только** с hand/tool/resource. Возвращает строгий Permit `{"allowed":true}` либо отказ, требует подтверждённых actor/Project/AgentSession/grant/revision и независимого service peer.
- [`services/authorization/_action_audiences.py`](../../../services/authorization/_action_audiences.py): фиксированный словарь V2 действий/Hand. Это не персонифицированная registry capabilities и не готовые отдельные read-only grants.
- [`services/gateway/src/bridge/_mcp_admission.py`](../../../services/gateway/src/bridge/_mcp_admission.py): выпущенный `main` содержит закрытый coarse `mcp.connect` admission через `TrustedGatewayDecisionPort`. **Точного tool-intent preflight API пока нет.**
- [`shared/hand_runtime/_effect_auth.py`](../../../shared/hand_runtime/_effect_auth.py): уже содержит общий PEP: подписанный ресурсный токен, неизменяемое `ToolEffectBinding`, owner resolver, current selectors, самостоятельный private Cedar decision. Это источник для единого SDK, не проект второго Cedar.
- [`hands/files/src/files_hand/_mcp_activation.py`](../../../hands/files/src/files_hand/_mcp_activation.py) и [матрица шести Hands](../../shared/runtime-six-hand-owner-matrix-20261016.md): staged-only фабрики. Реальные deployed `hands/*/server.py` остаются diagnostic-only; ни `files.read`, ни браузерный эффект не прошли signed product acceptance.

**Материальный пробел:** текущий `DecisionCommand` требует настоящий ресурс для tool-effect; Gateway его не знает и не должен придумывать. Для Gateway tool-intent требуется отдельный **versioned preflight contract** в **существующем** Authorization, а не ложный `EffectResource` или обход проверки. Backend владеет контрактом и его решением.

## 3. Версионированный каталог возможностей (proposal, ещё не API)

Каждая Hand предоставляет декларативные *метаданные*, а не исполняемый Cedar-политикод: `hand`, `tool`, `action`, `resource_kind`, read/write/side-effect classification, обязательный owner verifier, схемная версия. Пример из уже существующего словаря:

```yaml
schema_version: 1
hand: files
tools:
  - name: read_file
    action: files.read
    resource_kind: workspace_path
    effect_class: read
    owner_required: true
  - name: write_file
    action: files.write
    resource_kind: workspace_path
    effect_class: write
    owner_required: true
```

Это **предложение формата**, не утверждение, что `write_file` уже зарегистрирован в Dev. Спецификация подписывается/проверяется в цепочке **trusted source → review/CI → owner registry publication**; Authorization валидирует уникальность, версии, обязательный owner scope и совместимость action/Hand. Нельзя автоматически доверять runtime `tools/list`, `readOnlyHint`, тексту инструмента или клиентскому JSON как источнику политики. Новый/неизвестный инструмент по умолчанию Deny. Gateway читает только идентификатор `hand/tool` либо номер версии каталога; правила и grants находятся исключительно в Authorization.

Четыре отдельные read-only action для Terminal, SVC, Infrastructure и Reverse должны быть согласованы Backend: существующие `terminal.execute`, `integrations.use`, `analysis.import` **слишком широки** и не означают доступ к метаданным. Не активировать staged source, пока action vocabulary и доверенный owner контракт не утверждены.

## 4. Контракт Gateway ↔ Authorization (целевой, не существует в main)

- **Ingress:** Gateway проверяет Bearer как подлинный ресурсный Rauthy access token через доверенный verifier/Authorization; подпись, issuer, audience **конкретного Hand**, срок, purpose и при необходимости revocation. Наличие заголовка само по себе ничего не даёт. Ключи и issuer принадлежат Rauthy, не Gateway.
- **Current connection:** сохранить `mcp.connect` проверку текущего Project/AgentSession/grant/revision через существующий Backend до принятой замены. Произвольный заголовок `X-Briareus-Project-UUID` не является подтверждением владения.
- **Tool preflight:** Backend добавляет *отдельный* authenticated private preflight, вход которого в концепции: authenticated actor, `project_uuid`, `agent_session_uuid`, `expected_grant_revision`, `hand`, `tool`, `catalog_version`, request/peer-bound proof. Authorization проверяет, известен ли инструмент, привязанный action и есть ли предварительное разрешение вызвать его. **Нет** подставного конкретного `resource.id`, нет вызова `_decision_api` с неверным типом, Gateway не разбирает бизнес-аргументы. Статус/DTO успешного решения определяет Backend и фиксируют контрактные тесты; сам Gateway лишь исполняет Permit/Deny.
- **MCP envelope:** Gateway может ограниченно читать/проверять `tools/call.params.name` и другие защищённые классы MCP-протокола ради маршрута/preflight. Нельзя пропустить `resources/read`, `prompts/get`, notification/batch или будущий метод как альтернативу запретам. Требуется явная политика для `initialize`, `ping`, `tools/list`, `tools/call`, stream sessions, delete/session lifecycle и unsupported methods. Неизвестный protected method — Deny, либо безопасная передача только после общепротокольного разрешения, подтверждённого Backend. JSON-RPC запрос передаётся в Hand **без изменения**.
- **Fail closed:** недоступный issuer, нет приватного authenticator, policy/registry outage, неизвестный `tool`, stale revision, Cedar Deny → Gateway не вызывает Hand. Никакого Bearer → Permit fallback, кешированного старого Permit, Rauthy admin-token, синтетических ролей или off-prefix маршрутов.
- **MCP trace:** `hand`, стабильная категория метода, decision allow/deny/unavailable, latency bucket, HTTP status. Без токенов, аргументов, полных resource IDs, имён файлов/аккаунтов, query/password/cookies. Транспортные лимиты, anti-header-smuggling, фиксированные назначения и корректный стриминг сохраняются.

## 5. Контракт Hand ↔ Authorization

Один `shared/hand_runtime` SDK для шести Hands; Hand регистрирует фиксированное сопоставление `tool → action/resource_kind → owner resolver`, получает из владельца канонические аргументы и **настоящий** resource ID. Затем SDK запрашивает `/internal/v1/authorization/decide` или специализированный owner-confirmed read-decision через независимо аутентифицированный Hand peer с bound body/effect, nonce/replay и коротким сроком. Только соответствующий current Permit допускает side effect. Ревокация проверяется заново (и после чтения, когда это требует Files/Web); не полагаться на Gateway Permit.

Hand владеет жизненным циклом и целостностью **своего ресурса** (файл, worker, browser-session, repository, application), но не словарём ролей и не Cedar policy. Секреты и private provider credentials не передаются в Gateway или HTTP MCP client. Terminal/shell, browser navigation/click, download/upload, инфраструктурные мутации и внешние интеграции требуют дополнительных sandbox/capability gates.

## 6. Режим миграции без нового поломанного Dev

| Этап | Владелец | Доказательство/граница |
|---|---|---|
| **0. Зафиксировать решение** | Оркестратор #536 + все агенты | Обновить тело #536 **только оркестратором**, сделать этот документ единым маршрутизатором к Backend/Runtime/UI/Deployment. Незавершённую локальную ветку `runtime/gateway-authentication-only-20261016` **не публиковать**: она устраняет `mcp.connect` и пока не имеет tool preflight. Сохранить известный рабочий main/Dev. |
| **1. Owner contracts** | Backend: Authorization + Platform | Утверждённый catalog v1 с записью/обновлением/отзывом, current roles/Project/AgentSession, отдельный ingress tool preflight без реального ресурса; negative contract tests на неизвестный tool/role/revision/revoke. **Только Backend меняет эти пути и Cedar**. |
| **2. Generic ingress** | Runtime: Gateway | Небизнесовая MCP envelope классификация, signed resource authentication, `mcp.connect`, tool-intent preflight через private peer, фиксированный маршрут и оригинальный MCP body; ограниченная безопасная трассировка. Реальная Hand invocation только после Permit. UI/Nginx и Control Panel API — прозрачный proxy, без возвращения asset/MIME политики. |
| **3. Generic effect SDK** | Runtime: shared/hand_runtime + Hands | Подключить существующий `EffectAuthorizationMiddleware` к настоящему private peer, owner resolver/revision/lease. First effect Files read; остальные five staged кандидаты только после узкой политики и owner доказательств. Пакетные negative tests across all six. |
| **4. Control Panel grants** | Backend API BFF + Frontend UI | BFF предоставляет разрешённую owner-management API; UI показывает tool/Project/role scope и approvals/revoke, активность только при настоящем owner DTO. Никакого прямого UI→private Authorization, декоративного enabled tool или доступа по одному `tools/list`. |
| **5. Dev transport and accepted E2E** | Deployment совместно с владельцами lane | Только существующие UUID Dev, проверенный Rauthy token audience/JWKS, реальный mTLS/Unix/private peer, Coolify build/watch, signed identity + Permit/Deny/Revoke. Никаких новых приложений/SQL/сброса Users/PGDATA/Valkey/Files. Релиз раздельными проверенными source SHA с rollback. |

## 7. Acceptance contract: измеряемый, без фиктивного «готово»

1. **Identity:** отсутствующий/поддельный/просроченный/wrong audience Bearer отсекается **до** вызова Hand; не существует fallback по обычному заголовку.
2. **Per-tool:** один реальный Rauthy User и AgentSession имеют право на `files.read` и не имеют на `files.write` в том же Project; Gateway отказывает во втором **до** обращения к Files, не храня это правило у себя.
3. **Per-resource:** после ingress Permit Hand отвергает файл/браузер/репозиторий другого Project или устаревшую ревизию; ни Gateway, ни поддельный selector не создаёт owner mapping.
4. **Revocation:** отзыв права/изменение revision немедленно (по принятому bounded current check) закрывает последующий вызов; отсутствие Authorization/Cedar или расхождение каталога — отказ.
5. **Protocol:** `initialize/tools/list/tools/call`, streaming/notifications/session lifecycles и ошибочные методы защищены от альтернативного обхода; оригинальные HTTP/MCP bytes, status и headers доходят до владельца.
6. **Operational:** ingress policy/role/catalog change не требует пересборки Gateway или всех Hands; изменение **реальной** реализации tool требует owner release/review и согласования capability contract. Liveness, локальный signed fixture, build, Dev traffic и end-to-end signed product acceptance — разные состояния.
7. **MVP:** после Files read positive+deny+revoke те же общие механизмы проходят отдельную приёмку для Terminal/Web/SVC/Infrastructure/Reverse с их собственными sandbox/owner gates.

**Что сознательно не утверждается:** наличие реального verifier/peer в Gateway Dev, установленного policy catalog/preflight в Authorization или хотя бы одного подписанного разрешённого Files effect; все эти шаги пока открыты.
# Backend control-plane and data architecture roadmap

Status: architecture authority / implementation backlog  
Date: 2026-10-03

This document defines the backend state, cache, event, telemetry and API model for the MCP Bridge clean-architecture refactor. It complements `mcp-upstream-roadmap.md`.

## Core model

Do not use one storage/transport for everything.

| Concern | Primary mechanism | Role |
| --- | --- | --- |
| durable application state | SQL via SQLAlchemy | source of truth |
| hot cache / live state | Valkey | low-latency disposable state |
| durable/replayable events | Valkey Streams | bounded event log / queue |
| live fanout | Valkey Pub/Sub | wake-up / realtime delivery accelerator |
| traces/logs/metrics | OTLP -> SigNoz | observability system of record |
| large/local artifacts | filesystem / persistent volumes | files, browser profile, downloads, job logs where appropriate |
| agent/provider capabilities | MCP | callable capability protocol |
| frontend control plane | HTTP/OpenAPI + WebSocket | UI reads, writes and subscriptions |

### Terminology warning

Valkey is **not** a write-ahead log (WAL). It is an in-memory data store used here for cache, live state and event infrastructure.

A SQL WAL is an internal durability mechanism of the database. It should not be treated as an application cache API.

The application pattern is therefore:

```text
read hot state:
  application -> Valkey -> miss -> SQL -> Valkey -> application

write durable state:
  application -> SQL transaction -> Valkey update/invalidate -> settings/domain event

telemetry:
  application/frontend -> OTLP relay/exporter -> SigNoz

system event:
  producer -> EventPublisher -> Valkey Stream + Pub/Sub -> WebSocket subscribers/workers
```

## SQL ownership

SQL is the durable system of record for the MCP Bridge platform, not for MCP provider telemetry.

Expected durable domains include:

- application settings and revisions;
- provider/integration account metadata;
- encrypted provider credentials or references to encrypted secrets;
- authorization/session metadata that must survive restarts;
- future users, roles and account/MCP ACLs;
- OAuth state and revocation metadata where durable storage is required;
- audit/MCP-call records according to retention policy;
- coarse dashboard/application snapshots that must survive loss of Valkey/SigNoz;
- notification records only where product semantics require durable acknowledgement/history;
- migration/schema metadata.

Do **not** store raw traces, logs or high-frequency metric samples in this SQL database. SigNoz owns those.

### SQLite vs PostgreSQL

SQLAlchemy should make repositories database-agnostic, but a PostgreSQL migration is a separate decision from the clean-architecture refactor.

SQLite is acceptable while:

- Management is a single writer process;
- write volume remains modest;
- horizontal scaling is not required;
- WAL mode and bounded background writes are sufficient.

PostgreSQL becomes justified when we need:

- multiple Management instances/writers;
- real multi-user concurrency;
- stronger locking/transaction behavior;
- horizontal scale/high availability;
- larger relational query workloads.

Do not migrate merely because PostgreSQL sounds faster. The hot path should normally be served from Valkey anyway.

### Migrations

Adopt standard SQLAlchemy migrations (Alembic) as part of this refactor. Schema changes must become explicit migrations, not implicit startup mutation logic.

## Valkey ownership

Valkey is the high-speed coordination layer.

Use separate namespaces/contracts:

```text
cache:*          account/settings/provider resolution caches
live:*           current dashboard/runtime state
session:*        hot session/authorization state derived from durable authority
connections:*    active frontend/device/socket counters with TTL
stream:*         Valkey Streams for replayable domain/runtime events
pubsub:*         live event wake-up/fanout
lock:*           narrowly scoped distributed locks only where required
```

### Cache read pattern

```text
get(key)
  -> Valkey hit: return
  -> Valkey miss: read durable authority (SQL/provider)
  -> populate Valkey with TTL/version
  -> return
```

### Mutation pattern

For security-sensitive state such as account credential revocation or authorization invalidation:

1. write the durable state transition;
2. invalidate/update Valkey immediately;
3. publish a versioned invalidation/domain event;
4. consumers reject stale revisions;
5. operation is idempotent and safe to retry.

Never make correctness depend solely on a TTL expiring eventually.

### Valkey is disposable

Loss of Valkey must degrade performance/realtime continuity, not corrupt durable platform state. Durable state can be rebuilt from SQL/provider authorities.

## Event architecture

Services publish semantic events through an application-level `EventPublisher` port. Producers do not know about WebSocket clients.

Use Valkey Streams for bounded replay/history and Pub/Sub as the fast notification path.

Example:

```text
MCP invocation completed
  -> XADD stream:mcp.calls <event>
  -> PUBLISH pubsub:mcp.calls <stream-id>
  -> realtime gateway wakes
  -> reads missing Stream IDs
  -> fans event to every authorized subscriber
```

Do not use one Valkey consumer group for browser fanout; consumer groups distribute events between consumers, whereas UI clients commonly need the same event delivered to multiple subscribers.

### Event envelope

```json
{
  "id": "sortable-event-id",
  "topic": "mcp.calls",
  "type": "mcp.call.completed",
  "version": 1,
  "occurred_at": "ISO-8601",
  "source": "github",
  "severity": "info",
  "principal_id": "bootstrap-admin",
  "entity": {"kind": "mcp_call", "id": "..."},
  "payload": {}
}
```

Payloads are bounded and must never carry secrets, raw authorization headers, terminal stdin, browser form values or arbitrary page content.

## Frontend realtime API

One authenticated WebSocket endpoint should serve the management frontend:

```text
wss://<host>/api/v1/realtime
```

Subscriptions are view-driven:

```text
mcp.calls
notifications
dashboard.metrics
runtime.health
analysis.workers
analysis.projects
terminal.jobs
browser.state
settings.changed
infrastructure.deployments
```

Client protocol:

```json
{"op":"subscribe","topics":["mcp.calls","notifications"]}
{"op":"unsubscribe","topics":["mcp.calls"]}
{"op":"resume","cursors":{"mcp.calls":"..."}}
{"op":"ping"}
```

Server protocol:

```json
{"op":"hello","connection_id":"...","limits":{"topics":32,"message_bytes":65536}}
{"op":"event","topic":"mcp.calls","cursor":"...","event":{}}
{"op":"error","code":"...","message":"..."}
{"op":"pong"}
```

Security/limits:

- authenticated principal required before upgrade;
- exact Origin validation;
- WSS in production;
- no bearer/session token in query string;
- per-topic authorization;
- bounded message size and inbound rate;
- heartbeat/idle timeout;
- bounded send queue; disconnect slow consumers;
- configurable maximum active connections per principal, default `10`;
- session revocation/logout terminates active sockets.

The current SQL-polling MCP Calls SSE endpoint should be retired after frontend migration.

## Frontend telemetry ingress

Browser telemetry must never contain the upstream OTLP bearer secret.

Expose authenticated same-origin OTLP/HTTP-compatible backend ingress, e.g.:

```text
POST /api/v1/telemetry/v1/traces
POST /api/v1/telemetry/v1/metrics
POST /api/v1/telemetry/v1/logs
```

Flow:

```text
frontend OpenTelemetry SDK
  -> authenticated backend ingress
  -> session/principal + Origin + size/rate validation
  -> transparent body/content-type relay
  -> server adds Authorization: Bearer <secret>
  -> configured telemetry endpoint (standard target: telemetry.comednexus.ru)
  -> OTLP collector / SigNoz
```

Only authenticated application sessions are accepted. Unknown/anonymous telemetry is dropped/rejected.

The backend may enrich safe resource metadata such as environment/application/frontend version/principal class, but it must not inject sensitive user data.

### Telemetry settings

Durable encrypted application settings should include:

```text
telemetry.enabled
telemetry.endpoint
telemetry.bearer_token        # encrypted, never returned to frontend
telemetry.traces_enabled
telemetry.metrics_enabled
telemetry.logs_enabled
telemetry.frontend_sample_ratio
telemetry.max_request_bytes
telemetry.export_timeout_ms
```

Frontend receives only safe runtime configuration (enabled flags, sample ratio, same-origin ingest path).

## Live metrics versus observability metrics

Do not confuse these two classes.

### Observability telemetry

CPU, memory, request latency, errors, frontend Web Vitals, traces and logs go to OTLP/SigNoz.

### Live management state

Small derived counters/state required for interactive UI may live in Valkey:

```text
live:dashboard:mcp_calls_1m
live:dashboard:mcp_errors_1m
live:dashboard:active_jobs
live:dashboard:analysis_workers
live:dashboard:realtime_connections
```

They are disposable, timestamped and rebuildable. Historical charts should normally query SigNoz. SQL may receive coarse periodic snapshots only when the product needs history independent from SigNoz.

## Settings architecture

Replace the flat management config over time with typed versioned sections:

```text
general
security
telemetry
realtime
mcp
observability
browser
analysis
terminal
retention
ui
```

Persist each section with metadata:

```text
section
revision
schema_version
value
updated_at
updated_by
```

Secret fields are encrypted and omitted from read responses.

Update flow:

```text
API update
  -> typed validation
  -> SQL transaction
  -> Valkey update/invalidate
  -> settings.changed event {section, revision}
  -> sanitized API response
```

Move product settings out of Docker Compose when they can safely be changed at runtime.

Keep bootstrap/infrastructure requirements in environment/deployment configuration:

- DB URL;
- Valkey URL;
- encryption/master secret;
- session signing secret;
- bootstrap superuser credentials;
- internal service discovery/network addresses;
- public environment/base URL required for startup.

## Identity and future multi-user support

Do not implement full RBAC now, but stop treating a string admin username as the domain identity.

Introduce:

```text
Principal {
  id
  kind = bootstrap_superuser | user | service
  capabilities
}
```

Current frontend principal: bootstrap superuser.

Deferred model must support:

- users and roles;
- per-user sessions/devices;
- configurable max sessions/connections;
- integration/provider-account ACLs;
- per-MCP capability grants;
- user-owned provider auth/reauth;
- explicit session/device revocation.

The bootstrap superuser remains a break-glass path configured outside normal SQL account state.

## State placement examples

| State | Durable SQL | Valkey | Filesystem/volume | SigNoz |
| --- | --- | --- | --- | --- |
| GitHub/GitLab account metadata | yes | cache | no | audit only |
| encrypted provider secret | yes/secret store | short-lived resolved cache | no | never |
| app settings | yes | cache | no | change telemetry only |
| frontend login/session durable metadata | when needed | active/hot session | no | safe auth telemetry |
| MCP upstream connection object | no | no (process memory) | no | spans/metrics |
| MCP account/session routing metadata | if durable requirement | yes | no | spans/metrics |
| browser tabs | usually no | optional live state | Chromium profile owns actual state | safe telemetry |
| browser cookies/local storage | no | no | browser profile volume | never raw |
| workspace files/downloads | metadata only if product requires | optional cache | yes | operation telemetry |
| terminal job output | metadata SQL optional | live status | durable bounded log files | job telemetry |
| MCP invocation audit | yes, retention bounded | recent/live index optional | no | correlated trace |
| traces/logs/high-rate metrics | no | rolling UI aggregates only | no | yes |
| realtime event replay | optional coarse archive | Streams | no | event processing telemetry |

## Internal communication rules

Use the protocol that matches the problem:

- **MCP** for callable provider/agent capabilities and upstream proxying;
- **HTTP/OpenAPI** for frontend/control-plane CRUD/query APIs;
- **internal typed HTTP** for low-volume service control where MCP adds no value;
- **Valkey event bus** for asynchronous application/runtime events;
- **OTLP** for technical telemetry;
- **SQL** for durable state;
- **filesystem/object storage** for large binary/local artifacts.

Do not require every internal service-to-service interaction to become MCP. That would conflate RPC capabilities with event streaming and telemetry.

## OpenAPI/frontend contract

The public management API becomes versioned (`/api/v1`). OpenAPI is the authority for frontend code generation.

Rules:

- typed request/response DTOs;
- no direct SQL/provider models in frontend schema;
- stable error envelope with machine-readable `code` and correlation ID;
- pagination/cursor conventions shared across tables;
- generated frontend client is not manually forked;
- WebSocket event schemas are versioned alongside HTTP/OpenAPI contracts (JSON Schema/AsyncAPI-style documentation may be added even if codegen remains OpenAPI-first).

## Notification contract

Backend emits semantic notification events; frontend decides toast rendering/i18n.

```json
{
  "severity": "error",
  "code": "analysis.worker.recovery_failed",
  "title_key": "notifications.analysis_worker_recovery_failed",
  "message": "safe fallback",
  "details": {},
  "dedupe_key": "analysis:worker:1:recovery",
  "correlation_id": "..."
}
```

Known product notifications use translation keys. Raw exception strings are not the primary UI contract.

## Clean Architecture / DDD boundaries

Strengthen the existing `domain/application/infrastructure/presentation` split.

### Domain

Suggested bounded modules:

```text
identity
configuration
integrations
events
realtime
telemetry
audit
snapshots
```

No FastAPI, SQLAlchemy, Valkey, WebSocket or OTLP types in Domain.

### Application

Ports/use cases such as:

```text
ResolvePrincipal
GetSettings / UpdateSettings
ResolveIntegrationAccount
PublishEvent / ReadEventHistory
SubscribeRealtimeTopics
IngestFrontendTelemetry
ReadLiveDashboardState
RecordInvocation
BuildDashboardSnapshot
```

Ports describe behavior, not technology (`EventPublisher`, not `ValkeyPublisher`).

### Infrastructure

```text
SqlAlchemy repositories
Valkey cache adapter
Valkey event bus adapter
OTLP telemetry relay
MCP upstream transports
filesystem/process/browser/Ghidra adapters
```

### Presentation

```text
HTTP /api/v1
WebSocket /api/v1/realtime
internal service API
legacy admin compatibility (temporary)
```

## Implementation phases

### Phase 0 — contracts and authority

- freeze this state-placement model;
- introduce `Principal` abstraction;
- define versioned API error envelope;
- define EventEnvelope/topic vocabulary;
- define typed settings sections/revisions;
- introduce application ports for cache/event/telemetry relay;
- adopt Alembic migration baseline around current SQL schema.

### Phase 1 — event infrastructure

- add Valkey Streams + Pub/Sub event adapter;
- publish MCP invocation/settings/account/runtime events;
- add event retention/trim policy;
- add idempotency/version tests;
- keep existing SSE temporarily.

### Phase 2 — realtime gateway

- authenticated `/api/v1/realtime` WebSocket;
- subscribe/unsubscribe/resume protocol;
- per-principal connection limit (default 10);
- bounded queues/rates/heartbeat;
- MCP Calls frontend moves from polling SSE to event deltas;
- remove SSE after acceptance.

### Phase 3 — telemetry relay

- authenticated OTLP/HTTP frontend ingress;
- encrypted telemetry endpoint/token settings;
- safe resource enrichment;
- rate/body limits;
- frontend browser telemetry acceptance in SigNoz;
- never expose upstream bearer secret to browser.

### Phase 4 — settings and caching refactor

- split flat config into typed sections;
- settings revision/invalidation events;
- services consume cached settings instead of repeated SQL reads;
- move mutable product settings out of Compose where safe;
- add live dashboard state caches/rolling counters.

### Phase 5 — SQL/storage evolution

- benchmark actual SQLite contention after hot-path migration;
- keep SQLite if it remains adequate;
- migrate to PostgreSQL only if multi-writer/multi-user/HA requirements justify it;
- if migrating, preserve repository/application contracts and use Alembic data/schema migrations.

### Deferred — multi-user/RBAC

- user entities;
- roles/capabilities;
- account/MCP ACLs;
- per-user provider authorization;
- device/session management;
- configurable session limits and revocation.

## Acceptance criteria

The backend refactor is not complete until:

- SQL is not on repeated high-frequency read paths that can be safely cached;
- Valkey loss does not lose durable platform configuration/account state;
- every security-sensitive mutation invalidates relevant cache immediately and idempotently;
- raw observability telemetry is not duplicated into SQL;
- frontend telemetry never exposes the OTLP bearer token;
- anonymous frontend telemetry is rejected;
- realtime events have replay/cursor behavior across short disconnects;
- multiple frontend connections receive the same subscribed fanout event;
- slow clients cannot create unbounded server memory queues;
- API is generated from a stable OpenAPI contract;
- frontend no longer polls SQL every second for MCP Calls;
- storage/event/telemetry decisions are covered by integration tests and observable spans/metrics.

## Relationship to upstream-first MCP refactor

The upstream-first MCP roadmap and this backend roadmap converge on one product shape:

```text
Frontend/API/Realtime
        |
   Control Plane
  SQL + Valkey + Events
        |
Account/Auth/Policy/Audit
        |
Generic upstream MCP proxies
        |
GitHub / GitLab / SigNoz / Coolify / Playwright / Ghidra
        |
      OTLP
        v
     SigNoz
```

The bridge owns orchestration, identity, policy and product state. Upstreams own provider-domain behavior. SigNoz owns observability telemetry. Valkey owns hot/realtime state. SQL owns durable application state.

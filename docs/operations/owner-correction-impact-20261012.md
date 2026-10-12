# Briareus — последствия коррекции ТЗ, 12.10.2026

Current selected owner decisions: ../architecture/owner-decisions-20261012.md.
Execution: agent-migration-plan-20261012.md.

This is a SOURCE-IMPACT inventory and historical contradiction resolution, **not** evidence of code repair or a deployed product. Application source, Docker runtime, passwords/keys and Dev configuration were intentionally NOT mutated during this documentation correction.

## P0 actual code requiring work

**Identity bootstrap:** services/identity/_service.py previously issue_first_admin_setup() required restricted one-use operator delivery and forbade system signup after a claimed first superuser. Inspect current published main; change default Identity startup in services/identity/platform_runtime.py and first-user routes to count role=superuser. On zero print registration link in OPERATOR startup logs and allow exactly one first superuser; on one or more never log system link; remaining users invited only by authenticated superuser. Preserve one-use invitation and race safety; do not output code in generic OTLP traces/MCP logs. Retire Unix-only first-admin bootstrap wiring as a mandatory gate.

**Identity key:** services/identity/direct_first_user.py currently constructs an ephemeral Ed25519 private signer per process restart. Replace with already owner-discussed stable **Identity** signing key reference delivered via Environment Shared; no ADMIN_JWT_SIGNING_KEY fallback, no sharing the key with Gateway and no exposure of value. Confirm actual key name/format as a nonsecret coordination fact with Backend.

**Control Panel API/UI:** current legacy services/admin-api/src and admin-web-app were renamed conceptually to Control Panel API/UI. Keep /api/auth/register/login/logout, /api/platform/me and same-origin /panel/ working while their owners reorganize the code and deploy into service-local folders. The Gateway must remain thin /api proxy; do not revive gateway_transport business JWT/C2 chain.

**Watch and builds:** current deployed Identity Watch previously had fewer entries than published Git, including first_user source. Convert one app at a time to service-directory/** plus consumed shared/topic/**, confirm persisted Coolify Dev watch after safe independent cutover; do not mass edit all apps or introduce per-file regeneration. Avoid rebuilding unrelated services.

**Network isolation:** existing Hands runtime and Docker network attachments must be checked by Runtime for ability of untrusted MCP/Terminal/Web execution to call Identity, DB, Valkey, other Hands or Control Panel internal endpoints without genuine owner auth. Treat it as priority, but avoid non-scoped host/network or other-project observation. Constrain sandbox network/UID/capabilities/secret delivery in its OWN permitted service app as small safe slices.

**PostgreSQL:** existing Dev single principal / four logical DB accepted, no new split/role/global migrator required. Source migrations remain domain-owned; no wipe or data volume recreation.

## Documentation contradictions eliminated from active path

- Old product spec system link at every restart even with superuser -> removed; replaced by count(superuser)<1 only.
- ENV-1 prohibition of operator startup link / required Unix-only setup -> removed.
- ENV-1 all Project Shared / ADMIN_JWT_SIGNING_KEY default -> removed.
- Packaging-V1 one global immutable Python wheel, per-file AST source/watch -> removed from normative contracts.
- Gateway C2/JWT/business authorization -> removed from active architecture and maps.
- Separate deploy/<module> layout as required future -> retired; target local service folder + mirrored docs outside.
- New SQL roles/least privilege as **MVP prerequisite** -> retired; internal Hands sandbox risk prioritized instead.
- Old required preapproval, old READY_FOR_REVIEW copy block, worker chat tables -> removed.
- New unit/integration/e2e/smoke suites required as blanket acceptance -> prohibited for current owner phase; native build and real Dev observation retained.

## Archival provenance

Full prior contents of old active documents and coordination request journals are preserved in local/artifacts/owner-policy-reconciliation-20261012/originals/ as read-only evidence. They are not live normative rules and should never be reintroduced merely because an earlier text labels itself owner-approved. Active docs point only to the selected owner decision and executable agent task.

**Operational status:** documentation corrections only. Code fixes, startup logs, signer persistence, role-count semantics, sandbox isolation, build rerouting and actual service-folder migrations are still owned by Backend/Runtime/Frontend; no DONE/production-ready assertion is made here.

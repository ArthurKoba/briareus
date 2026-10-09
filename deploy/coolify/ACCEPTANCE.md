# Briareus deployment granularity — owner acceptance / correction

Date: 2026-10-09
Status: **D-owned staging corrected; awaiting independent orchestrator review and Git integration.** Not a Coolify runtime acceptance.

## Owner's requirement and rationale

The prior packaging split external PostgreSQL and Valkey into separate Coolify Applications, and GitHub/GitLab adapters into separate SVC Applications. The owner rejects this operationally excessive fragmentation. **The optimization objective is to restart/rebuild only a changed, meaningful Briareus functional module** without stopping Gateway, Auth, Browser/Terminal state or unrelated modules, and without forcing the operator to maintain a new deploy resource for each dependency, provider or tool.

The target architecture in `repo/docs/architecture/target-project-platform.md` §7.1 already states:
- A business/domain module does NOT imply one container per adapter/worker.
- **SVC** is one deployment unit for GitHub, GitLab, GitHub App and future version-control adapters.
- **Web** is one deployment unit for HTTP/cURL, Chromium, Remote Browser.
- **Reverse** is one domain release boundary for Analysis/Ghidra; an extra executor container only when the OS/process security contract requires one.
- **Infrastructure** hosts the Coolify/SigNoz/Grafana integrations within one module rather than one Coolify Application per provider.
- **Administration API, Administration UI, Authorization, Gateway and other large functional modules** retain independent updates because coupling them recreates the historical four-minute all-in-one legacy deploy problem.

For external data dependencies, one Coolify Application **`briareus-dev-data`** has two separately isolated **vendor containers** (PostgreSQL and Valkey). Putting a database daemon and cache daemon into a single OS container is unnecessary and harms vendor image/health/storage behavior; they nevertheless share **one** Coolify release/deploy lifecycle and require only **one** external dependency configuration. Other external systems (GitHub, GitLab, Grafana, SigNoz, Coolify API) are *connections consumed by Briareus*; they are not redeployed for every account or integration.

The new default is a **bounded module-oriented MVP**, not a return to an all-in-one Briareus application and not a microservice per adapter. A future split is justified only by observed deploy/startup latency, independent scaling, isolation or incompatible runtime lifetime, and must update source contracts, Watch Paths and ownership.

## Measurable change

| Scope | Previous staging | Corrected active staging |
| --- | ---: | ---: |
| Coolify Applications (release units) | 13 | **11** |
| Portable Compose files | 13 | **11** |
| Coolify-specific Compose files | 13 | **11** |
| Total Compose files | 26 | **22** |
| Vendor-data deploy resources | 2 (Postgres, Valkey) | **1** (`data`, 2 vendor containers) |
| Version-control deploy resources | 2 (`svc-github`, `svc-gitlab`) | **1** (`svc`, 1 staged combined image) |
| External infrastructure data modules | 2 | **1** |

**11 active Coolify Applications = 10 Briareus-owned modules + 1 external data group.** The 10 Briareus modules are `authorization`, `gateway`, `admin-api`, `admin-ui`, `files`, `terminal`, `web`, `svc`, `infrastructure`, `reverse`. The database group is not counted as a Briareus business module.

The four rejected release packages are preserved, excluded from the active deploy graph, at `local/deployment/obsolete/overgranular-release-units-2026-10-09/{postgres,valkey,svc-github,svc-gitlab}/`; no deletion of legacy state/source/volumes.

## Independent review changes — D1-WATCH-01 and D1-PACKAGE-02

- **D1-WATCH-01:** All seven rooted Python module-build consumers (Gateway, Files, Terminal, Web, SVC, Infrastructure, Reverse) now explicitly watch `services/modules/__init__.py`, because their actual Dockerfiles `COPY` this file. Rebuilt this document's Watch Paths inventory directly from the 11 authoritative Coolify Compose extensions.
- **D1-WATCH-01:** In `_build/Dockerfile.greenfield`, the `core` stage contains ONLY common/shared authorization and domain packages. The `admin-preview` stage alone COPYs `services/admin-api/src`; the `schema-init` stage alone COPYs `scripts/greenfield_schema.py`. Authorization is built FROM `core` and does not inherit these files. Admin preview no longer watches a schema-only script that its image does not copy. Shared stage/Dockerfile changes may still trigger true shared-consumer rebuilds, but Admin-only Python source edits do NOT rebuild Authorization.
- **D1-PACKAGE-02:** Moved `APPLICATIONS.json`, `sync_watch_paths_coolify.py`, `README.md`, `ACCEPTANCE.md`, `WATCH_PATHS.md`, and `SHA256SUMS` from the outer staging root into the actual proposed tracked Git root `deploy/coolify/**`. Orchestrator must transfer/review the WHOLE `deploy/coolify/` directory, not just Compose. The checksum manifest covers every other file therein (except itself) and can be verified relative to this path. No duplicates/source-of-truth ambiguity in outer stage root.
- **Scope:** This is SOURCE+STATIC staging correction; does NOT authorize Git publication, Coolify Applications, Docker build or C1-B2/C2 activation. Immutable published dev ref, installed parser/network Destination evidence, image builds and 11-app bootstrap remain blocked for independent review.

## Implementation acceptance (staged source only)

- [x] Combined Postgres + Valkey as two services in **one** `deploy/coolify/data/docker-compose.yaml`, with own distinct persistent volumes and healthchecks.
- [x] Combined GitHub + GitLab modules into a **single SVC image** defined in `deploy/coolify/svc/Dockerfile`, a **single SVC Compose service** and one future independent Coolify Application. Unified authenticated SVC ASGI server is an **explicit Runtime R9 dependency**; no fake running endpoint.
- [x] Web remains one package; no separate cURL, Chromium or Remote Web release units.
- [x] Infrastructure remains one package for infrastructure provider adapters.
- [x] Reverse remains one logical release unit; Analysis+Ghidra executor packaging and OS separation are explicitly still pending, not replaced by a second Coolify Application without a reviewed reason.
- [x] Each of the **11** release units has portable `docker-compose.yaml` and Coolify `docker-compose.coolify.yaml`, with per-module top-level `x-watch-path-coolify` lists. No separate vendor/provider application watch paths.
- [x] Every new Compose, including `data`, attaches to existing **external** `briareus-net`; no stack owns this network.
- [x] Staged `APPLICATIONS.json` with 11 desired Coolify Application identities and per-App Compose/watch sources for future single operator bootstrap (no automatic API provisioning is falsely claimed).
- [x] Source-only static YAML structure review: 11 Apps/22 Compose/12 container definitions, isolated external Briareus network, one group-specific Watch Paths list each. No actual Docker/Coolify build is inferred.
- [x] Existing legacy MCP Bridge, historical Ghidra, OAuth issuer, DNS and published identifiers are not modified.

## Runtime / publication acceptance (not complete)

- [ ] Independently review full 22-file staging delta with the orchestrator; assign `repo/deploy/coolify/**` ownership and integrate only accepted source.
- [ ] Validate Compose resolution and images via actual Coolify parser and Tambov dev builds. Staging/static YAML is NOT runtime readiness.
- [ ] Freeze real shared contracts: Backend A7 service identity and database, Runtime R9 FileQuota-v2/OS and new consolidated SVC runtime, Frontend B11 real Admin transport.
- [ ] Implement/review supported **one-time automated bootstrap** of the 11 resources via authenticated Coolify management API/UI, environment secrets, Destinations and recorded Watch Paths; do not expect operator to click through every provider. No such provisioning has been run.
- [ ] Publish exact approved Git dev ref once, then create private dev applications, initialize disposable Briareus schema and verify runtime.
- [ ] Separate C1-B2-PUBLIC/C2 approval required before protected MCP/Admin/public routes are enabled.

No Git commit/push/PR, no Coolify/DB/network mutation, no automated test suite. This is a corrected staging and owner-acceptance explanation.

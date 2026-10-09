# Briareus — Coolify DEV release package

**Stage only, not published and not deployed.** Source staging: `local/deployment/git-ready/deploy/coolify/`; exact future tracked Git location: `repo/deploy/coolify/`. Target: Coolify `koba`, server `tambov`. The existing legacy `mcp-bridge` and `ghidra-mcp` must not be modified.

## Why this granularity is fixed for MVP

Owner correction, 2026-10-09: **independent release by functional module, not by third-party integration, adapter, worker or subprocess.** Coolify deployment/build/restart takes time; splitting every GitHub, GitLab, cURL, Chromium or data component into independent Applications multiplies manual management and makes deployment architecture harder without improving the required module continuity. The accepted target architecture §7.1 already says GitHub+GitLab are **one SVC** and Web's HTTP/Chromium/Remote adapters are **one Web** release unit. More granular separation is an explicit later decision, justified by actual bottlenecks or incompatible lifecycles — not a default.

The earlier package had **13 Coolify Applications × 2 Compose files = 26 Compose files** (not 26 Applications). This package has **11 Coolify Applications × 2 Compose files = 22 Compose files**. Ten Applications are Briareus-owned modules, one is a grouped third-party data dependency. The four redundant release directories `postgres`, `valkey`, `svc-github`, `svc-gitlab` have been archived under `local/deployment/obsolete/overgranular-release-units-2026-10-09/` without deleting their content.

| Coolify Application | What it owns | Application containers |
| --- | --- | --- |
| `briareus-dev-data` | **External dependency group**: PostgreSQL + Valkey, new empty data/volumes | **2** vendor containers in **1** Compose Application |
| `briareus-dev-authorization` | Briareus local/OAuth verification, token lifecycle, grants | 1 |
| `briareus-dev-gateway` | Public MCP entry point and routing | 1 |
| `briareus-dev-admin-api` | Administration REST/API and scoped realtime | 1 |
| `briareus-dev-admin-ui` | Administration Vue/Bun frontend | 1 |
| `briareus-dev-files` | Project Files and quota consumer | 1 |
| `briareus-dev-terminal` | Project Terminal/Jobs | 1 |
| `briareus-dev-web` | **One Web module**: cURL/HTTP, Chromium, Remote Browser | 1 |
| `briareus-dev-svc` | **One SVC module**: GitHub + GitLab + future version-control adapters | 1 |
| `briareus-dev-infrastructure` | Coolify/SigNoz/observability/infrastructure adapters | 1 |
| `briareus-dev-reverse` | Analysis/Ghidra logical domain; optional dedicated executor *inside the same domain release* if OS isolation requires | 1 staged (Ghidra executor not yet packaged) |

The data group is **not** squeezed into one UNIX process/container: PostgreSQL and Valkey retain their vendor images, distinct persistent volumes, healthchecks and least-privilege lifecycles. They do share **one Coolify Application deploy/restart boundary**, which is acceptable because they are shared external dependencies rather than Briareus-owned code modules. One does not need to redeploy the data group to release Web, SVC, Files or Admin UI. Grafana, external Coolify and SigNoz instances, GitHub and GitLab provider APIs are integrations **consumed by Briareus**, not extra applications installed per provider/customer.

## D1-PACKAGE-02 — complete Git-owned artifact set

**The entirety of this directory is the publication unit: `repo/deploy/coolify/**`.** Orchestrator must integrate **all files in it as one reviewed source snapshot**, not just the 22 Compose manifests. Canonical management files are `deploy/coolify/APPLICATIONS.json` (11-Application desired-state registry), `deploy/coolify/sync_watch_paths_coolify.py` (approved Watch Paths reconciler, read-only by default), `deploy/coolify/ACCEPTANCE.md` (review contract), `deploy/coolify/README.md` (release design), `deploy/coolify/WATCH_PATHS.md` (derived inventory), and `deploy/coolify/SHA256SUMS` (full source manifest, paths relative to `deploy/coolify/`). These are Git-managed source/release assets but **not container build inputs**, so they must not be added to every Application Watch Paths and trigger unrelated redeploys.

The dev schema initializer has its own isolated image stage `schema-init` and is invoked **manually and explicitly against an approved empty database**, not by admin-preview and not as an extra long-running Application. The `authorization-staged` target inherits neither Admin API source nor schema initializer; Admin source changes must never redeploy Authorization.

## Exact Git layout
Every active release directory `deploy/coolify/<domain>/` contains:
- `docker-compose.yaml` — portable Compose, only its owned service(s);
- `docker-compose.coolify.yaml` — Coolify-specific `extends`, mirrored required/default variables and top-level `x-watch-path-coolify` for that **one Application**;
- dedicated Dockerfile only where needed (`svc/Dockerfile` is one combined GitHub+GitLab source image). Other release units currently use the verified repository build-target map; final image and entrypoint acceptance remains orchestrator/agent-owned.

**One-time desired-state registry:** `APPLICATIONS.json` lists exactly the 11 target Coolify resources (name, Base directory, Compose file and watch-path source), with a deliberately unset reviewed Git branch and no secrets. It is a specification for orchestrator-driven API provisioning, **not yet an implemented or executed bootstrap**. On normal updates Coolify watches only the affected module.

**No umbrella Compose for all ten modules.** `briareus-dev-data` is the only current bundle with two vendor containers. There are no separate PostgreSQL, Valkey, GitHub or GitLab Coolify Applications.

## Watch Paths and one-time Coolify configuration
The canonical watcher list for each Application is **inside its Coolify Compose**:

```yaml
x-watch-path-coolify:
  - "deploy/coolify/svc/docker-compose.yaml"
  - "deploy/coolify/svc/docker-compose.coolify.yaml"
  - "deploy/coolify/svc/Dockerfile"
  - "services/modules/github/**"
  - "services/modules/gitlab/**"
```

That is an illustrative subset; the actual Compose has the full source/lock/shared consumer list. Coolify itself **does not automatically parse/watch** this custom extension. `sync_watch_paths_coolify.py` reads it and writes the official per-Application `watch_paths` setting after exact UUID/source/branch checks. Run with review/dry-run by default and user-authorized API write only; never claim x-extension alone activates Watch Paths. `WATCH_PATHS.md` is a derived view, not a second authority.

The owner should **not have to create a fresh Coolify Application manually for each provider**. The future authorized one-time infrastructure bootstrap should reconcile the **eleven Applications** from reviewed Git definitions using supported Coolify API/UI orchestration, including environment references and persisted Watch Paths; a normal code change then triggers only matching Applications. A single click/one-time setup procedure is a **planned operator workflow**, not an implemented provisioning service in this package. No API credentials or changes have been executed.

## Shared network and secrets (minimal)
Provision one separately owned Coolify Standalone Docker Destination named `briareus-net` on Tambov before first app start. **All 22 Compose files, including data, join it only as an external network**:

```yaml
networks:
  briareus:
    external: true
    name: briareus-net
```

No app creates, removes or recreates the network. No additional network-manager application is required.

Private `development` Coolify environment-scoped variables provide the actual secrets. Required Compose values use `${NAME:?}`, optional safe defaults `${NAME:-default}`, then resource values may reference `{{environment.NAME}}` after inspecting parser output. Sensitive values are runtime-only, never committed or copied into image build arguments. Do not silently change existing OAuth issuer/audience, legacy DNS or Git repository identifiers.

- `briareus-dev-data`: PostgreSQL database **`briareus_dev`** (new/empty, ends `_dev`), `PLATFORM_DEV_DB_USER`, `PLATFORM_DEV_DB_PASSWORD`, `PLATFORM_DEV_VALKEY_PASSWORD` (64 lowercase hex). Named volumes `briareus-dev-postgres-v1` and `briareus-dev-valkey-v1`; NO public ports, no legacy data.
- Briareus core: `PLATFORM_DATABASE_URL` for private DNS `briareus-dev-postgres:5432/briareus_dev`; independent invitation, idempotency, resource and Admin JWT encryption/signing keys from Coolify dev environment. Valkey clients (when they are enabled) must use correct password-backed `briareus-dev-valkey:6379` and verified DB/namespace; no unauthenticated Redis fallback.
- Current Admin preview is loopback-only **within its container** with `--no-proxy-headers`. This is **not** a publicly reachable Admin API or a usable Admin UI integration.

## Current readiness and exact blockers
- Static only: independent Compose definitions, exact network, service/source watch paths and packaging of vendor data and SVC adapters. No Docker daemon or connected write-enabled Coolify access in current agent lane; **no Docker build, image, fresh-parser, DB, trusted-auth or DEV_RUNTIME acceptance**.
- `authorization`, `gateway`, `files`, `terminal`, `web`, `svc`, `infrastructure`, `reverse` remain **fail-closed**; do not enable protected Project MCP operations until Backend A7/Runtime R9 signed service peer transport, actual FilesQuota v2 receipt, OS isolation, and C1-B2/C2 reviewer approval. SVC's new combined image currently has both provider packages but deliberately does not claim a working combined ASGI handler; Runtime R9 owns that source work.
- The Reverse target currently packages Analysis source, not an accepted native Ghidra executor. A single Reverse domain package remains the target; adding a safe executor inside it must be reviewed, rather than launching an unreviewed provider Application.
- Data initializer `scripts/greenfield_schema.py` is a **separate one-shot container command**, not a permanently running Coolify app. Only after actual empty `*_dev` database identity and owner-approved DEV provisioning is confirmed.
- Legacy runtime remains untouched; remote Git `main` does not contain the new greenfield source or these staged files. Orchestrator must review/accept source, assign exact `repo/deploy/coolify/**` ownership, fan in B11/R9/A7 contracts, and publish one reviewed dev ref before any Git-backed Coolify Applications are created.

## Rollback, acceptance and potential future split
Application redeploy/restart/rollback is independent for each Briareus module. An external data-group update will affect both database and cache containers, but unrelated Briareus deployments **never** trigger that group. Preserve named data volumes on uncertain deployment outcome; do not remove the separate network or the legacy MCP. Single-user controlled bootstrap/provisioning is required before the first runtime, not repeated per application release.

**Only split a module** if there is live evidence of unacceptable build/restart latency, independent scaling or isolation requirements, or incompatible runtime/security lifecycles, and after updating the architecture, build inputs, Watch Paths and Coolify ownership. For MVP, module-level releases are the accepted minimum complexity.

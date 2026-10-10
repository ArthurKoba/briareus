# Briareus deployment source — module-first layout

Status: Git-backed deployment source. Changes to live container identities require independent rollout review and runtime validation. Target Coolify account/server: `koba` / `tambov`. Legacy `mcp-bridge` and `ghidra-mcp` are outside this package and must remain untouched.

## Layout

Each independently deployable functional unit owns one directory directly under `deploy/`:

- `deploy/data/` — grouped PostgreSQL + Valkey vendor dependency release.
- `deploy/authorization/`
- `deploy/gateway/`
- `deploy/admin-api/`
- `deploy/admin-ui/`
- `deploy/files/`
- `deploy/terminal/`
- `deploy/web/`
- `deploy/svc/` — GitHub + GitLab in one release unit.
- `deploy/infrastructure/` — Coolify/SigNoz provider runtime.
- `deploy/reverse/` — Analysis/Reverse domain; Ghidra executor remains a future inner runtime decision, not a separate Coolify Application by default.

Every module owns its `Dockerfile`, portable `docker-compose.yaml`, and `docker-compose.coolify.yaml`. Data has only two long-running vendor services. Schema migrations belong to normal Authorization startup after accepted A10 source. Global desired-state/bootstrap/review files live only at `deploy/`: `APPLICATIONS.json`, `bootstrap_coolify.py`, `sync_watch_paths_coolify.py`, `WATCH_PATHS.md`, `ENVIRONMENT.md`, `MIGRATION_MAP.md`, `FANIN.json`, `COOLIFY_CAPABILITIES.md`, `PUBLICATION.md`, `BOOTSTRAP.md`, `ACCEPTANCE.md`, `verify_deploy_static.py`, and `SHA256SUMS`.

## Coolify contract

For every Application:

- Repository: `ArthurKoba/briareus`.
- Server: Tambov only.
- Project/environment: `briareus` / `development`.
- Base directory: `/deploy/<module>`.
- Docker Compose location: `/docker-compose.coolify.yaml` (relative to Base directory).
- Build context for first-party images: repository root via `../..`.
- Dockerfile: `deploy/<module>/Dockerfile`; no root shared multi-stage Dockerfile and no cross-module Dockerfile.
- Auto-deploy stays disabled during bootstrap/review.
- Generated domains for Admin UI/API are source-owned Coolify directives; bootstrap itself performs no DNS or OAuth issuer mutation.
- Watch Paths are declared in top-level `x-watch-path-coolify` and must be persisted to the Coolify Application setting by supported API. The extension alone is not a native Coolify watcher.

All applications join one pre-existing external network:

```yaml
networks:
  briareus:
    external: true
    name: briareus-net
```

The network is a separate Coolify Docker Destination, not owned by Data or any module. This package does not add a network manager container.

## Release boundaries

There are **11 Coolify Applications / 12 long-running container definitions**: ten Briareus modules plus one grouped vendor-data Application with two containers. Web keeps HTTP/cURL + Chromium/Remote Browser together; SVC keeps GitHub + GitLab together; Infrastructure keeps its provider adapters together. Further split requires evidence of incompatible lifecycle, isolation, scaling or unacceptable restart/build time.

Authorization, Gateway, Files, Terminal, Web, SVC, Infrastructure and Reverse remain fail-closed in the current source until protected transport/C1-B2/C2 requirements are independently accepted. A green container image is not permission to enable those surfaces.

## Data and migrations

`deploy/data/docker-compose.yaml` owns only PostgreSQL 18 and Valkey 9 vendor containers, distinct named volumes and no host ports. Database is `briareus_dev`. No manual Data schema initializer is allowed. Accepted Authorization startup owns Alembic upgrade under a PostgreSQL advisory lock. Existing physical Data volumes are not renamed by service-naming cleanup.

## Bootstrap

`bootstrap_coolify.py` is dry-run-first. With authenticated write access and explicit owner approval, it may reconcile only:

1. Coolify project `briareus` and environment `development`;
2. independent `briareus-net` Destination on Tambov;
3. the 11 exact Git-backed Applications from `APPLICATIONS.json`;
4. Base directory, Compose path, branch, disabled auto-deploy and exact Watch Paths;
5. parsed Application variables to already-existing Team/Environment Shared references, runtime-only/buildtime-disabled.

It never deploys/starts Applications, never generates or prints secret values, never touches legacy applications, never changes DNS/OAuth, and never blindly retries a failed create. Missing current Team/Environment Shared bindings, required Application inputs, or pending Compose parser materialization stop reconciliation.

## Evidence boundary

D3-ENV static validation may prove paths, COPY→Watch dependencies, YAML structure, registry consistency and script syntax. It is **not** Docker image BUILD or Coolify parser/runtime acceptance. Installed Coolify version and authenticated Destination/Application bootstrap remain live evidence gates before the first deployment.

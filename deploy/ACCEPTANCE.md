# Briareus D2 — module-first deployment staging acceptance

Status: **SOURCE/STATIC staging only; pending independent review.**

## Owner requirement implemented

The deployment source root is `deploy/<functional-module>/`, not a provider-named parent. Each module owns its Dockerfile, portable Compose, Coolify Compose and module deployment scripts. Shared registry/bootstrap/review artifacts live directly at `deploy/` and create no runtime resource.

Expected source after fan-in contains exactly 11 module directories: `data`, `authorization`, `gateway`, `admin-api`, `admin-ui`, `files`, `terminal`, `web`, `svc`, `infrastructure`, `reverse`. Old deployment directories must be deleted rather than left as aliases or duplicates.

## Source/static acceptance points

- 11 module-owned Dockerfiles; no first-party Application builds from the repository root Dockerfile.
- 22 Compose files; every Coolify override extends its portable sibling.
- First-party build context is repository root (`../..`) and Dockerfile is `deploy/<module>/Dockerfile`.
- Coolify Base directory is `/deploy/<module>`; Compose location remains `/docker-compose.coolify.yaml`.
- Each Application has exact repo-relative `x-watch-path-coolify`; actual Docker `COPY` inputs are statically cross-checked.
- Admin UI Dockerfile copies explicit build inputs rather than the whole frontend directory.
- Authorization and Admin API have separate Dockerfiles; Admin-only edits do not rebuild Authorization.
- Data is one owner-approved release with Postgres + Valkey containers; schema initializer belongs to Data but is manual one-shot and does not trigger data service redeploy.
- External network is exact `briareus-net` in all 22 Compose files; no module creates/owns it.
- `APPLICATIONS.json`, bootstrap/watch tooling and review documents are at provider-neutral `deploy/` level.
- `bootstrap_coolify.py` is dry-run-first, idempotent/expected-state oriented, disables auto-deploy, never calls Application start/restart/deploy and refuses missing shared secrets.
- No legacy service, OAuth issuer, DNS or existing identifier is changed.

## Not accepted by this staging

Docker image builds, installed Coolify parser/version behavior, live Destination creation, secret values, DB initialization, Application deployment, actual protected service transport, C1-B2/C2, OS Files/Terminal isolation, or product readiness. Those require later explicit live DEV acceptance after source review/publication.

## D2 static evidence completed

- `verify_deploy_static.py`: **PASS** for 11 module directories, 22 YAML Compose files, 11 module Dockerfiles, 12 long-running Compose service definitions, exact `extends`/environment mirrors, external `briareus-net`, no host `ports`, future build contexts resolving to repository root, and registry Base directories `/deploy/<module>`.
- Docker `COPY` → repo-relative Watch Paths: **PASS** for every first-party module Dockerfile; all COPY sources exist in accepted source or the staged module package. Root shared `Dockerfile`/`docker-entrypoint.sh` are no longer build/watch inputs.
- Admin UI deployment Dockerfile copies explicit build/runtime files rather than the whole frontend directory.
- Data Valkey shell command: `sh -n` **PASS**. `deploy/data/greenfield_schema.py` is byte-identical to the accepted source initializer at staging time.
- Python syntax/compile: bootstrap, watch synchronizer, static verifier and schema initializer **PASS**.
- `bootstrap_coolify.py --branch main` without a write credential: source-only dry-run **PASS**, enumerating exactly 11 Apps and performing zero remote reads/writes.
- Live read-only Coolify evidence: Tambov exists, legacy MCP remains healthy, existing legacy app reports Compose parser state version `5`, no new Briareus applications observed. Connected Coolify credential is read-only, so exact installed Coolify version and write-path parser behavior remain unverified.

No Docker daemon/image build, Coolify resource creation, DB schema application, deployment, DNS/OAuth change, or protected runtime activation was performed.

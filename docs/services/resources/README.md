# Briareus Resource Catalog — service-local runtime

**Owner:** Backend, approved Briareus MCP Development Application. This
service is independent from Gateway, Control Panel UI/API and External Services.

- Source: `services/resources/src/` (all own Python packages; root legacy
  `services/projects` modules were copied byte-for-byte for the transition).
- Service migrations: `services/resources/migrations/`, copied **unchanged**
  from `scripts/alembic_owners/resources`. Alembic head and revision hashes are
  not rewritten or stamped.
- Runtime: Python 3.13, frozen `uv.lock`, `uv run --frozen --no-sync`,
  container `briareus-resources` and DNS alias of the same name, internal port
  8000. Health probe `GET /health/live`, not proof of business authorization.
- Database: existing `briareus_resources` in existing `briareus-postgres` server
  on `briareus-net`. There is **no new database server, named volume, SQL
  role, public HTTP domain or independent database migration sidecar**.
- Application only receives existing `{{environment.POSTGRES_USER}}`,
  `{{environment.POSTGRES_PASSWORD}}` and telemetry / timezone Shared
  references. Never copy or reveal actual Shared secret values.

## Shared dependency review

`Resource Catalog, provider registry and resources` are owned in this service folder. Both Platform and Catalog still
import a bounded subset of transitional `services/common/*.py` through the
`common` Python import root. This is one shared source of truth; **do not copy
the common package into each service's Git source** or move the authority of
another running Backend/Authorization owner in this cutover.

The Compose Watch paths are exactly:

- `services/resources/**` — service source, uv dependencies, Compose and migrations
- `services/common/**` — temporarily imported shared Python contracts/runtime
- `shared/build/**` — single shared build provenance utility

The service Dockerfile copies only its own local code plus explicitly selected
shared/common source files and one `shared/build/runtime_write_provenance.py`
utility. The accepted next refactor may promote narrow common DTOs to
`shared/contracts/` after all consumers are reconciled; until then, keep the
transitional import paths and Watch dependencies honest.

## Existing Coolify resource cutover and acceptance

Retain the **same approved** Coolify UUID (no new Application). Repo
`KobaProduction/briareus`, branch `main`.

- Base Directory: `/services/resources`
- Docker Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: the three paths above, in the same order
- Deployment is Git-backed, not a UI-only Compose replacement.
- Existing secret references, domain (none), networking and DB identity are
  unchanged. The old `deploy/resources/` source remains for rollback until the
  new runtime is independently accepted.

Verification requires: reviewed Git commit/green required CI; Coolify saved
Base/Compose/Watch and same-revision deployment; private container health;
owner database Alembic head (non-mutating observation), and a real relevant
private owner API response. Business permission/OAuth acceptance is independent
from container health. If cutover fails, restore the recorded prior
`/deploy/resources` Base and legacy Compose/Watch values and redeploy only
this application without deleting data.

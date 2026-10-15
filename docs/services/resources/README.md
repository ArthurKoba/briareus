# Briareus Resource Catalog — service-local runtime

**Owner:** Backend, approved Briareus MCP Development Application. This
service is independent from Gateway, Control Panel UI/API and External Services.

- Source: `services/resources/src/` (all own Python packages; root legacy
  `services/projects` modules were copied byte-for-byte for the transition).
- Service migrations: **one fresh Development baseline** resources_0001
  with the current complete Resource Catalog schema. Old resources_0002
  phase-upgrade history is retired. This is NOT compatible with an old
  populated Briareus Resources logical database: a separate target-qualified
  clean reset and subsequent verification are required before release.
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

## Rauthy-only current Catalog metadata inventory (local-first)

New Resources-owned private POST /internal/v1/resources/catalog/list accepts
{project_uuid:UUIDv4,kind:"integration"|"variable",limit:1..50}.
The JSON Project UUID selects a row set; it does NOT authenticate a user.
The independently injected TrustedCatalogReaderAttestor MUST verify
Rauthy subject→active Platform User, current Project/owning Team,
independent private service identity and actor's use_resources permission.
Without the attestor or verified owner ingress, Catalog returns 503.

Only Resource Catalog's own briareus_resources database is read. The
query selects non-deleted, current rows with owner_project_id equal to
the confirmed Project, or owner_team_id equal to its independently
verified owning Team. The SQL source and each returned row are checked
again for strict XOR ownership, UUIDv4, version >=1, bounded alias/name
key and exact Project/Team identity. A foreign Project, foreign Team,
deleted record, invalid source or permission expiry fails the complete
request instead of returning partial rows.

Response HTTP 200 has only
{items:[{resource_uuid:UUIDv4,kind,owner:{kind:"project"|"team",
id:UUIDv4},key:string,version:int>=1}]}, at most 50.
No integration credential, variable value (including nonsecret values),
provider_settings, tokens, raw upstream API response, refresh key or
Team/Project external privilege is included. 403 means Project access
denied; 503 means current Resource owner/peer unavailable.
The default Resources application has no attestor/SQL reader configured
and remains 503 despite healthy service status.

CRITICAL: these are current Catalog RECORD identifiers for displaying
integrations/variables only. They are NOT an executable MCP selector.
The Runtime Hand owner MUST still resolve the actual repository,
filesystem path, browser session or other effect from its real tool
arguments and independently attest the exact canonical V2 resource
before Cedar can Permit. Showing a Catalog item does not allow approval
of any Hand effect or expose a secret. Local source tests with synthetic
private owner proofs confirm own+Team results and reject foreign Project,
foreign Team, deleted records, missing service trust and data leakage.
No live SQL/mTLS/Rauthy/MCP acceptance is claimed.

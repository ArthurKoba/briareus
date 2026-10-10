# Briareus Coolify configuration contract

Coolify project/environment (`briareus` / `development`) own the deployment
scope. Service names, container DNS and generated `SERVICE_URL_*` identifiers
are stable across environments, without a `dev` naming component.

## Shared variable ownership

| Scope | Keys | Consumers |
| --- | --- | --- |
| Team Shared | `TZ`, `OTLP_ENDPOINT`, protected `OTLP_BEARER_TOKEN` | Server applications when configured; Admin UI receives only TZ |
| Environment Shared | `SERVICE_NAMESPACE`, `DEPLOYMENT_ENVIRONMENT` | Admin API and future accepted first-party server runtimes |
| Environment Shared | `POSTGRES_USER`, protected `POSTGRES_PASSWORD`, protected `VALKEY_PASSWORD` | Data and accepted DB/Valkey consumers |

`deploy/APPLICATIONS.json` holds **references only**, never resolved values.
`bootstrap_coolify.py` dry-runs by default; `--apply` binds already-parsed
Application variables to declared Team/Environment references without reading
secret values. No application is deployed or started by bootstrap.

## Admin API

Required, operator-supplied via Environment Shared:
`POSTGRES_USER=${POSTGRES_USER:?}` and
`POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?}`.

Optional/editable defaults: `TZ=UTC`, `OTLP_ENDPOINT` and
`OTLP_BEARER_TOKEN` (empty disables corresponding export),
`SERVICE_NAMESPACE=briareus`, `DEPLOYMENT_ENVIRONMENT=development`.
Shared binding supplies accepted non-default values when configured.

Source-owned constants: `OTEL_SERVICE_NAME=admin-api`,
`POSTGRES_HOST=briareus-postgres`, `POSTGRES_PORT=5432`,
`POSTGRES_DB=briareus_dev`, and internal port `8000`. The database's
`_dev` suffix is an existing data identifier, **not** a container name.

The public generated domain is a Coolify route to port 8000; it does **not**
authorize C1-B2/C2 endpoints. The current Admin API remains fail-closed.

## Data persistence during naming changes

The existing physical PostgreSQL/Valkey volume IDs retain their old names
(`briareus-dev-postgres-v1`, `briareus-dev-valkey-v1`) in Git to avoid an
implicit volume migration. A live Coolify storage record may have a
Coolify-generated physical name rather than the Git declaration. Never
merge/deploy a Data service rename until effective live Compose, actual volume
mounts and a safe rollback path are verified. Do not recreate/initialize
PostgreSQL or Valkey volumes as part of a naming cleanup.

## Excluded legacy/pseudo configuration

No old `PLATFORM_*`, per-signal OTLP endpoint, browser OTLP bearer,
`ADMIN_API_BASE_URL`, preview toggle, or auth-bypass variable is authorized.
Future security/signing keys require independent accepted C1-B2/C2 source and
runtime activation. Team collector credentials are server-side only.

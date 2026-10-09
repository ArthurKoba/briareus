# Briareus DEV environment variable matrix

Actual secret values live only in the Coolify `briareus` / `development` shared environment. Required Compose keys use `${NAME:?}`. `bootstrap_coolify.py` checks that the shared keys exist, then binds Application variables to `{{environment.NAME}}` with Runtime=true and Buildtime=false. It never generates or prints secret values.

| Module | Key | Contract | Desired value/source |
| --- | --- | --- | --- |
| admin-api | PLATFORM_ADMIN_JWT_SIGNING_KEY | required | {{environment.PLATFORM_ADMIN_JWT_SIGNING_KEY}} |
| admin-api | PLATFORM_DATABASE_URL | required | {{environment.PLATFORM_DATABASE_URL}} |
| admin-api | PLATFORM_IDEMPOTENCY_ENCRYPTION_KEY | required | {{environment.PLATFORM_IDEMPOTENCY_ENCRYPTION_KEY}} |
| admin-api | PLATFORM_INVITATION_ENCRYPTION_KEY | required | {{environment.PLATFORM_INVITATION_ENCRYPTION_KEY}} |
| admin-api | PLATFORM_REGISTRATION_BASE_URL | required | {{environment.PLATFORM_REGISTRATION_BASE_URL}} |
| admin-api | PLATFORM_RESOURCE_ENCRYPTION_KEY | required | {{environment.PLATFORM_RESOURCE_ENCRYPTION_KEY}} |
| admin-api | TZ | optional default | UTC |
| admin-ui | ADMIN_API_BASE_URL | optional default | (empty) |
| admin-ui | TZ | optional default | UTC |
| authorization | PLATFORM_ADMIN_JWT_SIGNING_KEY | required | {{environment.PLATFORM_ADMIN_JWT_SIGNING_KEY}} |
| authorization | PLATFORM_DATABASE_URL | required | {{environment.PLATFORM_DATABASE_URL}} |
| authorization | TZ | optional default | UTC |
| data | PLATFORM_DEV_DB_PASSWORD | required | {{environment.PLATFORM_DEV_DB_PASSWORD}} |
| data | PLATFORM_DEV_DB_USER | required | {{environment.PLATFORM_DEV_DB_USER}} |
| data | PLATFORM_DEV_VALKEY_PASSWORD | required | {{environment.PLATFORM_DEV_VALKEY_PASSWORD}} |
| data | TZ | optional default | UTC |
| files | TZ | optional default | UTC |
| gateway | TZ | optional default | UTC |
| infrastructure | TZ | optional default | UTC |
| reverse | TZ | optional default | UTC |
| svc | TZ | optional default | UTC |
| terminal | TZ | optional default | UTC |
| web | TZ | optional default | UTC |

Non-secret hard literals such as `POSTGRES_DB=briareus_dev`, workspace roots, disabled security flags and internal aliases remain in Compose and are not duplicated into shared variables. Public DNS/issuer values are intentionally not auto-generated in D2.

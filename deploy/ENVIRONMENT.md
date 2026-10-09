# Briareus deployment configuration contract — ENV-1

Environment variables are operator configuration only when the value has an independent deployment lifecycle. Product name and environment name are already expressed by Coolify project/environment scope, so they are not repeated in key prefixes.

## Current deploy inputs

Only the Data Application currently consumes operator-provided configuration.

| Key | Consumer | Type | Contract | Coolify ownership |
| --- | --- | --- | --- | --- |
| `POSTGRES_PASSWORD` | PostgreSQL | secret | required, no default | protected Project Shared Variable, referenced as `{{project.POSTGRES_PASSWORD}}` |
| `VALKEY_PASSWORD` | Valkey | secret | required, no default | protected Project Shared Variable, referenced as `{{project.VALKEY_PASSWORD}}` |
| `POSTGRES_USER` | PostgreSQL | nonsecret | safe default `briareus` | Compose default |
| `POSTGRES_DB` | PostgreSQL | nonsecret | safe disposable-dev default `briareus_dev` | Compose default |
| `TZ` | all staged containers | nonsecret | safe default `UTC` | Compose default |

`POSTGRES_HOST=briareus-dev-postgres` and `POSTGRES_PORT=5432` are internal topology/defaults. They are not Project Shared variables and are not required on the Data container. Backend A8 derives the async PostgreSQL DSN from canonical Postgres components when a database-consuming runtime is actually composed.

## Future activation inputs

These names are accepted by the completed A8 Backend source, but the current D package does **not** provision them preemptively because the corresponding Admin/Auth protected compositions are not active yet.

| Key | Future consumer | Type | Activation rule |
| --- | --- | --- | --- |
| `ADMIN_JWT_SIGNING_KEY` | Admin authentication | secret | Project Shared; required only when Admin auth composition is enabled |
| `CREDENTIAL_ENCRYPTION_KEY` | encrypted integrations/secret variables and context-derived crypto subkeys | secret | Project Shared; required only when protected platform composition is enabled |
| `DELEGATION_SIGNING_PRIVATE_KEY` | signed Authorization service identity | Ed25519 private key | Project Shared; required only by signed Authorization composition |
| `ADMIN_UI_PUBLIC_URL` | Identity invite/reset link generation | external nonsecret URL | Application/operator value only when those links are generated; not Shared secret |

No `PLATFORM_*`, `DEV_*` or `BRIAREUS_*` aliases are part of the new operator contract.

## Removed pseudo-configuration

D3-ENV removes these from Briareus deployment manifests/images rather than renaming them:

- Admin preview/log-invite/service-identity enable flags;
- Frontend preview, telemetry, event-mode and API-base runtime config;
- Gateway `OAUTH_ENABLED=false` bypass flag;
- global Files/Reverse/Web workspace/profile ENV;
- global Terminal workspace/home ENV aliases.

Current protected Gateway/Files/Terminal/Web/Reverse/Infrastructure/SVC services remain fail-closed through their existing guarded commands. Removing pseudo-ENV does not activate them.

## Internal image constants

Image/runtime constants such as `ASGI_APP`, `PYTHONPATH`, browser executable/cache paths, `HOME=/home/agent`, Chrome update/telemetry suppression flags and filesystem mount points are implementation topology, not operator configuration. They must not be promoted to Project Shared variables.

## Secret handling

All actual Briareus secret values are stored in protected Coolify **Project Shared Variables**. Git Compose contains only required placeholders. Application resource variables may contain `{{project.KEY}}` references, never copied plaintext secret values. D/agent tooling may inspect names/scopes/references only and does not retrieve resolved secret values.

# Briareus External Services — source and operator contract

This is the **existing** Coolify Development Application called **External Services**.
Its approved UUID remains `rgne4jjrnc6j6qb6zy5nelbp` in Briareus MCP / development.
No new Coolify Application for Rauthy, and no Cedar container.
Cedar stays embedded as the Rust-backed `cedarpy` library in Python Authorization.

## Planned one-Application layout

- `services/external/docker-compose.yaml`: portable Postgres, Valkey, Rauthy.
- `services/external/docker-compose.coolify.yaml`: Coolify override, source watches and variable discovery.
- `services/external/Dockerfile`, `Dockerfile.dockerignore`, `postgres-entrypoint.sh`,
  `owner-bootstrap.psql`: existing PostgreSQL release logic, using the new folder.
- `services/external/config/owner-databases.json`: inventory of owner DBs plus isolated Rauthy namespace.
- `services/external/rauthy/config.toml`: upstream Rauthy nonsecret settings.
- Persistent volumes: existing `briareus-dev-postgres-v1`, `briareus-dev-valkey-v1`;
  new `briareus-dev-rauthy-v1` for upstream cache and internal state.
- Existing shared external Docker network: `briareus-net`.
- Rauthy is private on 8080; public OIDC ingress belongs to the existing Gateway.
- Coolify Base directory: `/services/external`; Compose location: `/docker-compose.coolify.yaml`;
  Watch Paths: `services/external/**`. Docs are outside watched paths.

## Secret preparation — operator supplies values, never paste into chat

Coolify resolves Application variables to **protected references**, not literal
example secrets. Existing previously configured values must be reused, not
recreated, where they already exist.

| Application variable | Source / format | Meaning |
| --- | --- | --- |
| `TZ` | Existing Team Shared `{{team.TZ}}` | Timezone |
| `POSTGRES_USER` | Existing Environment Shared `{{environment.POSTGRES_USER}}` | Existing database principal |
| `POSTGRES_PASSWORD` | Existing Environment Shared `{{environment.POSTGRES_PASSWORD}}` | Existing database credential |
| `VALKEY_PASSWORD` | Existing Environment Shared `{{environment.VALKEY_PASSWORD}}` | Existing Valkey credential |
| `RAUTHY_HQL_SECRET_RAFT` | Operator-created protected value | Random high-entropy alphanumeric cluster secret, different from API secret |
| `RAUTHY_HQL_SECRET_API` | Operator-created protected value | Second independent random high-entropy alphanumeric cluster secret |
| `RAUTHY_ENC_KEYS` | Operator-created protected value | `<key-id>/<base64-of-exactly-32-random-bytes>` |
| `RAUTHY_ENC_KEY_ACTIVE` | Nonsecret Application literal | `<key-id>`, exactly matching the ID prefix in ENC_KEYS |
| `RAUTHY_BOOTSTRAP_ADMIN_PASSWORD_ARGON2ID` | Protected value | Complete encoded `$argon2id$...` password hash, NOT plaintext |
| `RAUTHY_BOOTSTRAP_ADMIN_EMAIL` | Operator Application value | Initial operator email, not an arbitrary fake user |
| `RAUTHY_TRUSTED_PROXIES` | Operator Application value after network inspection | Real Gateway proxy source CIDR; never trust-all |

The actual Rauthy container receives upstream variables without the `RAUTHY_`
prefix (via Compose mappings). `RAUTHY_*` are **Coolify configuration names**,
not additional upstream ENV names. The database host/port, public origin,
node ID, local listen port and database name are **stable Compose constants**,
not unnecessary extra shared variables. Do not create duplicate DB URL settings.

Offline secret generation (run privately, copy the output directly into the
approved protected Coolify value — no terminal logs in project artifacts):

- `openssl rand -hex 32` gives 64 random hexadecimal characters; run
  independently for RAUTHY_HQL_SECRET_RAFT and RAUTHY_HQL_SECRET_API.
- `openssl rand -hex 4` generates the encryption key ID; `openssl rand -base64 32`
  generates the encoded 32-byte key. Join as `id/base64` in RAUTHY_ENC_KEYS;
  put only `id` in RAUTHY_ENC_KEY_ACTIVE.
- For the admin password, generate a strong private password in an approved
  password manager and create its **Argon2id PHC hash** with the official
  Rauthy CLI or another authenticated Argon2id tool. The hash must begin
  `$argon2id$`. Never use `BOOTSTRAP_ADMIN_PASSWORD_PLAIN` for this setup.
- Keep the actual value of each encryption / HQL secret stable across restarts.
  Back up Rauthy storage and keys together. Do not rotate by changing the
  variables in place without the upstream key-rotation/migration procedure.

Official instructions:
https://sebadob.github.io/rauthy/getting_started/k8s.html#create-and-apply-secrets
https://sebadob.github.io/rauthy/config/encryption.html
https://sebadob.github.io/rauthy/config/bootstrap.html

## PostgreSQL and migration contract

The existing physical `briareus-postgres` server and its volume remain
unchanged. The proposed **fifth logical database** `briareus_rauthy` uses the
already-authorized Postgres principal and is created idempotently by the
existing Data Postgres startup reconciler, without new SQL roles or dropping
any database. Rauthy itself alone initializes/migrates that database on first
successful startup. Existing four owner databases are not stamped, copied,
reinitialized or used by Rauthy. Do not set `MIGRATE_DB_FROM`.
**This fifth DB is a migration boundary**: confirm a restorable state and
the exact owner approval before real deployment; the source diff alone must
never be called proof that new schema/data exists.

## Direct migration of unused source and live activation

The owner confirmed the old **deployment source path is unused as a development
contract** and requested immediate cleanup. The Git change removes
`deploy/data/**` in the same commit as the complete relocation to
`services/external/**`. Previous Git revisions remain available for
rollback; the old folder is not duplicated as a second active manifest.

The existing Coolify Application UUID is retained. Its CURRENT observed
Base before this migration was `/deploy/data`, with both existing data
volumes mounted. Its new desired-state Base is `/services/external`,
Compose location `/docker-compose.coolify.yaml`, and source Watch
`services/external/**`. Merely changing the Git registry does not
update existing Coolify parser/saved state. The stack must not be
started with unset required Rauthy secrets.

Operator supplies the protected Rauthy values and valid proxy CIDR.
The existing Application is then repointed and re-parsed; verify all
three service containers, old PostgreSQL database access, Valkey ping,
Rauthy startup/real issuer/discovery/JWKS, and restart persistence.
Only after Rauthy is verified may Gateway route live OIDC traffic.
Do not remove the old user Identity until real OIDC login works.

The existing PostgreSQL/Valkey volumes and network must NOT be wiped,
recreated or pruned. An unused old source path is not evidence that the
live underlying database is empty or disposable.

Validation stages: Git/source, YAML/parser, Coolify saved configuration,
container and persistent state, then actual OIDC and OAuth consumer behavior.

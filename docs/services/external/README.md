# Briareus External Services — source and operator contract

This is the **existing** Coolify Development Application called **External Services**.
The owner deleted the previous app. The newly created, allowlisted Briareus
Development application UUID is `pdx35bwnh9tjeopx30jslrb9`. No other
Coolify application is responsible for PostgreSQL, Valkey or Rauthy.
No new Coolify Application for Rauthy, and no Cedar container.
Cedar stays embedded as the Rust-backed `cedarpy` library in Python Authorization.

## Planned one-Application layout

- `services/external/docker-compose.yaml`: portable Postgres, Valkey, Rauthy.
- `services/external/docker-compose.coolify.yaml`: Coolify override, source watches and variable discovery.
- `services/external/Dockerfile`, `Dockerfile.dockerignore`, `postgres-entrypoint.sh`,
  `owner-bootstrap.psql`: existing PostgreSQL release logic, using the new folder.
- `services/external/config/owner-databases.json`: inventory of owner DBs plus isolated Rauthy namespace.
- Rauthy uses its official `serve` command and native `ENV` variables
  from the Compose, with **no separately mounted TOML file**. This avoids
  the missing `rauthy/config.toml` bind source from the failed deploy.
- Compose volumes: `postgres-data`, `valkey-data`, `rauthy-data`;
  **no hardcoded environment, project name or version** in a physical volume
  name. Coolify owns the application-specific naming.
- Existing shared external Docker network: `briareus-net`.
- Rauthy is private on 8080; public OIDC ingress belongs to the existing Gateway.
- Coolify Base directory: `/services/external`; Compose location: `/docker-compose.coolify.yaml`;
  Watch Paths: `services/external/**`. Docs are outside watched paths.

## Minimal MVP variables and initial admin

The existing PostgreSQL / Valkey shared bindings stay unchanged:
`TZ={{team.TZ}}`, `POSTGRES_USER={{environment.POSTGRES_USER}}`,
`POSTGRES_PASSWORD={{environment.POSTGRES_PASSWORD}}` and
`VALKEY_PASSWORD={{environment.VALKEY_PASSWORD}}`.

For a **single-instance MVP**, the operator creates exactly three NEW
Environment Shared values. All three are genuine secrets and the agent may
only configure their **references** inside this one Coolify Application:

| Environment Shared name | Application ENV reference | Rauthy native ENV |
| --- | --- | --- |
| `RAUTHY_HIQLITE_RAFT_SECRET` | `{{environment.RAUTHY_HIQLITE_RAFT_SECRET}}` | `HQL_SECRET_RAFT` |
| `RAUTHY_HIQLITE_API_SECRET` | `{{environment.RAUTHY_HIQLITE_API_SECRET}}` | `HQL_SECRET_API` |
| `RAUTHY_ENCRYPTION_KEY` | `{{environment.RAUTHY_ENCRYPTION_KEY}}` | `ENC_KEYS` |

The Rauthy-native `ENC_KEY_ACTIVE` is **fixed to `v1` in Compose**:
this is the ID of the one MVP encryption key, not another independent
secret. The Shared `RAUTHY_ENCRYPTION_KEY` value must be
`v1/<base64-of-32-random-bytes>`. Key rotation can be introduced later
with an explicit migration; NEVER casually replace a key protecting
existing encrypted data.

Run this locally on the operator's computer, not in an agent console;
copy the three output lines privately to Environment Shared Variables:

```bash
python3 - <<'PYTHON'
import base64
import secrets
print("RAUTHY_HIQLITE_RAFT_SECRET=" + secrets.token_hex(24))
print("RAUTHY_HIQLITE_API_SECRET=" + secrets.token_hex(24))
print("RAUTHY_ENCRYPTION_KEY=v1/" + base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
PYTHON
```

Upstream requires different Hiqlite API/Raft secrets (at least 16
characters), and one valid encryption key with an active ID. This is a
normal upstream minimum, not custom extra security. Reuse the exact
values across restarts and back up the encryption key together with
Rauthy's persistent state.

**No administrator bootstrap variables are necessary:** on first start
against an empty database Rauthy creates `admin@localhost` and generates
a password. The password is emitted **once** in its initial startup logs.
Capture it through the approved operator channel. Do not publish it or
replace it with an invented default. This happens only on first database
initialization, not every restart.

`RAUTHY_TRUSTED_PROXIES` is a **nonsecret, application-local network
input**. Determine the actual Gateway proxy source CIDR from the permitted
Briareus network before running a proxied login; do not put it in Shared
secrets or use a trust-all CIDR. Existing `POSTGRES_*`, `VALKEY_PASSWORD`
and `TZ` bindings remain unchanged.

After reloading Coolify Compose, obsolete parser variables with the old
`RAUTHY_HQL_SECRET_*`, `RAUTHY_ENC_*` and `RAUTHY_BOOTSTRAP_*` names
may still exist. Remove only these confirmed obsolete Application ENV
records, without accessing or revealing any Shared secret values.

Official references:
https://sebadob.github.io/rauthy/config/bootstrap.html
https://sebadob.github.io/rauthy/config/encryption.html
https://sebadob.github.io/rauthy/config/ha.html

## Fresh deployment

The owner removed the previous Coolify `External Services` application and
explicitly selected a clean MVP setup. The new application starts with fresh
Coolify-managed volumes; no old `briareus-dev-*-v1` resources, data migration,
or preexisting application UUID are assumed. **Container identities remain
prefixed**: `briareus-postgres`, `briareus-valkey`, `briareus-rauthy` and
their matching network aliases, because other Briareus services depend on
these stable Docker DNS names. Volume keys are independent of service identity.

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

Create **one** Git-backed Docker Compose Application in Briareus MCP /
Development, Base `/services/external`, Compose location
`/docker-compose.coolify.yaml`, Watch `services/external/**`.
Set the three Rauthy and existing PostgreSQL / Valkey Application references
to their protected Environment Shared keys. No secret value belongs in Git.
Deploy only after the ordinary required parameters are configured.

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

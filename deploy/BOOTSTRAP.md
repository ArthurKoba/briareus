# Briareus first-time Coolify bootstrap contract — ENV-1

The source bootstrap is dry-run first and does not deploy/start applications.

Current secret contract:

- `POSTGRES_PASSWORD` — Coolify Project Shared secret.
- `VALKEY_PASSWORD` — Coolify Project Shared secret.

Compose parser materializes those required Application variables; bootstrap may bind them to `{{project.POSTGRES_PASSWORD}}` and `{{project.VALKEY_PASSWORD}}` with Runtime=true and Buildtime=false. It never reads or prints Project Shared values.

Future Admin/Auth secrets are not created or attached until the corresponding protected runtime composition is actually activated. Safe defaults and internal topology remain in source/code rather than Shared variables.

Bootstrap may reconcile only project/environment identity, `briareus-net`, the 11 exact Git-backed Application definitions, source branch/Base/Compose path and Watch Paths. Auto-deploy/instant deploy/domain generation remain disabled during bootstrap. No schema initialization, DNS/OAuth mutation, legacy resource mutation or Application start/restart occurs here.

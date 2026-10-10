# Briareus Coolify bootstrap

`deploy/APPLICATIONS.json` contains 11 Application display names, explicit
module identities, Compose source paths and scoped Shared-variable references.
No module identity is derived from a user-facing Application display name.

A newly created Git-backed Compose Application is parsed by Coolify. `${KEY:?}`
materializes a required editable variable; `${KEY:-default}` materializes an
editable optional variable. Literal Compose values remain fixed source-owned
runtime settings and do not need a separate Application variable entry.

Run the source bootstrap in dry-run mode first. A separately authorized
`--apply` reconciles existing resource identity, git/Compose/watch paths and
binds parsed Application ENV keys to Team/Environment Shared references.
It never reads, copies, prints or invents secret values, never changes legacy
resources, and never deploys, restarts, creates schemas, or modifies database
contents. Configuration is not runtime acceptance.

For new Admin API releases, resolve `POSTGRES_USER` and `POSTGRES_PASSWORD`
required bindings **before** first deploy; otherwise Coolify must fail closed.
For an existing healthy Application, reconcile shared bindings and review
current runtime first, then allow a new source deployment.

A Compose service rename changes Coolify's component identity and generated
FQDN variable names. In particular, preserve/inspect live Data volume mounts
before applying a naming update to the running PostgreSQL/Valkey Application.
Do not assume a physical volume ID from the tracked Compose alone.

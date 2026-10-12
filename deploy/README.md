# Legacy deployment path — transition only

This is NOT the current authoritative runbook. See docs/architecture/owner-decisions-20261012.md and docs/operations/service-layout-transition.md.

Running Briareus Development Apps currently use deploy/<module>/Dockerfile and Compose paths. Keep them only as working rollback until each owner migrates its own service into services/platform|infrastructure|control-panel|hands/<service>/ with local source, Dockerfile/Compose, uv/Bun lock and simple service-directory Watch. All documentation belongs separately under docs/services/** and is excluded from Watch.

Development uses the existing common PostgreSQL principal across four logical owner databases; do NOT introduce new roles, global migrations, wipe data, change volumes or inspect secret values. Team Shared supplies TZ/OTLP; Environment Shared supplies PostgreSQL/Valkey/Identity signing material through protected references, not plaintext Docker images or Git. Old Project-only, separate-SQL-role and per-file-watch requirements are retired.

Only the owning agent changes its allowed Briareus MCP/development app, preserves UUID/alias/network, validates build/live HTTP, fixes actual failures, and removes its obsolete deploy path after a working same-app cutover. No new test suites or prepublication approval loops.

External Services is now sourced ONLY from `services/external/` and its vendor-stack Compose. `deploy/data/` is retired. Persistent PostgreSQL and Valkey volumes remain owned by the existing approved Coolify Application; no volume deletion is authorized.

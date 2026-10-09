# Coolify capability evidence for Briareus D2

Observed 2026-10-09 through the connected **read-only** Coolify MCP (`koba`):

- Coolify origin: `https://coolify.koba-nexus.ru`.
- Server target: `tambov`, UUID `5jrwg4jddi4axlzn2lspubrn`.
- Legacy `mcp-bridge` remains healthy and reports `build_pack=dockercompose`, `compose_parsing_version=5`; it is not a Briareus acceptance target.
- The connected token is explicitly exposed only through a **read-only safe-field projection**. D cannot use it for Destination/Application creation or obtain the raw token.
- Tambov currently has no new Briareus Applications in the read-only resource inventory. Legacy `mcp-bridge` and `ghidra-mcp` remain untouched.

Public Coolify `v4.3.23` source was inspected as a compatibility reference, not as proof of the installed build. That source exposes:

- standalone Docker Destinations via `GET/POST /api/v1/servers/{server_uuid}/destinations`;
- Project and Environment creation/read APIs;
- public Git Application creation using `build_pack=dockercompose`, `base_directory`, `docker_compose_location`, `destination_uuid`, `git_branch`, `watch_paths`, disabled auto/instant deploy and explicit no-domain configuration;
- `PATCH /api/v1/applications/{uuid}` including `watch_paths`;
- Application environment variable GET/PATCH with `is_runtime` / `is_buildtime` controls;
- environment-scoped shared variables.

`bootstrap_coolify.py` is limited to those reviewed contracts. It requires an exact live `--expected-version` before any `--apply`, so an installed-version mismatch stops mutation rather than assuming `v4.3.23` semantics.

## Live blocker before mutation

The read-only connector cannot perform `GET /api/v1/version` through the protected API surface, inspect raw Docker network state, or write resources. Therefore the first authorized mutation must use a separately authorized Coolify write credential/session. Before `--apply`, D must obtain the exact live version and confirm the Destination/Application API contract on that installed build. No application deployment is part of bootstrap itself.

# Files — migrated functional source snapshot

The old `deploy/files/Dockerfile` selected exactly **55** existing
Python modules from `services/common/` and `services/modules/`. Those actual
source files are now copied into this Hand's private `src/common/` and
`src/modules/` trees; the namespaced import paths are retained while external
callers transition. These are code snapshots, not stub handlers or generated
replacements. Old source stays unchanged only as rollback/other-owner input.

Own source ASGI entrypoint (not mounted yet): `modules.files.runtime:app`.
Tool registration/providers retained: `modules.files.file_tools`, `modules.files.workspace_store`, `modules.files.workspace_ingress`.
Legacy cross-package imports currently retained: `modules.__init__.py`, `modules.analysis`, `modules.files`, `modules.project_runtime`, `modules.workspace_compat`.

The locked dependencies were moved from `deploy/files/uv-project/` into the
independent `hands/files/pyproject.toml` and `uv.lock`. The container's
existing private ASGI lifecycle remains health-only; no real tool effect is
mounted, because the trusted peer/subject/Project/AgentSession authorization
contract is not yet active. `implementation.py` exports a static inventory and
lazy module loader for a future trusted tool-transport adapter, never a user
controlled dynamic module import.

**Migration debt:** some `common/` and `project_runtime/` owner code appears in
multiple Hand-private source closures. It remains private to each Hand rather
than being mislabeled as a small shared DTO: the original modules span owner
policy, databases, signing and transport. Only an owner-approved extraction
may later deduplicate genuinely small shared contracts. No runtime import from
`services/common` or `services/modules` is required after this snapshot.

The business implementation is SOURCE-PORTABLE. Neither independent physical
sandbox isolation, browser/terminal process prerequisites, credential custody,
nor an authorized MCP allow/deny/revoke operation has been accepted yet.

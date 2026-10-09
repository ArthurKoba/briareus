# D2 source relocation map

This file records the reviewed Git delta. The **final target tree contains no provider-parent deployment directory**; the old paths below are historical source paths to delete during fan-in, not compatibility aliases.

| Historical accepted path | New module-owned path |
| --- | --- |
| `deploy/coolify/data/*` | `deploy/data/*` |
| `deploy/coolify/authorization/*` | `deploy/authorization/*` |
| `deploy/coolify/gateway/*` | `deploy/gateway/*` |
| `deploy/coolify/admin-api/*` | `deploy/admin-api/*` |
| `deploy/coolify/admin-ui/*` | `deploy/admin-ui/*` |
| `deploy/coolify/files/*` | `deploy/files/*` |
| `deploy/coolify/terminal/*` | `deploy/terminal/*` |
| `deploy/coolify/web/*` | `deploy/web/*` |
| `deploy/coolify/svc/*` | `deploy/svc/*` |
| `deploy/coolify/infrastructure/*` | `deploy/infrastructure/*` |
| `deploy/coolify/reverse/*` | `deploy/reverse/*` |
| shared `_build/Dockerfile.greenfield` | split into `deploy/authorization/Dockerfile`, `deploy/admin-api/Dockerfile`, `deploy/data/Dockerfile` |
| deployment registry/review/tooling under provider parent | provider-neutral files directly under `deploy/` |

Additional module ownership changes:

- Gateway, Files, Terminal, Web, Infrastructure and Reverse no longer build from the repository root multi-stage Dockerfile; each has its own Dockerfile.
- Admin UI no longer builds using `admin-web-app/Dockerfile`; its release Dockerfile is `deploy/admin-ui/Dockerfile` and copies only actual frontend build/runtime inputs.
- SVC retains one combined GitHub+GitLab Dockerfile, now at `deploy/svc/Dockerfile`.
- The dev schema initializer is staged as `deploy/data/greenfield_schema.py`; the existing `scripts/greenfield_schema.py` remains outside this D-owned staging until the reviewed Git fan-in can remove the obsolete duplicate with proper source ownership coordination.

No old deployment directories are included in the final D2 staging tree.

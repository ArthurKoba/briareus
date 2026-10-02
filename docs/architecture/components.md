# Components

| Source module | Runtime service | Responsibility |
| --- | --- | --- |
| `auth_service` | `auth` | central OAuth/DCR, GitHub login, exact resource audiences, token state |
| `bridge` | `gateway` | public edge, MCP routing, protected-resource metadata, reverse proxying |
| `common` | — | shared typed runtime/config contracts |
| `management` | `management` | provider accounts, encrypted credentials, Admin UI and telemetry |
| `modules.github` | `github` | GitHub repository, review, history and Actions capabilities |
| `modules.gitlab` | `gitlab` | GitLab projects, repositories, merge requests, issues and CI |
| `modules.files` | `files` | immutable storage, metadata, uploads, collections and lifecycle |
| `modules.web` | `web` | structured HTTP, browser and DevTools operations |
| `modules.analysis` | `analysis` | structured analysis facade |
| `modules.ghidra` | `ghidra` | private native backend adapter |

Auth, gateway and management are distinct control-plane ownership boundaries. Provider
runtimes do not own OAuth state and do not read the management database directly.

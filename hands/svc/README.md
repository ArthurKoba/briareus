# SVC Hand — root Hand service folder

This is the target root-level `hands/svc` package. The currently deployed
SVC still runs from `services/hands/svc` until the existing Briareus
Development application's Base Directory, Compose file and Watch Paths
are changed and independently validated. Keep that deployed source as
rollback; do not redeploy both variants at once.

- Base Directory: `/hands/svc`
- Compose: `/docker-compose.coolify.yaml`
- Watch Paths: `hands/svc/**`, `shared/hand_runtime/**`

Docker builds from the repository root to read the Hand's own `pyproject.toml`,
`uv.lock` and `src`. This version has NO provider tools or grants, no DB
volume or public domain. `/health/live` is process-only; protected paths
return 503 and WebSockets deny admission. Real Rauthy OAuth and fresh Cedar
AgentSession admission are required before mounting protected tools.

Shared library modules are selected explicitly from root `shared/<package>/`
and packaged into each consuming Hand image at its pinned Git revision.
`shared/hand_runtime` is currently copied into `/app/src/hand_runtime` and
imported through its package public API. Every consumer MUST watch only its
selected `shared/<package>/**`, never `shared/**`.

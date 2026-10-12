# Briareus flat-layout: one batch, one CI gate

The selected owner layout is the repository-root `services/`, `hands/` and
`shared/`. This release plan replaces incremental per-service path edits as the
**coordination unit**, but never turns the 11 independent Coolify applications
into one Compose stack. Each application retains its existing UUID, current
service DNS, volume authority and isolated deployment lifecycle.

## Source of truth

`flat-batch-cutover.json` contains every approved Development application
UUID exactly once: 11 target modules and 3 explicitly retained legacy apps.
The target Base Directory and native Watch Paths are the exact Git/Compose
contract; the Compose location is `/docker-compose.coolify.yaml` for every
candidate. No global watch paths. When a new shared module is truly consumed,
update only those actual consumers in the same batch PR/CI revision.

`python3 scripts/verify_flat_batch.py --uv-locks --compose` validates the
**entire candidate batch**; the CI `docker` job runs it on every PR. One
`workflow_dispatch` of the existing `CI` workflow with `build_images=true`
also builds all 11 images from the same commit, collecting failures rather
than stopping on the first one. Required `test` and `docker` check identities
remain unchanged. The build images are validation artifacts, not proof of
Coolify deployments or product acceptance.

## Operational cutover gate

No bulk cutover until the whole candidate set has a green CI image pass, its
actual existing Dev resource has been compared against Git and captured for
rollback, and the owner-specific runtime prerequisites are demonstrably ready.
Especially for `services/external`, preserve PostgreSQL/Valkey volumes,
confirm supported Rauthy storage and non-secret config references, and do not
create another IdP application. Keep old Identity until actual OIDC/user
migration is verified. No agent inspects global projects, secrets or unapproved
UUIDs. Avoid forcing unavailable identity clients or Cedar permits to `allow`.

Batch saving a Base/Compose/Watch change does **not** deploy it; a follow-up
snapshot and exact Git revision/build/log read are required. A source-only
health-only Hand is not a working MCP provider: until a real verified token,
audience, policy and AgentSession grant are wired, all effects remain 503.
Retain old `deploy/<name>` / `services/hands/...` source and existing named
volumes for rollback. If any needed target is absent or any prerequisite is
unmet, report one batch-wide BLOCKED result rather than silently changing a
subset and calling it complete.

## Explicit legacy holds

- **Identity**: preserve the transitional application until real Rauthy
  sign-in, resource-token claims, user cutover and rollback are proven.
- **Platform Control and Resource Catalog**: the approved root
  `services/platform/` and `services/resources/` deployment definitions are
  not in published Git; Backend owns these migration decisions. No guessed
  paths or redeploys for them.

The separate ownership lanes retain their exclusive application source;
this batched gate coordinates evidence and timing, not source-edit rights.

# Hands

`hands/`, `services/` and `shared/` are independent, sibling directories at
the repository root. Do not nest Hands inside `services/`.

Each Hand owns `hands/<name>/` with its source, locked dependency inputs,
`Dockerfile`, portable `docker-compose.yaml` and Coolify
`docker-compose.coolify.yaml`. Compose builds using the repository-root Docker
context and an explicitly selected Hand Dockerfile. A Hand is one independent
Coolify application: changes to its deployment inputs must not redeploy other
Hands. Runtime functionality and privileged MCP admission are independently
accepted, not inferred from the layout.

`x-watch-path-coolify` in each Hand's Coolify Compose is the checked-in
source for native Coolify Watch Paths. Include `hands/<name>/**` plus each
actually consumed `shared/<package>/**` separately. Never watch all
`hands/**`, all `shared/**`, or all `services/**`. Watch shared packages only
when they enter the consuming Hand's Docker image. Keep unrelated docs outside
those watched package subdirectories when documentation is not a build input.

Existing `deploy/*` and `services/modules/*` are transitional code/rollback
inputs, not the target namespace. Migrate only after mapping imports and
retaining current Coolify app UUIDs, network/volume identity and accepted
fail-closed behavior; do not switch protected tools on as a side effect.

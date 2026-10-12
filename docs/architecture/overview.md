# Briareus — architecture overview

Current owner decision: owner-decisions-20261012.md.
Product/Team/Project model: target-project-platform.md.
Implementation: ../operations/agent-migration-plan-20261012.md.
Service documentation mirror: ../services/README.md.

Gateway routes traffic/stream/MCP and collects bounded safe telemetry; it never validates User JWT or Project grants. Control Panel API is a lightweight BFF calling independent Identity, Authorization, Platform/Resources and Hands owner APIs. Control Panel UI is a separate Vue browser application. Domain services and individual Hands are independent deployment units, with one source/build/Compose/lock folder each.

Target directories: services/infrastructure/**, services/platform/**, services/control-panel/**, services/hands/**, narrow shared/**; documentation separately in docs/services/**. No mandatory global wheel, AST exact per-file Watch/COPY or long-lasting deploy/<module> split. Changing one service must not restart its callers.

Identity logs one system invitation only while zero superusers exist; then superuser creates invites. Stable Identity signing key from protected Environment Shared, Team Shared for shared telemetry and timezone. Development keeps existing shared PostgreSQL user and owner databases; urgent network isolation is to deny untrusted MCP Hands sandbox arbitrary internal egress. No new test suites or routine prepublication review stages in MVP.

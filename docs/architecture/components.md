# Briareus — independent components

Selected owner contract: owner-decisions-20261012.md.

- Infrastructure: Gateway (routing/stream/metrics only), telemetry/data and their own runtime.
- Platform: Identity (User/bootstrap/signing), Authorization (access/grants), Platform Control (Team/Project), Resource Catalog (resources).
- Control Panel API: thin management HTTP facade to those owner service APIs, not a service or DB owner.
- Control Panel UI: separate frontend, same-origin API consumer.
- Hands/MCP: independent Files, Terminal, Web, SVC, Infrastructure, Reverse and future tools, with their own permission and untrusted runtime isolation.

All have self-contained service folder/dependencies/Compose and folder-based Watch; docs separate and mirror structure. Do not read older Gateway C2, one global migration owner or explicit per-file manifest as current architecture.

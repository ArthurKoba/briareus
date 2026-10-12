# Briareus: strict Coolify Development access scope

BINDING owner policy, 2026-10-12. Applies to Backend, Frontend, Runtime, Deployment, Orchestrator and all subagents and automated jobs. Overrides historical broader Coolify/host permissions.

## Exclusive allowlist (READ and WRITE)
- Coolify instance: https://coolify.koba-nexus.ru, used ONLY to reach the exact project/environment below. No root dashboard.
- Project: **Briareus MCP**, UUID 3xshlpoghb9wcyhjgktlqzzp.
- Environment: **development**, UUID naibrku1omovvmw5o0bcnp5c.
- Only permitted root URL path: /project/3xshlpoghb9wcyhjgktlqzzp/environment/naibrku1omovvmw5o0bcnp5c and the direct application pages nested under that exact pair.
- Briareus public site: https://briareus.koba-nexus.ru/ for external HTTP checks.
- Git repository: ArthurKoba/briareus.
- Known allowed development Applications:

| Slug | Name | UUID |
| --- | --- | --- |
| admin-api | Admin API | rf5gaooeijfzyiizgaw9kznr |
| admin-ui | Admin UI | pxv5fbwcogun3va4vygnejd4 |
| authorization | Authorization | kx1dpuamhtrlkbo4dg7tzanj |
| data | External Services | rgne4jjrnc6j6qb6zy5nelbp |
| files | Files | oeoerknk5tmjc3imqxljciga |
| gateway | Gateway | vpuhamswqggqtau3als7siuo |
| identity | Identity | 01sg4odymffwvc0kyrgspzvh |
| infrastructure | Infrastructure | mfhydae1l2xkxxkf31gomrw2 |
| platform | Platform Control | uvr5zfb9729ptfyfuxo3htmc |
| resources | Resource Catalog | 6vdxwespr1ufxeohy6xpa7wg |
| reverse | Reverse | wi49v2ea1urrchti6nxstr74 |
| svc | SVC | 0tsnkigy4fanthoywmatouig |
| terminal | Terminal | f2pguiu8qwlljggbfhmnim6z |
| web | Web | 1czkj4zvjrsaganivglrdvpy |


The known 14 UUIDs are an allowlist, not instructions to enumerate, inspect, or edit everything. New UUIDs or renamed apps are not automatically trusted; exact membership must be established by an already scoped trusted source or explicit owner consent, not by browsing other projects or guessing.

## Absolute prohibitions — including viewing
1. **DO NOT EVEN VIEW** other Coolify projects, any other environment (production/staging/test/preview), Shared Environments, Team/Root/Global scopes, their resources, logs, deployments, secrets, backups or metadata. Do not enter their pages, follow links there or run API requests to discover their contents.
2. DO NOT open Coolify root/team dashboard, project/environment selection or global app inventory, Shared Environments, Shared Variables/keys/tokens/global settings, servers/destinations or secret value reveals. Project Shared Variables remain owner-controlled secret storage: agent can reference existing nonsecret variable names in its OWN Development application configuration but must not view/edit secret VALUES or browse Shared Variables screens.
3. DO NOT call unfiltered global application inventories, project-wide/all-project logs, unscoped SigNoz/Observability searches, system-wide Docker ps/logs/journal/status queries or other tenant data. Only exact pre-authorized app UUID and scope-verified queries allowed. If the provider tool cannot constrain the request or displays unrelated resources, STOP rather than use it.
4. Browser navigation starts at the exact approved Development deep link. An off-scope link or redirect MUST NOT be followed. A broader root/admin credential or persistent authenticated browser DOES NOT extend permission.
5. No host/global networking, Traefik, Coolify instance, Docker daemon, shared databases/volumes, external Projects or globally shared infrastructure edits. No irreversible SQL/data wipe, protected C2/auth permission bypass, secret disclosure or disabling Auto Deploy.

## Permitted in this one Development environment
- Backend/Frontend/Runtime agents may autonomously use browser or scoped API for their OWN Briareus Dev Application to inspect/configure native Watch Paths, build/deploy, view bounded logs/metrics and debug failures. This removes routine need for Deployment permission/gating. Keep ownership coordination when a second Briareus Dev app must change.
- Deployment is optional on-demand help ONLY within the same Briareus project/development, not a standing release approver. Orchestrator post-publication audit is under the SAME restriction.
- Before EACH call, verify exact project UUID + environment UUID + known app UUID + owner service. For API paths without explicit project/environment, the target UUID MUST be pre-approved by this list and known to belong here. If uncertain: do not query; record an exact BLOCKED scope gap.
- Leave data/volumes/secrets and genuine User/Service/Project/JTI/grant proof protected. Record the exact target and real result without credentials; preserve independent Git PR/checks, on-push Auto Deploy and module ownership.

IMPORTANT: This is a mandatory agent behavioral rule. It does NOT physically reduce the access of existing Coolify browser sessions, API keys or account RBAC. Technical role/token scoping would require a separate verified administrator action.

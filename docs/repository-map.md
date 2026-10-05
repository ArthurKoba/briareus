# Repository map

```text
mcp-bridge/
├── .github/
├── docs/
├── services/
│   ├── auth_service/
│   │   └── access/            # internal agent-session/access module
│   ├── bridge/                 # public gateway only
│   ├── common/                 # shared contracts/settings/runtime primitives
│   ├── admin-api/
│   │   └── src/
│   │       └── admin_api/      # Python import package
│   │           ├── domain/
│   │           ├── application/
│   │           ├── infrastructure/
│   │           └── presentation/
│   └── modules/
│       ├── github/
│       ├── gitlab/
│       ├── files/
│       ├── web/
│       ├── analysis/
│       ├── ghidra/
│       ├── terminal/
│       └── observability/
├── admin-web-app/
├── Dockerfile
├── docker-compose.yaml
├── docker-entrypoint.sh
├── pyproject.toml
└── README.md
```

`bridge` owns only OAuth, public MCP surfaces and composition. `admin-api` owns dynamic
provider account persistence and encrypted credentials. Each provider module owns its API
semantics and consumes account data only through the common account port/client.

The root `docker-compose.yaml` owns only shared external infrastructure (`postgres` and `valkey`). Production application runtimes are independent Coolify Applications built directly from Dockerfile targets.

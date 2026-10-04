# Repository map

```text
mcp-bridge/
├── .github/
├── docs/
├── services/
│   ├── bridge/                 # public gateway only
│   ├── common/                 # shared contracts/settings/runtime primitives
│   ├── admin_api/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   └── presentation/
│   └── modules/
│       ├── github/
│       ├── gitlab/
│       ├── files/
│       ├── web/
│       ├── analysis/
│       └── terminal/
│   ├── bridge/
│   ├── common/
│   ├── admin_api/
│   └── modules/
├── Dockerfile
├── docker-compose.yaml
├── docker-entrypoint.sh
├── pyproject.toml
└── README.md
```

`bridge` owns only OAuth, public MCP surfaces and composition. `admin-api` owns dynamic
provider account persistence and encrypted credentials. Each provider module owns its API
semantics and consumes account data only through the common account port/client.

The root `docker-compose.yaml` is the production topology definition.

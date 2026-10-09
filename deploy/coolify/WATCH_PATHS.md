# Briareus — Coolify Watch Paths (derived)

The authoritative list for each deployment is the top-level `x-watch-path-coolify` key in its `docker-compose.coolify.yaml`. The approved `sync_watch_paths_coolify.py` reads the list and applies it to the matching Coolify Application via its API. Docker Compose and Coolify DO NOT automatically apply this extension.

All deployment source files, desired-state registry, this inventory and sync tooling are under one Git-owned directory: `deploy/coolify/**`. Watch lists exclude management docs/checksum files because they are not image build inputs.

## admin-api

```text
deploy/coolify/admin-api/docker-compose.yaml
deploy/coolify/admin-api/docker-compose.coolify.yaml
deploy/coolify/_build/Dockerfile.greenfield
pyproject.toml
uv.lock
services/common/**
services/authorization/**
services/identity/**
services/teams/**
services/projects/**
services/agents/**
services/admin-api/src/**
```

## admin-ui

```text
deploy/coolify/admin-ui/docker-compose.yaml
deploy/coolify/admin-ui/docker-compose.coolify.yaml
admin-web-app/Dockerfile
admin-web-app/package.json
admin-web-app/bun.lock
admin-web-app/index.html
admin-web-app/src/**
admin-web-app/public/**
admin-web-app/nginx.conf.template
admin-web-app/runtime-config.template.js
admin-web-app/docker-entrypoint.d/**
```

## authorization

```text
deploy/coolify/authorization/docker-compose.yaml
deploy/coolify/authorization/docker-compose.coolify.yaml
deploy/coolify/_build/Dockerfile.greenfield
pyproject.toml
uv.lock
services/common/**
services/authorization/**
services/identity/**
services/teams/**
services/projects/**
services/agents/**
```

## data

```text
deploy/coolify/data/docker-compose.yaml
deploy/coolify/data/docker-compose.coolify.yaml
```

## files

```text
deploy/coolify/files/docker-compose.yaml
deploy/coolify/files/docker-compose.coolify.yaml
Dockerfile
docker-entrypoint.sh
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/files/**
```

## gateway

```text
deploy/coolify/gateway/docker-compose.yaml
deploy/coolify/gateway/docker-compose.coolify.yaml
Dockerfile
docker-entrypoint.sh
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/bridge/**
```

## infrastructure

```text
deploy/coolify/infrastructure/docker-compose.yaml
deploy/coolify/infrastructure/docker-compose.coolify.yaml
Dockerfile
docker-entrypoint.sh
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/observability/**
services/modules/signoz/**
services/modules/coolify/**
```

## reverse

```text
deploy/coolify/reverse/docker-compose.yaml
deploy/coolify/reverse/docker-compose.coolify.yaml
Dockerfile
docker-entrypoint.sh
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/analysis/**
services/modules/files/**
```

## svc

```text
deploy/coolify/svc/docker-compose.yaml
deploy/coolify/svc/docker-compose.coolify.yaml
deploy/coolify/svc/Dockerfile
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/github/**
services/modules/gitlab/**
```

## terminal

```text
deploy/coolify/terminal/docker-compose.yaml
deploy/coolify/terminal/docker-compose.coolify.yaml
Dockerfile
docker-entrypoint.sh
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/terminal/**
```

## web

```text
deploy/coolify/web/docker-compose.yaml
deploy/coolify/web/docker-compose.coolify.yaml
Dockerfile
docker-entrypoint.sh
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/web/**
services/modules/files/**
```

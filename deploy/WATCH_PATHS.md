# Briareus Watch Paths (derived)

Source of truth is `x-watch-path-coolify` in each module `docker-compose.coolify.yaml`. This document is generated for review and is not independently edited.

## admin-api

```text
deploy/admin-api/Dockerfile
deploy/admin-api/docker-compose.yaml
deploy/admin-api/docker-compose.coolify.yaml
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
deploy/admin-ui/Dockerfile
deploy/admin-ui/docker-compose.yaml
deploy/admin-ui/docker-compose.coolify.yaml
admin-web-app/package.json
admin-web-app/bun.lock
admin-web-app/components.json
admin-web-app/index.html
admin-web-app/tsconfig.json
admin-web-app/vite.config.ts
admin-web-app/src/**
admin-web-app/public/**
admin-web-app/nginx.conf.template
```

## authorization

```text
deploy/authorization/Dockerfile
deploy/authorization/docker-compose.yaml
deploy/authorization/docker-compose.coolify.yaml
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
deploy/data/docker-compose.yaml
deploy/data/docker-compose.coolify.yaml
```

## files

```text
deploy/files/Dockerfile
deploy/files/docker-compose.yaml
deploy/files/docker-compose.coolify.yaml
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/files/**
```

## gateway

```text
deploy/gateway/Dockerfile
deploy/gateway/docker-compose.yaml
deploy/gateway/docker-compose.coolify.yaml
pyproject.toml
uv.lock
services/common/**
services/bridge/**
services/modules/__init__.py
services/modules/project_runtime/**
```

## infrastructure

```text
deploy/infrastructure/Dockerfile
deploy/infrastructure/docker-compose.yaml
deploy/infrastructure/docker-compose.coolify.yaml
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/signoz/**
services/modules/coolify/**
services/modules/observability/**
```

## reverse

```text
deploy/reverse/Dockerfile
deploy/reverse/docker-compose.yaml
deploy/reverse/docker-compose.coolify.yaml
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/files/**
services/modules/analysis/**
```

## svc

```text
deploy/svc/Dockerfile
deploy/svc/docker-compose.yaml
deploy/svc/docker-compose.coolify.yaml
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
deploy/terminal/Dockerfile
deploy/terminal/docker-compose.yaml
deploy/terminal/docker-compose.coolify.yaml
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/terminal/**
```

## web

```text
deploy/web/Dockerfile
deploy/web/docker-compose.yaml
deploy/web/docker-compose.coolify.yaml
pyproject.toml
uv.lock
services/common/**
services/modules/__init__.py
services/modules/project_runtime/**
services/modules/files/**
services/modules/web/**
```

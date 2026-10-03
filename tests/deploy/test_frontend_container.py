from __future__ import annotations

from pathlib import Path

import yaml

FRONTEND = Path("frontend")


def test_frontend_has_independent_docker_build_context() -> None:
    dockerfile = (FRONTEND / "Dockerfile").read_text()

    assert "COPY package.json bun.lock ./" in dockerfile
    assert "COPY . ./" in dockerfile
    assert "../" not in dockerfile
    assert "pyproject.toml" not in dockerfile
    assert "uv.lock" not in dockerfile
    assert "src/" not in dockerfile


def test_frontend_compose_contains_only_frontend_service() -> None:
    document = yaml.safe_load((FRONTEND / "docker-compose.yaml").read_text())
    services = document["services"]

    assert set(services) == {"management-ui"}
    assert services["management-ui"]["build"] == {
        "context": ".",
        "dockerfile": "Dockerfile",
    }


def test_root_compose_runs_frontend_as_isolated_service() -> None:
    root_compose = yaml.safe_load(Path("docker-compose.yaml").read_text())
    root_dockerfile = Path("Dockerfile").read_text()
    root_dockerignore = Path(".dockerignore").read_text().splitlines()

    service = root_compose["services"]["management-ui"]
    assert service["build"] == {"context": "./frontend", "dockerfile": "Dockerfile"}
    assert service["expose"] == ["8080"]
    assert root_compose["services"]["gateway"]["depends_on"]["management-ui"] == {
        "condition": "service_healthy",
        "required": True,
    }
    assert "AS management-ui" not in root_dockerfile
    assert "frontend" in root_dockerignore


def test_frontend_has_no_legacy_admin_runtime_dependency() -> None:
    source_files = list((FRONTEND / "src").rglob("*.ts")) + list((FRONTEND / "src").rglob("*.vue"))
    source = "\n".join(path.read_text() for path in source_files)
    nginx = (FRONTEND / "nginx.conf.template").read_text()

    assert "legacy_admin_path" not in source
    assert "/admin/browser/ws" not in source
    assert "/admin/browser/ticket" not in source
    assert "/admin/browser/ws" not in nginx


def test_frontend_public_routing_contract() -> None:
    vite = (FRONTEND / "vite.config.ts").read_text()
    index = (FRONTEND / "index.html").read_text()
    nginx = (FRONTEND / "nginx.conf.template").read_text()
    dockerfile = (FRONTEND / "Dockerfile").read_text()
    compose = (FRONTEND / "docker-compose.yaml").read_text()
    entrypoint = (FRONTEND / "docker-entrypoint.d/50-management-ui-runtime-config.sh").read_text()
    api = (FRONTEND / "src/shared/api/management.ts").read_text()
    events = (FRONTEND / "src/shared/events/bus.ts").read_text()
    browser = (FRONTEND / "src/pages/browser/BrowserPage.vue").read_text()

    assert 'base: "/admin/"' in vite
    assert '%BASE_URL%runtime-config.js' in index
    assert "proxy_pass" not in nginx
    assert "MANAGEMENT_BACKEND_ORIGIN" not in dockerfile
    assert "MANAGEMENT_BACKEND_ORIGIN" not in compose
    assert "MANAGEMENT_BACKEND_ORIGIN" not in entrypoint
    assert 'request("/api/session")' in api
    assert 'new EventSource("/api/calls/stream")' in events
    assert '/api/browser/operator/ws' in browser

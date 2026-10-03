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


def test_backend_container_topology_does_not_include_frontend() -> None:
    root_compose = yaml.safe_load(Path("docker-compose.yaml").read_text())
    root_dockerfile = Path("Dockerfile").read_text()
    root_dockerignore = Path(".dockerignore").read_text().splitlines()

    assert "management-ui" not in root_compose["services"]
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

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE_FILE = Path("docker-compose.yaml")
EXPECTED_SERVICES = {
    "auth",
    "gateway",
    "management",
    "github",
    "gitlab",
    "files",
    "curl",
    "analysis",
    "ghidra",
}


def _services() -> dict[str, dict[str, object]]:
    document = yaml.safe_load(COMPOSE_FILE.read_text())
    return document["services"]


def test_compose_keeps_runtime_services_independent() -> None:
    services = _services()

    assert set(services) == EXPECTED_SERVICES
    for service in services.values():
        assert service.get("restart") == "unless-stopped"
        assert "depends_on" not in service


def test_compose_does_not_publish_host_ports() -> None:
    services = _services()

    for name, service in services.items():
        assert "ports" not in service, name


def test_compose_owns_persistent_volumes() -> None:
    document = yaml.safe_load(COMPOSE_FILE.read_text())
    volumes = document["volumes"]

    assert set(volumes) == {"management-data", "files-data", "auth-data"}
    for config in volumes.values():
        assert config is None or "external" not in config

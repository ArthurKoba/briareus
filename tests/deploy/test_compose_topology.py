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


def _document() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_FILE.read_text())


def _services() -> dict[str, dict[str, object]]:
    return _document()["services"]


def test_compose_keeps_runtime_services_restartable() -> None:
    services = _services()

    assert set(services) == EXPECTED_SERVICES
    for service in services.values():
        assert service.get("restart") == "unless-stopped"


def test_compose_declares_only_primary_runtime_dependencies() -> None:
    services = _services()

    expected = {
        "github": {
            "management": {"condition": "service_healthy", "required": True}
        },
        "gitlab": {
            "management": {"condition": "service_healthy", "required": True}
        },
        "analysis": {
            "ghidra": {"condition": "service_healthy", "required": True}
        },
    }

    for name, service in services.items():
        if name in expected:
            assert service.get("depends_on") == expected[name]
        else:
            assert "depends_on" not in service


def test_gateway_is_not_health_gated_on_provider_availability() -> None:
    assert "depends_on" not in _services()["gateway"]


def test_compose_does_not_publish_host_ports() -> None:
    services = _services()

    for name, service in services.items():
        assert "ports" not in service, name


def test_compose_owns_clean_named_volumes() -> None:
    volumes = _document()["volumes"]

    assert set(volumes) == {"management", "files", "auth"}
    for config in volumes.values():
        assert config is None or "external" not in config


def test_persistent_mounts_use_absolute_container_paths() -> None:
    services = _services()

    assert services["management"]["volumes"] == [
        "management:/management",
        "files:/files",
    ]
    assert services["files"]["volumes"] == ["files:/files"]
    assert services["curl"]["volumes"] == ["files:/files"]
    assert services["auth"]["volumes"] == ["auth:/auth"]

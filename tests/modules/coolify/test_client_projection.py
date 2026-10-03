from __future__ import annotations

from common.account_contracts import ResolvedAccount
from modules.coolify.client import CoolifyClient


def _account() -> ResolvedAccount:
    return ResolvedAccount(
        id="1",
        alias="test",
        provider="coolify",
        auth_type="coolify_api_token",
        base_url="https://coolify.example.test",
        enabled=True,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        credential="secret-token",
    )


def test_application_projection_drops_nested_sensitive_data(monkeypatch) -> None:
    client = CoolifyClient(_account())
    payload = [
        {
            "uuid": "app-1",
            "name": "app",
            "status": "running",
            "git_repository": "owner/repo",
            "destination": {
                "server": {
                    "proxy": {
                        "last_saved_proxy_configuration": "environment:\n  TOKEN=very-secret"
                    },
                    "settings": {"sentinel_token": "very-secret"},
                }
            },
            "docker_compose": "SECRET=very-secret",
            "value": "very-secret",
        }
    ]
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: payload)

    result = client.applications()

    assert result == [
        {
            "uuid": "app-1",
            "name": "app",
            "status": "running",
            "git_repository": "owner/repo",
        }
    ]
    rendered = repr(result)
    assert "very-secret" not in rendered
    assert "destination" not in rendered
    assert "docker_compose" not in rendered


def test_deployment_projection_drops_unknown_fields(monkeypatch) -> None:
    client = CoolifyClient(_account())
    payload = [
        {
            "deployment_uuid": "dep-1",
            "application_name": "app",
            "status": "finished",
            "commit": "abc123",
            "logs": "SECRET=very-secret",
            "configuration": {"token": "very-secret"},
        }
    ]
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: payload)

    assert client.deployments() == [
        {
            "deployment_uuid": "dep-1",
            "application_name": "app",
            "status": "finished",
            "commit": "abc123",
        }
    ]


def test_team_projection_is_minimal(monkeypatch) -> None:
    client = CoolifyClient(_account())
    monkeypatch.setattr(
        client,
        "_get",
        lambda *_args, **_kwargs: {
            "id": 1,
            "name": "Root Team",
            "description": "root",
            "personal_team": True,
            "api_token": "very-secret",
        },
    )

    assert client.current_team() == {
        "id": 1,
        "name": "Root Team",
        "description": "root",
        "personal_team": True,
    }


def test_application_deployments_accepts_coolify_envelope_and_sanitizes(monkeypatch) -> None:
    client = CoolifyClient(_account())
    payload = {
        "deployments": [
            {
                "deployment_uuid": "dep-2",
                "application_name": "mcp-bridge",
                "status": "in_progress",
                "commit": "deadbeef",
                "logs": "TOKEN=very-secret",
                "configuration": {"secret": "very-secret"},
            }
        ],
        "count": 1,
        "internal": {"token": "very-secret"},
    }
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: payload)

    result = client.application_deployments("app-1")

    assert result == {
        "deployments": [
            {
                "deployment_uuid": "dep-2",
                "application_name": "mcp-bridge",
                "status": "in_progress",
                "commit": "deadbeef",
            }
        ],
        "count": 1,
    }
    assert "very-secret" not in repr(result)


def test_coolify_client_uses_pooled_transport_and_preserves_base_path() -> None:
    account = _account().model_copy(update={"base_url": "https://coolify.example.test/root"})
    client = CoolifyClient(account)

    assert client._target("/applications", {"page": "2"}) == (
        "/root/api/v1/applications?page=2"
    )
    assert client._transport.connection_count == 0


def test_application_variables_never_expose_values(monkeypatch) -> None:
    client = CoolifyClient(_account())
    payload = [
        {
            "uuid": "env-2",
            "key": "DATABASE_URL",
            "value": "postgres://very-secret",
            "real_value": "postgres://even-more-secret",
            "comment": "secret lives here too",
            "is_runtime": True,
            "is_buildtime": False,
            "is_preview": False,
            "is_shared": False,
            "is_shown_once": True,
        },
        {
            "uuid": "env-1",
            "key": "APP_ENV",
            "value": "production",
            "real_value": "production",
            "is_runtime": True,
            "is_buildtime": True,
        },
    ]
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: payload)

    result = client.application_variables("app-1")

    assert result == {
        "application_uuid": "app-1",
        "variables": [
            {
                "uuid": "env-1",
                "key": "APP_ENV",
                "is_runtime": True,
                "is_buildtime": True,
            },
            {
                "uuid": "env-2",
                "key": "DATABASE_URL",
                "is_preview": False,
                "is_runtime": True,
                "is_buildtime": False,
                "is_shared": False,
                "is_shown_once": True,
            },
        ],
        "count": 2,
        "values_exposed": False,
    }
    rendered = repr(result)
    assert "very-secret" not in rendered
    assert "postgres://" not in rendered
    assert "comment" not in rendered
    assert "value" not in rendered.replace("values_exposed", "")


def test_server_projection_drops_connection_and_nested_sensitive_data(monkeypatch) -> None:
    client = CoolifyClient(_account())
    payload = [
        {
            "uuid": "srv-1",
            "name": "tambov",
            "description": "production",
            "proxy_type": "traefik",
            "server_role": "both",
            "unreachable_count": 0,
            "ip": "10.0.0.1",
            "user": "root",
            "port": 22,
            "proxy": {"configuration": "TOKEN=very-secret"},
            "settings": {"sentinel_token": "very-secret"},
        }
    ]
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: payload)

    result = client.servers()

    assert result == [
        {
            "uuid": "srv-1",
            "name": "tambov",
            "description": "production",
            "proxy_type": "traefik",
            "server_role": "both",
            "unreachable_count": 0,
        }
    ]
    rendered = repr(result)
    assert "10.0.0.1" not in rendered
    assert "root" not in rendered
    assert "very-secret" not in rendered


def test_server_resources_projection_is_identity_and_status_only(monkeypatch) -> None:
    client = CoolifyClient(_account())
    payload = [
        {
            "uuid": "app-1",
            "name": "mcp-bridge",
            "type": "application",
            "status": "running:healthy",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "environment": {"SECRET": "very-secret"},
        }
    ]
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: payload)

    result = client.server_resources("srv-1")

    assert result == [
        {
            "uuid": "app-1",
            "name": "mcp-bridge",
            "type": "application",
            "status": "running:healthy",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
        }
    ]
    assert "very-secret" not in repr(result)


def test_application_storages_hide_contents_and_host_paths(monkeypatch) -> None:
    client = CoolifyClient(_account())
    payload = {
        "persistent_storages": [
            {
                "uuid": "storage-1",
                "name": "management",
                "mount_path": "/management",
                "host_path": "/var/lib/coolify/secret-path",
                "fs_path": "/srv/private",
            }
        ],
        "file_storages": [
            {
                "uuid": "file-1",
                "name": "config",
                "mount_path": "/app/config.json",
                "is_directory": False,
                "content": "TOKEN=very-secret",
                "fs_path": "/srv/private/config.json",
            }
        ],
    }
    monkeypatch.setattr(client, "_get", lambda *_args, **_kwargs: payload)

    result = client.application_storages("app-1")

    assert result == {
        "application_uuid": "app-1",
        "persistent_storages": [
            {
                "uuid": "storage-1",
                "name": "management",
                "mount_path": "/management",
                "type": "persistent",
            }
        ],
        "file_storages": [
            {
                "uuid": "file-1",
                "name": "config",
                "mount_path": "/app/config.json",
                "is_directory": False,
                "type": "file",
            }
        ],
        "count": 2,
        "contents_exposed": False,
        "host_paths_exposed": False,
    }
    rendered = repr(result)
    assert "very-secret" not in rendered
    assert "/srv/private" not in rendered
    assert "/var/lib/coolify" not in rendered

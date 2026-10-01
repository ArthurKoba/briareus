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

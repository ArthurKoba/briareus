from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from common.settings import GitLabSettings
from modules.gitlab.errors import GitLabError
from modules.gitlab.models import GitLabProfile, GitLabResponse
from modules.gitlab.repository import GitLabRepositoryClient


class LocalGitClient(GitLabRepositoryClient):
    def request(self, method, path, **kwargs):
        assert method == "GET"
        assert path == "/user"
        return GitLabResponse(
            status=200,
            data={
                "username": "arthur",
                "name": "Arthur Koba",
                "commit_email": "arthur@example.com",
            },
            headers={},
        )


def _client(tmp_path: Path, *, protected=frozenset()) -> LocalGitClient:
    profile = GitLabProfile(
        account_id="writer",
        alias="writer",
        base_url="https://gitlab.com",
        auth_type="private_token",
    )
    profile.bind_token("secret-token")
    return LocalGitClient(
        profile,
        protected_branches=protected,
        workspace_root=tmp_path / "workspace",
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    repo = root / "projects" / "bridge"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "feat/test", str(repo)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "https://gitlab.com/ArthurKoba/mcp-bridge.git",
        ],
        check=True,
    )
    return root


def test_gitlab_policy_has_no_fake_default_protected_branches() -> None:
    assert GitLabSettings().protected_branches == frozenset()


def test_authorize_local_git_configures_credentials_and_identity(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    client = _client(tmp_path)

    result = client.authorize_local_git(
        "ArthurKoba/mcp-bridge",
        "projects/bridge",
    )

    repo = root / "projects" / "bridge"
    config = (repo / ".git" / "config").read_text()
    credential_file = repo / ".git" / "koba-gitlab-credentials"
    assert result["authorized"] is True
    assert credential_file.stat().st_mode & 0o777 == 0o600
    assert "secret-token" not in config
    assert "koba-gitlab-credentials" in config
    assert "Arthur Koba" in config
    assert "arthur@example.com" in config

    filled = subprocess.run(
        ["git", "-C", str(repo), "credential", "fill"],
        input=(
            "protocol=https\n"
            "host=gitlab.com\n"
            "path=ArthurKoba/mcp-bridge.git\n\n"
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "username=oauth2" in filled.stdout
    assert "password=secret-token" in filled.stdout


def test_push_local_git_uses_force_with_lease_when_expected_sha_is_given(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _repo(tmp_path)
    client = _client(tmp_path)
    client.authorize_local_git("ArthurKoba/mcp-bridge", "projects/bridge")

    original = client._git_output
    captured: dict[str, object] = {}

    def fake_git_output(target: Path, *args: str) -> str:
        if args and args[0] == "push":
            captured["args"] = args
            return "To https://gitlab.com/ArthurKoba/mcp-bridge.git"
        if args == ("rev-parse", "HEAD"):
            return "a" * 40
        return original(target, *args)

    monkeypatch.setattr(client, "_git_output", fake_git_output)
    expected = "b" * 40
    result = client.push_local_git(
        "ArthurKoba/mcp-bridge",
        "projects/bridge",
        branch="development",
        expected_remote_sha=expected,
    )

    assert captured["args"] == (
        "push",
        "--porcelain",
        "--set-upstream",
        f"--force-with-lease=refs/heads/development:{expected}",
        "origin",
        "HEAD:refs/heads/development",
    )
    assert result["force_with_lease"] is True
    assert result["expected_remote_sha"] == expected


def test_push_local_git_rejects_invalid_expected_sha(tmp_path: Path) -> None:
    _repo(tmp_path)
    client = _client(tmp_path)
    client.authorize_local_git("ArthurKoba/mcp-bridge", "projects/bridge")

    with pytest.raises(GitLabError, match="40-character hexadecimal"):
        client.push_local_git(
            "ArthurKoba/mcp-bridge",
            "projects/bridge",
            branch="development",
            expected_remote_sha="not-a-sha",
        )


def test_push_local_git_keeps_optional_bridge_deny_list(tmp_path: Path) -> None:
    _repo(tmp_path)
    client = _client(tmp_path, protected=frozenset({"production"}))
    client.authorize_local_git("ArthurKoba/mcp-bridge", "projects/bridge")

    with pytest.raises(GitLabError, match="protected branch"):
        client.push_local_git(
            "ArthurKoba/mcp-bridge",
            "projects/bridge",
            branch="production",
        )

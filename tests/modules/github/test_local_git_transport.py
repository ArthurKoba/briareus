from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from modules.github.github_agent import GitHubAgentError
from modules.github.github_identity import GitHubPrettyIdentityClient


class LocalGitClient(GitHubPrettyIdentityClient):
    def _app_identity(self):
        return {
            "source": "test",
            "display_name": "Koba AI Agent",
            "login": "koba-ai-agent[bot]",
            "id": 330168119,
            "type": "Bot",
            "name": "Koba AI Agent",
            "email": "330168119+koba-ai-agent[bot]@users.noreply.github.com",
        }

    def _installation_token(self, repository: str) -> str:
        assert repository == "ArthurKoba/mcp-bridge"
        return "secret-installation-token"

    def _assert_branch_mutation_allowed(self, repository: str, branch: str) -> str:
        if branch.casefold() in self.protected_branches:
            raise GitHubAgentError(f"branch is reserved by bridge mutation policy: {branch}")
        return branch


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    repo = root / "projects" / "bridge"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "feat/test", str(repo)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "git@github.com:ArthurKoba/mcp-bridge.git",
        ],
        check=True,
    )
    return root


def test_authorize_local_git_stores_only_non_secret_markers(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    client = LocalGitClient(
        app_id="123",
        private_key="unused",
        account_id="writer",
        workspace_root=root,
    )

    result = client.authorize_local_git("ArthurKoba/mcp-bridge", "projects/bridge")

    repo = root / "projects" / "bridge"
    config = (repo / ".git" / "config").read_text()
    assert result["authorized"] is True
    assert result["credential_storage"] == "none"
    assert "secret-installation-token" not in config
    assert "secret-installation-token" not in str(result)
    assert "https://github.com/ArthurKoba/mcp-bridge.git" in config
    assert "writer" in config


def test_push_local_git_injects_secret_only_into_git_process(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)
    client = LocalGitClient(
        app_id="123",
        private_key="unused",
        account_id="writer",
        workspace_root=root,
    )
    client.authorize_local_git("ArthurKoba/mcp-bridge", "projects/bridge")

    captured: dict[str, object] = {}

    def fake_push_repository(target: Path, **kwargs):
        captured["target"] = target
        captured.update(kwargs)
        return {
            "head": "a" * 40,
            "git_output": "To https://github.com/ArthurKoba/mcp-bridge.git",
        }

    monkeypatch.setattr(
        "modules.github.github_identity.push_repository",
        fake_push_repository,
    )
    result = client.push_local_git("ArthurKoba/mcp-bridge", "projects/bridge", branch="feat/test")

    assert "secret-installation-token" not in str(result)
    assert captured["auth_scope"] == "https://github.com/"
    assert "secret-installation-token" not in str(captured["auth_header"])
    assert str(captured["auth_header"]).startswith("Authorization: Basic ")
    assert result["pushed"] is True
    assert result["branch"] == "feat/test"


def test_push_local_git_refuses_reserved_branch(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    client = LocalGitClient(
        app_id="123",
        private_key="unused",
        account_id="writer",
        workspace_root=root,
    )
    client.authorize_local_git("ArthurKoba/mcp-bridge", "projects/bridge")

    with pytest.raises(GitHubAgentError, match="reserved"):
        client.push_local_git("ArthurKoba/mcp-bridge", "projects/bridge", branch="main")


def test_push_local_git_requires_matching_authorization(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    client = LocalGitClient(
        app_id="123",
        private_key="unused",
        account_id="writer",
        workspace_root=root,
    )

    with pytest.raises(GitHubAgentError, match="not authorized"):
        client.push_local_git("ArthurKoba/mcp-bridge", "projects/bridge", branch="feat/test")

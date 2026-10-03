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


def test_authorize_local_git_configures_ordinary_git_credentials(tmp_path: Path) -> None:
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
    credential_file = repo / ".git" / "koba-credentials"
    hook = repo / ".git" / "hooks" / "pre-push"
    assert result["authorized"] is True
    assert result["credential_storage"] == "git_credential_store"
    assert result["push_mode"] == "ordinary_git"
    assert credential_file.stat().st_mode & 0o777 == 0o600
    assert hook.stat().st_mode & 0o777 == 0o700
    assert "secret-installation-token" not in config
    assert "secret-installation-token" not in str(result)
    assert "[credential]" in config
    assert "helper = store --file=" in config
    assert "koba-credentials" in config
    assert "https://github.com/ArthurKoba/mcp-bridge.git" in config
    assert "writer" in config

    filled = subprocess.run(
        ["git", "-C", str(repo), "credential", "fill"],
        input=("protocol=https\nhost=github.com\npath=ArthurKoba/mcp-bridge.git\n\n"),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "username=x-access-token" in filled.stdout
    assert "password=secret-installation-token" in filled.stdout

    denied = subprocess.run(
        [str(hook), "origin", "https://github.com/ArthurKoba/mcp-bridge.git"],
        input=(
            "refs/heads/feat/test aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
            "refs/heads/main bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert denied.returncode == 1
    assert "reserved branch denied: main" in denied.stderr

    allowed = subprocess.run(
        [str(hook), "origin", "https://github.com/ArthurKoba/mcp-bridge.git"],
        input=(
            "refs/heads/feat/test aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
            "refs/heads/feat/test bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert allowed.returncode == 0


def test_push_local_git_uses_configured_ordinary_git_transport(tmp_path: Path, monkeypatch) -> None:
    root = _repo(tmp_path)
    client = LocalGitClient(
        app_id="123",
        private_key="unused",
        account_id="writer",
        workspace_root=root,
    )
    client.authorize_local_git("ArthurKoba/mcp-bridge", "projects/bridge")

    original = client._git_output
    captured: dict[str, object] = {}

    def fake_git_output(target: Path, *args: str, env=None) -> str:
        if args and args[0] == "push":
            captured["args"] = args
            captured["env"] = env
            return "To https://github.com/ArthurKoba/mcp-bridge.git"
        if args == ("rev-parse", "HEAD"):
            return "a" * 40
        return original(target, *args, env=env)

    monkeypatch.setattr(client, "_git_output", fake_git_output)
    result = client.push_local_git("ArthurKoba/mcp-bridge", "projects/bridge", branch="feat/test")

    assert captured["env"] is None
    assert captured["args"] == (
        "push",
        "--porcelain",
        "--set-upstream",
        "origin",
        "HEAD:refs/heads/feat/test",
    )
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

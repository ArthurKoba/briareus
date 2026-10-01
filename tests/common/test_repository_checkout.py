from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from common.repository_checkout import (
    RepositoryCheckoutError,
    checkout_repository,
)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.name", "Test User", cwd=repo)
    _git("config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "README.md", cwd=repo)
    _git("commit", "-m", "initial", cwd=repo)
    return repo


def test_snapshot_checkout_removes_git_metadata(
    tmp_path: Path,
    source_repo: Path,
) -> None:
    workspace = tmp_path / "workspace"

    result = checkout_repository(
        source_repo.as_uri(),
        "repos/snapshot",
        workspace_root=workspace,
        mode="snapshot",
    )

    target = workspace / "repos" / "snapshot"
    assert result["path"] == "repos/snapshot"
    assert result["git_metadata"] is False
    assert (target / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert not (target / ".git").exists()


def test_git_checkout_keeps_history(
    tmp_path: Path,
    source_repo: Path,
) -> None:
    workspace = tmp_path / "workspace"

    result = checkout_repository(
        source_repo.as_uri(),
        "repos/full",
        workspace_root=workspace,
        mode="git",
    )

    target = workspace / "repos" / "full"
    assert result["git_metadata"] is True
    assert (target / ".git").is_dir()
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert count == "1"


def test_checkout_rejects_workspace_escape(
    tmp_path: Path,
    source_repo: Path,
) -> None:
    with pytest.raises(RepositoryCheckoutError, match="escapes"):
        checkout_repository(
            source_repo.as_uri(),
            "../outside",
            workspace_root=tmp_path / "workspace",
        )

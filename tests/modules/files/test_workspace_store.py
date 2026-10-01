from __future__ import annotations

import base64
from pathlib import Path

import pytest

from common.settings import TerminalSettings
from modules.files.workspace_store import WorkspaceFileError, WorkspaceFileStore
from modules.terminal.manager import TerminalManager


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceFileStore:
    return WorkspaceFileStore(tmp_path / "workspace")


def test_workspace_file_lifecycle(workspace: WorkspaceFileStore) -> None:
    created = workspace.write_text("projects/demo/readme.txt", "hello")
    assert created["path"] == "projects/demo/readme.txt"

    listing = workspace.list("projects/demo")
    assert [item["name"] for item in listing["entries"]] == ["readme.txt"]

    read = workspace.read("projects/demo/readme.txt")
    assert base64.b64decode(str(read["data_base64"])) == b"hello"

    moved = workspace.move(
        "projects/demo/readme.txt",
        "projects/demo/renamed.txt",
    )
    assert moved["path"] == "projects/demo/renamed.txt"

    copied = workspace.copy(
        "projects/demo/renamed.txt",
        "artifacts/copy.txt",
    )
    assert copied["path"] == "artifacts/copy.txt"

    deleted = workspace.delete("artifacts/copy.txt")
    assert deleted["deleted"] is True


def test_workspace_rejects_escape(workspace: WorkspaceFileStore) -> None:
    with pytest.raises(WorkspaceFileError, match="escapes"):
        workspace.write_text("../escape.txt", "no")

    outside = workspace.root.parent / "outside"
    outside.mkdir()
    workspace.ensure()
    (workspace.root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceFileError, match="escapes"):
        workspace.write_text("link/escape.txt", "no")


@pytest.mark.asyncio
async def test_files_and_terminal_share_same_workspace_root(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    files = WorkspaceFileStore(root)
    files.write_text("projects/demo/input.txt", "shared")

    terminal = TerminalManager(
        TerminalSettings(
            workspace_root=root,
            home=tmp_path / "home",
            shell="/bin/bash",
        )
    )
    result = await terminal.terminal_exec("demo", "cat input.txt")

    assert result["exit_code"] == 0
    assert result["stdout"] == "shared"

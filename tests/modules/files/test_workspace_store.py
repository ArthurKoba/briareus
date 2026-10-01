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


def test_workspace_rejects_directory_copy_or_move_into_itself(
    workspace: WorkspaceFileStore,
) -> None:
    workspace.write_text("tree/source.txt", "data")

    with pytest.raises(WorkspaceFileError, match="inside source"):
        workspace.copy("tree", "tree/nested")

    with pytest.raises(WorkspaceFileError, match="inside source"):
        workspace.move("tree", "tree/nested")


def test_workspace_listing_does_not_follow_symlinks(
    workspace: WorkspaceFileStore,
) -> None:
    outside = workspace.root.parent / "outside-list"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    workspace.ensure()
    (workspace.root / "outside-link").symlink_to(outside, target_is_directory=True)

    listing = workspace.list()
    assert "outside-link" not in {item["name"] for item in listing["entries"]}


def test_workspace_copy_overwrite_replaces_destination_type(
    workspace: WorkspaceFileStore,
) -> None:
    workspace.write_text("source.txt", "file")
    workspace.mkdir("destination")
    workspace.write_text("destination/old.txt", "old")

    result = workspace.copy("source.txt", "destination", overwrite=True)

    assert result["type"] == "file"
    assert workspace.path_for("destination").read_text(encoding="utf-8") == "file"

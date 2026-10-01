from __future__ import annotations

import json
from pathlib import Path

from common.settings import FileSettings
from modules.files.file_store import FileStore
from modules.files.migration import migrate_legacy_store
from modules.files.workspace_store import WorkspaceFileStore


def test_migrates_legacy_files_with_manifest(tmp_path: Path) -> None:
    store = FileStore(FileSettings(root=tmp_path / "files"))
    first = store.put_bytes(
        b"first",
        name="first.bin",
        mime_type="application/octet-stream",
        source="test",
    )
    second = store.put_text("second.txt", "second")
    store.add_reference(
        str(first["file_id"]),
        "ghidra-project",
        "project-1",
        "source",
    )
    workspace = WorkspaceFileStore(tmp_path / "workspace")

    result = migrate_legacy_store(store, workspace)

    assert result["migrated"] == 2
    assert result["expected"] == 2
    assert result["all_verified"] is True
    assert workspace.path_for("projects/migrated-files/first.bin").read_bytes() == b"first"
    assert workspace.path_for("projects/migrated-files/second.txt").read_text() == "second"

    manifest = json.loads(
        workspace.path_for(
            "projects/migrated-files/migration-manifest.json"
        ).read_text()
    )
    assert manifest["file_count"] == 2
    by_id = {item["old_file_id"]: item for item in manifest["files"]}
    migrated_first = by_id[str(first["file_id"])]
    assert migrated_first["sha256"] == first["sha256"]
    assert migrated_first["references"][0]["consumer_id"] == "project-1"
    assert str(second["file_id"]) in by_id

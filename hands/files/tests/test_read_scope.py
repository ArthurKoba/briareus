"""Pure selector parity vectors, not resource-owner or permission evidence."""

from __future__ import annotations

import hashlib
from typing import cast
from uuid import UUID

from files_hand._read_adapter import FilesMcpReadUnavailable, FilesReadArguments
from files_hand._read_scope import FilesReadSelector


def main() -> None:
    project = UUID("12345678-1234-4234-8234-123456789abc")
    other = UUID("12345678-1234-4234-8234-123456789abd")
    long_path = "/".join(["a" * 255] * 16)  # 4095 UTF-8 bytes, 16 valid components
    paths = ("folder/report.txt", "документы/отчёт.txt", long_path, "%2e%2e/literal")
    for path in paths:
        args = FilesReadArguments.parse({"path": path, "max_bytes": 16})
        selected = FilesReadSelector(project, args)
        digest = hashlib.sha256(b"files-project-relative-v1\x00" + path.encode()).hexdigest()
        assert selected.resource_id == f"project-path-v1:{project}:{digest}"
        assert len(selected.resource_id) == 117 and selected.resource_id.isascii()
        assert selected.decision_resource() == {
            "kind": "workspace_path",
            "id": selected.resource_id,
        }
        assert selected.resource_id != FilesReadSelector(other, args).resource_id
        # Byte budget is an execution argument, not a second file identity.
        larger = FilesReadArguments.parse({"path": path, "max_bytes": 32})
        assert selected.resource_id == FilesReadSelector(project, larger).resource_id
        assert args.canonical_arguments() != larger.canonical_arguments()
    assert (
        FilesReadSelector(project, FilesReadArguments("a/b", 1)).resource_id
        != FilesReadSelector(project, FilesReadArguments("a:b", 1)).resource_id
    )
    for invalid in (None, str(project), UUID(int=0)):
        try:
            FilesReadSelector(cast(UUID, invalid), FilesReadArguments("file", 1))
        except FilesMcpReadUnavailable as exc:
            assert exc.code == "FILES_READ_SELECTOR_INVALID"
        else:
            raise AssertionError("invalid server Project accepted")
    print("FILES_DRAFT_SELECTOR_LONG_PATH_PROJECT_BINDING_PASS")
    print("NO_OWNER_LOOKUP_NO_MCP_TOOL_NO_PERMISSION_PROVEN")


if __name__ == "__main__":
    main()

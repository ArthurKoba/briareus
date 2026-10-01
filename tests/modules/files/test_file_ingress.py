from __future__ import annotations

import hashlib
import io
import urllib.parse

import pytest

from modules.files import workspace_ingress
from modules.files.workspace_store import (
    WorkspaceFileError,
    WorkspaceFileStore,
)


class _FakeAttachmentResponse:
    def __init__(self, payload: bytes) -> None:
        self._buffer = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def geturl(self) -> str:
        return "https://files.example.invalid/download/token"

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def _patch_remote(monkeypatch, payload: bytes) -> None:
    monkeypatch.setattr(
        workspace_ingress,
        "_validate_remote_file_url",
        urllib.parse.urlsplit,
    )
    monkeypatch.setattr(
        workspace_ingress,
        "_open_remote_file",
        lambda request: _FakeAttachmentResponse(payload),
    )


def test_attachment_ingress_writes_workspace_file(tmp_path, monkeypatch) -> None:
    payload = b"workspace-attachment"
    digest = hashlib.sha256(payload).hexdigest()
    workspace = WorkspaceFileStore(tmp_path / "workspace")
    _patch_remote(monkeypatch, payload)

    result = workspace_ingress.ingest_workspace_file(
        file={
            "download_url": "https://files.example.invalid/download/token",
            "file_name": "input.bin",
        },
        destination="projects/demo/input.bin",
        expected_size=len(payload),
        expected_sha256=digest,
        workspace=workspace,
        max_bytes=16 * 1024 * 1024,
    )

    assert result["path"] == "projects/demo/input.bin"
    assert result["sha256"] == digest
    assert workspace.path_for("projects/demo/input.bin").read_bytes() == payload


def test_attachment_ingress_rejects_bad_checksum(tmp_path, monkeypatch) -> None:
    payload = b"actual"
    workspace = WorkspaceFileStore(tmp_path / "workspace")
    _patch_remote(monkeypatch, payload)

    with pytest.raises(WorkspaceFileError, match="SHA-256 mismatch"):
        workspace_ingress.ingest_workspace_file(
            file={
                "download_url": "https://files.example.invalid/download/token",
                "file_name": "bad.bin",
            },
            destination="bad.bin",
            expected_size=len(payload),
            expected_sha256=hashlib.sha256(b"different").hexdigest(),
            workspace=workspace,
            max_bytes=16 * 1024 * 1024,
        )

    assert not (workspace.root / "bad.bin").exists()


def test_attachment_ingress_rejects_non_https_source(tmp_path) -> None:
    workspace = WorkspaceFileStore(tmp_path / "workspace")
    with pytest.raises(WorkspaceFileError, match="HTTPS attachment URL"):
        workspace_ingress.ingest_workspace_file(
            file={"download_url": "/mnt/data/local.bin", "file_name": "local.bin"},
            destination="local.bin",
            workspace=workspace,
            max_bytes=16 * 1024 * 1024,
        )

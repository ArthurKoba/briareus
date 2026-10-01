from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from common.models import JsonObject
from common.settings import FileSettings
from modules.files.workspace_store import WorkspaceFileStore


def _size_display(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


class FileAdminStore:
    """Administration adapter over the shared workspace filesystem."""

    def __init__(self, settings: FileSettings) -> None:
        self.workspace = WorkspaceFileStore(settings.workspace_root)
        self.workspace.ensure()

    def list(
        self,
        path: str = "",
        *,
        offset: int = 0,
        limit: int = 500,
    ) -> JsonObject:
        return self.workspace.list(path, offset=offset, limit=limit)

    def status(self) -> JsonObject:
        status = self.workspace.status()
        for field in ("free_bytes", "used_bytes", "total_bytes"):
            raw = status.get(field)
            if isinstance(raw, int):
                status[field.removesuffix("_bytes") + "_display"] = _size_display(raw)
        return status

    def stats(self) -> JsonObject:
        self.workspace.ensure()
        files = 0
        size_bytes = 0
        for root, dirs, names in os.walk(self.workspace.root):
            dirs[:] = [
                name
                for name in dirs
                if not (Path(root) / name).is_symlink()
            ]
            for name in names:
                path = Path(root) / name
                if path.is_symlink():
                    continue
                try:
                    size_bytes += path.stat().st_size
                    files += 1
                except FileNotFoundError:
                    continue
        status = self.status()
        status.update(
            {
                "files": files,
                "size_bytes": size_bytes,
                "size_display": _size_display(size_bytes),
            }
        )
        return status

    def info(self, path: str) -> JsonObject:
        return self.workspace.info(path)

    def upload(
        self,
        stream: BinaryIO,
        *,
        destination: str,
        overwrite: bool = False,
    ) -> JsonObject:
        return self.workspace.put_stream(
            stream,
            destination,
            overwrite=overwrite,
        )

    def path_for(self, path: str) -> Path:
        return self.workspace.path_for(path)

    def mkdir(self, path: str) -> JsonObject:
        return self.workspace.mkdir(path)

    def delete(self, path: str, *, recursive: bool = False) -> JsonObject:
        return self.workspace.delete(path, recursive=recursive)

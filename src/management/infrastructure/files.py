from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from common.models import JsonObject, json_array
from common.settings import FileSettings
from modules.files.file_primitives import FileError
from modules.files.file_store import FileStore
from modules.files.workspace_store import WorkspaceFileStore


class FileAdminStore:
    """Administration adapter over the canonical persistent FileStore."""

    def __init__(self, settings: FileSettings) -> None:
        self.store = FileStore(settings)
        self.store.ensure()
        self.workspace = WorkspaceFileStore(settings.workspace_root)

    def list(
        self,
        *,
        query: str = "",
        offset: int = 0,
        limit: int = 100,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> JsonObject:
        return self.store.list(
            query=query,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def stats(self) -> JsonObject:
        return self.store.stats()

    def info(self, file_id: str) -> JsonObject:
        return self.store.info(file_id)

    def upload(self, stream: BinaryIO, *, name: str, mime_type: str = "") -> JsonObject:
        return self.store.put_stream(stream, name=name, mime_type=mime_type, source="admin-upload")

    def path_for(self, file_id: str) -> Path:
        return self.store.path_for(file_id)

    def delete(self, file_id: str, *, force: bool = False) -> JsonObject:
        return self.store.delete(file_id, force=force)

    def workspace_list(
        self,
        path: str = "",
        *,
        offset: int = 0,
        limit: int = 500,
    ) -> JsonObject:
        return self.workspace.list(path, offset=offset, limit=limit)

    def workspace_info(self, path: str) -> JsonObject:
        return self.workspace.info(path)

    def workspace_upload(
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

    def workspace_path_for(self, path: str) -> Path:
        return self.workspace.path_for(path)

    def workspace_mkdir(self, path: str) -> JsonObject:
        return self.workspace.mkdir(path)

    def workspace_delete(self, path: str, *, recursive: bool = False) -> JsonObject:
        return self.workspace.delete(path, recursive=recursive)

    def cleanup(self, *, retention_days: int, limit: int, dry_run: bool = False) -> JsonObject:
        bounded_limit = min(max(limit, 1), 10_000)
        cutoff = datetime.now(UTC) - timedelta(days=max(retention_days, 1))
        preview = self.store.gc(dry_run=True, limit=bounded_limit)
        raw_candidates = preview.get("candidates", [])
        candidates: list[str] = []
        if isinstance(raw_candidates, list):
            for file_id in raw_candidates:
                if not isinstance(file_id, str):
                    continue
                try:
                    details = self.store.info(file_id)
                except FileError:
                    continue
                created = details.get("created_at")
                if not isinstance(created, str):
                    continue
                try:
                    created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                if created_at < cutoff:
                    candidates.append(file_id)

        if dry_run:
            return {
                "dry_run": True,
                "count": len(candidates),
                "candidates": json_array(candidates, context="cleanup candidates"),
            }

        deleted: list[str] = []
        for file_id in candidates:
            try:
                self.store.delete(file_id)
            except FileError:
                continue
            deleted.append(file_id)
        return {
            "dry_run": False,
            "count": len(deleted),
            "deleted": json_array(deleted, context="deleted files"),
        }

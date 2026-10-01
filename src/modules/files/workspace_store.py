from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from common.models import JsonObject, JsonValue


class WorkspaceFileError(RuntimeError):
    """Workspace filesystem operation failed."""


class WorkspaceFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str, *, allow_root: bool = False) -> Path:
        self.ensure()
        raw = value.strip().replace("\\", "/")
        if not raw or raw == ".":
            if allow_root:
                return self.root
            raise WorkspaceFileError("path is required")
        if raw.startswith("/"):
            raw = raw.lstrip("/")
        candidate = (self.root / raw).resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            raise WorkspaceFileError("path escapes workspace root")
        if candidate == self.root and not allow_root:
            raise WorkspaceFileError("operation on workspace root is not allowed")
        return candidate

    def relative(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self.root):
            raise WorkspaceFileError("path escapes workspace root")
        value = resolved.relative_to(self.root).as_posix()
        return "/" if not value else value

    def status(self) -> JsonObject:
        self.ensure()
        usage = shutil.disk_usage(self.root)
        return {
            "root": str(self.root),
            "free_bytes": usage.free,
            "used_bytes": usage.used,
            "total_bytes": usage.total,
        }

    @staticmethod
    def _entry(path: Path, root: Path) -> JsonObject:
        stat = path.stat()
        kind = "directory" if path.is_dir() else "file"
        relative = path.relative_to(root).as_posix()
        result: JsonObject = {
            "path": relative,
            "name": path.name,
            "type": kind,
            "size_bytes": stat.st_size if kind == "file" else 0,
            "modified_at_ns": stat.st_mtime_ns,
        }
        if kind == "file":
            result["mime_type"] = mimetypes.guess_type(path.name)[0] or ""
        return result

    def list(
        self,
        path: str = "",
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> JsonObject:
        if offset < 0:
            raise WorkspaceFileError("offset must be >= 0")
        if not 1 <= limit <= 1000:
            raise WorkspaceFileError("limit must be between 1 and 1000")
        directory = self._path(path, allow_root=True)
        if not directory.is_dir():
            raise WorkspaceFileError(f"directory not found: {path or '/'}")
        entries = sorted(
            directory.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.casefold()),
        )
        selected: list[JsonValue] = [
            self._entry(item, self.root)
            for item in entries[offset : offset + limit]
        ]
        return {
            "path": self.relative(directory),
            "entries": selected,
            "count": len(selected),
            "total": len(entries),
            "offset": offset,
            "limit": limit,
            "truncated": offset + len(selected) < len(entries),
        }

    def info(self, path: str) -> JsonObject:
        target = self._path(path)
        if not target.exists():
            raise WorkspaceFileError(f"path not found: {path}")
        return self._entry(target, self.root)

    def read(
        self,
        path: str,
        *,
        offset: int = 0,
        length: int = 1024 * 1024,
    ) -> JsonObject:
        if offset < 0:
            raise WorkspaceFileError("offset must be >= 0")
        if not 1 <= length <= 16 * 1024 * 1024:
            raise WorkspaceFileError("length must be between 1 and 16777216")
        target = self._path(path)
        if not target.is_file():
            raise WorkspaceFileError(f"file not found: {path}")
        size = target.stat().st_size
        if offset > size:
            raise WorkspaceFileError("offset exceeds file size")
        with target.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
        next_offset = offset + len(data)
        return {
            "path": self.relative(target),
            "offset": offset,
            "bytes_read": len(data),
            "next_offset": next_offset,
            "size_bytes": size,
            "eof": next_offset >= size,
            "data_base64": base64.b64encode(data).decode("ascii"),
        }

    def write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = True,
        create_parents: bool = True,
    ) -> JsonObject:
        target = self._path(path)
        if target.exists() and not overwrite:
            raise WorkspaceFileError(f"path already exists: {path}")
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.is_dir():
            raise WorkspaceFileError("parent directory does not exist")
        target.write_text(content, encoding="utf-8")
        return self.info(self.relative(target))

    def mkdir(self, path: str, *, parents: bool = True) -> JsonObject:
        target = self._path(path)
        target.mkdir(parents=parents, exist_ok=True)
        return self.info(self.relative(target))

    def copy(self, source: str, destination: str, *, overwrite: bool = False) -> JsonObject:
        src = self._path(source)
        dst = self._path(destination)
        if not src.exists():
            raise WorkspaceFileError(f"source not found: {source}")
        if dst.exists() and not overwrite:
            raise WorkspaceFileError(f"destination already exists: {destination}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists() and overwrite:
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return self.info(self.relative(dst))

    def move(self, source: str, destination: str, *, overwrite: bool = False) -> JsonObject:
        src = self._path(source)
        dst = self._path(destination)
        if not src.exists():
            raise WorkspaceFileError(f"source not found: {source}")
        if dst.exists():
            if not overwrite:
                raise WorkspaceFileError(f"destination already exists: {destination}")
            self.delete(destination, recursive=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return self.info(self.relative(dst))

    def delete(self, path: str, *, recursive: bool = False) -> JsonObject:
        target = self._path(path)
        if not target.exists():
            return {"path": self.relative(target), "already_absent": True}
        if target.is_dir():
            if not recursive:
                try:
                    target.rmdir()
                except OSError as exc:
                    raise WorkspaceFileError(
                        "directory is not empty; use recursive=true"
                    ) from exc
            else:
                shutil.rmtree(target)
        else:
            target.unlink()
        return {"path": path.strip().lstrip("/"), "deleted": True}

    def put_stream(
        self,
        stream: BinaryIO,
        destination: str,
        *,
        overwrite: bool = False,
    ) -> JsonObject:
        target = self._path(destination)
        if target.exists() and not overwrite:
            raise WorkspaceFileError(f"destination already exists: {destination}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (
            f".{target.name}.upload-{uuid.uuid4().hex}.part"
        )
        try:
            with temporary.open("wb") as handle:
                shutil.copyfileobj(stream, handle, length=1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
            if target.exists() and not overwrite:
                raise WorkspaceFileError(
                    f"destination already exists: {destination}"
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return self.info(self.relative(target))

    def place_file(
        self,
        source: Path,
        destination: str,
        *,
        overwrite: bool = False,
        consume: bool = False,
    ) -> JsonObject:
        target = self._path(destination)
        if target.exists() and not overwrite:
            raise WorkspaceFileError(f"destination already exists: {destination}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if consume:
            os.replace(source, target)
        else:
            shutil.copy2(source, target)
        return self.info(self.relative(target))

    def sha256(self, path: str) -> str:
        target = self._path(path)
        if not target.is_file():
            raise WorkspaceFileError(f"file not found: {path}")
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def path_for(self, path: str) -> Path:
        target = self._path(path)
        if not target.exists():
            raise WorkspaceFileError(f"path not found: {path}")
        return target

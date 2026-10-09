from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from common.models import JsonObject, validated_call
from modules.project_runtime.workspace_roots import ProjectFileError

from ._attachment_transport import open_public_attachment, validate_public_attachment_url
from .models import ClientFile
from .project_workspace import _rename_no_replace
from .workspace_store import WorkspaceFileError, WorkspaceFileStore


def _validate_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
        raise WorkspaceFileError("expected_sha256 must be a 64-character hex digest")
    return digest


@contextmanager
def _legacy_pinned_parent(root: Path, parent: Path) -> Iterator[int]:
    """Pin the real destination directory, denying symlink swaps.

    Unlike Project Files, the old global workspace has no per-Project actor,
    quota or mount namespace; this only removes the obvious path-following
    window from external attachment writes. No public Files API is changed.
    """
    relative = parent.relative_to(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(root, flags)
    try:
        for part in relative.parts:
            with suppress(FileExistsError):
                os.mkdir(part, 0o700, dir_fd=fd)
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@validated_call
def ingest_workspace_file(
    file: ClientFile,
    destination: str,
    expected_size: int | None = None,
    expected_sha256: str = "",
    overwrite: bool = False,
    *,
    workspace: WorkspaceFileStore,
    max_bytes: int,
) -> JsonObject:
    download_url = file.download_url.strip()
    validate_public_attachment_url(download_url)
    expected_digest = _validate_sha256(expected_sha256)
    if expected_size is not None and (expected_size < 0 or expected_size > max_bytes):
        raise WorkspaceFileError(f"expected_size must be between 0 and {max_bytes}")

    if max_bytes <= 0:
        raise WorkspaceFileError("maximum attachment size must be positive")
    target = workspace.target_path(destination)
    if target.exists() and not overwrite:
        raise WorkspaceFileError(f"destination already exists: {destination}")
    digest = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + 600.0

    # A persistent directory descriptor prevents a concurrent symlink swap
    # between initial validation, download and the final atomic placement.
    with _legacy_pinned_parent(workspace.root, target.parent) as parent_fd:
        temp_name = f".{target.name}.upload-{uuid.uuid4().hex}.part"
        try:
            try:
                response = open_public_attachment(download_url)
            except Exception as exc:
                if isinstance(exc, WorkspaceFileError):
                    raise
                raise WorkspaceFileError(
                    f"attachment download failed: {type(exc).__name__}"
                ) from exc

            with response:
                length_headers = response.headers.get_all("Content-Length", [])
                if len(length_headers) > 1:
                    raise WorkspaceFileError("attachment returned conflicting Content-Length")
                declared = length_headers[0] if length_headers else None
                declared_size: int | None = None
                if declared is not None:
                    try:
                        declared_size = int(declared)
                    except ValueError as exc:
                        raise WorkspaceFileError(
                            "attachment returned invalid Content-Length"
                        ) from exc
                    if declared_size < 0 or declared_size > max_bytes:
                        raise WorkspaceFileError("attachment exceeds configured upload size limit")
                    if expected_size is not None and declared_size != expected_size:
                        raise WorkspaceFileError(
                            "attachment Content-Length does not match expected_size"
                        )

                temp_fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=parent_fd,
                )
                with os.fdopen(temp_fd, "wb") as handle:
                    while True:
                        if time.monotonic() >= deadline:
                            raise WorkspaceFileError("attachment download time limit exceeded")
                        chunk = response.read(1024 * 1024)
                        if time.monotonic() >= deadline:
                            raise WorkspaceFileError("attachment download time limit exceeded")
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise WorkspaceFileError(
                                "attachment exceeds configured upload size limit"
                            )
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())

            actual_digest = digest.hexdigest()
            if declared_size is not None and total != declared_size:
                # read1 can return EOF before a declared HTTP body length.
                # Never persist a truncated attachment as completed data.
                raise WorkspaceFileError("attachment body is shorter than Content-Length")
            if expected_size is not None and total != expected_size:
                raise WorkspaceFileError(
                    f"attachment size mismatch: expected {expected_size}, received {total}"
                )
            if expected_digest and actual_digest != expected_digest:
                raise WorkspaceFileError(
                    f"attachment SHA-256 mismatch: expected {expected_digest}, "
                    f"found {actual_digest}"
                )
            if overwrite:
                # os.replace(dir_fd) replaces the entry itself, never follows
                # a newly swapped final symlink outside the configured root.
                os.replace(
                    temp_name,
                    target.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                )
            else:
                try:
                    _rename_no_replace(parent_fd, temp_name, parent_fd, target.name)
                except ProjectFileError as exc:
                    if exc.code == "FILE_EXISTS":
                        raise WorkspaceFileError(
                            f"destination already exists: {destination}"
                        ) from exc
                    raise WorkspaceFileError("atomic attachment placement unavailable") from exc
            try:
                os.fsync(parent_fd)
            except OSError as exc:
                # Atomic rename already occurred: never imply safe retry.
                raise WorkspaceFileError("attachment commit outcome uncertain") from exc
            result = workspace.info(workspace.relative(target))
            result["sha256"] = actual_digest
            result["completed"] = True
            result["transport"] = "client-file"
            return result
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=parent_fd)

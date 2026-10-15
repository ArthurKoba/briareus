"""Bounded read from an owner-held FD, not an identity or permission API.

No path selects a Project root, no directory is created and no legacy
ProjectPermit/A6 identity epochs are needed for these OS primitives.
Only a separately authenticated read-owner scope may invoke this code in
production. The default MCP entrypoint does not import or expose it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from modules.files.project_workspace import _checked_file, _components
from modules.project_runtime.workspace_roots import (
    _DIR_FLAGS,
    ProjectFileError,
    _open_beneath,
    _safe_directory,
)

from ._read_adapter import FilesReadArguments

_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True, slots=True)
class FilesNodeStamp:
    """Facts observed on a live FD; never an attestation or owner revision."""

    device: int
    inode: int
    owner_uid: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, info: os.stat_result) -> FilesNodeStamp:
        return cls(
            info.st_dev,
            info.st_ino,
            info.st_uid,
            info.st_mode,
            info.st_nlink,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )


def observe_root(root_fd: int) -> FilesNodeStamp:
    if type(root_fd) is not int or root_fd < 0:
        raise ProjectFileError("FILES_ROOT_DESCRIPTOR_INVALID")
    _safe_directory(root_fd)
    return FilesNodeStamp.from_stat(os.fstat(root_fd))


@contextmanager
def _open_leaf(root_fd: int, request: FilesReadArguments) -> Iterator[int]:
    # _components and _open_beneath are the existing Files lexical and
    # openat2 NO_XDEV/NO_SYMLINKS/BENEATH gates; no weaker fallback.
    parts = _components(request.path)
    parent = os.dup(root_fd)
    leaf = -1
    try:
        device = os.fstat(root_fd).st_dev
        for part in parts[:-1]:
            child = _open_beneath(parent, part, _DIR_FLAGS)
            os.close(parent)
            parent = child
            _safe_directory(parent, expected_device=device)
        leaf = _open_beneath(parent, parts[-1], _FILE_FLAGS)
        _checked_file(leaf, device=device)
        yield leaf
    finally:
        if leaf >= 0:
            os.close(leaf)
        os.close(parent)


@dataclass(frozen=True, slots=True)
class FilesReadObservation:
    root: FilesNodeStamp
    file: FilesNodeStamp


@dataclass(slots=True)
class HeldFilesRead:
    """Private bytes and duplicated root FD retained until owner revalidation."""

    request: FilesReadArguments
    observation: FilesReadObservation
    payload: bytes = field(repr=False)
    _root_fd: int = field(repr=False)

    def validate_current(self) -> None:
        if self._root_fd < 0 or observe_root(self._root_fd) != self.observation.root:
            raise ProjectFileError("FILES_ROOT_CHANGED_DURING_READ")
        # Reopen the FULL relative path from the retained root, not just
        # the last parent: a renamed ancestor must not preserve an old name.
        with _open_leaf(self._root_fd, self.request) as current:
            now = FilesNodeStamp.from_stat(
                _checked_file(current, device=self.observation.root.device)
            )
            if now != self.observation.file:
                raise ProjectFileError("FILE_CHANGED_DURING_READ")

    def close(self) -> None:
        descriptor, self._root_fd = self._root_fd, -1
        self.payload = b""
        if descriptor >= 0:
            os.close(descriptor)


def open_confined_read(
    root_fd: int, expected_root: FilesNodeStamp, request: FilesReadArguments
) -> HeldFilesRead:
    """Observe one bounded regular file; no caller or grant authentication.

    Root is supplied only by the trusted owner port. No absolute user path
    or Project ID is translated to a root in this primitive.
    """
    if not isinstance(request, FilesReadArguments) or not isinstance(expected_root, FilesNodeStamp):
        raise ProjectFileError("FILES_READ_BINDING_INVALID")
    descriptor = os.dup(root_fd)
    snapshot: HeldFilesRead | None = None
    try:
        root = observe_root(descriptor)
        if root != expected_root:
            raise ProjectFileError("FILES_ROOT_BINDING_CHANGED")
        with _open_leaf(descriptor, request) as source:
            before = FilesNodeStamp.from_stat(_checked_file(source, device=root.device))
            if before.size > request.max_bytes:
                raise ProjectFileError("FILE_TOO_LARGE")
            data = bytearray()
            while len(data) <= request.max_bytes:
                chunk = os.read(source, min(65536, request.max_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            after = FilesNodeStamp.from_stat(_checked_file(source, device=root.device))
            if before != after or len(data) != before.size or len(data) > request.max_bytes:
                raise ProjectFileError("FILE_CHANGED_DURING_READ")
        snapshot = HeldFilesRead(
            request, FilesReadObservation(root, before), bytes(data), descriptor
        )
        snapshot.validate_current()
        return snapshot
    except BaseException:
        if snapshot is not None:
            snapshot.close()
        else:
            os.close(descriptor)
        raise

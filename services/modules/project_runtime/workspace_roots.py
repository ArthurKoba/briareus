"""Owned Project-directory allocator shared by Files, Terminal and Web adapters.

Only authenticated Project management callers may provision roots. All opens
are descriptor-based and reject symlinks. Deletion of the Project root itself
requires a separately approved lifecycle contract and is not implemented.
"""

from __future__ import annotations

import ctypes
import errno
import os
import platform
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .authorization import ProjectPermit

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

# Linux 6.8/x86_64: verified against installed linux/openat2.h and
# asm/unistd_64.h. Reject unsupported platforms instead of silently using a
# weaker os.open() fallback for Project-contained content or root entries.
_OPENAT2_X86_64 = 437
_RESOLVE_NO_XDEV = 0x01
_RESOLVE_NO_SYMLINKS = 0x04
_RESOLVE_BENEATH = 0x08


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


def _open_beneath(directory_fd: int, name: str, flags: int) -> int:
    """Pin a single direct child without symlinks, bind mounts or magic links.

    The already trusted storage-volume ancestors are opened separately.
    Under the Project root, ALL traversals require openat2 mount fencing.
    """
    if (
        os.name != "posix"
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\x00" in name
    ):
        raise ProjectFileError("PROJECT_OPENAT2_UNAVAILABLE")
    how = _OpenHow(
        flags=flags | os.O_NOFOLLOW | os.O_CLOEXEC,
        mode=0,
        resolve=_RESOLVE_NO_XDEV | _RESOLVE_NO_SYMLINKS | _RESOLVE_BENEATH,
    )
    libc = ctypes.CDLL(None, use_errno=True)
    result: int = libc.syscall(
        ctypes.c_long(_OPENAT2_X86_64),
        ctypes.c_int(directory_fd),
        ctypes.c_char_p(os.fsencode(name)),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if result >= 0:
        return result
    number = ctypes.get_errno()
    if number in {errno.ENOSYS, errno.EINVAL}:
        raise ProjectFileError("PROJECT_OPENAT2_UNAVAILABLE")
    if number in {errno.EXDEV, errno.ELOOP}:
        raise ProjectFileError("FILE_LINK_OR_MOUNT_DENIED")
    raise OSError(number, os.strerror(number))


def _safe_ancestor(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}:
        raise ProjectFileError("PROJECT_ROOT_ANCESTOR_UNSAFE")
    writable = info.st_mode & 0o022
    # Root-owned sticky /tmp is safe for a private owner-controlled child.
    if writable and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
        raise ProjectFileError("PROJECT_ROOT_ANCESTOR_UNSAFE")


class ProjectFileError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_directory(fd: int, *, expected_device: int | None = None) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise ProjectFileError("FILE_DIRECTORY_REQUIRED")
    if expected_device is not None and info.st_dev != expected_device:
        raise ProjectFileError("FILE_MOUNT_CROSSING_DENIED")
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        # A Project tree must not be visible to other Unix users/groups, even
        # if the directory isn't writable. The owner/UID separation is an
        # additional OS security gate, not replaced by these mode checks.
        raise ProjectFileError("FILE_DIRECTORY_UNSAFE")


class ProjectRootRegistry:
    """Dedicated, owner-controlled storage tree: `<base>/<canonical Project UUID>`.

    No default root, user-supplied workspace name, symlink-following ancestor,
    unknown Project auto-create or recursive Project deletion is permitted.
    """

    def __init__(self, base_root: Path) -> None:
        if not base_root.is_absolute() or ".." in base_root.parts:
            raise ProjectFileError("PROJECT_ROOT_INVALID")
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise ProjectFileError("PROJECT_FILESYSTEM_UNSUPPORTED")
        self.base_root = base_root

    @contextmanager
    def _base_fd(self, *, provision: bool = False) -> Iterator[int]:
        root_fd = os.open("/", _DIR_FLAGS)
        try:
            _safe_ancestor(root_fd)
            parts = self.base_root.parts[1:]
            for index, name in enumerate(parts):
                last = index == len(parts) - 1
                if provision and last:
                    with suppress(FileExistsError):
                        os.mkdir(name, mode=0o700, dir_fd=root_fd)
                child_fd = os.open(name, _DIR_FLAGS, dir_fd=root_fd)
                os.close(root_fd)
                root_fd = child_fd
                _safe_ancestor(root_fd)
            _safe_directory(root_fd)
            yield root_fd
        except FileNotFoundError as exc:
            raise ProjectFileError("PROJECT_ROOT_NOT_PROVISIONED") from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ProjectFileError("PROJECT_ROOT_SYMLINK_DENIED") from exc
            raise
        finally:
            os.close(root_fd)

    @staticmethod
    def _project_name(permit: ProjectPermit) -> str:
        if not isinstance(permit, ProjectPermit) or not isinstance(permit.project_id, UUID):
            raise ProjectFileError("PROJECT_ID_INVALID")
        if (
            not isinstance(permit.expires_at, datetime)
            or permit.expires_at.tzinfo is None
            or permit.expires_at <= datetime.now(UTC)
            or type(permit.decision_version) is not int
            or permit.decision_version < 1
        ):
            raise ProjectFileError("PROJECT_PERMIT_EXPIRED")
        return str(permit.project_id)

    def provision(self, permit: ProjectPermit) -> None:
        if permit.action != "files.manage":
            raise ProjectFileError("PROJECT_PROVISION_DENIED")
        name = self._project_name(permit)
        with self._base_fd(provision=True) as base_fd:
            with suppress(FileExistsError):
                os.mkdir(name, mode=0o700, dir_fd=base_fd)
            fd = _open_beneath(base_fd, name, _DIR_FLAGS)
            try:
                _safe_directory(fd, expected_device=os.fstat(base_fd).st_dev)
            finally:
                os.close(fd)
            os.fsync(base_fd)

    @contextmanager
    def open(self, permit: ProjectPermit) -> Iterator[int]:
        name = self._project_name(permit)
        with self._base_fd() as base_fd:
            try:
                root_fd = _open_beneath(base_fd, name, _DIR_FLAGS)
            except FileNotFoundError as exc:
                raise ProjectFileError("PROJECT_ROOT_NOT_PROVISIONED") from exc
            try:
                _safe_directory(root_fd, expected_device=os.fstat(base_fd).st_dev)
                yield root_fd
            finally:
                os.close(root_fd)

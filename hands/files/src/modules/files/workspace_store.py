"""Backwards-compatible legacy Files import; stable shared workspace source.

This shim preserves old type identities for Files callers without exposing
legacy path-based IO as protected Project storage authorization.
"""

from modules.workspace_compat.legacy_store import WorkspaceFileError, WorkspaceFileStore

__all__ = ["WorkspaceFileError", "WorkspaceFileStore"]

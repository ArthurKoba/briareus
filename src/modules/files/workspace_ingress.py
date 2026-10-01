from __future__ import annotations

import hashlib
import os
import urllib.request
import uuid
from contextlib import suppress

from common.models import JsonObject, validated_call

from .file_ingress import _open_remote_file, _validate_remote_file_url
from .file_store import FileError
from .models import ClientFile
from .validation import validate_sha256
from .workspace_store import WorkspaceFileStore


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
    """Stream a client-authorized attachment directly into the shared workspace."""
    parsed = _validate_remote_file_url(file.download_url.strip())
    del parsed
    expected_digest = validate_sha256(expected_sha256)
    if expected_size is not None and (expected_size < 0 or expected_size > max_bytes):
        raise FileError(f"expected_size must be between 0 and {max_bytes}")

    target = workspace._path(destination)
    if target.exists() and not overwrite:
        raise FileError(f"destination already exists: {destination}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.upload-{uuid.uuid4().hex}.part"
    request = urllib.request.Request(
        file.download_url.strip(),
        headers={"User-Agent": "mcp-bridge/0.1 workspace-ingress"},
    )
    digest = hashlib.sha256()
    total = 0

    try:
        try:
            response = _open_remote_file(request)
        except Exception as exc:
            if isinstance(exc, FileError):
                raise
            raise FileError(
                f"attachment download failed: {type(exc).__name__}"
            ) from exc

        with response:
            _validate_remote_file_url(str(response.geturl()))
            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise FileError("attachment returned invalid Content-Length") from exc
                if declared_size < 0 or declared_size > max_bytes:
                    raise FileError("attachment exceeds the configured upload size limit")
                if expected_size is not None and declared_size != expected_size:
                    raise FileError(
                        "attachment Content-Length does not match expected_size"
                    )

            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise FileError(
                            "attachment exceeds the configured upload size limit"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        actual_digest = digest.hexdigest()
        if expected_size is not None and total != expected_size:
            raise FileError(
                f"attachment size mismatch: expected {expected_size}, received {total}"
            )
        if expected_digest and actual_digest != expected_digest:
            raise FileError(
                "attachment SHA-256 mismatch: "
                f"expected {expected_digest}, found {actual_digest}"
            )
        if target.exists() and not overwrite:
            raise FileError(f"destination already exists: {destination}")
        os.replace(temporary, target)
        result = workspace.info(workspace.relative(target))
        result["sha256"] = actual_digest
        result["completed"] = True
        result["transport"] = "client-file"
        return result
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()

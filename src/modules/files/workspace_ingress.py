from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import socket
import urllib.parse
import urllib.request
import uuid
from contextlib import suppress
from typing import IO, cast

from common.models import JsonObject, validated_call

from .models import ClientFile
from .workspace_store import WorkspaceFileError, WorkspaceFileStore


def _validate_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if digest and (
        len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise WorkspaceFileError("expected_sha256 must be a 64-character hex digest")
    return digest


def _validate_remote_file_url(file: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(file.strip())
    if parsed.scheme.casefold() != "https":
        raise WorkspaceFileError(
            "file must resolve to an HTTPS attachment URL; pass the client "
            "attachment/file argument directly"
        )
    if not parsed.hostname:
        raise WorkspaceFileError("attachment URL has no hostname")
    if parsed.username or parsed.password:
        raise WorkspaceFileError("attachment URL must not contain userinfo")
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise WorkspaceFileError("attachment hostname cannot be resolved") from exc
    if not addresses:
        raise WorkspaceFileError("attachment hostname cannot be resolved")
    for item in addresses:
        raw_ip = str(item[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise WorkspaceFileError(
                "attachment hostname resolved to an invalid address"
            ) from exc
        if not address.is_global:
            raise WorkspaceFileError(
                "attachment URL resolves to a non-public address"
            )
    return parsed


class _AttachmentRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        _validate_remote_file_url(str(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_remote_file(request: urllib.request.Request) -> http.client.HTTPResponse:
    opener = urllib.request.build_opener(_AttachmentRedirectHandler())
    return cast(http.client.HTTPResponse, opener.open(request, timeout=60))


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
    _validate_remote_file_url(download_url)
    expected_digest = _validate_sha256(expected_sha256)
    if expected_size is not None and (expected_size < 0 or expected_size > max_bytes):
        raise WorkspaceFileError(
            f"expected_size must be between 0 and {max_bytes}"
        )

    target = workspace.target_path(destination)
    if target.exists() and not overwrite:
        raise WorkspaceFileError(f"destination already exists: {destination}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.upload-{uuid.uuid4().hex}.part"
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "mcp-bridge/0.1 workspace-ingress"},
    )
    digest = hashlib.sha256()
    total = 0

    try:
        try:
            response = _open_remote_file(request)
        except Exception as exc:
            if isinstance(exc, WorkspaceFileError):
                raise
            raise WorkspaceFileError(
                f"attachment download failed: {type(exc).__name__}"
            ) from exc

        with response:
            _validate_remote_file_url(str(response.geturl()))
            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    declared_size = int(declared)
                except ValueError as exc:
                    raise WorkspaceFileError(
                        "attachment returned invalid Content-Length"
                    ) from exc
                if declared_size < 0 or declared_size > max_bytes:
                    raise WorkspaceFileError(
                        "attachment exceeds the configured upload size limit"
                    )
                if expected_size is not None and declared_size != expected_size:
                    raise WorkspaceFileError(
                        "attachment Content-Length does not match expected_size"
                    )

            with temporary.open("xb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise WorkspaceFileError(
                            "attachment exceeds the configured upload size limit"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        actual_digest = digest.hexdigest()
        if expected_size is not None and total != expected_size:
            raise WorkspaceFileError(
                f"attachment size mismatch: expected {expected_size}, received {total}"
            )
        if expected_digest and actual_digest != expected_digest:
            raise WorkspaceFileError(
                "attachment SHA-256 mismatch: "
                f"expected {expected_digest}, found {actual_digest}"
            )
        if target.exists() and not overwrite:
            raise WorkspaceFileError(
                f"destination already exists: {destination}"
            )
        os.replace(temporary, target)
        result = workspace.info(workspace.relative(target))
        result["sha256"] = actual_digest
        result["completed"] = True
        result["transport"] = "client-file"
        return result
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()

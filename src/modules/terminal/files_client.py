from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from pathlib import Path
from typing import cast

from fastmcp import Client

from common.models import JsonObject, JsonValue, json_loads, json_object, json_value


def _decode_result(value: object) -> JsonValue:
    current: object = value
    for _ in range(8):
        if isinstance(current, dict):
            if "result" in current:
                current = current["result"]
                continue
            if "data" in current:
                current = current["data"]
                continue
            return json_value(current, context="terminal files result")
        if isinstance(current, str):
            try:
                current = json_loads(current, context="terminal files result")
            except ValueError:
                return current
            continue
        return json_value(current, context="terminal files result")
    return json_value(current, context="terminal files result")


def _decode_call_result(result: object) -> JsonValue | None:
    candidates: list[object | None] = [
        cast(object | None, getattr(result, "structured_content", None)),
        cast(object | None, getattr(result, "data", None)),
    ]
    content = cast(object | None, getattr(result, "content", None))
    if isinstance(content, list):
        for block in content:
            text = cast(object | None, getattr(block, "text", None))
            if isinstance(text, str):
                candidates.append(text)
    for candidate in candidates:
        if candidate is not None:
            return _decode_result(candidate)
    return None


class TerminalFilesClient:
    def __init__(self, url: str, *, timeout_seconds: float = 300.0) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _decoded(result: object, tool: str) -> JsonObject:
        decoded = _decode_call_result(result)
        if decoded is None:
            raise RuntimeError(f"{tool} returned no result")
        return json_object(decoded, context=f"{tool} result")

    async def import_to_path(
        self,
        file_id: str,
        destination: Path,
        *,
        chunk_bytes: int = 1024 * 1024,
    ) -> JsonObject:
        destination.parent.mkdir(parents=True, exist_ok=True)
        offset = 0
        size_bytes = 0
        try:
            async with Client(self.url, timeout=self.timeout_seconds) as client:
                with destination.open("wb") as stream:
                    while True:
                        payload = self._decoded(
                            await client.call_tool(
                                "file_read",
                                {
                                    "file_id": file_id,
                                    "offset": offset,
                                    "length": chunk_bytes,
                                },
                            ),
                            "file_read",
                        )
                        data = base64.b64decode(str(payload.get("data_base64") or ""))
                        stream.write(data)
                        size_raw = payload.get("size_bytes")
                        if isinstance(size_raw, int):
                            size_bytes = size_raw
                        next_raw = payload.get("next_offset")
                        if not isinstance(next_raw, int) or next_raw < offset:
                            raise RuntimeError("file_read returned an invalid next_offset")
                        offset = next_raw
                        if bool(payload.get("eof")):
                            break
        except Exception:
            with suppress(OSError):
                await asyncio.to_thread(destination.unlink)
            raise
        return {
            "file_id": file_id,
            "size_bytes": size_bytes,
            "bytes_copied": offset,
        }

    async def export_from_path(
        self,
        source: Path,
        *,
        name: str,
        mime_type: str = "",
        chunk_bytes: int = 1024 * 1024,
    ) -> JsonObject:
        source_stat = await asyncio.to_thread(source.stat)
        size_bytes = source_stat.st_size
        async with Client(self.url, timeout=self.timeout_seconds) as client:
            begin = self._decoded(
                await client.call_tool(
                    "file_upload_begin",
                    {
                        "name": name,
                        "size_bytes": size_bytes,
                        "mime_type": mime_type,
                        "expected_sha256": "",
                    },
                ),
                "file_upload_begin",
            )
            upload_id = str(begin.get("upload_id") or "")
            if not upload_id:
                raise RuntimeError("file_upload_begin returned no upload_id")
            offset = 0
            try:
                with source.open("rb") as stream:
                    while True:
                        data = stream.read(chunk_bytes)
                        if not data:
                            break
                        write = self._decoded(
                            await client.call_tool(
                                "file_upload_write",
                                {
                                    "upload_id": upload_id,
                                    "offset": offset,
                                    "data_base64": base64.b64encode(data).decode("ascii"),
                                },
                            ),
                            "file_upload_write",
                        )
                        next_raw = write.get("next_offset")
                        if not isinstance(next_raw, int) or next_raw <= offset:
                            raise RuntimeError(
                                "file_upload_write returned an invalid next_offset"
                            )
                        offset = next_raw
                finish = self._decoded(
                    await client.call_tool(
                        "file_upload_finish",
                        {"upload_id": upload_id},
                    ),
                    "file_upload_finish",
                )
            except Exception:
                with suppress(Exception):
                    await client.call_tool(
                        "file_upload_cancel",
                        {"upload_id": upload_id},
                    )
                raise
        file_value = finish.get("file")
        if not isinstance(file_value, dict):
            raise RuntimeError("file_upload_finish returned no file metadata")
        return json_object(file_value, context="exported file metadata")

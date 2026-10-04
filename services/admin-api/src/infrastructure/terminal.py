from __future__ import annotations

import asyncio
from typing import cast

from fastmcp import Client

from common.mcp_client_pool import PersistentMcpClientPool
from common.models import JsonObject, JsonValue, json_loads, json_object, json_value

_DEFAULT_TERMINAL_MCP_URL = "http://terminal:8000/mcp"


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
            return json_value(current, context="terminal admin result")
        if isinstance(current, str):
            try:
                current = json_loads(current, context="terminal admin result")
            except ValueError:
                return current
            continue
        return json_value(current, context="terminal admin result")
    return json_value(current, context="terminal admin result")


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


class TerminalAdminClient:
    def __init__(
        self,
        url: str = _DEFAULT_TERMINAL_MCP_URL,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._pool = PersistentMcpClientPool(
            lambda: Client(self.url, timeout=self.timeout_seconds),
            name="admin-api-terminal",
            size=3,
        )

    async def _call(self, tool: str, arguments: JsonObject | None = None) -> JsonValue:
        result = await self._pool.call_tool(
            tool,
            arguments or {},
            timeout_seconds=self.timeout_seconds,
        )
        decoded = _decode_call_result(result)
        if decoded is None:
            raise RuntimeError(f"{tool} returned no result")
        if isinstance(decoded, dict):
            error = decoded.get("error")
            if isinstance(error, str) and error.strip():
                raise RuntimeError(error)
        return decoded

    async def overview(self) -> JsonObject:
        status_raw, workspaces_raw, jobs_raw = await asyncio.gather(
            self._call("terminal_status"),
            self._call("workspace_list"),
            self._call("job_list"),
        )
        status = json_object(status_raw, context="terminal status")
        workspaces_payload = json_object(workspaces_raw, context="terminal workspaces")
        jobs_payload = json_object(jobs_raw, context="terminal jobs")
        workspaces = workspaces_payload.get("workspaces")
        jobs = jobs_payload.get("jobs")
        return {
            "status": status,
            "workspaces": workspaces if isinstance(workspaces, list) else [],
            "jobs": jobs if isinstance(jobs, list) else [],
        }

    async def job_status(self, job_id: str) -> JsonObject:
        return json_object(
            await self._call("job_status", {"job_id": job_id}),
            context="terminal job status",
        )

    async def job_tail(self, job_id: str, max_bytes: int = 16 * 1024) -> JsonObject:
        status = await self.job_status(job_id)
        raw_size = status.get("output_bytes")
        size = raw_size if isinstance(raw_size, int) else 0
        cursor = max(0, size - max_bytes)
        return json_object(
            await self._call(
                "job_read",
                {
                    "job_id": job_id,
                    "cursor": cursor,
                    "max_bytes": max_bytes,
                    "wait_seconds": 0,
                },
            ),
            context="terminal job tail",
        )

    async def cancel_job(self, job_id: str) -> JsonObject:
        return json_object(
            await self._call(
                "job_cancel",
                {"job_id": job_id, "grace_seconds": 2},
            ),
            context="terminal job cancel",
        )

    async def delete_job(self, job_id: str) -> JsonObject:
        return json_object(
            await self._call("job_delete", {"job_id": job_id}),
            context="terminal job delete",
        )

    async def cleanup_jobs(
        self,
        older_than_hours: int = 168,
        dry_run: bool = False,
    ) -> JsonObject:
        return json_object(
            await self._call(
                "job_cleanup",
                {
                    "older_than_hours": older_than_hours,
                    "dry_run": dry_run,
                    "limit": 1000,
                },
            ),
            context="terminal job cleanup",
        )

    async def delete_workspace(self, workspace_id: str) -> JsonObject:
        return json_object(
            await self._call(
                "workspace_delete",
                {"workspace_id": workspace_id, "force": False},
            ),
            context="terminal workspace delete",
        )

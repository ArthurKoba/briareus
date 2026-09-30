from __future__ import annotations

from typing import cast

from fastmcp import Client

from common.models import JsonObject, JsonValue, json_loads, json_object, json_value

_DEFAULT_GHIDRA_MCP_URL = "http://ghidra:8000/mcp"


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
            return json_value(current, context="reverse admin result")
        if isinstance(current, str):
            try:
                current = json_loads(current, context="reverse admin result")
            except ValueError:
                return current
            continue
        return json_value(current, context="reverse admin result")
    return json_value(current, context="reverse admin result")


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
        if candidate is None:
            continue
        return _decode_result(candidate)
    return None


class ReverseAdminClient:
    """Read/control project worker state through the private Ghidra MCP service."""

    def __init__(self, url: str = _DEFAULT_GHIDRA_MCP_URL) -> None:
        self.url = url

    async def _call(self, tool: str, arguments: JsonObject | None = None) -> JsonValue:
        async with Client(self.url) as client:
            result = await client.call_tool(tool, arguments or {})
        decoded = _decode_call_result(result)
        if decoded is None:
            raise RuntimeError(f"{tool} returned no result")
        if isinstance(decoded, dict):
            error = decoded.get("error")
            if isinstance(error, str) and error.strip():
                raise RuntimeError(error)
        return decoded

    async def overview(self) -> JsonObject:
        payload = json_object(
            await self._call("list_projects"),
            context="reverse project overview",
        )
        workers_raw = payload.get("workers")
        workers = workers_raw if isinstance(workers_raw, list) else []
        projects_raw = payload.get("projects")
        projects = projects_raw if isinstance(projects_raw, list) else []

        worker_by_project: dict[str, int] = {}
        for raw in workers:
            if not isinstance(raw, dict):
                continue
            project_id = raw.get("project_id")
            worker_index = raw.get("worker_index")
            if isinstance(project_id, str) and isinstance(worker_index, int):
                worker_by_project[project_id] = worker_index

        enriched: list[JsonValue] = []
        for raw in projects:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            project_id = item.get("project_id")
            if isinstance(project_id, str):
                item["worker_index"] = worker_by_project.get(project_id)
            enriched.append(json_value(item, context="reverse project"))

        payload["projects"] = enriched
        return payload

    async def session_info(self, project_id: str) -> JsonObject:
        return json_object(
            await self._call("project_session_info", {"project_id": project_id}),
            context="reverse session info",
        )

    async def open_session(self, project_id: str) -> JsonObject:
        return json_object(
            await self._call("open_project", {"project_id": project_id}),
            context="reverse open session",
        )

    async def release_session(self, project_id: str) -> JsonObject:
        return json_object(
            await self._call(
                "release_project_session",
                {"project_id": project_id, "close_project": True},
            ),
            context="reverse release session",
        )

    async def project_files(self, project_id: str, folder: str = "/") -> JsonObject:
        return json_object(
            await self._call(
                "list_project_files",
                {"project_id": project_id, "folder": folder},
            ),
            context="reverse project files",
        )

    async def open_programs(self, project_id: str) -> list[JsonValue]:
        value = await self._call("list_open_programs", {"project_id": project_id})
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("programs", "open_programs"):
                items = value.get(key)
                if isinstance(items, list):
                    return items
        return []

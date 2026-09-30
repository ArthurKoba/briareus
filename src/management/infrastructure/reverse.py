from __future__ import annotations

import posixpath
from statistics import fmean
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

    def __init__(
        self,
        url: str = _DEFAULT_GHIDRA_MCP_URL,
        *,
        timeout_seconds: float = 180.0,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    async def _call(self, tool: str, arguments: JsonObject | None = None) -> JsonValue:
        async with Client(self.url, timeout=self.timeout_seconds) as client:
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
            path = item.get("path")
            if isinstance(path, str):
                parent = posixpath.dirname(path)
                if parent in {"", "/", "/projects"}:
                    group = "Root"
                elif parent.startswith("/projects/"):
                    group = parent[len("/projects/") :]
                else:
                    group = parent
                item["group"] = group
            enriched.append(json_value(item, context="reverse project"))

        enriched.sort(
            key=lambda item: (
                str(item.get("group", "")).casefold()
                if isinstance(item, dict)
                else "",
                str(item.get("name", "")).casefold()
                if isinstance(item, dict)
                else "",
            )
        )
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


    async def create_project(self, name: str, parent_dir: str = "") -> JsonObject:
        return json_object(
            await self._call(
                "create_project",
                {"name": name, "parent_dir": parent_dir},
            ),
            context="reverse create project",
        )

    async def delete_project(self, project_id: str) -> JsonObject:
        return json_object(
            await self._call("delete_project", {"project_id": project_id}),
            context="reverse delete project",
        )

    async def set_worker_enabled(
        self,
        worker_index: int,
        enabled: bool,
    ) -> JsonObject:
        return json_object(
            await self._call(
                "set_worker_enabled",
                {
                    "worker_index": worker_index,
                    "enabled": enabled,
                    "close_project": not enabled,
                },
            ),
            context="reverse worker control",
        )

    async def coverage(
        self,
        project_id: str,
        program: str,
        *,
        full: bool = False,
        sample_size: int = 50,
        batch_size: int = 20,
    ) -> JsonObject:
        count_payload = json_object(
            await self._call(
                "get_function_count",
                {"project_id": project_id, "program": program},
            ),
            context="reverse function count",
        )
        total_raw = count_payload.get("function_count")
        total_functions = int(total_raw) if isinstance(total_raw, int) else 0

        listing = json_object(
            await self._call(
                "list_functions_enhanced",
                {
                    "project_id": project_id,
                    "program": program,
                    "offset": 0,
                    "limit": max(total_functions, 10000),
                },
            ),
            context="reverse function listing",
        )
        raw_functions = listing.get("functions")
        functions = raw_functions if isinstance(raw_functions, list) else []
        addresses = [
            str(item.get("address"))
            for item in functions
            if isinstance(item, dict) and item.get("address")
        ]
        total_functions = max(total_functions, len(addresses))

        approximate = not full and len(addresses) > sample_size
        if approximate:
            target = max(1, sample_size)
            if target == 1:
                selected = addresses[:1]
            else:
                last = len(addresses) - 1
                indices = {
                    round(index * last / (target - 1))
                    for index in range(target)
                }
                selected = [addresses[index] for index in sorted(indices)]
        else:
            selected = addresses

        results: list[JsonObject] = []
        for start in range(0, len(selected), max(1, batch_size)):
            batch = selected[start : start + max(1, batch_size)]
            payload = json_object(
                await self._call(
                    "analyze_function_completeness",
                    {
                        "project_id": project_id,
                        "program": program,
                        "addresses": ",".join(batch),
                        "compact": True,
                    },
                ),
                context="reverse completeness batch",
            )
            raw_results = payload.get("results")
            if isinstance(raw_results, list):
                results.extend(
                    item for item in raw_results if isinstance(item, dict)
                )

        scores = [
            float(score)
            for item in results
            if isinstance((score := item.get("effective_score")), (int, float))
        ]
        raw_scores = [
            float(score)
            for item in results
            if isinstance((score := item.get("completeness_score")), (int, float))
        ]

        complete = sum(score >= 80 for score in scores)
        strong = sum(60 <= score < 80 for score in scores)
        partial = sum(40 <= score < 60 for score in scores)
        low = sum(score < 40 for score in scores)
        evaluated = len(scores)

        def pct(count: int) -> float:
            return round((count * 100.0 / evaluated), 1) if evaluated else 0.0

        return {
            "project_id": project_id,
            "program": program,
            "total_functions": total_functions,
            "evaluated_functions": evaluated,
            "approximate": approximate,
            "sample_size": len(selected),
            "average_effective_score": round(fmean(scores), 1) if scores else 0.0,
            "average_raw_score": round(fmean(raw_scores), 1) if raw_scores else 0.0,
            "complete_80_plus": complete,
            "complete_80_plus_percent": pct(complete),
            "strong_60_79": strong,
            "strong_60_79_percent": pct(strong),
            "partial_40_59": partial,
            "partial_40_59_percent": pct(partial),
            "low_under_40": low,
            "low_under_40_percent": pct(low),
            "custom_named": sum(bool(item.get("has_custom_name")) for item in results),
            "plate_documented": sum(bool(item.get("has_plate_comment")) for item in results),
            "prototype_set": sum(bool(item.get("has_prototype")) for item in results),
            "return_type_resolved": sum(
                bool(item.get("return_type_resolved")) for item in results
            ),
        }


    async def session_settings(self) -> JsonObject:
        return json_object(
            await self._call("project_session_settings"),
            context="reverse session settings",
        )

    async def set_idle_timeout(self, idle_timeout_seconds: float) -> JsonObject:
        return json_object(
            await self._call(
                "set_project_idle_timeout",
                {"idle_timeout_seconds": idle_timeout_seconds},
            ),
            context="reverse session settings update",
        )

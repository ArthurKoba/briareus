from __future__ import annotations

from typing import cast

import httpx
from fastmcp import Client

from common.mcp_client_pool import PersistentMcpClientPool
from common.models import JsonObject, JsonValue, json_loads, json_object, json_value

_DEFAULT_WEB_MCP_URL = "http://web:8000/mcp"


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
            return json_value(current, context="web admin result")
        if isinstance(current, str):
            try:
                current = json_loads(current, context="web admin result")
            except ValueError:
                return current
            continue
        return json_value(current, context="web admin result")
    return json_value(current, context="web admin result")


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


class WebAdminClient:
    def __init__(self, url: str = _DEFAULT_WEB_MCP_URL, *, timeout_seconds: float = 30.0) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._pool = PersistentMcpClientPool(
            lambda: Client(self.url, timeout=self.timeout_seconds),
            name="admin-api-web",
            size=2,
        )
        self._http = httpx.AsyncClient(
            base_url="http://web:8000",
            follow_redirects=False,
            timeout=10.0,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )

    async def _call(self, tool: str, arguments: JsonObject | None = None) -> JsonObject:
        result = await self._pool.call_tool(
            tool,
            arguments or {},
            timeout_seconds=self.timeout_seconds,
        )
        decoded = _decode_call_result(result)
        if decoded is None:
            raise RuntimeError(f"{tool} returned no result")
        return json_object(decoded, context=f"web admin {tool}")

    async def status(self) -> JsonObject:
        return await self._call("browser_status")

    async def set_viewport(self, page_id: str, width: int, height: int) -> JsonObject:
        return await self._call(
            "browser_set_viewport",
            {"page_id": page_id, "width": width, "height": height},
        )

    async def set_theme(self, color_scheme: str) -> JsonObject:
        return await self._call("browser_set_theme", {"color_scheme": color_scheme})

    async def debug_target(self, page_id: str) -> JsonObject:
        return await self._call("browser_debug_target", {"page_id": page_id})

    async def devtools_asset(
        self,
        token: str,
        target_id: str,
        asset_path: str,
        query: str = "",
    ) -> tuple[int, dict[str, str], bytes]:
        path = f"/cdp-ui/{token}/page/{target_id}/{asset_path}"
        if query:
            path += f"?{query}"
        response = await self._http.get(path)
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.casefold()
            not in {"content-length", "content-encoding", "transfer-encoding", "connection"}
        }
        return response.status_code, headers, response.content

    async def close(self) -> None:
        await self._pool.close()
        await self._http.aclose()

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, cast

from fastmcp import Client

from common.models import JsonObject, JsonValue, json_array, json_object, json_value


@dataclass(frozen=True)
class BackendDescriptor:
    name: str
    url: str
    public_path: str
    purpose: str


class _RemoteTool(Protocol):
    name: str
    description: str | None


def _schema(tool: _RemoteTool, snake: str, camel: str) -> JsonObject | None:
    value = getattr(tool, snake, None)
    if value is None:
        value = getattr(tool, camel, None)
    return json_object(value, context=f"{tool.name} {camel}") if isinstance(value, dict) else None


def _tool_public(tool: _RemoteTool) -> JsonObject:
    title = getattr(tool, "title", None)
    result: JsonObject = {
        "name": tool.name,
        "description": tool.description or "",
    }
    if isinstance(title, str) and title:
        result["title"] = title
    input_schema = _schema(tool, "input_schema", "inputSchema")
    output_schema = _schema(tool, "output_schema", "outputSchema")
    if input_schema is not None:
        result["input_schema"] = input_schema
    if output_schema is not None:
        result["output_schema"] = output_schema
    return result


def _decode_call_result(result: object) -> JsonValue | None:
    for attribute in ("structured_content", "data"):
        value = cast(object | None, getattr(result, attribute, None))
        if value is not None:
            return json_value(value, context="backend tool result")

    content = cast(object | None, getattr(result, "content", None))
    if not isinstance(content, list):
        return None

    blocks: list[JsonValue] = []
    for block in content:
        text = cast(object | None, getattr(block, "text", None))
        if isinstance(text, str):
            blocks.append(text)
    return blocks or None


class BackendRouter:
    def __init__(
        self,
        backends: tuple[BackendDescriptor, ...],
        *,
        timeout_provider: Callable[[], Awaitable[float]] | None = None,
    ) -> None:
        self._backends = {backend.name: backend for backend in backends}
        self._timeout_provider = timeout_provider

    async def _timeout_seconds(self) -> float:
        if self._timeout_provider is None:
            return 5.0
        try:
            return max(1.0, float(await self._timeout_provider()))
        except Exception:
            return 5.0

    def _get(self, name: str) -> BackendDescriptor:
        key = name.strip().casefold()
        backend = self._backends.get(key)
        if backend is None:
            raise ValueError(f"unknown backend {name!r}; expected one of {sorted(self._backends)}")
        return backend

    async def _catalog(self, backend: BackendDescriptor) -> list[_RemoteTool]:
        timeout = await self._timeout_seconds()
        async with Client(backend.url, timeout=timeout) as client:
            return list(cast(list[_RemoteTool], await client.list_tools()))

    async def describe(self) -> JsonObject:
        async def probe(backend: BackendDescriptor) -> JsonObject:
            try:
                tools = await self._catalog(backend)
            except Exception as exc:
                return {
                    "name": backend.name,
                    "public_path": backend.public_path,
                    "purpose": backend.purpose,
                    "status": "not_available",
                    "tool_count": 0,
                    "error_type": type(exc).__name__,
                }
            return {
                "name": backend.name,
                "public_path": backend.public_path,
                "purpose": backend.purpose,
                "status": "available",
                "tool_count": len(tools),
            }

        values = await asyncio.gather(*(probe(backend) for backend in self._backends.values()))
        return {
            "status": "ok",
            "backends": json_array(values, context="bridge backends"),
            "count": len(values),
        }

    async def tools(self, name: str) -> JsonObject:
        backend = self._get(name)
        try:
            tools = await self._catalog(backend)
        except Exception as exc:
            return {
                "backend": backend.name,
                "public_path": backend.public_path,
                "status": "not_available",
                "tools": [],
                "error_type": type(exc).__name__,
            }
        return {
            "backend": backend.name,
            "public_path": backend.public_path,
            "status": "available",
            "tools": [_tool_public(tool) for tool in tools],
            "count": len(tools),
        }

    async def call(
        self,
        name: str,
        tool_name: str,
        arguments: JsonObject | None = None,
    ) -> JsonObject:
        backend = self._get(name)
        try:
            timeout = await self._timeout_seconds()
            async with Client(backend.url, timeout=timeout) as client:
                result = await client.call_tool(tool_name, arguments or {})
        except Exception as exc:
            message = str(exc)[:1000]
            timed_out = "timed out" in message.casefold() or isinstance(exc, TimeoutError)
            return {
                "backend": backend.name,
                "tool": tool_name,
                "status": "error",
                "error_type": "MCP_BACKEND_TIMEOUT" if timed_out else type(exc).__name__,
                "message": message,
                "hint": (
                    "Retry, narrow the request, or use an asynchronous job tool when available."
                    if timed_out
                    else ""
                ),
            }
        return {
            "backend": backend.name,
            "tool": tool_name,
            "status": "ok",
            "result": _decode_call_result(result),
        }

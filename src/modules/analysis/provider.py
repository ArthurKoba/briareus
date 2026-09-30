from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Sequence
from typing import Protocol, cast

from fastmcp import Client
from fastmcp.server.providers import Provider
from fastmcp.tools import FunctionTool, Tool
from fastmcp.utilities.components import FastMCPComponent

from common.models import JsonObject, JsonValue, json_object
from common.settings import AnalysisSettings

from .result import adapt_analysis_result, decode_call_result
from .terminology import (
    analysis_schema,
    analysis_surface_violations,
    analysis_text,
    analysis_tool_name,
    normalize_arguments,
)


class _BackendTool(Protocol):
    name: str
    description: str | None


class _SignatureTarget(Protocol):
    __signature__: inspect.Signature
    __annotations__: dict[str, object]


class AnalysisProviderError(RuntimeError):
    pass


def _backend_tool_schema(tool: _BackendTool) -> JsonObject:
    raw = getattr(tool, "input_schema", None)
    if raw is None:
        raw = getattr(tool, "inputSchema", None)
    if not isinstance(raw, dict):
        raise AnalysisProviderError(f"backend tool {tool.name!r} has no input schema")
    return json_object(raw, context=f"backend tool {tool.name} schema")


def _backend_tool_title(tool: _BackendTool) -> str | None:
    value = getattr(tool, "title", None)
    return value if isinstance(value, str) else None


def _parameter_type(property_schema: JsonObject) -> object:
    raw_type = property_schema.get("type")
    nullable = False
    if isinstance(raw_type, list):
        nullable = "null" in raw_type
        non_null = [
            value
            for value in raw_type
            if isinstance(value, str) and value != "null"
        ]
        raw_type = non_null[0] if len(non_null) == 1 else None
    if not isinstance(raw_type, str):
        return JsonValue
    base: object = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list[JsonValue],
        "object": JsonObject,
    }.get(raw_type, JsonValue)
    if nullable and isinstance(base, type):
        return base | None
    return base


def _analysis_signature(input_schema: JsonObject, tool_name: str) -> inspect.Signature:
    schema = analysis_schema(input_schema, tool_name)
    raw_properties = schema.get("properties")
    properties = raw_properties if isinstance(raw_properties, dict) else {}
    raw_required = schema.get("required")
    required = {str(name) for name in raw_required} if isinstance(raw_required, list) else set()

    parameters: list[inspect.Parameter] = []
    for name, raw_property in properties.items():
        if not isinstance(raw_property, dict):
            continue
        property_schema = json_object(raw_property, context=f"analysis parameter {name}")
        default = inspect.Parameter.empty if name in required else property_schema.get("default")
        if name not in required and "default" not in property_schema:
            default = None
        parameters.append(
            inspect.Parameter(
                str(name),
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_parameter_type(property_schema),
            )
        )
    return inspect.Signature(parameters, return_annotation=JsonValue | None)


class AnalysisToolProvider(Provider):
    """Expose the private backend through a fully separated Analysis vocabulary."""

    def __init__(self, settings: AnalysisSettings) -> None:
        super().__init__()
        self.settings = settings
        self._cache: tuple[float, list[Tool]] | None = None
        self._cache_lock = asyncio.Lock()

    def _backend_url(self) -> str:
        value = self.settings.backend_url.strip()
        if not value:
            raise AnalysisProviderError("analysis backend URL is not configured")
        return value

    async def get_tasks(self) -> Sequence[FastMCPComponent]:
        """Analysis tools are dynamic RPC facades, not background-task registrations."""
        return []

    async def _list_tools(self) -> Sequence[Tool]:
        ttl = self.settings.schema_cache_ttl_seconds
        now = time.monotonic()
        cached = self._cache
        if ttl > 0 and cached is not None and cached[0] > now:
            return list(cached[1])

        async with self._cache_lock:
            now = time.monotonic()
            cached = self._cache
            if ttl > 0 and cached is not None and cached[0] > now:
                return list(cached[1])

            async with Client(self._backend_url()) as client:
                backend_tools = cast(Sequence[_BackendTool], await client.list_tools())

            tools = self._adapt_catalog(backend_tools)
            self._validate_public_catalog(tools)
            if ttl > 0:
                self._cache = (now + ttl, tools)
            return list(tools)

    def _adapt_catalog(self, backend_tools: Sequence[_BackendTool]) -> list[Tool]:
        adapted: list[Tool] = []
        owners: dict[str, str] = {}
        for backend_tool in backend_tools:
            alias = analysis_tool_name(backend_tool.name)
            owner = owners.get(alias)
            if owner is not None and owner != backend_tool.name:
                raise AnalysisProviderError(
                    f"analysis tool alias collision: {owner!r} and "
                    f"{backend_tool.name!r} -> {alias!r}"
                )
            owners[alias] = backend_tool.name
            adapted.append(self._adapt_tool(backend_tool, alias))
        return adapted

    @staticmethod
    def _validate_public_catalog(tools: Sequence[Tool]) -> None:
        violations: list[str] = []
        for tool in tools:
            public_metadata = {
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            encoded = json.dumps(public_metadata, ensure_ascii=False, default=str)
            leaked = analysis_surface_violations(encoded)
            if leaked:
                violations.append(f"{tool.name}: {', '.join(leaked)}")
        if violations:
            raise AnalysisProviderError(
                "analysis public vocabulary leak: " + "; ".join(violations[:12])
            )

    def _adapt_tool(self, backend_tool: _BackendTool, analysis_name: str) -> Tool:
        ghidra_name = backend_tool.name
        ghidra_schema = _backend_tool_schema(backend_tool)
        exposed_schema = analysis_schema(ghidra_schema, ghidra_name)
        exposed_schema["title"] = f"{analysis_name}Arguments"

        async def invoke(**arguments: JsonValue) -> JsonValue | None:
            canonical = normalize_arguments(
                ghidra_schema,
                json_object(arguments, context=f"{analysis_name} arguments"),
                ghidra_name,
            )
            async with Client(self._backend_url()) as client:
                result = await client.call_tool(ghidra_name, canonical)
            decoded = decode_call_result(result)
            return adapt_analysis_result(decoded) if decoded is not None else None

        signature_target = cast(_SignatureTarget, invoke)
        signature = _analysis_signature(ghidra_schema, ghidra_name)
        signature_target.__signature__ = signature
        signature_target.__annotations__ = {
            name: parameter.annotation
            for name, parameter in signature.parameters.items()
        }
        signature_target.__annotations__["return"] = signature.return_annotation
        description = analysis_text(backend_tool.description or "")
        title = _backend_tool_title(backend_tool)
        tool = FunctionTool.from_function(
            invoke,
            name=analysis_name,
            title=analysis_text(title) if title else None,
            description=description,
        )
        return tool.model_copy(update={"parameters": exposed_schema})

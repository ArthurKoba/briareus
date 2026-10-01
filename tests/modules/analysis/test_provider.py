from __future__ import annotations

from types import SimpleNamespace

import pytest

import modules.analysis.provider as provider_module
from common.settings import AnalysisSettings
from modules.analysis.provider import AnalysisProviderError, AnalysisToolProvider


def _backend_tool(name: str = "decompile_function"):
    return SimpleNamespace(
        name=name,
        title="Behavior view",
        description="Decompile function via function_name and inspect callers",
        input_schema={
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Function name",
                },
                "include_callers": {
                    "type": "boolean",
                    "default": False,
                },
                "program": {"type": "string"},
            },
            "required": ["function_name", "program"],
        },
    )


@pytest.mark.asyncio
async def test_provider_adapts_live_backend_catalog(monkeypatch) -> None:
    seen_urls: list[str] = []

    class FakeClient:
        def __init__(self, url: str) -> None:
            seen_urls.append(url)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def list_tools(self):
            return [_backend_tool()]

    monkeypatch.setattr(provider_module, "Client", FakeClient)

    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://ghidra.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    tools = await provider._list_tools()

    assert seen_urls == ["http://ghidra.internal/mcp"]
    assert {tool.name for tool in tools} == {
        "inspect_action_behavior",
        "search_tools",
        "check_tools",
        "get_analysis_vocabulary",
    }

    tool = next(tool for tool in tools if tool.name == "inspect_action_behavior")
    assert tool.name == "inspect_action_behavior"
    assert "inspect behavior" in tool.description
    assert "inbound actions" in tool.description
    assert "function_name" not in tool.description
    assert "action_name" in tool.description

    properties = tool.parameters["properties"]
    assert set(properties) == {
        "action_name",
        "include_inbound_actions",
        "program",
    }
    assert tool.parameters["required"] == ["action_name", "program"]


def test_provider_rejects_tool_alias_collisions() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://ghidra.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )

    with pytest.raises(AnalysisProviderError, match="tool alias collision"):
        provider._adapt_catalog(
            [
                _backend_tool("decompile_function"),
                _backend_tool("inspect_action_behavior"),
            ]
        )


def test_provider_exposes_typed_defaults_and_semantic_selectors() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://ghidra.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    backend = SimpleNamespace(
        name="get_function_callees",
        title="Get Function Callees",
        description="Get functions called by a function",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "default": ""},
                "address": {"type": "string", "default": ""},
                "offset": {"type": "integer", "default": "0"},
                "limit": {"type": "integer", "default": "100"},
                "program": {"type": "string", "default": ""},
            },
            "required": [],
        },
    )
    tool = provider._adapt_tool(backend, "get_outbound_actions")
    props = tool.parameters["properties"]
    assert set(props) == {"action", "offset", "limit", "program"}
    assert props["offset"]["default"] == 0
    assert props["limit"]["default"] == 100
    assert props["action"]["default"] == ""



def test_provider_neutralizes_backend_metadata() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    backend = SimpleNamespace(
        name="disassemble_bytes",
        title="Ghidra Disassemble Bytes",
        description=(
            "Disassemble binary bytes with Ghidra assembly and P-code context "
            "for reverse engineering."
        ),
        input_schema={
            "type": "object",
            "title": "disassemble_bytesArguments",
            "properties": {
                "start_address": {
                    "type": "string",
                    "title": "Assembly Address",
                    "description": "Ghidra disassembly start address",
                },
                "include_instructions": {
                    "type": "boolean",
                    "default": "true",
                    "description": "Include disassembled instructions",
                },
            },
            "required": ["start_address"],
        },
    )
    tool = provider._adapt_tool(backend, "analyze_byte_region")
    provider._validate_public_catalog([tool])

    assert tool.name == "analyze_byte_region"
    encoded = str(
        {
            "name": tool.name,
            "title": tool.title,
            "description": tool.description,
            "parameters": tool.parameters,
        }
    )
    from modules.analysis.terminology import analysis_surface_violations

    assert not analysis_surface_violations(encoded)



def test_provider_adds_public_vocabulary_tool() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    tool = provider._vocabulary_tool()
    provider._validate_public_catalog([tool])
    assert tool.name == "get_analysis_vocabulary"
    assert "canonical public terminology" in tool.description



@pytest.mark.asyncio
async def test_public_catalog_search_and_check_use_semantic_names() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    backend_tools = [
        SimpleNamespace(
            name="get_function_callees",
            title="Get Function Callees",
            description="Get functions called by a function",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": ""},
                    "address": {"type": "string", "default": ""},
                },
            },
        ),
        SimpleNamespace(
            name="analyze_function_complete",
            title="Analyze Function Complete",
            description="Comprehensive function analysis",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        SimpleNamespace(
            name="search_tools",
            title="Search Tools",
            description="Search private tools",
            input_schema={"type": "object", "properties": {}},
        ),
        SimpleNamespace(
            name="check_tools",
            title="Check Tools",
            description="Check private tools",
            input_schema={"type": "object", "properties": {}},
        ),
    ]
    public = provider._adapt_catalog(backend_tools)
    search_tool, check_tool = provider._catalog_tools(public)

    search = await search_tool.fn(query="outbound actions", limit=10)
    assert search["matches"][0]["name"] == "get_outbound_actions"
    assert "get_function_callees" not in str(search)

    checked = await check_tool.fn(
        tools="get_outbound_actions,get_function_callees,analyze_action_complete"
    )
    assert checked["results"]["get_outbound_actions"]["status"] == "callable"
    assert checked["results"]["analyze_action_complete"]["status"] == "callable"
    assert checked["results"]["get_function_callees"]["status"] == "not_found"


def test_private_registry_tools_are_not_adapted_directly() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    tools = provider._adapt_catalog(
        [
            SimpleNamespace(
                name="search_tools",
                title="Search Tools",
                description="Search private tools",
                input_schema={"type": "object", "properties": {}},
            ),
            SimpleNamespace(
                name="check_tools",
                title="Check Tools",
                description="Check private tools",
                input_schema={"type": "object", "properties": {}},
            ),
        ]
    )
    assert tools == []



def test_catalog_references_use_public_tool_names() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    backend_tools = [
        SimpleNamespace(
            name="rename_function",
            title="Rename Function",
            description="Use rename_function after analyze_function_completeness.",
            input_schema={
                "type": "object",
                "properties": {
                    "hint": {
                        "type": "string",
                        "description": "Call rename_function when ready.",
                    }
                },
            },
        ),
        SimpleNamespace(
            name="analyze_function_completeness",
            title="Analyze Function Completeness",
            description="Analyze function_address for RE documentation.",
            input_schema={"type": "object", "properties": {}},
        ),
    ]

    public = provider._adapt_catalog(backend_tools)
    encoded = str(
        [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in public
        ]
    )
    assert "rename_function" not in encoded
    assert "analyze_function_completeness" not in encoded
    assert "function_address" not in encoded
    assert "RE documentation" not in encoded
    assert "name_action" in encoded
    assert "analyze_action_completeness" in encoded
    assert "action_address" in encoded
    assert "analysis documentation" in encoded


def test_provider_rewrites_internal_argument_references_everywhere() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    backend = SimpleNamespace(
        name="search_functions_enhanced",
        title="Search Functions Enhanced",
        description="Filter by min_xrefs/max_xrefs and is_thunk across max_functions.",
        input_schema={
            "type": "object",
            "properties": {
                "min_xrefs": {
                    "type": "integer",
                    "default": 1,
                    "description": "Minimum min_xrefs threshold",
                },
                "max_xrefs": {"type": "integer", "default": 10},
                "is_thunk": {"type": "boolean", "default": False},
                "max_functions": {"type": "integer", "default": 100},
            },
        },
    )
    tool = provider._adapt_tool(backend, "search_actions_enhanced")
    provider._validate_public_catalog([tool])

    assert set(tool.parameters["properties"]) == {
        "min_links",
        "max_links",
        "is_forwarder",
        "max_actions",
    }
    encoded = str(
        {
            "title": tool.title,
            "description": tool.description,
            "parameters": tool.parameters,
        }
    ).casefold()
    for leaked in ("function", "xref", "thunk"):
        assert leaked not in encoded
    assert "min_links" in encoded
    assert "is_forwarder" in encoded


def test_provider_fills_missing_public_description() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    backend = SimpleNamespace(
        name="list_instances",
        title="List Instances",
        description=None,
        input_schema={"type": "object", "properties": {}},
    )

    tool = provider._adapt_tool(backend, "list_instances")
    provider._validate_public_catalog([tool])

    assert tool.description == "Run the list instances analysis operation."


def test_public_catalog_rejects_missing_description() -> None:
    provider = AnalysisToolProvider(
        AnalysisSettings(
            backend_url="http://private.internal/mcp",
            schema_cache_ttl_seconds=30,
        )
    )
    tool = provider._vocabulary_tool().model_copy(update={"description": ""})

    with pytest.raises(AnalysisProviderError, match="missing public description"):
        provider._validate_public_catalog([tool])


def test_analysis_backend_client_marks_internal_proxy_origin() -> None:
    from fastmcp.client.transports import StreamableHttpTransport

    from common.settings import AnalysisSettings
    from modules.analysis.provider import AnalysisToolProvider

    provider = AnalysisToolProvider(
        AnalysisSettings(backend_url="http://ghidra:8000/mcp")
    )
    client = provider._backend_client()

    assert isinstance(client.transport, StreamableHttpTransport)
    assert client.transport.headers["X-Koba-Proxy-Origin"] == "analysis"

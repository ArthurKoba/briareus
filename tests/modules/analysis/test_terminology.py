from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.analysis.terminology import (
    analysis_schema,
    analysis_text,
    analysis_tool_name,
    arguments_for_surface,
    normalize_arguments,
    tool_alias,
)


def _function_schema():
    return {
        "type": "object",
        "properties": {
            "function_name": {"type": "string", "description": "Function name"},
            "include_callers": {"type": "boolean", "default": False},
            "max_steps": {"type": "integer", "default": 32},
            "program": {"type": "string"},
        },
        "required": ["function_name", "program"],
    }


def test_argument_model_accepts_ghidra_names() -> None:
    result = normalize_arguments(
        _function_schema(),
        {"function_name": "FUN_1000", "include_callers": True, "program": "fw"},
    )
    assert result == {
        "function_name": "FUN_1000",
        "include_callers": True,
        "max_steps": 32,
        "program": "fw",
    }


def test_argument_model_accepts_analysis_aliases() -> None:
    result = normalize_arguments(
        _function_schema(),
        {"action_name": "FUN_1000", "include_inbound_actions": True, "program": "fw"},
    )
    assert result["function_name"] == "FUN_1000"
    assert result["include_callers"] is True


def test_argument_model_serializes_either_surface() -> None:
    arguments = {
        "function_name": "FUN_1000",
        "include_callers": True,
        "program": "fw",
    }
    assert (
        arguments_for_surface(_function_schema(), arguments, "ghidra")["function_name"]
        == "FUN_1000"
    )
    analysis = arguments_for_surface(_function_schema(), arguments, "analysis")
    assert analysis["action_name"] == "FUN_1000"
    assert analysis["include_inbound_actions"] is True
    assert "function_name" not in analysis


def test_analysis_alias_wins_when_both_surfaces_are_supplied() -> None:
    result = normalize_arguments(
        _function_schema(),
        {
            "function_name": "FUN_1000",
            "action_name": "FUN_2000",
            "include_callers": False,
            "include_inbound_actions": True,
            "program": "fw",
        },
    )
    assert result["function_name"] == "FUN_2000"
    assert result["include_callers"] is True


def test_unknown_arguments_are_rejected() -> None:
    with pytest.raises(ValidationError):
        normalize_arguments(
            _function_schema(),
            {"action_name": "FUN_1000", "program": "fw", "surprise": True},
        )


def test_analysis_schema_renames_only_domain_arguments() -> None:
    schema = analysis_schema(_function_schema())
    assert set(schema["properties"]) == {
        "action_name",
        "include_inbound_actions",
        "max_steps",
        "program",
    }
    assert schema["required"] == ["action_name", "program"]
    assert schema["properties"]["action_name"]["description"] == "action node name"


def test_tool_alias_uses_behavior_terminology() -> None:
    alias = tool_alias("analyze_call_graph", _function_schema())
    assert alias.analysis_name == "analyze_link_map"
    assert alias.argument_aliases["function_name"] == "action_name"


def test_common_tool_name_translations_are_stable() -> None:
    assert analysis_tool_name("decompile_function") == "inspect_action_behavior"
    assert analysis_tool_name("get_function_callers") == "get_inbound_actions"
    assert (
        analysis_tool_name("analyze_function_completeness")
        == "analyze_action_completeness"
    )


def test_description_translation_uses_project_vocabulary() -> None:
    text = analysis_text("Decompile function and inspect call graph xrefs")
    assert "inspect behavior" in text
    assert "action node" in text
    assert "link map" in text
    assert "links" in text


def test_analysis_schema_rejects_alias_collisions() -> None:
    schema = {
        "type": "object",
        "properties": {
            "function": {"type": "string"},
            "action": {"type": "string"},
        },
    }
    with pytest.raises(ValueError, match="alias collision"):
        analysis_schema(schema)

def test_backend_schema_alias_metadata_overrides_fallback_mapping() -> None:
    schema = _function_schema()
    schema["properties"]["function_name"]["x-analysis-alias"] = "behavior_node"

    exposed = analysis_schema(schema)
    assert "behavior_node" in exposed["properties"]
    assert "action_name" not in exposed["properties"]
    assert exposed["required"] == ["behavior_node", "program"]

    normalized = normalize_arguments(
        schema,
        {"behavior_node": "FUN_1000", "program": "fw"},
    )
    assert normalized["function_name"] == "FUN_1000"

    analysis = arguments_for_surface(
        schema,
        {"function_name": "FUN_1000", "program": "fw"},
        "analysis",
    )
    assert analysis["behavior_node"] == "FUN_1000"


def test_backend_schema_alias_metadata_participates_in_collision_detection() -> None:
    schema = {
        "type": "object",
        "properties": {
            "function_name": {
                "type": "string",
                "x-analysis-alias": "node",
            },
            "address": {
                "type": "string",
                "x-analysis-alias": "node",
            },
        },
    }
    with pytest.raises(ValueError, match="alias collision"):
        analysis_schema(schema)


def test_numeric_and_boolean_schema_defaults_are_typed() -> None:
    schema = {
        "type": "object",
        "properties": {
            "offset": {"type": "integer", "default": "0"},
            "limit": {"type": "integer", "default": "100"},
            "enabled": {"type": "boolean", "default": "true"},
        },
    }
    exposed = analysis_schema(schema, "search_functions")
    assert exposed["properties"]["offset"]["default"] == 0
    assert exposed["properties"]["limit"]["default"] == 100
    assert exposed["properties"]["enabled"]["default"] is True
    assert normalize_arguments(schema, {}, "search_functions") == {
        "offset": 0,
        "limit": 100,
        "enabled": True,
    }


def test_semantic_action_selector_aliases_are_tool_specific() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "default": ""},
            "address": {"type": "string", "default": ""},
            "offset": {"type": "integer", "default": "0"},
        },
    }
    exposed = analysis_schema(schema, "get_function_callees")
    assert set(exposed["properties"]) == {"action", "offset"}
    normalized = normalize_arguments(
        schema,
        {"action": "ParseHeader"},
        "get_function_callees",
    )
    assert normalized["name"] == "ParseHeader"
    assert normalized["address"] == ""
    assert set(analysis_schema(schema, "unrelated_tool")["properties"]) == {
        "name",
        "address",
        "offset",
    }


def test_single_reference_read_tools_use_action_selector() -> None:
    schema = {
        "type": "object",
        "properties": {
            "address": {"type": "string"},
            "program": {"type": "string", "default": ""},
        },
        "required": ["address"],
    }
    for tool_name in (
        "decompile_function",
        "disassemble_function",
        "get_function_by_address",
        "audit_globals_in_function",
        "force_decompile",
    ):
        exposed = analysis_schema(schema, tool_name)
        assert set(exposed["properties"]) == {"action", "program"}
        assert exposed["required"] == ["action"]
        assert normalize_arguments(
            schema,
            {"action": "ParseHeader"},
            tool_name,
        )["address"] == "ParseHeader"

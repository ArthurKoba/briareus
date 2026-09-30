from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.analysis.terminology import (
    analysis_group_name,
    analysis_result_key,
    analysis_result_text,
    analysis_schema,
    analysis_surface_violations,
    analysis_text,
    analysis_tool_name,
    analysis_vocabulary,
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


def test_comment_read_accepts_semantic_action_selector() -> None:
    schema = {
        "type": "object",
        "properties": {
            "address": {"type": "string"},
            "program": {"type": "string", "default": ""},
        },
        "required": ["address"],
    }
    exposed = analysis_schema(schema, "get_comment")
    assert set(exposed["properties"]) == {"action", "program"}
    assert exposed["required"] == ["action"]
    normalized = normalize_arguments(
        schema,
        {"action": "RomLoaderStubEntry", "program": "loader.bin"},
        "get_comment",
    )
    assert normalized["address"] == "RomLoaderStubEntry"



def test_low_level_backend_tool_names_are_neutralized() -> None:
    expected = {
        "disassemble_bytes": "analyze_byte_region",
        "force_decompile": "refresh_action_behavior",
        "get_assembly_context": "get_low_level_context",
        "get_action_pcode": "get_action_ir",
        "detect_malware_behaviors": "detect_behavior_patterns",
        "run_ghidra_script": "run_analysis_script",
        "run_script_inline": "run_analysis_script_inline",
        "exit_ghidra": "stop_analysis_runtime",
        "read_memory": "read_data_region",
        "search_instructions": "search_low_level_operations",
    }
    for backend_name, public_name in expected.items():
        assert analysis_tool_name(backend_name) == public_name
        assert not analysis_surface_violations(public_name)


def test_analysis_text_removes_backend_specific_vocabulary() -> None:
    source = (
        "Ghidra reverse engineering decompiler disassembly assembly P-code opcode "
        "malware binary"
    )
    public = analysis_text(source)
    assert not analysis_surface_violations(public)
    assert "analysis runtime" in public
    assert "behavior" in public
    assert "program" in public


def test_result_keys_use_analysis_vocabulary() -> None:
    assert analysis_result_key("functions") == "actions"
    assert analysis_result_key("callees") == "outbound_actions"
    assert analysis_result_key("callers") == "inbound_actions"
    assert analysis_result_key("decompiled_code") == "behavior"
    assert analysis_result_key("disassembly") == "low_level_view"
    assert analysis_result_key("pcode") == "ir"
    assert analysis_result_text("thunk", "classification") == "forwarder"



def test_argument_names_neutralize_backend_tokens() -> None:
    schema = {
        "type": "object",
        "properties": {
            "ghidra_path": {"type": "string"},
            "binary_name": {"type": "string"},
            "pcode_mode": {"type": "string"},
            "assembly_context": {"type": "integer"},
            "max_functions": {"type": "integer"},
            "min_xrefs": {"type": "integer"},
            "is_thunk": {"type": "boolean"},
            "gzf_path": {"type": "string"},
            "gar_path": {"type": "string"},
        },
    }
    exposed = analysis_schema(schema, "synthetic_backend_tool")
    assert set(exposed["properties"]) == {
        "analysis_path",
        "program_name",
        "ir_mode",
        "low_level_context",
        "max_actions",
        "min_links",
        "is_forwarder",
        "package_path",
        "archive_path",
    }


def test_analysis_vocabulary_is_public_only() -> None:
    vocabulary = analysis_vocabulary()
    assert "action" in vocabulary
    assert "behavior" in vocabulary
    assert "ir" in vocabulary
    assert not analysis_surface_violations(str(vocabulary))



def test_plural_backend_terms_are_neutralized() -> None:
    public = analysis_text(
        "Repair flow and re-disassembles retained code for alternative decompilers."
    )
    assert not analysis_surface_violations(public)
    assert "re-analyze low-level operations" in public
    assert "behavior engines" in public



def test_public_metadata_hardening_terms_are_neutralized() -> None:
    source = (
        "GhidraServerManager requires GHIDRA_MCP_ALLOW_SCRIPTS. "
        "Include Disasm, inspect memory, decode instructions, "
        "and replace set_decompiler_comment / set_disassembly_comment."
    )
    public = analysis_text(source)
    assert not analysis_surface_violations(public)
    lowered = public.casefold()
    assert "repository manager" in lowered
    assert "analysis scripting setting" in lowered
    assert "low-level view" in lowered
    assert "data space" in lowered
    assert "low-level operations" in lowered
    assert "set_behavior_annotation" in public
    assert "set_low_level_annotation" in public


def test_hardening_guard_rejects_embedded_backend_identifiers() -> None:
    for leaked in (
        "GHIDRA_MCP_ALLOW_SCRIPTS",
        "GhidraServerManager",
        "Include Disasm",
        "memory bytes",
        "instructions",
        "set_decompiler_comment",
        "function_name",
        "min_xrefs",
        "is_thunk",
        "xrefed",
        "headless",
        "BSim",
        "DomainFile",
        "ClearFlowAndRepairCmd",
        "Swing thread",
        "Java source",
        "FUN_*",
        "DAT_*",
        "gzf_path",
        "gar_path",
    ):
        assert analysis_surface_violations(leaked)



def test_internal_variable_type_name_is_neutralized() -> None:
    public = analysis_text(
        "Replaces set_local_variable_type / set_parameter_type / "
        "set_decompiler_variable_type."
    )
    assert "set_behavior_variable_type" in public
    assert not analysis_surface_violations(public)



def test_internal_tool_names_are_removed_from_public_text() -> None:
    source = (
        "Use add_function_tag, delete_function_tag, analyze_function_completeness, "
        "rename_function, set_function_this_type, add_memory_reference, "
        "and batch_remove_function_tags."
    )
    public = analysis_text(source)
    for internal_name in (
        "add_function_tag",
        "delete_function_tag",
        "analyze_function_completeness",
        "rename_function",
        "set_function_this_type",
        "add_memory_reference",
        "batch_remove_function_tags",
    ):
        assert internal_name not in public
    assert "add_action_tag" in public
    assert "delete_action_tag" in public
    assert "analyze_action_completeness" in public
    assert "name_action" in public
    assert "set_action_this_type" in public
    assert "add_data_link" in public
    assert "remove_action_tag" in public


def test_analysis_group_names_hide_backend_categories() -> None:
    assert analysis_group_name("function") == "actions"
    assert analysis_group_name("xref") == "links"
    assert analysis_group_name("headless") == "project runtime"
    assert analysis_group_name("server") == "repository"
    assert analysis_group_name("comment") == "annotations"


def test_backend_implementation_markers_are_neutralized() -> None:
    source = (
        "FUN_* DAT_*-style autogen xrefed headless BSim DomainFile "
        "ClearFlowAndRepairCmd Swing thread Java source"
    )
    public = analysis_text(source)
    assert not analysis_surface_violations(public)
    lowered = public.casefold()
    assert "default-named" in lowered
    assert "auto-generated placeholders" in lowered
    assert "linked" in lowered
    assert "isolated" in lowered
    assert "project file" in lowered
    assert "runtime repair command" in lowered
    assert "runtime command thread" in lowered
    assert "source code" in lowered


def test_enhanced_action_search_omits_invalid_empty_backend_defaults() -> None:
    schema = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "name_pattern": {"type": "string", "default": ""},
            "min_xrefs": {"type": "integer", "default": ""},
            "max_xrefs": {"type": "integer", "default": ""},
            "calling_convention": {"type": "string", "default": ""},
            "has_custom_name": {"type": "boolean", "default": ""},
            "is_thunk": {"type": "boolean", "default": ""},
            "is_external": {"type": "boolean", "default": ""},
            "regex": {"type": "boolean", "default": False},
            "sort_by": {"type": "string", "default": "address"},
            "offset": {"type": "integer", "default": 0},
            "limit": {"type": "integer", "default": 100},
            "program": {"type": "string", "default": ""},
        },
        "required": ["project_id"],
    }

    exposed = analysis_schema(schema, "search_functions_enhanced")
    assert "default" not in exposed["properties"]["min_links"]
    assert "default" not in exposed["properties"]["max_links"]
    assert "default" not in exposed["properties"]["has_custom_name"]
    assert "default" not in exposed["properties"]["is_forwarder"]
    assert "default" not in exposed["properties"]["is_external"]

    normalized = normalize_arguments(
        schema,
        {"project_id": "project-1", "has_custom_name": True},
        "search_functions_enhanced",
    )

    assert normalized["project_id"] == "project-1"
    assert normalized["has_custom_name"] is True
    assert "min_xrefs" not in normalized
    assert "max_xrefs" not in normalized
    assert "is_thunk" not in normalized
    assert "is_external" not in normalized
    assert normalized["regex"] is False
    assert normalized["sort_by"] == "address"
    assert normalized["offset"] == 0
    assert normalized["limit"] == 100

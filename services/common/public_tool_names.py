from __future__ import annotations

_ANALYSIS_TOOL_NAME_ALIASES: dict[str, str] = {
    "disassemble_bytes": "inspect_low_level_region",
    "force_decompile": "refresh_high_level_behavior_view",
    "get_assembly_context": "get_low_level_context",
    "get_action_pcode": "get_action_ir",
    "detect_malware_behaviors": "detect_behavior_patterns",
    "run_ghidra_script": "run_analysis_script",
    "run_script_inline": "run_analysis_script_inline",
    "exit_ghidra": "stop_analysis_runtime",
    "read_memory": "read_program_data",
    "inspect_memory_content": "inspect_program_data",
    "create_memory_block": "create_data_block",
    "add_memory_reference": "add_data_relationship",
    "remove_reference": "remove_link",
    "get_address_spaces": "get_data_spaces",
    "list_segments": "list_data_regions",
    "search_instructions": "search_low_level_operations",
    "server_connect": "connect_repository_service",
    "server_disconnect": "disconnect_repository_service",
    "get_function_callers": "get_inbound_action_links",
    "get_function_callees": "get_outbound_action_links",
    "get_function_call_graph": "get_action_route_map",
    "decompile_function": "get_high_level_behavior_view",
    "disassemble_function": "get_low_level_action_view",
    "rename_function": "set_action_name",
    "analyze_function_complete": "inspect_action",
    "analyze_function_completeness": "measure_action_documentation",
    "open_program": "open_project_program",
    "load_program_from_project": "load_project_program",
    "list_open_programs": "list_active_programs",
    "run_analysis": "refresh_program_behavior",
    "reanalyze": "rebuild_program_behavior",
    "list_data_items": "list_defined_data",
    "set_comment": "set_annotation",
    "list_calling_conventions": "list_action_calling_conventions",
}


_ANALYSIS_TOOL_PHRASES: tuple[tuple[str, str], ...] = (
    ("analyze_call_graph", "analyze_link_map"),
    ("function_callers", "inbound_actions"),
    ("function_callees", "outbound_actions"),
    ("call_graph", "link_map"),
    ("cross_references", "links"),
    ("cross_reference", "link"),
)

_ANALYSIS_TOOL_TOKENS: dict[str, str] = {
    "ghidra": "analysis",
    "decompile": "inspect",
    "decompiler": "behavior",
    "disassemble": "analyze",
    "disassembly": "low_level",
    "assembly": "low_level",
    "pcode": "ir",
    "opcode": "operation",
    "malware": "behavior",
    "binary": "program",
    "memory": "data",
    "instructions": "operations",
    "instruction": "operation",
    "functions": "actions",
    "function": "action",
    "callers": "inbound_actions",
    "caller": "inbound_action",
    "callees": "outbound_actions",
    "callee": "outbound_action",
    "xrefs": "links",
    "xref": "link",
}


def analysis_public_tool_name(tool_name: str) -> str:
    direct = _ANALYSIS_TOOL_NAME_ALIASES.get(tool_name)
    if direct is not None:
        return direct
    value = tool_name
    for source, target in _ANALYSIS_TOOL_PHRASES:
        value = value.replace(source, target)
    return "_".join(_ANALYSIS_TOOL_TOKENS.get(part, part) for part in value.split("_"))


def public_tool_name(module: str, tool_name: str) -> str:
    if module == "analysis":
        return analysis_public_tool_name(tool_name)
    return tool_name

from __future__ import annotations

_ANALYSIS_TOOL_NAME_ALIASES: dict[str, str] = {
    "disassemble_bytes": "analyze_byte_region",
    "force_decompile": "refresh_action_behavior",
    "get_assembly_context": "get_low_level_context",
    "get_action_pcode": "get_action_ir",
    "detect_malware_behaviors": "detect_behavior_patterns",
    "run_ghidra_script": "run_analysis_script",
    "run_script_inline": "run_analysis_script_inline",
    "exit_ghidra": "stop_analysis_runtime",
    "read_memory": "read_data_region",
    "inspect_memory_content": "inspect_data_region",
    "create_memory_block": "create_data_block",
    "add_memory_reference": "add_data_link",
    "remove_reference": "remove_link",
    "get_address_spaces": "get_data_spaces",
    "list_segments": "list_data_regions",
    "search_instructions": "search_low_level_operations",
    "server_connect": "connect_repository_service",
    "server_disconnect": "disconnect_repository_service",
}

_ANALYSIS_TOOL_PHRASES: tuple[tuple[str, str], ...] = (
    ("analyze_call_graph", "analyze_link_map"),
    ("get_function_callers", "get_inbound_actions"),
    ("get_function_callees", "get_outbound_actions"),
    ("decompile_function", "inspect_action_behavior"),
    ("disassemble_function", "inspect_low_level_action"),
    ("rename_function", "name_action"),
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

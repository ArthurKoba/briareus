from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Literal, Protocol, cast

from pydantic import AliasChoices, ConfigDict, Field, create_model
from pydantic.fields import FieldInfo

from common.models import JsonObject, JsonValue, StrictModel, json_object

Surface = Literal["ghidra", "analysis"]


class ToolArgumentsBase(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class ToolAlias(StrictModel):
    ghidra_name: str
    analysis_name: str
    argument_aliases: dict[str, str]


class _DynamicModelFactory(Protocol):
    def __call__(
        self,
        model_name: str,
        /,
        *,
        __base__: type[ToolArgumentsBase],
        **field_definitions: tuple[object, FieldInfo],
    ) -> type[ToolArgumentsBase]: ...


_ARGUMENT_ALIASES: dict[str, str] = {
    "function": "action",
    "function_name": "action_name",
    "function_address": "action_address",
    "function_names": "action_names",
    "start_function": "start_action",
    "end_function": "end_action",
    "source_function": "source_action",
    "target_function": "target_action",
    "caller": "inbound_action",
    "callers": "inbound_actions",
    "callee": "outbound_action",
    "callees": "outbound_actions",
    "include_callers": "include_inbound_actions",
    "include_callees": "include_outbound_actions",
    "include_disasm": "include_low_level_view",
    "decompiler_comments": "behavior_annotations",
    "disassembly_comments": "low_level_annotations",
    "disassemble_first": "analyze_low_level_first",
    "include_assembly_patterns": "include_low_level_patterns",
    "context_instructions": "context_operations",
}

_TOOL_ARGUMENT_ALIASES: dict[str, dict[str, str]] = {
    "get_function_callees": {"name": "action"},
    "get_function_callers": {"name": "action"},
    "get_function_call_graph": {"name": "action"},
    "get_function_xrefs": {"name": "action"},
    "analyze_function_complete": {"name": "action"},
    "decompile_function": {"address": "action", "functions": "actions"},
    "disassemble_function": {"address": "action"},
    "get_function_by_address": {"address": "action"},
    "audit_globals_in_function": {"address": "action"},
    "force_decompile": {"address": "action"},
    "get_comment": {"address": "action"},
    "disassemble_bytes": {
        "include_instructions": "include_low_level_operations",
    },
}

_COLLAPSED_ACTION_SELECTOR_TOOLS = frozenset(
    {
        "get_function_callees",
        "get_function_callers",
        "get_function_call_graph",
        "get_function_xrefs",
    }
)

_ARGUMENT_TOKENS: dict[str, str] = {
    "ghidra": "analysis",
    "binary": "program",
    "memory": "data",
    "assembly": "low_level",
    "disassembly": "low_level_view",
    "disassemble": "analyze_low_level",
    "decompiler": "behavior",
    "decompile": "behavior",
    "pcode": "ir",
    "opcode": "operation",
    "malware": "behavior",
    "instructions": "operations",
    "instruction": "operation",
}

_TOOL_NAME_ALIASES: dict[str, str] = {
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

_TOOL_PHRASES: tuple[tuple[str, str], ...] = (
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

_TOOL_TOKENS: dict[str, str] = {
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

_TEXT_TERMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bGhidra Server\b", re.IGNORECASE), "repository service"),
    (re.compile(r"\bGhidra GUI\b", re.IGNORECASE), "desktop analysis client"),
    (re.compile(r"\bGhidra-native\b", re.IGNORECASE), "native analysis"),
    (re.compile(r"\bGhidra projects?\b", re.IGNORECASE), "analysis projects"),
    (re.compile(r"\bGhidra tools?\b", re.IGNORECASE), "analysis tools"),
    (re.compile(r"\bGhidra's\b", re.IGNORECASE), "analysis runtime's"),
    (re.compile(r"\bGhidra(?:MCP)?\b", re.IGNORECASE), "analysis runtime"),
    (re.compile(r"\bTraceRmi\b", re.IGNORECASE), "runtime trace interface"),
    (re.compile(r"\bdbgeng\b", re.IGNORECASE), "runtime debug engine"),
    (re.compile(r"\bWinDbg\b", re.IGNORECASE), "runtime debugger"),
    (re.compile(r"\bJython\b", re.IGNORECASE), "scripting runtime"),
    (re.compile(r"\breverse engineering\b", re.IGNORECASE), "behavior analysis"),
    (re.compile(r"\breversing\b", re.IGNORECASE), "behavior recovery"),
    (re.compile(r"\bcross[- ]binary\b", re.IGNORECASE), "cross-program"),
    (re.compile(r"\bbinary files?\b", re.IGNORECASE), "program files"),
    (re.compile(r"\bbinary versions?\b", re.IGNORECASE), "program versions"),
    (re.compile(r"\bbinaries\b", re.IGNORECASE), "programs"),
    (re.compile(r"\bbinary\b", re.IGNORECASE), "program"),
    (re.compile(r"\bP[- ]?code\b", re.IGNORECASE), "intermediate representation"),
    (re.compile(r"\bHighFunction\b", re.IGNORECASE), "high-level behavior graph"),
    (re.compile(r"\bvarnodes?\b", re.IGNORECASE), "value nodes"),
    (re.compile(r"\bopcode\b", re.IGNORECASE), "operation"),
    (re.compile(r"\bmalware behaviors?\b", re.IGNORECASE), "behavior patterns"),
    (re.compile(r"\bmalware\b", re.IGNORECASE), "behavior"),
    (re.compile(r"\bdecompiler's\b", re.IGNORECASE), "behavior engine's"),
    (re.compile(r"\bdecompilers\b", re.IGNORECASE), "behavior engines"),
    (re.compile(r"\bdecompiler\b", re.IGNORECASE), "behavior engine"),
    (re.compile(r"\bdecompilation\b", re.IGNORECASE), "behavior inspection"),
    (re.compile(r"\bdecompiled\b", re.IGNORECASE), "behavior view"),
    (re.compile(r"\bdecompile\b", re.IGNORECASE), "inspect behavior"),
    (
        re.compile(r"\bre-disassembl(?:e|es|ed|y)\b", re.IGNORECASE),
        "re-analyze low-level operations",
    ),
    (re.compile(r"\bdisassembled\b", re.IGNORECASE), "decoded low-level"),
    (re.compile(r"\bdisassemble\b", re.IGNORECASE), "analyze low-level operations"),
    (re.compile(r"\bdisassembly\b", re.IGNORECASE), "low-level action view"),
    (re.compile(r"\bassembly\b", re.IGNORECASE), "low-level operations"),
    (re.compile(r"\bcall graph\b", re.IGNORECASE), "link map"),
    (re.compile(r"\bcross[- ]references?\b", re.IGNORECASE), "links"),
    (re.compile(r"\bxrefs?\b", re.IGNORECASE), "links"),
    (re.compile(r"\bcallers\b", re.IGNORECASE), "inbound actions"),
    (re.compile(r"\bcaller\b", re.IGNORECASE), "inbound action"),
    (re.compile(r"\bcallees\b", re.IGNORECASE), "outbound actions"),
    (re.compile(r"\bcallee\b", re.IGNORECASE), "outbound action"),
    (re.compile(r"\bfunctions\b", re.IGNORECASE), "action nodes"),
    (re.compile(r"\bfunction\b", re.IGNORECASE), "action node"),
    (re.compile(r"\.gzf\b", re.IGNORECASE), " program package"),
    (re.compile(r"\bGZF\b", re.IGNORECASE), "program package"),
    (re.compile(r"\.gar\b", re.IGNORECASE), " project archive"),
)

_FORBIDDEN_ANALYSIS_TERMS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bghidra\b", re.IGNORECASE),
    re.compile(r"\breverse(?:\s+engineering)?\b", re.IGNORECASE),
    re.compile(r"\bdecompil\w*\b", re.IGNORECASE),
    re.compile(r"\bdisassembl\w*\b", re.IGNORECASE),
    re.compile(r"\bassembly\b", re.IGNORECASE),
    re.compile(r"\bp[- ]?code\b", re.IGNORECASE),
    re.compile(r"\bopcode\b", re.IGNORECASE),
    re.compile(r"\bmalware\b", re.IGNORECASE),
    re.compile(r"\bTraceRmi\b", re.IGNORECASE),
    re.compile(r"\bdbgeng\b", re.IGNORECASE),
    re.compile(r"\bWinDbg\b", re.IGNORECASE),
    re.compile(r"\bJython\b", re.IGNORECASE),
)

_RESULT_KEY_ALIASES: dict[str, str] = {
    "function": "action",
    "functions": "actions",
    "function_name": "action_name",
    "function_address": "action_address",
    "caller": "inbound_action",
    "callers": "inbound_actions",
    "callee": "outbound_action",
    "callees": "outbound_actions",
    "xrefs": "links",
    "xref_count": "link_count",
    "cross_references": "links",
    "cross_reference": "link",
    "decompiled": "behavior",
    "decompiled_code": "behavior",
    "disassembly": "low_level_view",
    "instructions": "low_level_operations",
    "instruction": "operation",
    "isThunk": "is_forwarder",
    "isExternal": "is_external",
    "pcode": "ir",
    "high_pcode": "high_ir",
    "low_pcode": "low_ir",
    "opcode": "operation",
    "ghidra_version": "runtime_version",
}

_RESULT_METADATA_KEYS = frozenset(
    {
        "error",
        "message",
        "warning",
        "warnings",
        "note",
        "notes",
        "suggestion",
        "suggestions",
        "status",
        "classification",
        "reason",
        "details",
        "diagnostic",
        "diagnostics",
    }
)

_RESULT_OPAQUE_KEYS = frozenset(
    {
        "behavior",
        "code",
        "source",
        "bytes",
        "data",
        "data_base64",
        "value",
        "comment",
        "plate",
        "pre",
        "eol",
        "post",
        "repeatable",
        "path",
        "file_path",
        "executable_path",
        "output",
        "stdout",
        "stderr",
    }
)


ANALYSIS_VOCABULARY: JsonObject = {
    "action": "A named behavior unit that can be addressed and inspected.",
    "actions": "A collection of behavior units.",
    "inbound_action": "An action that links into the selected action.",
    "outbound_action": "An action reached from the selected action.",
    "link": "A relationship between locations, data, or actions.",
    "link_map": "A graph of inbound and outbound action relationships.",
    "behavior": "A high-level behavioral representation of an action.",
    "low_level_view": "An ordered view of low-level operations for an action or data region.",
    "low_level_operation": "One decoded operation in a low-level view.",
    "ir": "An intermediate representation used for value-flow and behavior inspection.",
    "program": "A loaded analysis target within a project.",
    "project": "A persistent analysis workspace containing programs and metadata.",
    "data_region": "A bounded region of program data addressed within a program.",
    "data_link": "A relationship between data locations.",
    "data_space": "A named address space used by a program.",
    "forwarder": "A small action whose primary behavior is forwarding control to another action.",
    "behavior_annotation": "A semantic annotation attached to a behavior view.",
    "low_level_annotation": "An annotation attached to a low-level operation view.",
}


def analysis_vocabulary() -> JsonObject:
    return json_object(dict(ANALYSIS_VOCABULARY), context="analysis vocabulary")


def analysis_argument_name(
    ghidra_name: str,
    property_schema: JsonObject | None = None,
    tool_name: str | None = None,
) -> str:
    if property_schema is not None:
        schema_alias = property_schema.get("x-analysis-alias")
        if isinstance(schema_alias, str) and schema_alias.strip():
            return schema_alias.strip()
    if tool_name is not None:
        tool_alias = _TOOL_ARGUMENT_ALIASES.get(tool_name, {}).get(ghidra_name)
        if tool_alias is not None:
            return tool_alias
    direct = _ARGUMENT_ALIASES.get(ghidra_name)
    if direct is not None:
        return direct
    parts = ghidra_name.split("_")
    translated = [_ARGUMENT_TOKENS.get(part, part) for part in parts]
    return "_".join(translated)


def analysis_tool_name(ghidra_name: str) -> str:
    direct = _TOOL_NAME_ALIASES.get(ghidra_name)
    if direct is not None:
        return direct
    value = ghidra_name
    for source, target in _TOOL_PHRASES:
        value = value.replace(source, target)
    parts = value.split("_")
    translated = [_TOOL_TOKENS.get(part, part) for part in parts]
    return "_".join(translated)


def analysis_text(text: str) -> str:
    value = text
    for pattern, replacement in _TEXT_TERMS:
        value = pattern.sub(replacement, value)
    return value


def analysis_result_key(key: str) -> str:
    direct = _RESULT_KEY_ALIASES.get(key)
    if direct is not None:
        return direct
    parts = key.split("_")
    translated = [_TOOL_TOKENS.get(part, part) for part in parts]
    return "_".join(translated)


def analysis_result_text(text: str, key: str | None = None) -> str:
    if key in _RESULT_OPAQUE_KEYS:
        return text
    if key == "classification" and text.casefold() == "thunk":
        return "forwarder"
    if key is None or key in _RESULT_METADATA_KEYS:
        return analysis_text(text)
    return text


def analysis_surface_violations(text: str) -> list[str]:
    return sorted(
        {
            match.group(0)
            for pattern in _FORBIDDEN_ANALYSIS_TERMS
            for match in pattern.finditer(text)
        },
        key=str.casefold,
    )


def tool_alias(ghidra_name: str, input_schema: JsonObject) -> ToolAlias:
    properties = _schema_properties(input_schema)
    aliases = {
        name: analysis_argument_name(name, property_schema, ghidra_name)
        for name, property_schema in properties.items()
        if analysis_argument_name(name, property_schema, ghidra_name) != name
    }
    return ToolAlias(
        ghidra_name=ghidra_name,
        analysis_name=analysis_tool_name(ghidra_name),
        argument_aliases=aliases,
    )


def analysis_schema(input_schema: JsonObject, tool_name: str | None = None) -> JsonObject:
    schema = json.loads(json.dumps(input_schema))
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return json_object(schema, context="analysis tool schema")

    renamed: dict[str, JsonValue] = {}
    owners: dict[str, str] = {}
    for ghidra_name, raw_property in properties.items():
        canonical = str(ghidra_name)
        if tool_name in _COLLAPSED_ACTION_SELECTOR_TOOLS and canonical == "address":
            continue
        property_schema = json_object(raw_property, context="tool property schema")
        alias = analysis_argument_name(canonical, property_schema, tool_name)
        owner = owners.get(alias)
        if owner is not None and owner != canonical:
            raise ValueError(
                f"analysis argument alias collision: {owner!r} and "
                f"{canonical!r} -> {alias!r}"
            )
        owners[alias] = canonical
        description = property_schema.get("description")
        if isinstance(description, str):
            property_schema["description"] = analysis_text(description)
        title = property_schema.get("title")
        if isinstance(title, str):
            property_schema["title"] = analysis_text(title)
        if "default" in property_schema:
            property_schema["default"] = _typed_default(property_schema)
        renamed[alias] = property_schema
    schema["properties"] = renamed
    schema_title = schema.get("title")
    if isinstance(schema_title, str):
        schema["title"] = analysis_text(schema_title)
    schema_description = schema.get("description")
    if isinstance(schema_description, str):
        schema["description"] = analysis_text(schema_description)

    required = schema.get("required")
    if isinstance(required, list):
        source_properties = _schema_properties(input_schema)
        schema["required"] = [
            analysis_argument_name(
                str(name),
                source_properties.get(str(name)),
                tool_name,
            )
            for name in required
        ]
    if tool_name in _COLLAPSED_ACTION_SELECTOR_TOOLS:
        required = schema.setdefault("required", [])
        if isinstance(required, list) and "action" not in required:
            required.append("action")
    return json_object(schema, context="analysis tool schema")


def normalize_arguments(
    input_schema: JsonObject,
    arguments: JsonObject,
    tool_name: str | None = None,
) -> JsonObject:
    model = _argument_model(_schema_cache_key(input_schema), tool_name)
    validated = model.model_validate(_prefer_analysis_aliases(input_schema, arguments, tool_name))
    return json_object(validated.model_dump(mode="json"), context="normalized tool arguments")


def arguments_for_surface(
    input_schema: JsonObject,
    arguments: JsonObject,
    surface: Surface,
    tool_name: str | None = None,
) -> JsonObject:
    model = _argument_model(_schema_cache_key(input_schema), tool_name)
    validated = model.model_validate(_prefer_analysis_aliases(input_schema, arguments, tool_name))
    return json_object(
        validated.model_dump(mode="json", by_alias=surface == "analysis"),
        context=f"{surface} tool arguments",
    )


def _schema_properties(input_schema: JsonObject) -> dict[str, JsonObject]:
    raw = input_schema.get("properties")
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): json_object(schema, context=f"tool property {name}")
        for name, schema in raw.items()
        if isinstance(schema, dict)
    }


def _schema_cache_key(input_schema: JsonObject) -> str:
    return json.dumps(input_schema, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=512)
def _argument_model(schema_key: str, tool_name: str | None = None) -> type[ToolArgumentsBase]:
    schema = json_object(json.loads(schema_key), context="tool input schema")
    properties = _schema_properties(schema)
    required_raw = schema.get("required")
    required = {str(name) for name in required_raw} if isinstance(required_raw, list) else set()

    fields: dict[str, tuple[object, FieldInfo]] = {}
    for ghidra_name, property_schema in properties.items():
        field_type = _python_type(property_schema)
        default: object
        if ghidra_name in required and "default" not in property_schema:
            default = ...
        else:
            default = _typed_default(property_schema)
        analysis_name = analysis_argument_name(ghidra_name, property_schema, tool_name)
        if analysis_name == ghidra_name:
            field = cast(FieldInfo, Field(default=default))
        else:
            field = cast(
                FieldInfo,
                Field(
                    default=default,
                    validation_alias=AliasChoices(analysis_name, ghidra_name),
                    serialization_alias=analysis_name,
                ),
            )
        fields[ghidra_name] = (field_type, field)

    model_factory = cast(_DynamicModelFactory, create_model)
    return model_factory(
        "ToolArguments",
        __base__=ToolArgumentsBase,
        **fields,
    )


def _typed_default(property_schema: JsonObject) -> JsonValue:
    value = property_schema.get("default")
    raw_type = property_schema.get("type")
    if not isinstance(value, str) or not isinstance(raw_type, str):
        return value
    if raw_type == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    if raw_type == "number":
        try:
            return float(value)
        except ValueError:
            return value
    if raw_type == "boolean":
        lowered = value.casefold()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return value


def _python_type(property_schema: JsonObject) -> object:
    raw_type = property_schema.get("type")
    if isinstance(raw_type, list):
        non_null = [
            value
            for value in raw_type
            if isinstance(value, str) and value != "null"
        ]
        raw_type = non_null[0] if len(non_null) == 1 else None
    if not isinstance(raw_type, str):
        return JsonValue
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list[JsonValue],
        "object": JsonObject,
    }.get(raw_type, JsonValue)


def _prefer_analysis_aliases(
    input_schema: JsonObject,
    arguments: JsonObject,
    tool_name: str | None = None,
) -> JsonObject:
    normalized = dict(arguments)
    for ghidra_name, property_schema in _schema_properties(input_schema).items():
        analysis_name = analysis_argument_name(ghidra_name, property_schema, tool_name)
        if analysis_name == ghidra_name or analysis_name not in normalized:
            continue
        normalized.pop(ghidra_name, None)
    return json_object(normalized, context="analysis tool arguments")

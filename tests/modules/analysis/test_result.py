from __future__ import annotations

from types import SimpleNamespace

from modules.analysis.result import adapt_analysis_result, decode_call_result, decode_result


def test_decode_result_parses_raw_json_string() -> None:
    result = decode_result('{"has_project":true,"project_name":"camera"}')
    assert result["has_project"] is True
    assert result["project_name"] == "camera"


def test_decode_result_recursively_unwraps_result_envelopes() -> None:
    result = decode_result({"result": '{"result":{"value":7}}'})
    assert result == {"value": 7}


def test_decode_call_result_prefers_structured_content() -> None:
    result = SimpleNamespace(
        data={"value": "lossy"},
        structured_content={"result": '{"value":"exact"}'},
        content=[],
    )
    assert decode_call_result(result) == {"value": "exact"}


def test_decode_call_result_falls_back_to_text_content() -> None:
    result = SimpleNamespace(
        data=None,
        structured_content=None,
        content=[SimpleNamespace(text='{"value":"text"}')],
    )
    assert decode_call_result(result) == {"value": "text"}



def test_adapt_analysis_result_translates_structure_and_metadata() -> None:
    result = adapt_analysis_result(
        {
            "function": {
                "function_name": "ParseHeader",
                "callees": ["OpenStream"],
                "callers": ["Dispatch"],
                "decompiled_code": "void ParseHeader(void) { /* Ghidra */ }",
                "classification": "thunk",
                "warning": "Ghidra decompiler warning",
            },
            "xrefs": [{"from_function": "Dispatch"}],
        }
    )
    assert result["action"]["action_name"] == "ParseHeader"
    assert result["action"]["outbound_actions"] == ["OpenStream"]
    assert result["action"]["inbound_actions"] == ["Dispatch"]
    assert result["action"]["classification"] == "forwarder"
    assert result["action"]["behavior"] == "void ParseHeader(void) { /* Ghidra */ }"
    assert "Ghidra" not in result["action"]["warning"]
    assert "links" in result


def test_adapt_analysis_result_preserves_opaque_payloads() -> None:
    payload = {"decompiled": "Ghidra P-code assembly text belongs to payload"}
    result = adapt_analysis_result(payload)
    assert result["behavior"] == payload["decompiled"]



def test_adapt_analysis_result_translates_suffixed_metadata() -> None:
    result = adapt_analysis_result(
        {"return_type_warning": "Do not trust decompiler display in Ghidra."}
    )
    warning = result["return_type_warning"]
    assert isinstance(warning, str)
    assert "decompiler" not in warning.casefold()
    assert "ghidra" not in warning.casefold()
    assert "behavior engine" in warning.casefold()


def test_adapt_analysis_result_translates_tool_group_catalog() -> None:
    result = adapt_analysis_result(
        {
            "groups": [
                {
                    "group": "function",
                    "description": "Decompile functions and inspect disassembly xrefs",
                    "tools": [
                        "disassemble_bytes",
                        "force_decompile",
                        "get_function_call_graph",
                    ],
                }
            ]
        }
    )
    group = result["groups"][0]
    assert group["group"] == "actions"
    assert "decompile" not in group["description"].casefold()
    assert "disassembly" not in group["description"].casefold()
    assert "xref" not in group["description"].casefold()
    assert group["tools"] == [
        "analyze_byte_region",
        "refresh_action_behavior",
        "get_action_link_map",
    ]


def test_adapt_analysis_result_uses_public_group_names() -> None:
    result = adapt_analysis_result(
        {
            "groups": [
                {"group": "headless", "tools": []},
                {"group": "server", "tools": []},
                {"group": "xref", "tools": []},
            ]
        }
    )
    assert [group["group"] for group in result["groups"]] == [
        "project runtime",
        "repository",
        "links",
    ]

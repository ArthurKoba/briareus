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

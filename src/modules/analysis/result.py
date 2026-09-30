from __future__ import annotations

from typing import cast

from common.models import JsonValue, json_loads, json_value

from .terminology import analysis_result_key, analysis_result_text


def decode_result(data: object) -> JsonValue:
    """Recursively unwrap backend result envelopes and JSON strings."""
    value: object = data
    for _ in range(8):
        if isinstance(value, dict) and "result" in value:
            nested = value["result"]
            if nested is value:
                return json_value(value, context="analysis backend result")
            value = nested
            continue
        if isinstance(value, str):
            try:
                decoded = json_loads(value, context="analysis backend result")
            except ValueError:
                return value
            if decoded == value:
                return value
            value = decoded
            continue
        return json_value(value, context="analysis backend result")
    return json_value(value, context="analysis backend result")


def decode_call_result(result: object) -> JsonValue | None:
    """Decode FastMCP results across structured and legacy content forms."""
    candidates: list[object | None] = [
        cast(object | None, getattr(result, "structured_content", None)),
        cast(object | None, getattr(result, "data", None)),
    ]
    content = cast(object | None, getattr(result, "content", None))
    if isinstance(content, list):
        for block in content:
            text = cast(object | None, getattr(block, "text", None))
            if isinstance(text, str):
                candidates.append(text)

    for candidate in candidates:
        if candidate is None:
            continue
        decoded = decode_result(candidate)
        if decoded is not None:
            return decoded
    return None



def adapt_analysis_result(value: JsonValue, parent_key: str | None = None) -> JsonValue:
    """Translate backend result structure into the public Analysis vocabulary."""
    if isinstance(value, dict):
        translated: dict[str, JsonValue] = {}
        for raw_key, raw_value in value.items():
            key = analysis_result_key(str(raw_key))
            translated[key] = adapt_analysis_result(raw_value, key)
        return translated
    if isinstance(value, list):
        return [adapt_analysis_result(item, parent_key) for item in value]
    if isinstance(value, str):
        return analysis_result_text(value, parent_key)
    return value

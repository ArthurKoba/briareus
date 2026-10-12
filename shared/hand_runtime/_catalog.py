"""Source-derived, nonsecret capability metadata for private MCP Hands.

No imported provider code, configured credentials, or executable callable is
needed to report registered tool declarations. This is NOT tool availability.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TypedDict


class SourceTool(TypedDict):
    name: str
    module: str


def _declared_tool_name(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "mcp"
        ):
            continue
        overridden = next((key.value for key in decorator.keywords if key.arg == "name"), None)
        if isinstance(overridden, ast.Constant) and isinstance(overridden.value, str):
            return overridden.value
        return node.name
    return None


def discover_source_tools(modules_root: Path) -> list[SourceTool]:
    """Inspect copied source registrations without running tool constructors."""
    if not modules_root.is_dir():
        raise FileNotFoundError("Hand source tool package is absent")
    result: list[SourceTool] = []
    for source in sorted(modules_root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        module = "modules." + ".".join(source.relative_to(modules_root).with_suffix("").parts)
        parsed = ast.parse(source.read_text(encoding="utf-8"), filename=module)
        for node in ast.walk(parsed):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = _declared_tool_name(node)
                if name is not None:
                    result.append({"name": name, "module": module})
    return sorted(result, key=lambda item: (item["module"], item["name"]))


def source_capabilities(hand: str, modules_root: Path) -> dict[str, object]:
    """Stable internal v1 read-only inventory, never an authorization decision."""
    if not hand or not hand.replace("-", "").isidentifier():
        raise ValueError("invalid Hand identifier")
    tools = discover_source_tools(modules_root)
    return {
        "schema_version": 1,
        "hand": hand,
        "source": "packaged_tool_declarations",
        "declared_tool_count": len(tools),
        "declared_tools": tools,
        "mcp_transport": "not_mounted",
        "authorization": "not_configured",
        "execution": "disabled",
    }

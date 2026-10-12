"""Real MCP transport with strictly non-authoritative diagnostic tools.

No provider implementation is imported and no executor, credential, workspace,
user data, or authenticated tool is exposed by this transport.
"""

from __future__ import annotations

from collections import Counter

from fastmcp import FastMCP


def diagnostic_mcp(hand: str, catalog: dict[str, object]) -> FastMCP:
    """Return a private Streamable HTTP MCP server with no side effects."""
    mcp = FastMCP(f"briareus-{hand}-diagnostics")
    declared_count = int(catalog["declared_tool_count"])
    tools = catalog["declared_tools"]
    assert isinstance(tools, list)
    groups = Counter(
        str(item["module"]).split(".")[1]
        for item in tools
        if isinstance(item, dict) and isinstance(item.get("module"), str)
    )

    @mcp.tool(
        title="Hand runtime status",
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    def hand_status() -> dict[str, object]:
        """Report process-level MCP diagnostics, not tool execution readiness."""
        return {
            "hand": hand,
            "transport": "diagnostic_only",
            "authorization": "not_configured",
            "protected_execution": "disabled",
            "declared_legacy_tool_count": declared_count,
            "registered_diagnostic_tools": 2,
            "ready": False,
        }

    @mcp.tool(
        title="Hand source tool summary",
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    def hand_source_summary() -> dict[str, object]:
        """Summarize copied source declarations without activating them."""
        return {
            "hand": hand,
            "declared_legacy_tool_count": declared_count,
            "source_modules": dict(sorted(groups.items())),
            "source_declarations_are_callable": False,
        }

    return mcp

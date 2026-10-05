from __future__ import annotations

import unittest

import mcp_types as mt
from fastmcp.tools.base import Tool

from bridge.access_middleware import AccessSessionMiddleware, _with_session_parameter


def tool(name: str, *, read_only: bool | None) -> Tool:
    annotations = (
        None
        if read_only is None
        else mt.ToolAnnotations(readOnlyHint=read_only)
    )
    return Tool(
        name=name,
        parameters={"type": "object", "properties": {}},
        annotations=annotations,
    )


class AccessMiddlewareClassificationTest(unittest.TestCase):
    def middleware(self, surface: str) -> AccessSessionMiddleware:
        return AccessSessionMiddleware(surface=surface, client=object())  # type: ignore[arg-type]

    def test_read_only_annotations_are_allowed_on_provider_surfaces(self) -> None:
        middleware = self.middleware("github")
        self.assertTrue(
            middleware._is_base_read_only(
                "github_agent_get_file",
                tool("github_agent_get_file", read_only=True),
            )
        )
        self.assertFalse(
            middleware._is_base_read_only(
                "github_agent_put_file",
                tool("github_agent_put_file", read_only=False),
            )
        )

    def test_unknown_tool_defaults_to_full_access(self) -> None:
        middleware = self.middleware("terminal")
        self.assertFalse(
            middleware._is_base_read_only(
                "future_tool",
                tool("future_tool", read_only=None),
            )
        )

    def test_root_safe_catalog_tools_remain_read_only(self) -> None:
        middleware = self.middleware("root")
        self.assertTrue(
            middleware._is_base_read_only(
                "bridge_tools",
                tool("bridge_tools", read_only=None),
            )
        )
        self.assertFalse(
            middleware._is_base_read_only(
                "bridge_call",
                tool("bridge_call", read_only=None),
            )
        )

    def test_session_parameter_is_injected_but_not_marked_required(self) -> None:
        original = tool("terminal_status", read_only=True)
        enriched = _with_session_parameter(original)
        properties = enriched.parameters["properties"]
        self.assertIn("session_id", properties)
        self.assertNotIn("required", enriched.parameters)


if __name__ == "__main__":
    unittest.main()

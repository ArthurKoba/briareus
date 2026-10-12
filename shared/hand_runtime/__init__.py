"""Small public building blocks for independently deployed MCP Hands."""

from ._catalog import discover_source_tools, source_capabilities
from ._closed import create_closed_hand_app

__all__ = ["create_closed_hand_app", "discover_source_tools", "source_capabilities"]

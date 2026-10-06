from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from common.models import JsonObject

from .browser import BrowserManager


def register_browser_tools(
    mcp: FastMCP,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    *,
    browser: BrowserManager,
) -> None:
    @mcp.tool(title="Browser diagnostics", annotations=read_annotations)
    async def browser_diagnostics() -> JsonObject:
        """Run a bounded Chromium executable/headless probe and return stderr/stdout tails."""
        return await browser.diagnostics()

    @mcp.tool(title="Browser status", annotations=read_annotations)
    async def browser_status() -> JsonObject:
        """Start the persistent Chromium profile if needed and report browser/page status."""
        return await browser.status()

    @mcp.tool(title="Browser restart", annotations=write_annotations)
    async def browser_restart() -> JsonObject:
        """Restart Chromium while preserving profile, cookies, storage and dev extensions."""
        return await browser.restart()

    @mcp.tool(title="Browser pages", annotations=read_annotations)
    async def browser_pages() -> JsonObject:
        """List open browser pages/tabs in the persistent browser context."""
        return await browser.pages()

    @mcp.tool(title="Browser open", annotations=write_annotations)
    async def browser_open(url: str, page_id: str = "") -> JsonObject:
        """Open a URL in a new page, or navigate an existing page_id."""
        return await browser.open(url, page_id)

    @mcp.tool(title="Browser set theme", annotations=write_annotations)
    async def browser_set_theme(color_scheme: str) -> JsonObject:
        """Set persistent browser color scheme: dark, light, or system."""
        return await browser.set_color_scheme(color_scheme)

    @mcp.tool(title="Browser remote debug target", annotations=read_annotations)
    async def browser_debug_target(page_id: str) -> JsonObject:
        """Resolve the CDP target for one application page without exposing the raw debug port."""
        return await browser.debug_target(page_id)

    @mcp.tool(title="Browser set viewport", annotations=write_annotations)
    async def browser_set_viewport(page_id: str, width: int, height: int) -> JsonObject:
        """Set one browser page viewport and return the effective measured viewport."""
        return await browser.set_viewport(page_id, width, height)

    @mcp.tool(title="Browser set page label", annotations=write_annotations)
    async def browser_set_page_label(page_id: str, label: str) -> JsonObject:
        """Assign or clear a short human-readable label for one browser tab."""
        return await browser.set_page_label(page_id, label)

    @mcp.tool(title="Browser snapshot", annotations=read_annotations)
    async def browser_snapshot(
        page_id: str,
        max_text_chars: int | None = None,
        max_elements: int | None = None,
    ) -> JsonObject:
        """
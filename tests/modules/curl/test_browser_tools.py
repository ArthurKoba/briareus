from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from modules.curl.browser import BrowserError, BrowserManager
from modules.curl.browser_tools import register_browser_tools


class FakeBrowser:
    async def diagnostics(self):
        return {"probe_exit_code": 0, "probe_stdout": "probe-ok", "probe_stderr": ""}

    async def status(self):
        return {"running": True, "page_count": 0, "pages": []}

    async def pages(self):
        return {"count": 0, "pages": []}

    async def open(self, url, page_id=""):
        return {"page_id": page_id or "page-1", "url": url, "title": "Example"}

    async def set_page_label(self, page_id, label):
        return {"page_id": page_id, "label": label}

    async def snapshot(self, page_id, *, max_text_chars=None, max_elements=None):
        return {"page_id": page_id, "text": "hello", "elements": []}

    async def click(self, page_id, ref):
        return {"page_id": page_id, "ref": ref}

    async def fill(self, page_id, ref, value, *, press_enter):
        return {"page_id": page_id, "ref": ref, "filled": bool(value), "enter": press_enter}

    async def press(self, page_id, ref, key):
        return {"page_id": page_id, "ref": ref, "key": key}

    async def select_option(self, page_id, ref, value):
        return {"page_id": page_id, "selected": [value]}

    async def upload(self, page_id, ref, workspace_path):
        return {"page_id": page_id, "workspace_path": workspace_path}

    async def download(self, page_id, ref, workspace_path, *, overwrite):
        return {"page_id": page_id, "path": workspace_path, "overwrite": overwrite}

    async def screenshot(self, page_id, workspace_path, *, full_page, overwrite):
        return {
            "page_id": page_id,
            "path": workspace_path,
            "full_page": full_page,
            "overwrite": overwrite,
        }

    async def wait(self, page_id, *, state, timeout_seconds):
        return {"page_id": page_id, "state": state, "timeout": timeout_seconds}

    async def back(self, page_id):
        return {"page_id": page_id}

    async def reload(self, page_id):
        return {"page_id": page_id}

    async def close_page(self, page_id):
        return {"page_id": page_id, "closed": True}


@pytest.mark.asyncio
async def test_browser_tools_publish_compact_stateful_surface() -> None:
    mcp = FastMCP("browser-test")
    read = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    write = ToolAnnotations(read_only_hint=False, open_world_hint=True)
    register_browser_tools(mcp, read, write, browser=FakeBrowser())  # type: ignore[arg-type]

    async with Client(mcp) as client:
        tools = {tool.name for tool in await client.list_tools()}

    assert tools == {
        "browser_diagnostics",
        "browser_status",
        "browser_pages",
        "browser_open",
        "browser_set_page_label",
        "browser_snapshot",
        "browser_click",
        "browser_fill",
        "browser_press",
        "browser_select_option",
        "browser_upload",
        "browser_download",
        "browser_screenshot",
        "browser_wait",
        "browser_back",
        "browser_reload",
        "browser_close_page",
    }


def test_browser_rejects_non_http_urls() -> None:
    with pytest.raises(BrowserError, match="absolute http"):
        BrowserManager._url("file:///etc/passwd")
    with pytest.raises(BrowserError, match="absolute http"):
        BrowserManager._url("javascript:alert(1)")
    assert BrowserManager._url("https://example.com/path") == "https://example.com/path"


def test_browser_runtime_uses_private_remote_debugging_endpoint() -> None:
    source = Path("src/modules/curl/browser.py").read_text()
    assert '"--no-sandbox"' in source
    assert '_REMOTE_DEBUGGING_HOST = "127.0.0.1"' in source
    assert '_REMOTE_DEBUGGING_PORT = 9222' in source
    assert 'f"--remote-debugging-address={_REMOTE_DEBUGGING_HOST}"' in source
    assert 'f"--remote-debugging-port={_REMOTE_DEBUGGING_PORT}"' in source

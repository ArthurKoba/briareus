from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from modules.web.browser import BrowserError, BrowserManager
from modules.web.browser_tools import register_browser_tools


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
    source = Path("src/modules/web/browser.py").read_text()
    assert '"--no-sandbox"' in source
    assert '_REMOTE_DEBUGGING_HOST = "127.0.0.1"' in source
    assert '_REMOTE_DEBUGGING_PORT = 9222' in source
    assert 'f"--remote-debugging-address={_REMOTE_DEBUGGING_HOST}"' in source
    assert 'f"--remote-debugging-port={_REMOTE_DEBUGGING_PORT}"' in source
    assert 'playwright.chromium.connect_over_cdp(' in source
    assert 'asyncio.create_subprocess_exec(' in source
    assert 'launch_persistent_context(' not in source
    assert 'command.append("--headless=new")' in source
    assert 'command.append(f"--lang={self.locale}")' in source
    assert 'command.append(f"--accept-lang={self.accept_language}")' in source
    assert '"Xvfb"' in source
    assert "_terminate_display_process" in source


def test_browser_headful_identity_configuration(tmp_path: Path) -> None:
    from modules.files.workspace_store import WorkspaceFileStore

    browser = BrowserManager(
        workspace=WorkspaceFileStore(tmp_path / "workspace"),
        profile_dir=tmp_path / "profile",
        executable_path="/usr/bin/chromium",
        headless=False,
        timeout_ms=30_000,
        viewport_width=1440,
        viewport_height=900,
        max_snapshot_text_chars=30_000,
        max_snapshot_elements=250,
        locale="ru-RU",
        accept_language="ru-RU,ru,en-US,en",
        display=":99",
        color_depth=24,
        xvfb_enabled=True,
        timezone="Europe/Moscow",
        posix_locale="ru_RU.UTF-8",
    )

    command = browser._browser_command()
    process_command = browser._browser_process_command()

    assert "--headless=new" not in command
    assert "--lang=ru-RU" in command
    assert "--accept-lang=ru-RU,ru,en-US,en" in command
    assert "--window-size=1440,900" in command
    assert process_command[:5] == [
        "/usr/bin/env",
        "DISPLAY=:99",
        "TZ=Europe/Moscow",
        "LANG=ru_RU.UTF-8",
        "LC_ALL=ru_RU.UTF-8",
    ]
    assert browser.display == ":99"
    assert browser.timezone == "Europe/Moscow"
    assert browser.posix_locale == "ru_RU.UTF-8"


def test_browser_timezone_blank_env_falls_back_to_moscow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from common.settings import BrowserSettings

    monkeypatch.setenv("TZ", "")
    monkeypatch.delenv("BROWSER_TIMEZONE", raising=False)
    settings = BrowserSettings()

    assert settings.timezone == "Europe/Moscow"


def test_browser_specific_environment_aliases_take_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from common.settings import BrowserSettings

    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setenv("BROWSER_TIMEZONE", "Europe/Moscow")
    monkeypatch.setenv("BROWSER_DISPLAY", ":99")
    settings = BrowserSettings()

    assert settings.timezone == "Europe/Moscow"
    assert settings.display == ":99"

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from modules.curl.browser import BrowserError, BrowserManager
from modules.files.workspace_store import WorkspaceFileStore


def _browser(tmp_path: Path) -> BrowserManager:
    return BrowserManager(
        workspace=WorkspaceFileStore(tmp_path / "workspace"),
        profile_dir=tmp_path / "profile",
        executable_path="/usr/bin/chromium",
        headless=True,
        timeout_ms=30_000,
        viewport_width=1440,
        viewport_height=900,
        max_snapshot_text_chars=30_000,
        max_snapshot_elements=250,
    )


@pytest.mark.asyncio
async def test_operator_sessions_share_control_with_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = _browser(tmp_path)

    class FakeResponse:
        status = 200

    class FakePage:
        url = ""

        async def goto(self, url: str, *, wait_until: str) -> FakeResponse:
            del wait_until
            self.url = url
            return FakeResponse()

    class FakeContext:
        async def new_page(self) -> FakePage:
            return FakePage()

    async def fake_started() -> Any:
        return cast(Any, FakeContext())

    async def fake_summary(page_id: str, page: Any) -> dict[str, object]:
        return {
            "page_id": page_id,
            "label": "",
            "page_agent_access": True,
            "agent_access": True,
            "url": page.url,
            "title": "",
        }

    async def fake_operator_page_items() -> list[dict[str, object]]:
        return [
            {
                "page_id": "page-one",
                "label": "",
                "page_agent_access": True,
                "agent_access": True,
                "url": "https://example.test/",
                "title": "Example",
            }
        ]

    monkeypatch.setattr(browser, "_ensure_started", fake_started)
    monkeypatch.setattr(browser, "_summary", fake_summary)
    monkeypatch.setattr(browser, "_operator_page_items", fake_operator_page_items)

    first = await browser.operator_acquire()
    second = await browser.operator_acquire()

    assert first["owner_token"] != second["owner_token"]
    first_state = await browser.operator_state(str(first["owner_token"]))
    second_state = await browser.operator_state(str(second["owner_token"]))
    assert first_state["control"] == "shared"
    assert first_state["operator_count"] == 2
    assert second_state["operator_count"] == 2

    opened = await browser.open("https://example.test/agent")
    assert opened["url"] == "https://example.test/agent"
    assert opened["http_status"] == 200

    await browser.operator_release(str(first["owner_token"]))
    assert (await browser.operator_state(str(second["owner_token"])))["operator_count"] == 1


@pytest.mark.asyncio
async def test_page_policy_labels_and_redacts_locked_tabs(tmp_path: Path) -> None:
    browser = _browser(tmp_path)

    class FakePage:
        url = "https://secret.example/private"

        def is_closed(self) -> bool:
            return False

        async def title(self) -> str:
            return "Private Area"

    class FakeContext:
        def __init__(self, page: FakePage) -> None:
            self.pages = [page]

    page = FakePage()
    page_id = browser._register_page(cast(Any, page))

    async def fake_started() -> Any:
        return cast(Any, FakeContext(page))

    browser._ensure_started = fake_started  # type: ignore[method-assign]
    browser._page_labels[page_id] = "Banking"
    browser._page_agent_access[page_id] = False

    state = await browser.status()
    item = cast(dict[str, object], cast(list[object], state["pages"])[0])
    assert item == {
        "page_id": page_id,
        "label": "Banking",
        "page_agent_access": False,
        "agent_access": False,
        "locked": True,
        "developer_locked": False,
        "url": "",
        "title": "",
    }
    with pytest.raises(BrowserError, match="locked by operator"):
        browser._require_agent_access(page_id)


@pytest.mark.asyncio
async def test_operator_master_switch_blocks_agent_but_not_operator_state(tmp_path: Path) -> None:
    browser = _browser(tmp_path)

    async def fake_operator_page_items() -> list[dict[str, object]]:
        return [
            {
                "page_id": "page-one",
                "label": "Admin",
                "page_agent_access": True,
                "agent_access": False,
                "url": "https://admin.example/",
                "title": "Admin",
            }
        ]

    browser._operator_pages["owner"] = "page-one"
    browser._operator_page_items = fake_operator_page_items  # type: ignore[method-assign]

    result = await browser.operator_set_agent_access("owner", False)
    assert result["agent_access_enabled"] is False
    with pytest.raises(BrowserError, match="agent access is disabled"):
        browser._require_agent_access("page-one")

    state = await browser.operator_state("owner")
    assert state["agent_access_enabled"] is False
    assert cast(list[object], state["pages"])[0] == {
        "page_id": "page-one",
        "label": "Admin",
        "page_agent_access": True,
        "agent_access": False,
        "url": "https://admin.example/",
        "title": "Admin",
    }


@pytest.mark.asyncio
async def test_developer_mode_requires_separate_agent_permission(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""

    with pytest.raises(BrowserError, match="developer mode is disabled"):
        browser._developer_url("chrome://extensions", agent=False)

    await browser.operator_set_developer_mode("owner", True)
    assert browser._developer_url("chrome://settings", agent=False) == "chrome://settings"
    with pytest.raises(BrowserError, match="developer access is disabled"):
        browser._developer_url("chrome://extensions", agent=True)

    await browser.operator_set_agent_developer_access("owner", True)
    assert browser._developer_url("chrome://extensions", agent=True) == "chrome://extensions"

    reloaded = _browser(tmp_path)
    assert reloaded._developer_mode_enabled is True
    assert reloaded._agent_developer_access_enabled is True


@pytest.mark.asyncio
async def test_developer_page_is_redacted_when_agent_dev_access_revoked(tmp_path: Path) -> None:
    browser = _browser(tmp_path)

    class FakePage:
        url = "chrome://extensions/"

        def is_closed(self) -> bool:
            return False

        async def title(self) -> str:
            return "Extensions"

    class FakeContext:
        def __init__(self, page: FakePage) -> None:
            self.pages = [page]

    page = FakePage()
    page_id = browser._register_page(cast(Any, page))

    async def fake_started() -> Any:
        return cast(Any, FakeContext(page))

    browser._ensure_started = fake_started  # type: ignore[method-assign]
    browser._developer_mode_enabled = True
    browser._agent_developer_access_enabled = False

    state = await browser.status()
    item = cast(dict[str, object], cast(list[object], state["pages"])[0])
    assert item["page_id"] == page_id
    assert item["developer_locked"] is True
    assert item["url"] == ""
    assert item["title"] == ""
    with pytest.raises(BrowserError, match="developer access is disabled"):
        await browser._agent_page(page_id)


@pytest.mark.asyncio
async def test_unpacked_extension_requires_workspace_manifest(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._developer_mode_enabled = True
    browser._agent_developer_access_enabled = True
    extension = tmp_path / "workspace" / "extensions" / "demo"
    extension.mkdir(parents=True)

    with pytest.raises(BrowserError, match="manifest not found"):
        await browser.extension_load_unpacked("extensions/demo")

    (extension / "manifest.json").write_text('{"manifest_version":3,"name":"Demo","version":"1"}')

    async def fake_command(method: str, params=None):
        assert method == "Extensions.loadUnpacked"
        assert params and params["path"] == str(extension.resolve())
        return {"id": "abcdefghijklmnop"}

    browser._extension_command = fake_command  # type: ignore[method-assign]
    result = await browser.extension_load_unpacked("extensions/demo")
    assert result["id"] == "abcdefghijklmnop"
    assert result["workspace_path"] == "extensions/demo"


@pytest.mark.asyncio
async def test_master_agent_access_persists_in_browser_profile(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""

    await browser.operator_set_agent_access("owner", False)

    reloaded = _browser(tmp_path)
    assert reloaded._agent_access_enabled is False


@pytest.mark.asyncio
async def test_wrong_operator_token_cannot_control_browser(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""

    with pytest.raises(BrowserError, match="not active"):
        await browser.operator_state("other")

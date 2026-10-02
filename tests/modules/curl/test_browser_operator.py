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


def test_operator_allows_only_bounded_chromium_internal_pages() -> None:
    assert BrowserManager._operator_url("chrome://extensions/") == "chrome://extensions/"
    assert BrowserManager._operator_url("chrome://settings/") == "chrome://settings/"
    assert BrowserManager._operator_url("https://example.com/") == "https://example.com/"
    with pytest.raises(BrowserError, match="absolute http"):
        BrowserManager._operator_url("chrome://history/")


@pytest.mark.asyncio
async def test_operator_opens_devtools_for_selected_tab(tmp_path: Path) -> None:
    browser = _browser(tmp_path)

    class FakePage:
        url = "https://example.test/"

        def is_closed(self) -> bool:
            return False

        async def title(self) -> str:
            return "Example"

    class FakeSession:
        def __init__(self) -> None:
            self.detached = False
            self.calls: list[tuple[str, object | None]] = []

        async def send(self, method: str, params: object | None = None):
            self.calls.append((method, params))
            if method == "Target.getTargetInfo":
                return {"targetInfo": {"targetId": "target-page"}}
            if method == "Target.openDevTools":
                return {"targetId": "target-devtools"}
            return {}

        async def detach(self) -> None:
            self.detached = True

    page = FakePage()
    session = FakeSession()

    class FakeContext:
        def __init__(self) -> None:
            self.pages = [page]

        async def new_cdp_session(self, _page: object) -> FakeSession:
            return session

    page_id = browser._register_page(cast(Any, page))
    browser._operator_pages["owner"] = page_id

    async def fake_started() -> Any:
        return cast(Any, FakeContext())

    browser._ensure_started = fake_started  # type: ignore[method-assign]
    result = await browser.operator_open_devtools("owner", page_id)

    assert result["opened_devtools"] is True
    assert result["devtools_target_id"] == "target-devtools"
    assert result["page_id"] == page_id
    assert session.detached is True
    assert (
        "Target.openDevTools",
        {"targetId": "target-page", "panelId": "elements"},
    ) in session.calls


@pytest.mark.asyncio
async def test_operator_clean_browser_erases_profile_and_blocks_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = _browser(tmp_path)
    browser.profile_dir.mkdir(parents=True, exist_ok=True)
    (browser.profile_dir / "Cookies").write_text("secret")
    cache = tmp_path / "cache"
    config = tmp_path / "config"
    crash = tmp_path / "crash"
    for directory in (cache, config, crash):
        directory.mkdir()
        (directory / "state").write_text("secret")
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("BREAKPAD_DUMP_LOCATION", str(crash))

    class OldContext:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class OldPlaywright:
        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    class BlankPage:
        url = "about:blank"

        def is_closed(self) -> bool:
            return False

        async def title(self) -> str:
            return ""

    class NewContext:
        def __init__(self, page: BlankPage) -> None:
            self.pages = [page]

    old_context = OldContext()
    old_playwright = OldPlaywright()
    browser._context = cast(Any, old_context)
    browser._playwright = cast(Any, old_playwright)
    browser._operator_pages["owner"] = "old-page"

    async def fake_start_locked() -> None:
        blank = BlankPage()
        browser._context = cast(Any, NewContext(blank))
        browser._playwright = None
        browser._register_page(cast(Any, blank))

    browser._start_locked = fake_start_locked  # type: ignore[method-assign]
    result = await browser.operator_clean_browser("owner")

    assert old_context.closed is True
    assert old_playwright.stopped is True
    assert result["cleaned"] is True
    assert result["agent_access_enabled"] is False
    assert result["page_count"] == 1
    assert not (browser.profile_dir / "Cookies").exists()
    assert not cache.exists()
    assert not config.exists()
    assert not crash.exists()
    policy = browser._policy_path.read_text()
    assert '"agent_access_enabled":false' in policy
    with pytest.raises(BrowserError, match="agent access is disabled"):
        browser._require_agent_access()

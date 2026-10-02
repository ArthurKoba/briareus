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
        return {"page_id": page_id, "url": page.url}

    async def fake_pages() -> dict[str, object]:
        return {
            "count": 1,
            "pages": [
                {
                    "page_id": "page-one",
                    "url": "https://example.test/",
                    "title": "Example",
                }
            ],
        }

    monkeypatch.setattr(browser, "_ensure_started", fake_started)
    monkeypatch.setattr(browser, "pages", fake_pages)
    monkeypatch.setattr(browser, "_summary", fake_summary)

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
async def test_wrong_operator_token_cannot_control_browser(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._operator_pages["owner"] = ""

    with pytest.raises(BrowserError, match="not active"):
        await browser.operator_state("other")

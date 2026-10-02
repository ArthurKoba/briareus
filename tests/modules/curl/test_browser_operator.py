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
async def test_human_operator_lock_blocks_agent_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = _browser(tmp_path)

    async def fake_started() -> Any:
        return cast(Any, object())

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

    owner = await browser.operator_acquire()
    assert owner["selected_page_id"] == "page-one"

    with pytest.raises(BrowserError, match="human control"):
        await browser.open("https://example.test/other")

    with pytest.raises(BrowserError, match="already under human control"):
        await browser.operator_acquire()

    state = await browser.operator_state(str(owner["owner_token"]))
    assert state["control"] == "human"
    assert state["page_count"] == 1

    await browser.operator_release(str(owner["owner_token"]))
    browser._require_agent_control()


@pytest.mark.asyncio
async def test_wrong_operator_token_cannot_control_browser(tmp_path: Path) -> None:
    browser = _browser(tmp_path)
    browser._operator_token = "owner"

    with pytest.raises(BrowserError, match="not active"):
        await browser.operator_state("other")

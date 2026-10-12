from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from modules.web.browser import BrowserError, BrowserManager


class FakePage:
    def __init__(self) -> None:
        self.closed = False
        self.url = "about:blank"

    def is_closed(self) -> bool:
        return self.closed

    async def goto(self, url: str, *, wait_until: str) -> SimpleNamespace:
        del wait_until
        self.url = url
        return SimpleNamespace(status=200)

    async def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self) -> None:
        self.pages: list[FakePage] = []

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page


class BrowserTabBudgetTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(self, context: FakeContext) -> BrowserManager:
        manager = object.__new__(BrowserManager)
        manager.max_agent_tabs = 2
        manager.max_tabs = 3
        manager._tab_create_lock = asyncio.Lock()
        manager._agent_open_semaphore = asyncio.Semaphore(2)
        manager._agent_page_ids = set()
        manager._pages = {}
        manager._page_ids = {}
        manager._page_labels = {}
        manager._page_agent_access = {}
        manager._operator_pages = {"operator": ""}
        manager._agent_access_enabled = True
        manager._operator_lock = asyncio.Lock()
        manager._context = context
        manager._ensure_started = AsyncMock(return_value=context)
        manager._summary = AsyncMock(side_effect=lambda page_id, _page: {"page_id": page_id})
        manager._apply_color_scheme = AsyncMock()
        return manager

    async def test_agent_limit_rejects_new_tabs_but_allows_reuse(self) -> None:
        context = FakeContext()
        manager = self.make_manager(context)
        first = await manager.open("https://example.com")
        await manager.open("https://example.org")
        with self.assertRaisesRegex(BrowserError, "agent tab limit reached"):
            await manager.open("https://example.net")
        self.assertEqual(len(context.pages), 2)
        reused = await manager.open("https://example.edu", first["page_id"])
        self.assertEqual(reused["http_status"], 200)
        self.assertEqual(len(context.pages), 2)

    async def test_closing_a_tab_restores_capacity(self) -> None:
        context = FakeContext()
        manager = self.make_manager(context)
        first = await manager.open("https://example.com")
        await manager.open("https://example.org")
        await manager.close_page(first["page_id"])
        await manager.open("https://example.net")
        self.assertEqual(manager._live_agent_tab_count(), 2)

    async def test_total_limit_includes_operator_tabs_without_closing_them(self) -> None:
        context = FakeContext()
        manager = self.make_manager(context)
        existing = await context.new_page()
        await context.new_page()
        await manager.open("https://example.com")
        with self.assertRaisesRegex(BrowserError, "browser tab limit reached"):
            await manager.operator_new_page("operator")
        self.assertFalse(existing.closed)
        self.assertEqual(len(context.pages), 3)

    async def test_new_direct_cdp_overflow_tab_is_rejected(self) -> None:
        context = FakeContext()
        manager = self.make_manager(context)
        existing = [await context.new_page() for _ in range(3)]
        overflow = await context.new_page()
        manager._on_context_page(overflow)
        await asyncio.sleep(0)
        self.assertTrue(overflow.closed)
        self.assertTrue(all(not page.closed for page in existing))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Locator, Page, Playwright

from common.models import JsonObject, JsonValue
from modules.files.workspace_store import WorkspaceFileStore


class BrowserError(RuntimeError):
    """Browser operation failed."""


class BrowserManager:
    def __init__(
        self,
        *,
        workspace: WorkspaceFileStore,
        profile_dir: Path,
        executable_path: str,
        headless: bool,
        timeout_ms: int,
        viewport_width: int,
        viewport_height: int,
        max_snapshot_text_chars: int,
        max_snapshot_elements: int,
    ) -> None:
        self.workspace = workspace
        self.profile_dir = profile_dir.resolve(strict=False)
        self.executable_path = executable_path
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.max_snapshot_text_chars = max_snapshot_text_chars
        self.max_snapshot_elements = max_snapshot_elements
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._pages: dict[str, Page] = {}
        self._page_ids: dict[int, str] = {}
        self._start_lock = asyncio.Lock()

    async def _start_locked(self) -> None:
        if self._context is not None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.ensure()
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (self.profile_dir / lock_name).unlink(missing_ok=True)
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                executable_path=self.executable_path,
                headless=self.headless,
                accept_downloads=True,
                args=["--no-sandbox"],
                viewport={"width": self.viewport_width, "height": self.viewport_height},
            )
        except Exception:
            await playwright.stop()
            raise
        context.set_default_timeout(self.timeout_ms)
        context.set_default_navigation_timeout(self.timeout_ms)
        self._playwright = playwright
        self._context = context
        for page in context.pages:
            self._register_page(page)

    async def _ensure_started(self) -> BrowserContext:
        if self._context is None:
            async with self._start_lock:
                await self._start_locked()
        if self._context is None:
            raise BrowserError("browser failed to start")
        return self._context

    def _register_page(self, page: Page) -> str:
        key = id(page)
        existing = self._page_ids.get(key)
        if existing:
            return existing
        page_id = f"page-{uuid.uuid4().hex[:10]}"
        self._pages[page_id] = page
        self._page_ids[key] = page_id
        return page_id

    def _forget_page(self, page_id: str) -> None:
        page = self._pages.pop(page_id, None)
        if page is not None:
            self._page_ids.pop(id(page), None)

    async def _page(self, page_id: str) -> Page:
        await self._ensure_started()
        page = self._pages.get(page_id)
        if page is None or page.is_closed():
            self._forget_page(page_id)
            raise BrowserError(f"browser page not found: {page_id}")
        return page

    @staticmethod
    def _url(value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BrowserError("browser URL must be absolute http(s)")
        return value

    async def _summary(self, page_id: str, page: Page) -> JsonObject:
        return {
            "page_id": page_id,
            "url": page.url,
            "title": await page.title(),
        }

    async def status(self) -> JsonObject:
        context = await self._ensure_started()
        pages: list[JsonValue] = []
        for page in list(context.pages):
            if page.is_closed():
                continue
            page_id = self._register_page(page)
            pages.append(await self._summary(page_id, page))
        return {
            "running": True,
            "headless": self.headless,
            "browser": "chromium",
            "executable_path": self.executable_path,
            "profile_dir": str(self.profile_dir),
            "page_count": len(pages),
            "pages": pages,
        }

    async def pages(self) -> JsonObject:
        status = await self.status()
        raw_pages = status.get("pages")
        pages = raw_pages if isinstance(raw_pages, list) else []
        return {"count": len(pages), "pages": pages}

    async def open(self, url: str, page_id: str = "") -> JsonObject:
        context = await self._ensure_started()
        target_url = self._url(url)
        if page_id:
            page = await self._page(page_id)
        else:
            page = await context.new_page()
            page_id = self._register_page(page)
        response = await page.goto(target_url, wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result["http_status"] = response.status if response is not None else None
        return result

    async def snapshot(
        self,
        page_id: str,
        *,
        max_text_chars: int | None = None,
        max_elements: int | None = None,
    ) -> JsonObject:
        page = await self._page(page_id)
        text_limit = min(
            max_text_chars or self.max_snapshot_text_chars,
            self.max_snapshot_text_chars,
        )
        element_limit = min(
            max_elements or self.max_snapshot_elements,
            self.max_snapshot_elements,
        )
        if text_limit <= 0 or element_limit <= 0:
            raise BrowserError("snapshot limits must be positive")
        text = await page.locator("body").inner_text(timeout=self.timeout_ms)
        text_truncated = len(text) > text_limit
        if text_truncated:
            text = text[:text_limit]
        raw_elements: object = await page.evaluate(
            """
            (limit) => {
              document.querySelectorAll('[data-koba-ref]').forEach(
                (el) => el.removeAttribute('data-koba-ref')
              );
              const selector = [
                'a[href]', 'button', 'input', 'textarea', 'select', 'summary',
                '[role="button"]', '[role="link"]', '[role="checkbox"]',
                '[role="radio"]', '[role="tab"]', '[contenteditable="true"]'
              ].join(',');
              const nodes = Array.from(document.querySelectorAll(selector))
                .filter((el) => {
                  if (el.matches('input[type="file"]')) return true;
                  const style = window.getComputedStyle(el);
                  return style.visibility !== 'hidden' && style.display !== 'none' &&
                    el.getClientRects().length > 0;
                })
                .slice(0, limit);
              return nodes.map((el, index) => {
                const ref = `e${index + 1}`;
                el.setAttribute('data-koba-ref', ref);
                const text = (el.innerText || el.textContent || '').trim();
                const inputType = (el.getAttribute('type') || '').toLowerCase();
                const value = inputType === 'password'
                  ? '<redacted>'
                  : ('value' in el ? String(el.value || '') : '');
                return {
                  ref,
                  tag: el.tagName.toLowerCase(),
                  role: el.getAttribute('role') || '',
                  type: el.getAttribute('type') || '',
                  name: el.getAttribute('aria-label') || el.getAttribute('title') ||
                    el.getAttribute('placeholder') || text.slice(0, 240),
                  href: el.getAttribute('href') || '',
                  value: value.slice(0, 240),
                  disabled: Boolean(el.disabled),
                };
              });
            }
            """,
            element_limit,
        )
        if not isinstance(raw_elements, list):
            raise BrowserError("browser snapshot returned invalid element data")
        elements = cast(list[JsonValue], raw_elements)
        summary = await self._summary(page_id, page)
        summary.update(
            {
                "text": text,
                "text_truncated": text_truncated,
                "elements": elements,
                "element_count": len(elements),
            }
        )
        return summary

    async def _locator(self, page_id: str, ref: str) -> tuple[Page, Locator]:
        page = await self._page(page_id)
        ref = ref.strip()
        if not ref:
            raise BrowserError("element ref is required")
        locator = page.locator(f'[data-koba-ref="{ref}"]')
        if await locator.count() != 1:
            raise BrowserError(
                f"element ref {ref!r} is stale or ambiguous; take a new browser_snapshot"
            )
        return page, locator

    async def click(self, page_id: str, ref: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        await locator.click()
        await page.wait_for_timeout(150)
        return await self._summary(page_id, page)

    async def fill(self, page_id: str, ref: str, value: str, *, press_enter: bool) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        await locator.fill(value)
        if press_enter:
            await locator.press("Enter")
            await page.wait_for_timeout(150)
        return await self._summary(page_id, page)

    async def press(self, page_id: str, ref: str, key: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        await locator.press(key)
        await page.wait_for_timeout(100)
        return await self._summary(page_id, page)

    async def select_option(self, page_id: str, ref: str, value: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        selected = await locator.select_option(value=value)
        result = await self._summary(page_id, page)
        result["selected"] = cast(list[JsonValue], selected)
        return result

    async def upload(self, page_id: str, ref: str, workspace_path: str) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        source = self.workspace.path_for(workspace_path)
        if not source.is_file():
            raise BrowserError(f"upload path is not a file: {workspace_path}")
        await locator.set_input_files(str(source))
        result = await self._summary(page_id, page)
        result["workspace_path"] = self.workspace.relative(source)
        return result

    async def download(
        self,
        page_id: str,
        ref: str,
        workspace_path: str,
        *,
        overwrite: bool,
    ) -> JsonObject:
        page, locator = await self._locator(page_id, ref)
        target = self.workspace.target_path(workspace_path)
        if target.exists() and not overwrite:
            raise BrowserError(f"destination already exists: {workspace_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        async with page.expect_download() as download_info:
            await locator.click()
        download = await download_info.value
        await download.save_as(str(target))
        result = self.workspace.info(self.workspace.relative(target))
        result["suggested_filename"] = download.suggested_filename
        return result

    async def screenshot(
        self,
        page_id: str,
        workspace_path: str,
        *,
        full_page: bool,
        overwrite: bool,
    ) -> JsonObject:
        page = await self._page(page_id)
        target = self.workspace.target_path(workspace_path)
        if target.exists() and not overwrite:
            raise BrowserError(f"destination already exists: {workspace_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target), full_page=full_page)
        return self.workspace.info(self.workspace.relative(target))

    async def wait(
        self,
        page_id: str,
        *,
        state: str,
        timeout_seconds: float,
    ) -> JsonObject:
        page = await self._page(page_id)
        normalized = state.strip().casefold()
        if normalized not in {"load", "domcontentloaded", "networkidle"}:
            raise BrowserError("wait state must be load, domcontentloaded, or networkidle")
        if not 0 < timeout_seconds <= 120:
            raise BrowserError("timeout_seconds must be between 0 and 120")
        load_state = cast(
            Literal["load", "domcontentloaded", "networkidle"],
            normalized,
        )
        await page.wait_for_load_state(load_state, timeout=timeout_seconds * 1000)
        return await self._summary(page_id, page)

    async def back(self, page_id: str) -> JsonObject:
        page = await self._page(page_id)
        await page.go_back(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def reload(self, page_id: str) -> JsonObject:
        page = await self._page(page_id)
        response = await page.reload(wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result["http_status"] = response.status if response is not None else None
        return result

    async def close_page(self, page_id: str) -> JsonObject:
        page = await self._page(page_id)
        await page.close()
        self._forget_page(page_id)
        return {"page_id": page_id, "closed": True}

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, CDPSession, Locator, Page, Playwright

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
        self._reset_lock = asyncio.Lock()
        self._operator_lock = asyncio.Lock()
        self._operator_pages: dict[str, str] = {}
        self._policy_lock = asyncio.Lock()
        self._policy_path = self.profile_dir / "koba-browser-policy.json"
        self._agent_access_enabled = True
        self._page_labels: dict[str, str] = {}
        self._page_agent_access: dict[str, bool] = {}
        self._load_policy()

    def _load_policy(self) -> None:
        try:
            payload = json.loads(self._policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(payload, dict) and isinstance(payload.get("agent_access_enabled"), bool):
            self._agent_access_enabled = payload["agent_access_enabled"]

    def _persist_policy(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._policy_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"agent_access_enabled": self._agent_access_enabled},
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(self._policy_path)

    def _require_operator(self, owner_token: str) -> None:
        if not owner_token or owner_token not in self._operator_pages:
            raise BrowserError("browser operator session is not active")

    def _agent_access_allowed(self, page_id: str = "") -> bool:
        if not self._agent_access_enabled:
            return False
        return not (page_id and not self._page_agent_access.get(page_id, True))

    def _require_agent_access(self, page_id: str = "") -> None:
        if not self._agent_access_enabled:
            raise BrowserError("browser agent access is disabled by operator")
        if page_id and not self._page_agent_access.get(page_id, True):
            raise BrowserError(f"browser page is locked by operator: {page_id}")

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
        self._page_labels.pop(page_id, None)
        self._page_agent_access.pop(page_id, None)
        for owner_token, selected_page_id in list(self._operator_pages.items()):
            if selected_page_id == page_id:
                self._operator_pages[owner_token] = ""

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

    @classmethod
    def _operator_url(cls, value: str) -> str:
        value = value.strip()
        if value in {
            "chrome://extensions",
            "chrome://extensions/",
            "chrome://settings",
            "chrome://settings/",
            "chrome://version",
            "chrome://version/",
        }:
            return value
        return cls._url(value)

    async def _summary(self, page_id: str, page: Page) -> JsonObject:
        return {
            "page_id": page_id,
            "label": self._page_labels.get(page_id, ""),
            "page_agent_access": self._page_agent_access.get(page_id, True),
            "agent_access": self._agent_access_allowed(page_id),
            "url": page.url,
            "title": await page.title(),
        }

    async def _agent_summary(self, page_id: str, page: Page) -> JsonObject:
        if self._agent_access_allowed(page_id):
            return await self._summary(page_id, page)
        return {
            "page_id": page_id,
            "label": self._page_labels.get(page_id, ""),
            "page_agent_access": self._page_agent_access.get(page_id, True),
            "agent_access": False,
            "locked": True,
            "url": "",
            "title": "",
        }

    async def diagnostics(self) -> JsonObject:
        self.profile_dir.parent.mkdir(parents=True, exist_ok=True)

        async def run(*args: str) -> tuple[int, str, str]:
            process = await asyncio.create_subprocess_exec(
                self.executable_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
            except TimeoutError:
                process.kill()
                await process.wait()
                return -1, "", "timed out after 20s"
            return (
                int(process.returncode or 0),
                stdout.decode("utf-8", errors="replace")[-12000:],
                stderr.decode("utf-8", errors="replace")[-12000:],
            )

        version_code, version_stdout, version_stderr = await run("--version")
        with tempfile.TemporaryDirectory(
            prefix="browser-probe-",
            dir=self.profile_dir.parent,
        ) as temporary_profile:
            probe_code, probe_stdout, probe_stderr = await run(
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={temporary_profile}",
                "--dump-dom",
                "data:text/html,<title>KobaBrowserProbe</title><body>probe-ok</body>",
            )
        return {
            "executable_path": self.executable_path,
            "profile_dir": str(self.profile_dir),
            "version_exit_code": version_code,
            "version_stdout": version_stdout,
            "version_stderr": version_stderr,
            "probe_exit_code": probe_code,
            "probe_stdout": probe_stdout,
            "probe_stderr": probe_stderr,
        }

    async def status(self) -> JsonObject:
        context = await self._ensure_started()
        pages: list[JsonValue] = []
        for page in list(context.pages):
            if page.is_closed():
                continue
            page_id = self._register_page(page)
            pages.append(await self._agent_summary(page_id, page))
        return {
            "running": True,
            "agent_access_enabled": self._agent_access_enabled,
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
        self._require_agent_access(page_id)
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
        self._require_agent_access(page_id)
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
        self._require_agent_access(page_id)
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
        self._require_agent_access(page_id)
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
        self._require_agent_access(page_id)
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
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        await page.go_back(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def reload(self, page_id: str) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        response = await page.reload(wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result["http_status"] = response.status if response is not None else None
        return result

    async def close_page(self, page_id: str) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        await page.close()
        self._forget_page(page_id)
        return {"page_id": page_id, "closed": True}

    async def set_page_label(self, page_id: str, label: str) -> JsonObject:
        self._require_agent_access(page_id)
        page = await self._page(page_id)
        normalized = label.strip()
        if len(normalized) > 120:
            raise BrowserError("browser page label must be at most 120 characters")
        async with self._policy_lock:
            if normalized:
                self._page_labels[page_id] = normalized
            else:
                self._page_labels.pop(page_id, None)
        return await self._summary(page_id, page)

    async def operator_set_page_label(
        self, owner_token: str, page_id: str, label: str
    ) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        normalized = label.strip()
        if len(normalized) > 120:
            raise BrowserError("browser page label must be at most 120 characters")
        async with self._policy_lock:
            if normalized:
                self._page_labels[page_id] = normalized
            else:
                self._page_labels.pop(page_id, None)
        return await self._summary(page_id, page)

    async def operator_set_page_agent_access(
        self, owner_token: str, page_id: str, allowed: bool
    ) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        async with self._policy_lock:
            if allowed:
                self._page_agent_access.pop(page_id, None)
            else:
                self._page_agent_access[page_id] = False
        return await self._summary(page_id, page)

    async def operator_set_agent_access(
        self, owner_token: str, allowed: bool
    ) -> JsonObject:
        self._require_operator(owner_token)
        async with self._policy_lock:
            self._agent_access_enabled = allowed
            await asyncio.to_thread(self._persist_policy)
        return {"agent_access_enabled": self._agent_access_enabled}

    async def _operator_page_items(self) -> list[JsonValue]:
        context = await self._ensure_started()
        items: list[JsonValue] = []
        for page in list(context.pages):
            if page.is_closed():
                continue
            page_id = self._register_page(page)
            items.append(await self._summary(page_id, page))
        return items

    async def operator_acquire(self) -> JsonObject:
        await self._ensure_started()
        page_items = await self._operator_page_items()
        selected_page_id = (
            str(page_items[0].get("page_id") or "")
            if page_items and isinstance(page_items[0], dict)
            else ""
        )
        owner_token = uuid.uuid4().hex
        async with self._operator_lock:
            self._operator_pages[owner_token] = selected_page_id
        return {
            "owner_token": owner_token,
            "selected_page_id": selected_page_id,
        }

    async def operator_release(self, owner_token: str) -> None:
        async with self._operator_lock:
            self._operator_pages.pop(owner_token, None)

    async def operator_state(self, owner_token: str) -> JsonObject:
        self._require_operator(owner_token)
        page_items = await self._operator_page_items()
        valid_ids = {
            str(item.get("page_id"))
            for item in page_items
            if isinstance(item, dict) and item.get("page_id")
        }
        selected_page_id = self._operator_pages.get(owner_token, "")
        if selected_page_id not in valid_ids:
            selected_page_id = next(iter(valid_ids), "")
            async with self._operator_lock:
                if owner_token in self._operator_pages:
                    self._operator_pages[owner_token] = selected_page_id
        return {
            "control": "shared",
            "selected_page_id": selected_page_id,
            "pages": page_items,
            "page_count": len(page_items),
            "operator_count": len(self._operator_pages),
            "agent_access_enabled": self._agent_access_enabled,
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
        }

    async def operator_select_page(self, owner_token: str, page_id: str) -> None:
        self._require_operator(owner_token)
        await self._page(page_id)
        async with self._operator_lock:
            self._operator_pages[owner_token] = page_id

    async def operator_cdp_session(self, owner_token: str, page_id: str) -> tuple[Page, CDPSession]:
        self._require_operator(owner_token)
        context = await self._ensure_started()
        page = await self._page(page_id)
        return page, await context.new_cdp_session(page)

    async def operator_new_page(self, owner_token: str, url: str = "") -> JsonObject:
        self._require_operator(owner_token)
        context = await self._ensure_started()
        page = await context.new_page()
        page_id = self._register_page(page)
        if url.strip():
            await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        async with self._operator_lock:
            self._operator_pages[owner_token] = page_id
        return await self._summary(page_id, page)

    async def operator_navigate(self, owner_token: str, page_id: str, url: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        response = await page.goto(self._operator_url(url), wait_until="domcontentloaded")
        result = await self._summary(page_id, page)
        result["http_status"] = response.status if response is not None else None
        return result


    async def operator_open_devtools(
        self,
        owner_token: str,
        page_id: str,
        *,
        panel: str = "elements",
    ) -> JsonObject:
        self._require_operator(owner_token)
        context = await self._ensure_started()
        page = await self._page(page_id)
        before = {id(candidate) for candidate in context.pages}
        session = await context.new_cdp_session(page)
        try:
            info = await session.send("Target.getTargetInfo")
            target_info = info.get("targetInfo") if isinstance(info, dict) else None
            target_id = (
                str(target_info.get("targetId") or "")
                if isinstance(target_info, dict)
                else ""
            )
            if not target_id:
                raise BrowserError("selected browser tab has no DevTools target")
            try:
                opened = await session.send(
                    "Target.openDevTools",
                    {"targetId": target_id, "panelId": panel},
                )
            except Exception as exc:
                raise BrowserError(f"Chromium could not open DevTools: {exc}") from exc
        finally:
            await session.detach()

        devtools_target_id = (
            str(opened.get("targetId") or "") if isinstance(opened, dict) else ""
        )
        for _ in range(10):
            await asyncio.sleep(0.1)
            for candidate in context.pages:
                if id(candidate) in before or candidate.is_closed():
                    continue
                candidate_id = self._register_page(candidate)
                async with self._operator_lock:
                    self._operator_pages[owner_token] = candidate_id
                result = await self._summary(candidate_id, candidate)
                result["devtools_target_id"] = devtools_target_id
                result["opened_devtools"] = True
                return result
        return {
            "opened_devtools": True,
            "devtools_target_id": devtools_target_id,
            "page_id": page_id,
        }

    async def operator_clean_browser(self, owner_token: str) -> JsonObject:
        self._require_operator(owner_token)
        async with self._reset_lock:
            # Block agents before destroying the credential-bearing profile.
            async with self._policy_lock:
                self._agent_access_enabled = False

            context = self._context
            playwright = self._playwright
            self._context = None
            self._playwright = None
            if context is not None:
                with contextlib.suppress(Exception):
                    await context.close()
            if playwright is not None:
                with contextlib.suppress(Exception):
                    await playwright.stop()

            self._pages.clear()
            self._page_ids.clear()
            self._page_labels.clear()
            self._page_agent_access.clear()
            await asyncio.to_thread(shutil.rmtree, self.profile_dir, True)
            state_root = self.profile_dir.parent
            for name in ("cache", "config", "crash"):
                await asyncio.to_thread(shutil.rmtree, state_root / name, True)
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._persist_policy)

            async with self._start_lock:
                await self._start_locked()
            page_items = await self._operator_page_items()
            if not page_items:
                context = await self._ensure_started()
                page = await context.new_page()
                page_id = self._register_page(page)
                page_items = [await self._summary(page_id, page)]
            first_page = page_items[0] if page_items else None
            selected_page_id = (
                str(first_page.get("page_id") or "")
                if isinstance(first_page, dict)
                else ""
            )
            async with self._operator_lock:
                for token in list(self._operator_pages):
                    self._operator_pages[token] = selected_page_id
            return {
                "cleaned": True,
                "agent_access_enabled": False,
                "selected_page_id": selected_page_id,
                "page_count": len(page_items),
            }

    async def operator_back(self, owner_token: str, page_id: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        await page.go_back(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def operator_reload(self, owner_token: str, page_id: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        await page.reload(wait_until="domcontentloaded")
        return await self._summary(page_id, page)

    async def operator_close_page(self, owner_token: str, page_id: str) -> JsonObject:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        await page.close()
        self._forget_page(page_id)
        async with self._operator_lock:
            if self._operator_pages.get(owner_token) == page_id:
                self._operator_pages[owner_token] = ""
        return {"page_id": page_id, "closed": True}

    async def operator_mouse(
        self,
        owner_token: str,
        page_id: str,
        *,
        event_type: str,
        x: float,
        y: float,
        button: str,
        click_count: int,
        delta_x: float,
        delta_y: float,
    ) -> None:
        self._require_operator(owner_token)
        page = await self._page(page_id)
        if event_type == "mouseMoved":
            await page.mouse.move(x, y)
            return
        if event_type == "mouseWheel":
            await page.mouse.move(x, y)
            await page.mouse.wheel(delta_x, delta_y)
            return
        if event_type not in {"mousePressed", "mouseReleased"}:
            raise BrowserError("unsupported mouse event")
        button_name = cast(
            Literal["left", "middle", "right"],
            button if button in {"left", "middle", "right"} else "left",
        )
        await page.mouse.move(x, y)
        if event_type == "mousePressed":
            await page.mouse.down(button=button_name, click_count=max(1, click_count))
        else:
            await page.mouse.up(button=button_name, click_count=max(1, click_count))

    async def operator_key(self, owner_token: str, page_id: str, key: str) -> None:
        self._require_operator(owner_token)
        if not key.strip():
            raise BrowserError("key is required")
        page = await self._page(page_id)
        await page.keyboard.press(key)

    async def operator_text(self, owner_token: str, page_id: str, text: str) -> None:
        self._require_operator(owner_token)
        if len(text) > 10_000:
            raise BrowserError("operator text input is too large")
        page = await self._page(page_id)
        await page.keyboard.insert_text(text)

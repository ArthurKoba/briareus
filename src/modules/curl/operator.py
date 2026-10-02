from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from .browser import BrowserError, BrowserManager


def _bearer_token(websocket: WebSocket) -> str:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer":
        return ""
    return token.strip()


async def browser_operator_websocket(
    websocket: WebSocket,
    *,
    browser: BrowserManager,
    service_token: str,
) -> None:
    supplied = _bearer_token(websocket)
    if not supplied or not hmac.compare_digest(supplied, service_token):
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        owner = await browser.operator_acquire()
    except BrowserError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4409)
        return

    owner_token = str(owner["owner_token"])
    selected_page_id = str(owner.get("selected_page_id") or "")
    stream_task: asyncio.Task[None] | None = None
    devtools_stream_task: asyncio.Task[None] | None = None

    async def send_state() -> None:
        state = await browser.operator_state(owner_token)
        state["type"] = "state"
        await websocket.send_json(state)

    async def stream(page_id: str, *, role: str = "main") -> None:
        page, session = await browser.operator_cdp_session(owner_token, page_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
        loop = asyncio.get_running_loop()

        def on_frame(payload: dict[str, Any]) -> None:
            session_id = payload.get("sessionId")
            if session_id is not None:
                ack_task = loop.create_task(
                    session.send(
                        "Page.screencastFrameAck",
                        {"sessionId": session_id},
                    )
                )
                ack_task.add_done_callback(
                    lambda task: task.exception() if not task.cancelled() else None
                )
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

        session.on("Page.screencastFrame", on_frame)
        try:
            await session.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 72,
                    "maxWidth": browser.viewport_width,
                    "maxHeight": browser.viewport_height,
                    "everyNthFrame": 1,
                },
            )
            while True:
                payload = await queue.get()
                await websocket.send_json(
                    {
                        "type": "frame",
                        "role": role,
                        "page_id": page_id,
                        "data": payload.get("data", ""),
                        "metadata": payload.get("metadata", {}),
                        "url": page.url,
                    }
                )
        finally:
            with contextlib.suppress(Exception):
                await session.send("Page.stopScreencast")
            with contextlib.suppress(Exception):
                await session.detach()

    async def select_page(page_id: str) -> None:
        nonlocal selected_page_id, stream_task
        await browser.operator_select_page(owner_token, page_id)
        selected_page_id = page_id
        if stream_task is not None:
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        stream_task = asyncio.create_task(
            stream(page_id, role="main"),
            name="browser-operator-stream",
        )
        await send_state()

    try:
        await send_state()
        if selected_page_id:
            stream_task = asyncio.create_task(
                stream(selected_page_id, role="main"),
                name="browser-operator-stream",
            )

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid JSON"})
                continue
            if not isinstance(message, dict):
                continue
            kind = str(message.get("type") or "")

            try:
                if kind == "select_page":
                    await select_page(str(message.get("page_id") or ""))
                elif kind == "refresh_state":
                    await send_state()
                elif kind == "set_label":
                    page_id = str(message.get("page_id") or "")
                    await browser.operator_set_page_label(
                        owner_token,
                        page_id,
                        str(message.get("label") or ""),
                    )
                    await send_state()
                elif kind == "set_page_agent_access":
                    page_id = str(message.get("page_id") or "")
                    allowed = message.get("allowed")
                    if not isinstance(allowed, bool):
                        raise BrowserError("allowed must be a boolean")
                    await browser.operator_set_page_agent_access(
                        owner_token, page_id, allowed
                    )
                    await send_state()
                elif kind == "set_agent_access":
                    allowed = message.get("allowed")
                    if not isinstance(allowed, bool):
                        raise BrowserError("allowed must be a boolean")
                    await browser.operator_set_agent_access(owner_token, allowed)
                    await send_state()
                elif kind == "navigate":
                    if not selected_page_id:
                        raise BrowserError("no browser page selected")
                    await browser.operator_navigate(
                        owner_token,
                        selected_page_id,
                        str(message.get("url") or ""),
                    )
                    await send_state()
                elif kind == "new_page":
                    result = await browser.operator_new_page(
                        owner_token,
                        str(message.get("url") or ""),
                    )
                    await select_page(str(result["page_id"]))
                elif kind == "open_devtools":
                    if not selected_page_id:
                        raise BrowserError("no browser page selected")
                    dock = message.get("dock") is True
                    result = await browser.operator_open_devtools(
                        owner_token,
                        selected_page_id,
                        panel=str(message.get("panel") or "elements"),
                        dock=dock,
                    )
                    new_page_id = str(result.get("page_id") or "")
                    if dock:
                        if devtools_stream_task is not None:
                            devtools_stream_task.cancel()
                            await asyncio.gather(
                                devtools_stream_task, return_exceptions=True
                            )
                        if new_page_id:
                            devtools_stream_task = asyncio.create_task(
                                stream(new_page_id, role="devtools"),
                                name="browser-operator-devtools-stream",
                            )
                        await send_state()
                    elif new_page_id and new_page_id != selected_page_id:
                        await select_page(new_page_id)
                    else:
                        await send_state()
                elif kind == "close_devtools":
                    await browser.operator_close_devtools(owner_token)
                    if devtools_stream_task is not None:
                        devtools_stream_task.cancel()
                        await asyncio.gather(
                            devtools_stream_task, return_exceptions=True
                        )
                        devtools_stream_task = None
                    await send_state()
                elif kind == "reopen_closed_page":
                    result = await browser.operator_reopen_closed_page(owner_token)
                    await select_page(str(result["page_id"]))
                elif kind == "clean_app":
                    if not selected_page_id:
                        raise BrowserError("no browser page selected")
                    await browser.operator_clean_app(owner_token, selected_page_id)
                    await send_state()
                elif kind == "clean_browser":
                    if stream_task is not None:
                        stream_task.cancel()
                        await asyncio.gather(stream_task, return_exceptions=True)
                        stream_task = None
                    if devtools_stream_task is not None:
                        devtools_stream_task.cancel()
                        await asyncio.gather(
                            devtools_stream_task, return_exceptions=True
                        )
                        devtools_stream_task = None
                    result = await browser.operator_clean_browser(owner_token)
                    selected_page_id = str(result.get("selected_page_id") or "")
                    if selected_page_id:
                        stream_task = asyncio.create_task(
                            stream(selected_page_id, role="main"),
                            name="browser-operator-stream",
                        )
                    await send_state()
                elif kind == "back":
                    await browser.operator_back(owner_token, selected_page_id)
                    await send_state()
                elif kind == "reload":
                    await browser.operator_reload(owner_token, selected_page_id)
                    await send_state()
                elif kind == "close_page":
                    closed = await browser.operator_close_page(
                        owner_token, selected_page_id
                    )
                    if closed.get("closed_devtools_page_id") and devtools_stream_task is not None:
                        devtools_stream_task.cancel()
                        await asyncio.gather(
                            devtools_stream_task, return_exceptions=True
                        )
                        devtools_stream_task = None
                    state = await browser.operator_state(owner_token)
                    next_page = str(state.get("selected_page_id") or "")
                    if next_page:
                        await select_page(next_page)
                    else:
                        if stream_task is not None:
                            stream_task.cancel()
                            await asyncio.gather(stream_task, return_exceptions=True)
                            stream_task = None
                        selected_page_id = ""
                        await send_state()
                elif kind == "mouse":
                    target_page_id = str(message.get("page_id") or selected_page_id)
                    await browser.operator_mouse(
                        owner_token,
                        target_page_id,
                        event_type=str(message.get("event") or ""),
                        x=float(message.get("x") or 0),
                        y=float(message.get("y") or 0),
                        button=str(message.get("button") or "none"),
                        click_count=int(message.get("click_count") or 0),
                        delta_x=float(message.get("delta_x") or 0),
                        delta_y=float(message.get("delta_y") or 0),
                    )
                elif kind == "key":
                    target_page_id = str(message.get("page_id") or selected_page_id)
                    await browser.operator_key(
                        owner_token,
                        target_page_id,
                        str(message.get("key") or ""),
                    )
                elif kind == "text":
                    target_page_id = str(message.get("page_id") or selected_page_id)
                    await browser.operator_text(
                        owner_token,
                        target_page_id,
                        str(message.get("text") or ""),
                    )
                elif kind == "release":
                    break
            except BrowserError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        if stream_task is not None:
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        if devtools_stream_task is not None:
            devtools_stream_task.cancel()
            await asyncio.gather(devtools_stream_task, return_exceptions=True)
        await browser.operator_release(owner_token)
        with contextlib.suppress(RuntimeError):
            await websocket.close()

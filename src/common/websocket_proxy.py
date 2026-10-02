from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from typing import cast

from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin


async def relay_websocket(
    websocket: WebSocket,
    target_url: str,
    *,
    headers: Mapping[str, str] | None = None,
    origin: str | None = None,
    accept_downstream: bool = True,
) -> None:
    """Relay one authenticated Starlette WebSocket to an internal WebSocket."""

    try:
        async with connect(
            target_url,
            additional_headers=dict(headers or {}),
            origin=cast(Origin | None, origin),
            proxy=None,
            max_size=None,
            open_timeout=10,
            close_timeout=5,
        ) as upstream:
            if accept_downstream:
                await websocket.accept()

            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    kind = message.get("type")
                    if kind == "websocket.disconnect":
                        return
                    text = message.get("text")
                    data = message.get("bytes")
                    if isinstance(text, str):
                        await upstream.send(text)
                    elif isinstance(data, bytes):
                        await upstream.send(data)

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(bytes(message))

            tasks = {
                asyncio.create_task(client_to_upstream(), name="websocket-client-upstream"),
                asyncio.create_task(upstream_to_client(), name="websocket-upstream-client"),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                with contextlib.suppress(WebSocketDisconnect):
                    task.result()
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=1000)
    except WebSocketDisconnect:
        return
    except ConnectionClosed as exc:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=int(exc.code), reason=str(exc.reason or ""))
        return
    except Exception:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=1011)
        raise

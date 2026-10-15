"""Close a private upstream even if the downstream never starts its body.

A generator's finally block is not entered when sending response headers
fails first. Cleanup therefore belongs to both body and ASGI-response
lifecycle, with exactly one slot release across success and cancellation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


class ProxyStreamingResponse(StreamingResponse):
    def __init__(
        self,
        upstream: httpx.Response,
        *,
        slots: asyncio.Semaphore,
        open_responses: set[httpx.Response],
        tracked_streams: set[ProxyStreamingResponse] | None = None,
    ) -> None:
        self._upstream = upstream
        self._slots = slots
        self._open_responses = open_responses
        self._cleanup: asyncio.Task[None] | None = None
        self._tracked_streams = tracked_streams
        super().__init__(self._stream(), status_code=upstream.status_code)

    async def _release(self) -> None:
        try:
            async with asyncio.timeout(3):
                await self._upstream.aclose()
        except Exception:
            # Closing must not expose upstream errors or mask a disconnect.
            # The response is removed and the admission slot freed below.
            pass
        finally:
            self._open_responses.discard(self._upstream)
            if self._tracked_streams is not None:
                self._tracked_streams.discard(self)
            self._slots.release()

    async def _finish(self) -> None:
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._release())
        cancelled = False
        # A second cancellation must not interrupt upstream close or leak a
        # slot. The actual cleanup has its own short finite deadline.
        while not self._cleanup.done():
            try:
                await asyncio.shield(self._cleanup)
            except asyncio.CancelledError:
                cancelled = True
        self._cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def aclose(self) -> None:
        """Gateway shutdown and downstream exit share exactly one cleanup."""
        await self._finish()

    async def _stream(self) -> AsyncIterator[bytes]:
        try:
            async for data in self._upstream.aiter_raw():
                yield data
        finally:
            await self._finish()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._finish()

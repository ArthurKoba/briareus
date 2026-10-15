"""Own an upstream request until response headers, including slow client input.

Socket timeouts alone do not bound awaiting ASGI request-body events. A
pending start is a distinct lifetime from a streaming response and must
be canceled during Gateway shutdown without abandoning a late response.
"""

from __future__ import annotations

import asyncio

import httpx

_START_SECONDS = 60


class PendingProxyStart:
    def __init__(self, client: httpx.AsyncClient, request: httpx.Request) -> None:
        self._task = asyncio.create_task(self._send(client, request))
        self._claimed = False
        self._aborted = False
        self._cleanup: asyncio.Task[None] | None = None

    @staticmethod
    async def _send(client: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
        try:
            async with asyncio.timeout(_START_SECONDS):
                return await client.send(request, stream=True)
        except TimeoutError:
            raise httpx.ReadTimeout("upstream response-start deadline exceeded") from None

    async def take_response(self) -> httpx.Response:
        try:
            response = await asyncio.shield(self._task)
            if self._aborted:
                await self.abort()
                raise httpx.ReadError("gateway stopped before response handoff")
            self._claimed = True
            return response
        except asyncio.CancelledError:
            await self.abort()
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            # Canceling the owned upstream at shutdown is not cancellation
            # requested by the downstream caller; keep its 502/503 contract.
            raise httpx.ReadError("gateway stopped pending upstream") from None
        except BaseException:
            await self.abort()
            raise

    async def _abort(self) -> None:
        if not self._task.done():
            self._task.cancel()
        try:
            response = await self._task
        except (asyncio.CancelledError, Exception):
            return
        if not self._claimed:
            try:
                async with asyncio.timeout(3):
                    await response.aclose()
            except Exception:
                pass

    async def abort(self) -> None:
        self._aborted = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._abort())
        cancelled = False
        while not self._cleanup.done():
            try:
                await asyncio.shield(self._cleanup)
            except asyncio.CancelledError:
                cancelled = True
        self._cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

"""Transport-only cleanup regression; no authenticated MCP/owner permission."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

import httpx
from starlette.requests import ClientDisconnect, Request
from starlette.types import Message, Scope

from bridge.thin_gateway import ThinGateway


class Bytes(httpx.AsyncByteStream):
    def __init__(self, *, slow_close: bool = False) -> None:
        self.close_calls = 0
        self.slow_close = slow_close
        self.closing = asyncio.Event()
        self.release = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"data: first\n\n"
        yield b"data: second\n\n"

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closing.set()
        if self.slow_close:
            await self.release.wait()


def scope(version: str = "2.4") -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": version},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/transport-probe",
        "raw_path": b"/api/transport-probe",
        "query_string": b"",
        "headers": [(b"host", b"briareus.koba-nexus.ru")],
        "server": ("briareus.koba-nexus.ru", 443),
        "client": ("127.0.0.1", 1000),
    }


async def receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def main() -> None:
    current = Bytes()

    async def owner(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"content-type": "text/event-stream"}, stream=current)

    async with httpx.AsyncClient(transport=httpx.MockTransport(owner)) as client:
        gateway = ThinGateway()
        gateway._client = client
        # More than the whole 64-slot pool: none may be stranded before
        # body iteration, even when the very first send fails.
        for index in range(80):
            current = Bytes()
            response = await gateway.api(Request(scope(), receive))

            async def failing_send(message: Message, *, before_body: bool = index % 2 == 0) -> None:
                if before_body or message["type"] == "http.response.body":
                    raise OSError("fixture downstream disconnected")

            try:
                await response(scope(), receive, failing_send)
            except ClientDisconnect:
                pass
            else:
                raise AssertionError("failed transport did not signal disconnect")
            assert not gateway._open and gateway._slots._value == 64
            assert current.close_calls == 1
        print("80_EARLY_AND_MIDSTREAM_DISCONNECTS_NO_UPSTREAM_OR_SLOT_LEAK_PASS")

        current = Bytes()
        response = await gateway.api(Request(scope(), receive))
        parts: list[bytes] = []

        async def send(message: Message) -> None:
            if message["type"] == "http.response.body":
                parts.append(message["body"])

        await response(scope(), receive, send)
        assert b"".join(parts) == b"data: first\n\ndata: second\n\n"
        assert current.close_calls == 1 and not gateway._open and gateway._slots._value == 64
        print("SUCCESSFUL_SSE_BYTES_PRESERVED_SINGLE_CLEANUP_PASS")

        # Cancellation while headers are pending, then cancellation AGAIN
        # while upstream is closing. Cleanup must finish before returning.
        current = Bytes(slow_close=True)
        response = await gateway.api(Request(scope(), receive))
        header_started = asyncio.Event()

        async def blocked_send(_message: Message) -> None:
            header_started.set()
            await asyncio.Event().wait()

        operation = asyncio.create_task(response(scope(), receive, blocked_send))
        await asyncio.wait_for(header_started.wait(), 2)
        operation.cancel()
        await asyncio.wait_for(current.closing.wait(), 2)
        operation.cancel()
        current.release.set()
        try:
            await operation
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("caller cancellation swallowed")
        assert current.close_calls == 1 and not gateway._open and gateway._slots._value == 64
        print("REPEATED_CANCELLATION_CLOSES_UPSTREAM_ONCE_PASS")

        # ASGI 2.0 uses disconnect events rather than OSError on send.
        current = Bytes()
        old_scope = scope("2.0")
        response = await gateway.api(Request(old_scope, receive))

        async def disconnected() -> Message:
            return {"type": "http.disconnect"}

        await response(old_scope, disconnected, send)
        assert not gateway._open and gateway._slots._value == 64
        assert current.close_calls == 1
        print("ASGI20_DISCONNECT_EVENT_CLEANUP_PASS")

        class CloseFailure(Bytes):
            async def aclose(self) -> None:
                self.close_calls += 1
                raise OSError("fixture close failed")

        # Shutdown must close ALL responses even if one close raises; it
        # shares cleanup with an already disconnecting response, not a
        # second raw aclose loop that races the first cleanup.
        gateway._client = None
        slow = [Bytes(slow_close=True) for _ in range(4)]
        failing = CloseFailure()
        async with gateway.lifespan(None):
            streams = []
            for raw in [*slow, failing]:
                await gateway._slots.acquire()
                streams.append(gateway._stream_response(httpx.Response(200, stream=raw)))
            draining = asyncio.create_task(gateway._drain_streams())
            await asyncio.wait_for(asyncio.gather(*(raw.closing.wait() for raw in slow)), 1)
            # Parallel closure: every slow stream entered aclose before any
            # one was released. A per-response serial loop cannot do this.
            concurrent = asyncio.create_task(streams[0].aclose())
            draining.cancel()
            await asyncio.sleep(0)
            draining.cancel()
            for raw in slow:
                raw.release.set()
            try:
                await draining
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("shutdown cancellation lost")
            await concurrent
        assert all(raw.close_calls == 1 for raw in [*slow, failing])
        assert not gateway._open and not gateway._streams
        assert gateway._slots._value == 64 and gateway._client is None
        print("GATEWAY_SHUTDOWN_PARALLEL_FAILURE_AND_DISCONNECT_SHARE_SINGLE_CLEANUP_PASS")

        # A pending owner's response may arrive after the drain snapshot.
        # It must close immediately instead of becoming a new live stream.
        gateway = ThinGateway()
        started, release = asyncio.Event(), asyncio.Event()
        late = Bytes()

        async def late_owner(_request: httpx.Request) -> httpx.Response:
            started.set()
            # Model headers received as shutdown cancels the transport;
            # the newly received orphan response must still close.
            with suppress(asyncio.CancelledError):
                await release.wait()
            return httpx.Response(200, stream=late)

        async with httpx.AsyncClient(transport=httpx.MockTransport(late_owner)) as late_client:
            gateway._client = late_client
            pending = asyncio.create_task(gateway.api(Request(scope(), receive)))
            await started.wait()
            gateway._draining = True
            gateway._client = None
            await gateway._drain_streams()
            release.set()
            result = await pending
            assert result.status_code == 502
        assert late.close_calls == 1
        assert not gateway._open and not gateway._streams and gateway._slots._value == 64
        print("GATEWAY_LATE_UPSTREAM_AFTER_DRAIN_DENIED_AND_CLOSED_PASS")

        # Multiple never-completing close methods share one bounded wall
        # interval, rather than accumulating a timeout per response.
        gateway = ThinGateway()
        blocked = [Bytes(slow_close=True) for _ in range(4)]
        for raw in blocked:
            await gateway._slots.acquire()
            gateway._stream_response(httpx.Response(200, stream=raw))
        began = asyncio.get_running_loop().time()
        await asyncio.wait_for(gateway._drain_streams(), 5)
        assert asyncio.get_running_loop().time() - began < 5
        assert all(raw.close_calls == 1 for raw in blocked)
        assert not gateway._open and not gateway._streams and gateway._slots._value == 64
        print("FOUR_STALLED_UPSTREAM_CLOSES_HAVE_ONE_BOUNDED_SHUTDOWN_WINDOW_PASS")

        # An unfinished caller upload is not yet in the response registry.
        # Drain must abort that start too and release all admission slots.
        gateway = ThinGateway()
        body_entered = asyncio.Event()
        contacted = []

        async def unfinished_body() -> Message:
            body_entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def body_owner(request: httpx.Request) -> httpx.Response:
            contacted.append(request)
            return httpx.Response(200, stream=Bytes())

        post_scope = scope()
        post_scope["method"] = "POST"
        post_scope["headers"].append((b"content-length", b"2"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(body_owner)) as body_client:
            gateway._client = body_client
            waiting = asyncio.create_task(gateway.api(Request(post_scope, unfinished_body)))
            await body_entered.wait()
            assert gateway._slots._value == 63 and gateway._pending
            gateway._draining = True
            gateway._client = None
            await asyncio.wait_for(gateway._drain_streams(), 1)
            denied = await asyncio.wait_for(waiting, 1)
            assert denied.status_code == 502 and not contacted
        assert not gateway._pending and gateway._slots._value == 64
        print("PENDING_ASGI_BODY_DRAIN_ABORTS_WITHOUT_OWNER_CONTACT_OR_SLOT_LEAK_PASS")

        # Product deadline is60s; short fixture deadline proves it bounds
        # empty ASGI events, not only socket reads or final response bytes.
        from bridge import _proxy_start

        original_deadline = _proxy_start._START_SECONDS
        _proxy_start._START_SECONDS = 0.03
        gateway = ThinGateway()

        async def endless_empty_body() -> Message:
            await asyncio.sleep(0.001)
            return {"type": "http.request", "body": b"", "more_body": True}

        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(body_owner)) as body_client:
                gateway._client = body_client
                denied = await asyncio.wait_for(
                    gateway.api(Request(post_scope, endless_empty_body)),
                    1,
                )
                assert denied.status_code == 502 and not contacted
                assert not gateway._pending and gateway._slots._value == 64
        finally:
            _proxy_start._START_SECONDS = original_deadline
        print("RESPONSE_START_TOTAL_DEADLINE_COVERS_UNFINISHED_INPUT_PASS")


if __name__ == "__main__":
    asyncio.run(main())

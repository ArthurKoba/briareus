from __future__ import annotations

import asyncio
import hmac
from urllib.parse import urlsplit

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from common.settings import ManagementSettings
from management.application.services import InvocationAuditService, SnapshotService
from management.infrastructure.web import WebAdminClient
from management.realtime import REALTIME_TOPICS, RealtimeBus, RealtimeEnvelope

_SESSION_KEY = "management_admin"


def build_realtime_router(
    settings: ManagementSettings,
    bus: RealtimeBus,
    audit: InvocationAuditService,
    snapshots: SnapshotService,
    web: WebAdminClient,
) -> APIRouter:
    router = APIRouter()

    async def topic_snapshot(topic: str) -> object | None:
        if topic == "mcp.calls":
            events = await asyncio.to_thread(audit.recent, limit=100)
            return {
                "events": [item.model_dump(mode="json") for item in events],
                "count": len(events),
            }
        if topic == "browser.runtime":
            try:
                return await web.status()
            except Exception as exc:
                return {"available": False, "error": str(exc)}
        if topic == "system.metrics":
            calls = await asyncio.to_thread(audit.summary)
            workspace = await asyncio.to_thread(snapshots.get, "workspace:stats")
            analysis = await asyncio.to_thread(snapshots.get, "reverse:overview")
            return {
                "calls": calls,
                "workspace": workspace.payload if workspace is not None else {},
                "analysis": analysis.payload if analysis is not None else {},
            }
        cached = bus.snapshot(topic)
        if isinstance(cached, dict):
            return cached.get("data")
        return None

    @router.websocket("/admin/api/realtime")
    async def management_realtime_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin", "")
        public_host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host", "")
        if origin and urlsplit(origin).netloc.casefold() != public_host.casefold():
            await websocket.close(code=4403)
            return
        session = websocket.scope.get("session")
        username = session.get(_SESSION_KEY) if isinstance(session, dict) else None
        if not isinstance(username, str) or not hmac.compare_digest(
            username, settings.admin_username
        ):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        subscriber = bus.register()
        await websocket.send_json(
            {"version": 1, "type": "ready", "topics": sorted(REALTIME_TOPICS)}
        )

        async def receive_commands() -> None:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    continue
                kind = str(message.get("type") or "")
                raw_topics = message.get("topics")
                if isinstance(raw_topics, str):
                    requested = [raw_topics]
                elif isinstance(raw_topics, list):
                    requested = [str(item) for item in raw_topics]
                else:
                    topic = str(message.get("topic") or "")
                    requested = [topic] if topic else []
                if kind == "subscribe":
                    try:
                        topics = [bus.validate_topic(item) for item in requested]
                    except ValueError as exc:
                        await websocket.send_json(
                            {
                                "version": 1,
                                "type": "error",
                                "code": "invalid_topic",
                                "message": str(exc),
                            }
                        )
                        continue
                    subscriber.topics.update(topics)
                    await websocket.send_json(
                        {
                            "version": 1,
                            "type": "subscribed",
                            "topics": sorted(subscriber.topics),
                        }
                    )
                    for topic in topics:
                        data = await topic_snapshot(topic)
                        if data is not None:
                            event = RealtimeEnvelope(topic=topic, type="snapshot", data=data)
                            await websocket.send_json(event.model_dump(mode="json"))
                elif kind == "unsubscribe":
                    subscriber.topics.difference_update(requested)
                    await websocket.send_json(
                        {
                            "version": 1,
                            "type": "unsubscribed",
                            "topics": sorted(subscriber.topics),
                        }
                    )
                elif kind == "ping":
                    await websocket.send_json({"version": 1, "type": "pong"})

        async def send_events() -> None:
            while True:
                await websocket.send_json(await subscriber.queue.get())

        receive_task = asyncio.create_task(receive_commands())
        send_task = asyncio.create_task(send_events())
        try:
            done, pending = await asyncio.wait(
                {receive_task, send_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(*done, return_exceptions=True)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            bus.unregister(subscriber)
            for task in (receive_task, send_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(receive_task, send_task, return_exceptions=True)

    return router

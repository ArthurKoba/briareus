from __future__ import annotations

import asyncio
import queue
import urllib.error
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from common.models import JsonValue
from common.settings import FileSettings, ManagementSettings, ValkeySettings
from management.api_errors import install_admin_api_error_handlers
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from management.browser_api import build_browser_operator_api_router
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import Base, ManagementConfigRecord, create_database
from management.infrastructure.files import FileAdminStore
from management.infrastructure.provider_checks import ProviderConnectionVerifier
from management.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyManagementConfigRepository,
    SqlAlchemyOAuthSessionRepository,
    SqlAlchemyRuntimeSettingsRepository,
    SqlAlchemySnapshotRepository,
)
from management.presentation.web_api import WebApiServices, build_admin_api_router
from management.realtime import RealtimeBus
from management.realtime_api import build_realtime_router
from management.telemetry_ingest import FrontendTelemetryProxy, TelemetryUpstream


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, JsonValue] = {}

    def key(self, *parts: str) -> str:
        return ":".join(parts)

    def get_json(self, key: str) -> JsonValue | None:
        return self.values.get(key)

    def set_json(self, key: str, value: object, *, ttl_seconds: int) -> bool:
        del ttl_seconds
        assert isinstance(value, (dict, list, str, int, float, bool)) or value is None
        self.values[key] = value
        return True

    def delete(self, *keys: str) -> bool:
        for key in keys:
            self.values.pop(key, None)
        return True


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


class FakeBroker:
    def __init__(self) -> None:
        self.subscribers: dict[str, list[queue.Queue[dict[str, str]]]] = {}

    def client(self):
        broker = self

        class Client:
            def publish(self, channel: str, payload: str) -> int:
                targets = list(broker.subscribers.get(channel, []))
                for target in targets:
                    target.put({"data": payload})
                return len(targets)

            def pubsub(self, *, ignore_subscribe_messages: bool = True):
                del ignore_subscribe_messages
                return PubSub()

        class PubSub:
            def __init__(self) -> None:
                self.channel = ""
                self.messages: queue.Queue[dict[str, str]] = queue.Queue()

            def subscribe(self, channel: str) -> None:
                self.channel = channel
                broker.subscribers.setdefault(channel, []).append(self.messages)

            def get_message(self, *, timeout: float = 1.0):
                try:
                    return self.messages.get(timeout=timeout)
                except queue.Empty:
                    return None

            def close(self) -> None:
                if self.channel and self.messages in broker.subscribers.get(self.channel, []):
                    broker.subscribers[self.channel].remove(self.messages)

        return Client()


def _settings(tmp_path: Path) -> ManagementSettings:
    return ManagementSettings(
        database_path=tmp_path / "management.sqlite3",
        encryption_key=Fernet.generate_key().decode(),
        service_token="service-token",
        admin_username="admin",
        admin_password="password",
        session_secret="session-secret",
        session_https_only=False,
        frontend_telemetry_upstream_url="",
    )


def _build_services(tmp_path: Path, settings: ManagementSettings):
    engine, sessions = create_database(settings.database_url)
    Base.metadata.create_all(engine)
    with sessions.begin() as session:
        session.add(ManagementConfigRecord(id=1))
    config = ManagementConfigService(SqlAlchemyManagementConfigRepository(sessions))
    audit = InvocationAuditService(SqlAlchemyInvocationRepository(sessions), config)
    snapshots = SnapshotService(SqlAlchemySnapshotRepository(sessions))
    reverse = Mock(
        session_settings=AsyncMock(return_value={"idle_timeout_seconds": 900.0}),
        set_idle_timeout=AsyncMock(return_value={"idle_timeout_seconds": 900.0}),
        overview=AsyncMock(
            return_value={
                "workers": [
                    {
                        "worker_index": 2,
                        "queued": 0,
                        "running": False,
                        "healthy": True,
                        "enabled": True,
                    }
                ],
                "projects": [],
            }
        ),
        clear_worker_queue=AsyncMock(return_value={"cancelled_queued": 3}),
        recover_worker=AsyncMock(return_value={"cancelled_total": 4, "recovered": True}),
    )
    web = Mock(
        status=AsyncMock(
            return_value={
                "running": True,
                "capabilities": {"set_viewport": True},
                "pages": [],
            }
        ),
        set_viewport=AsyncMock(
            return_value={
                "page_id": "page-1",
                "viewport": {"width": 1280, "height": 720},
                "requested_viewport": {"width": 1280, "height": 720},
            }
        ),
    )
    telemetry = FrontendTelemetryProxy(TelemetryUpstream(url=""))
    services = WebApiServices(
        accounts=AccountService(
            SqlAlchemyAccountRepository(sessions),
            FernetCredentialCipher(settings.encryption_key),
            ProviderConnectionVerifier(),
        ),
        audit=audit,
        oauth_sessions=OAuthSessionService(SqlAlchemyOAuthSessionRepository(sessions)),
        snapshots=snapshots,
        config=config,
        runtime_settings=RuntimeSettingsService(SqlAlchemyRuntimeSettingsRepository(sessions)),
        files=FileAdminStore(FileSettings(workspace_root=tmp_path / "workspace")),
        reverse=reverse,
        terminal=Mock(),
        web=web,
        snapshot_refresher=Mock(),
        telemetry=telemetry,
    )
    return engine, services, reverse, web, telemetry


def _client(
    tmp_path: Path,
) -> tuple[TestClient, WebApiServices, Mock, Mock, FrontendTelemetryProxy]:
    settings = _settings(tmp_path)
    _engine, services, reverse, web, telemetry = _build_services(tmp_path, settings)
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    install_admin_api_error_handlers(app)
    app.include_router(build_admin_api_router(settings, services))
    return TestClient(app), services, reverse, web, telemetry


def _login(client: TestClient) -> None:
    response = client.post("/admin/api/login", json={"username": "admin", "password": "password"})
    assert response.status_code == 200


def test_admin_api_route_contract_is_explicit_and_complete(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    router = build_admin_api_router(settings, None)
    actual = {
        (method, route.path)
        for route in router.routes
        for method in sorted(getattr(route, "methods", set()) or set())
    }
    expected = {
        ("GET", "/admin/api/session"),
        ("POST", "/admin/api/login"),
        ("POST", "/admin/api/logout"),
        ("GET", "/admin/api/bootstrap"),
        ("GET", "/admin/api/dashboard"),
        ("GET", "/admin/api/accounts"),
        ("POST", "/admin/api/accounts"),
        ("PUT", "/admin/api/accounts/{provider}/{account_id}"),
        ("DELETE", "/admin/api/accounts/{provider}/{account_id}"),
        ("POST", "/admin/api/accounts/{provider}/{account_id}/verify"),
        ("GET", "/admin/api/calls"),
        ("DELETE", "/admin/api/calls"),
        ("DELETE", "/admin/api/calls/{call_id}"),
        ("GET", "/admin/api/calls/stream"),
        ("GET", "/admin/api/oauth-sessions"),
        ("GET", "/admin/api/files"),
        ("POST", "/admin/api/files/upload"),
        ("POST", "/admin/api/files/mkdir"),
        ("GET", "/admin/api/files/download"),
        ("DELETE", "/admin/api/files"),
        ("GET", "/admin/api/terminal"),
        ("GET", "/admin/api/terminal/jobs/{job_id}"),
        ("POST", "/admin/api/terminal/jobs/{job_id}/cancel"),
        ("DELETE", "/admin/api/terminal/jobs/{job_id}"),
        ("POST", "/admin/api/terminal/jobs/cleanup"),
        ("DELETE", "/admin/api/terminal/workspaces/{workspace_id}"),
        ("GET", "/admin/api/analysis"),
        ("GET", "/admin/api/analysis/projects/{project_id:path}"),
        ("POST", "/admin/api/analysis/projects"),
        ("POST", "/admin/api/analysis/projects/{project_id:path}/open"),
        ("POST", "/admin/api/analysis/projects/{project_id:path}/release"),
        ("DELETE", "/admin/api/analysis/projects/{project_id:path}"),
        ("PUT", "/admin/api/analysis/workers/{worker_index}"),
        ("GET", "/admin/api/analysis/workers"),
        ("GET", "/admin/api/analysis/workers/{worker_index}"),
        ("POST", "/admin/api/analysis/workers/{worker_index}/clear-queue"),
        ("POST", "/admin/api/analysis/workers/{worker_index}/recover"),
        ("GET", "/admin/api/analysis/projects/{project_id:path}/coverage"),
        ("GET", "/admin/api/browser/state"),
        ("PUT", "/admin/api/browser/viewport"),
        ("GET", "/admin/api/browser/ticket"),
        ("POST", "/admin/api/telemetry"),
        ("GET", "/admin/api/settings"),
        ("PUT", "/admin/api/settings"),
        ("POST", "/admin/api/settings/cleanup-logs"),
    }
    assert actual == expected


def test_analysis_clear_queue_recover_and_state_are_structured(tmp_path: Path) -> None:
    client, _services, reverse, _web, _telemetry = _client(tmp_path)
    with client:
        _login(client)
        workers = client.get("/admin/api/analysis/workers")
        assert workers.status_code == 200
        assert workers.json()["workers"][0]["worker_index"] == 2

        cleared = client.post("/admin/api/analysis/workers/2/clear-queue")
        assert cleared.status_code == 200
        assert cleared.json()["operation"] == "clear_queue"
        assert cleared.json()["result"]["cancelled_queued"] == 3
        assert cleared.json()["worker"]["worker_index"] == 2

        recovered = client.post(
            "/admin/api/analysis/workers/2/recover", json={"timeout_seconds": 5.0}
        )
        assert recovered.status_code == 200
        assert recovered.json()["operation"] == "recover"
        assert recovered.json()["result"]["recovered"] is True
        reverse.recover_worker.assert_awaited_with(2, timeout_seconds=5.0)


def test_browser_viewport_api_returns_effective_state(tmp_path: Path) -> None:
    client, _services, _reverse, web, _telemetry = _client(tmp_path)
    with client:
        _login(client)
        state = client.get("/admin/api/browser/state")
        assert state.status_code == 200
        assert state.json()["capabilities"]["set_viewport"] is True

        response = client.put(
            "/admin/api/browser/viewport",
            json={"page_id": "page-1", "width": 1280, "height": 720},
        )
        assert response.status_code == 200
        assert response.json()["viewport"] == {"width": 1280, "height": 720}
        web.set_viewport.assert_awaited_once_with("page-1", 1280, 720)


def test_provider_failure_does_not_destroy_management_session(tmp_path: Path) -> None:
    client, _services, reverse, _web, _telemetry = _client(tmp_path)
    reverse.overview = AsyncMock(side_effect=RuntimeError("backend unavailable"))
    with client:
        _login(client)
        failed = client.get("/admin/api/analysis/workers")
        assert failed.status_code == 502
        assert failed.json()["error"]["code"] == "provider_unavailable"
        session = client.get("/admin/api/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True


def test_service_unavailable_does_not_destroy_management_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    install_admin_api_error_handlers(app)
    app.include_router(build_admin_api_router(settings, None))

    with TestClient(app) as client:
        _login(client)
        failed = client.get("/admin/api/settings")
        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "service_unavailable"
        session = client.get("/admin/api/session")
        assert session.status_code == 200
        assert session.json()["authenticated"] is True


def test_frontend_telemetry_requires_session_and_redacts_payload(tmp_path: Path) -> None:
    client, _services, _reverse, _web, telemetry = _client(tmp_path)
    payload = {
        "events": [
            {
                "type": "api",
                "headers": {"Authorization": "Bearer super-secret", "X-Trace": "ok"},
                "message": "failed with Bearer hidden-token",
                "provider_token": "secret-provider-token",
                "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbiJ9.signature",
            }
        ]
    }
    with client:
        anonymous = client.post("/admin/api/telemetry", json=payload)
        assert anonymous.status_code == 401
        assert anonymous.json()["error"]["code"] == "unauthorized"

        _login(client)
        accepted = client.post("/admin/api/telemetry", json=payload)
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] == 1
        queued = telemetry.queue.get_nowait()
        rendered = repr(queued)
        assert "super-secret" not in rendered
        assert "hidden-token" not in rendered
        assert "secret-provider-token" not in rendered
        assert "eyJhbGciOiJIUzI1NiJ9" not in rendered
        assert "<redacted>" in rendered


@pytest.mark.asyncio
async def test_telemetry_upstream_failure_is_isolated(monkeypatch) -> None:
    proxy = FrontendTelemetryProxy(TelemetryUpstream(url="https://telemetry.invalid"))

    def fail(_events):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(proxy, "_send", fail)
    proxy.start()
    result = proxy.enqueue([{"type": "navigation", "path": "/"}])
    assert result["accepted"] == 1
    await asyncio.wait_for(proxy.queue.join(), timeout=2)
    await proxy.close()


@pytest.mark.asyncio
async def test_realtime_bus_fans_out_only_to_active_topics(monkeypatch) -> None:
    cache = MemoryCache()
    bus = RealtimeBus(cache, ValkeySettings(url="redis://127.0.0.1:1"))  # type: ignore[arg-type]
    fake_redis = FakeRedis()
    monkeypatch.setattr(bus, "_redis", fake_redis)
    subscribed = bus.register()
    ignored = bus.register()
    subscribed.topics.add("system.notifications")
    ignored.topics.add("mcp.calls")

    await bus.publish("system.notifications", "notice", {"message": "hello"})

    event = subscribed.queue.get_nowait()
    assert event["topic"] == "system.notifications"
    assert ignored.queue.empty()
    assert fake_redis.published
    assert bus.snapshot("system.notifications") is not None

    subscribed.topics.clear()
    await bus.publish("system.notifications", "notice", {"message": "second"})
    assert subscribed.queue.empty()


@pytest.mark.asyncio
async def test_realtime_valkey_fanout_crosses_bus_instances(monkeypatch) -> None:
    broker = FakeBroker()
    cache_a = MemoryCache()
    cache_b = MemoryCache()
    settings = ValkeySettings(url="redis://127.0.0.1:1")
    bus_a = RealtimeBus(cache_a, settings)  # type: ignore[arg-type]
    bus_b = RealtimeBus(cache_b, settings)  # type: ignore[arg-type]
    monkeypatch.setattr(bus_a, "_redis", broker.client())
    monkeypatch.setattr(bus_b, "_redis", broker.client())
    subscriber = bus_b.register()
    subscriber.topics.add("management.events")
    bus_a.start()
    bus_b.start()
    await asyncio.sleep(0.05)

    await bus_a.publish("management.events", "test.event", {"value": 7})
    received = await asyncio.wait_for(subscriber.queue.get(), timeout=2)

    assert received["topic"] == "management.events"
    assert received["type"] == "test.event"
    assert received["data"] == {"value": 7}
    await bus_a.close()
    await bus_b.close()


def test_realtime_websocket_uses_management_session(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _engine, services, _reverse, web, _telemetry = _build_services(tmp_path, settings)
    cache = MemoryCache()
    bus = RealtimeBus(cache, ValkeySettings(url="redis://127.0.0.1:1"))  # type: ignore[arg-type]
    monkeypatch.setattr(bus, "_redis", FakeRedis())
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    app.include_router(build_admin_api_router(settings, services))
    app.include_router(
        build_realtime_router(settings, bus, services.audit, services.snapshots, web)
    )

    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as unauthorized,
            client.websocket_connect("/admin/api/realtime"),
        ):
            pass
        assert unauthorized.value.code == 4401

        _login(client)
        with client.websocket_connect("/admin/api/realtime") as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            websocket.send_json({"type": "subscribe", "topics": ["system.notifications"]})
            subscribed = websocket.receive_json()
            assert subscribed == {
                "version": 1,
                "type": "subscribed",
                "topics": ["system.notifications"],
            }
            websocket.send_json({"type": "unsubscribe", "topic": "system.notifications"})
            unsubscribed = websocket.receive_json()
            assert unsubscribed == {"version": 1, "type": "unsubscribed", "topics": []}


def test_browser_operator_api_websocket_uses_management_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _engine, services, _reverse, _web, _telemetry = _build_services(tmp_path, settings)
    relayed: list[dict[str, object]] = []

    async def fake_relay(websocket, target_url, **kwargs):
        relayed.append({"target_url": target_url, **kwargs})
        await websocket.accept()
        await websocket.send_json({"type": "relay-ready"})
        await websocket.close()

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    app.include_router(build_admin_api_router(settings, services))
    app.include_router(build_browser_operator_api_router(settings, relay=fake_relay))

    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as unauthorized,
            client.websocket_connect("/admin/api/browser/operator/ws"),
        ):
            pass
        assert unauthorized.value.code == 4401

        _login(client)
        with client.websocket_connect("/admin/api/browser/operator/ws") as websocket:
            assert websocket.receive_json() == {"type": "relay-ready"}

    assert relayed == [
        {
            "target_url": "ws://web:8000/operator/ws",
            "headers": {"Authorization": "Bearer service-token"},
        }
    ]


def test_legacy_starlette_admin_remains_mounted() -> None:
    source = Path("src/management/runtime.py").read_text()
    assert "build_admin(" in source
    assert "admin.mount_to(app)" in source


def test_admin_api_unhandled_error_is_json_500(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)
    install_admin_api_error_handlers(app)

    @app.get("/admin/api/fail")
    async def fail():
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/admin/api/fail")
        assert response.status_code == 500
        assert response.json() == {
            "error": {
                "version": 1,
                "code": "internal_error",
                "message": "internal server error",
                "status": 500,
            }
        }


def test_realtime_call_publish_respects_capture_policy_and_redacts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine, sessions = create_database(settings.database_url)
    Base.metadata.create_all(engine)
    with sessions.begin() as session:
        session.add(ManagementConfigRecord(id=1, logging_capture_payloads=False))
    config = ManagementConfigService(SqlAlchemyManagementConfigRepository(sessions))
    published: list[tuple[str, str, object]] = []
    audit = InvocationAuditService(
        SqlAlchemyInvocationRepository(sessions),
        config,
        publisher=lambda topic, kind, data: published.append((topic, kind, data)),
    )
    from management.domain.telemetry import Invocation

    audit.record(
        Invocation(
            module="github",
            tool="example",
            status="error",
            duration_ms=1.0,
            arguments_json='{"authorization":"Bearer super-secret"}',
            result_json='{"token":"hidden"}',
            error_message="Bearer error-secret",
        )
    )

    assert len(published) == 1
    topic, kind, data = published[0]
    assert topic == "mcp.calls"
    assert kind == "batch"
    rendered = repr(data)
    assert "super-secret" not in rendered
    assert "hidden" not in rendered
    assert "error-secret" not in rendered
    assert "arguments_json': ''" in rendered
    engine.dispose()

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.websockets import WebSocket

from common.cache import SharedCache
from common.observability import announce_runtime_started, build_observability
from common.settings import FileSettings, ManagementSettings, ValkeySettings
from common.websocket_proxy import relay_websocket
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from management.browser_operator_auth import (
    BrowserOperatorAuthError,
    verify_browser_operator_ticket,
)
from management.infrastructure.crypto import FernetCredentialCipher
from management.infrastructure.database import (
    create_database,
    ensure_zero_state_schema,
)
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
from management.infrastructure.reverse import ReverseAdminClient
from management.infrastructure.snapshot_worker import SnapshotRefresher
from management.presentation.admin import build_admin
from management.presentation.api import ApiServices, build_internal_router
from management.presentation.web_api import build_admin_api_router

logger = logging.getLogger(__name__)

settings = ManagementSettings()
settings.validate_bootstrap()
_observability = build_observability("management")
announce_runtime_started(_observability, "management")
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine, sessions = create_database(settings.database_url)
if ensure_zero_state_schema(engine):
    logger.info("management schema initialized missing tables")

cache_settings = ValkeySettings()
shared_cache = SharedCache(cache_settings)
cipher = FernetCredentialCipher(settings.encryption_key)
account_repository = SqlAlchemyAccountRepository(sessions)
invocation_repository = SqlAlchemyInvocationRepository(sessions)
config_repository = SqlAlchemyManagementConfigRepository(sessions)
runtime_settings_repository = SqlAlchemyRuntimeSettingsRepository(sessions)
oauth_session_repository = SqlAlchemyOAuthSessionRepository(sessions)
snapshot_repository = SqlAlchemySnapshotRepository(sessions)
config_service = ManagementConfigService(
    config_repository, cache=shared_cache, cache_settings=cache_settings
)
runtime_settings = RuntimeSettingsService(
    runtime_settings_repository, cache=shared_cache, cache_settings=cache_settings
)
oauth_sessions = OAuthSessionService(oauth_session_repository)
snapshots = SnapshotService(snapshot_repository)
config_service.get()
accounts = AccountService(
    account_repository,
    cipher,
    ProviderConnectionVerifier(),
    cache=shared_cache,
    cache_settings=cache_settings,
)
audit = InvocationAuditService(invocation_repository, config_service)
files = FileAdminStore(FileSettings())
reverse = ReverseAdminClient()
snapshot_refresher = SnapshotRefresher(snapshots, files, reverse)


async def _maintenance_loop() -> None:
    interval_seconds = 3600
    while True:
        try:
            config = await asyncio.to_thread(config_service.get)
            interval_seconds = config.maintenance_interval_minutes * 60
            logger.info(
                "management cleanup scan started retention_days=%d "
                "max_records=%d interval_minutes=%d",
                config.logging_retention_days,
                config.logging_max_records,
                config.maintenance_interval_minutes,
            )
            removed = await asyncio.to_thread(audit.cleanup)
            logger.info(
                "management cleanup scan completed reason=retention_or_max_records "
                "removed_records=%d",
                removed,
            )
        except Exception:
            logger.exception("management maintenance cycle failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await snapshot_refresher.ensure_base_snapshots()
    tasks = [
        asyncio.create_task(_maintenance_loop(), name="management-maintenance"),
        asyncio.create_task(
            snapshot_refresher.workspace_loop(),
            name="management-workspace-snapshots",
        ),
        asyncio.create_task(
            snapshot_refresher.reverse_loop(),
            name="management-reverse-snapshots",
        ),
        asyncio.create_task(
            snapshot_refresher.coverage_loop(),
            name="management-coverage-snapshots",
        ),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="MCP Management",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    middleware=[
        Middleware(
            SessionMiddleware,
            secret_key=settings.session_secret,
            https_only=settings.session_https_only,
            same_site="lax",
        )
    ],
)
app.include_router(
    build_internal_router(
        ApiServices(
            accounts=accounts,
            audit=audit,
            oauth_sessions=oauth_sessions,
            runtime_settings=runtime_settings,
            service_token=settings.service_token,
        )
    )
)
app.include_router(build_admin_api_router(settings))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/admin/browser/ws")
async def browser_operator_socket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin", "")
    public_host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host", "")
    if origin and urlsplit(origin).netloc.casefold() != public_host.casefold():
        await websocket.close(code=4403)
        return

    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        message = json.loads(raw)
        if not isinstance(message, dict) or message.get("type") != "auth":
            raise BrowserOperatorAuthError("browser operator auth message is required")
        verify_browser_operator_ticket(
            str(message.get("ticket") or ""),
            settings.session_secret,
            settings.admin_username,
        )
    except (
        TimeoutError,
        json.JSONDecodeError,
        BrowserOperatorAuthError,
    ):
        await websocket.close(code=4401)
        return

    await relay_websocket(
        websocket,
        "ws://web:8000/operator/ws",
        headers={"Authorization": f"Bearer {settings.service_token}"},
        accept_downstream=False,
    )


admin = build_admin(
    engine,
    settings,
    cipher,
    accounts,
    audit,
    oauth_sessions,
    snapshots,
    config_service,
    runtime_settings,
    files,
    reverse,
    base_url="/admin/legacy",
)
admin.mount_to(app)

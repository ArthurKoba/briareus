from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from admin_api.api_errors import install_admin_api_error_handlers
from admin_api.application.services import (
    AccountService,
    AdminConfigService,
    InvocationAuditService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from admin_api.browser_api import build_browser_operator_api_router
from admin_api.dashboard_state import build_dashboard_state
from admin_api.infrastructure.crypto import FernetCredentialCipher
from admin_api.infrastructure.database import (
    create_database,
    ensure_zero_state_schema,
)
from admin_api.infrastructure.files import FileAdminStore
from admin_api.infrastructure.provider_checks import ProviderConnectionVerifier
from admin_api.infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyAdminConfigRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyOAuthSessionRepository,
    SqlAlchemyRuntimeSettingsRepository,
    SqlAlchemySnapshotRepository,
)
from admin_api.infrastructure.reverse import ReverseAdminClient
from admin_api.infrastructure.snapshot_worker import SnapshotRefresher
from admin_api.infrastructure.terminal import TerminalAdminClient
from admin_api.infrastructure.web import WebAdminClient
from admin_api.presentation.api import ApiServices, build_internal_router
from admin_api.presentation.web_api import WebApiServices, build_admin_api_router
from admin_api.realtime import RealtimeBus
from admin_api.realtime_api import build_realtime_router
from admin_api.telemetry_ingest import FrontendTelemetryProxy, TelemetryUpstream
from common.cache import SharedCache
from common.observability import announce_runtime_started, build_observability
from common.settings import AdminApiSettings, FileSettings, ValkeySettings

logger = logging.getLogger(__name__)

settings = AdminApiSettings()
settings.validate_bootstrap()
_observability = build_observability("admin-api")
announce_runtime_started(_observability, "admin-api")
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine, sessions = create_database(settings.database_url)
if ensure_zero_state_schema(engine):
    logger.info("admin-api schema initialized missing tables")

cache_settings = ValkeySettings()
shared_cache = SharedCache(cache_settings)
realtime = RealtimeBus(shared_cache, cache_settings)
telemetry = FrontendTelemetryProxy(
    TelemetryUpstream(
        url=settings.frontend_telemetry_upstream_url,
        bearer_token=settings.frontend_telemetry_bearer_token,
    )
)
cipher = FernetCredentialCipher(settings.encryption_key)
account_repository = SqlAlchemyAccountRepository(sessions)
invocation_repository = SqlAlchemyInvocationRepository(sessions)
config_repository = SqlAlchemyAdminConfigRepository(sessions)
runtime_settings_repository = SqlAlchemyRuntimeSettingsRepository(sessions)
oauth_session_repository = SqlAlchemyOAuthSessionRepository(sessions)
snapshot_repository = SqlAlchemySnapshotRepository(sessions)
config_service = AdminConfigService(
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
    publisher=realtime.publish_sync,
)
audit = InvocationAuditService(
    invocation_repository, config_service, publisher=realtime.publish_sync
)
files = FileAdminStore(FileSettings())
reverse = ReverseAdminClient()
snapshot_refresher = SnapshotRefresher(snapshots, files, reverse)
terminal = TerminalAdminClient()
web_admin = WebAdminClient()


async def _realtime_state_loop() -> None:
    while True:
        try:
            dashboard_state = await build_dashboard_state(
                accounts, audit, oauth_sessions, snapshots
            )
            await realtime.publish("system.metrics", "snapshot", dashboard_state)
            try:
                browser_state = await web_admin.status()
            except Exception as exc:
                browser_state = {"available": False, "error": str(exc)}
            await realtime.publish("browser.runtime", "state", browser_state)
        except Exception:
            logger.exception("admin_api realtime state refresh failed")
        await asyncio.sleep(10)


async def _maintenance_loop() -> None:
    interval_seconds = 3600
    while True:
        try:
            config = await asyncio.to_thread(config_service.get)
            interval_seconds = config.maintenance_interval_minutes * 60
            logger.info(
                "admin_api cleanup scan started retention_days=%d "
                "max_records=%d interval_minutes=%d",
                config.logging_retention_days,
                config.logging_max_records,
                config.maintenance_interval_minutes,
            )
            removed = await asyncio.to_thread(audit.cleanup)
            logger.info(
                "admin_api cleanup scan completed reason=retention_or_max_records "
                "removed_records=%d",
                removed,
            )
        except Exception:
            logger.exception("admin_api maintenance cycle failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    realtime.start()
    telemetry.start()
    await snapshot_refresher.ensure_base_snapshots()
    tasks = [
        asyncio.create_task(_realtime_state_loop(), name="admin-api-realtime-state"),
        asyncio.create_task(_maintenance_loop(), name="admin-api-maintenance"),
        asyncio.create_task(
            snapshot_refresher.workspace_loop(),
            name="admin-api-workspace-snapshots",
        ),
        asyncio.create_task(
            snapshot_refresher.reverse_loop(),
            name="admin-api-reverse-snapshots",
        ),
        asyncio.create_task(
            snapshot_refresher.coverage_loop(),
            name="admin-api-coverage-snapshots",
        ),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await telemetry.close()
        await realtime.close()
        await web_admin.close()


app = FastAPI(
    title="MCP Admin API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=[settings.admin_ui_origin] if settings.admin_ui_origin else [],
            allow_credentials=True,
            allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        ),
        Middleware(
            SessionMiddleware,
            secret_key=settings.session_secret,
            https_only=settings.session_https_only,
            same_site="lax",
        ),
    ],
)


install_admin_api_error_handlers(app)

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
app.include_router(
    build_admin_api_router(
        settings,
        WebApiServices(
            accounts=accounts,
            audit=audit,
            oauth_sessions=oauth_sessions,
            snapshots=snapshots,
            config=config_service,
            runtime_settings=runtime_settings,
            files=files,
            reverse=reverse,
            terminal=terminal,
            web=web_admin,
            snapshot_refresher=snapshot_refresher,
            realtime=realtime,
            telemetry=telemetry,
        ),
    )
)
app.include_router(
    build_realtime_router(settings, realtime, accounts, audit, oauth_sessions, snapshots, web_admin)
)
app.include_router(build_browser_operator_api_router(settings))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from api_errors import install_admin_api_error_handlers
from application.services import (
    AccountService,
    AdminConfigService,
    InvocationAuditService,
    OAuthSessionService,
    RuntimeSettingsService,
    SnapshotService,
)
from browser_api import build_browser_operator_api_router
from dashboard_state import build_dashboard_state
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from infrastructure.authorization_access import AuthorizationAccessAdminClient
from infrastructure.authorization_identity import AuthorizationIdentityClient
from infrastructure.crypto import FernetCredentialCipher
from infrastructure.database import DatabaseManager
from infrastructure.files import FileAdminStore
from infrastructure.provider_checks import ProviderConnectionVerifier
from infrastructure.repositories import (
    SqlAlchemyAccountRepository,
    SqlAlchemyAdminConfigRepository,
    SqlAlchemyInvocationRepository,
    SqlAlchemyOAuthSessionRepository,
    SqlAlchemyRuntimeSettingsRepository,
    SqlAlchemySnapshotRepository,
)
from infrastructure.reverse import ReverseAdminClient
from infrastructure.snapshot_worker import SnapshotRefresher
from infrastructure.terminal import TerminalAdminClient
from infrastructure.web import WebAdminClient
from presentation.api import ApiServices, build_internal_router
from presentation.web_api import WebApiServices, build_admin_api_router
from realtime import RealtimeBus
from realtime_api import build_realtime_router
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from telemetry_ingest import FrontendTelemetryProxy

from common.cache import SharedCache
from common.observability import announce_runtime_started, build_observability
from common.settings import AdminApiSettings, FileSettings, ObservabilitySettings, ValkeySettings

logger = logging.getLogger(__name__)

settings = AdminApiSettings()
settings.validate_bootstrap()
observability_settings = ObservabilitySettings()
_observability = build_observability("admin-api", settings=observability_settings)
announce_runtime_started(_observability, "admin-api")
database = DatabaseManager(
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
    username=settings.postgres_user,
    password=settings.postgres_password,
)
sessions = database.sessions

cache_settings = ValkeySettings()
shared_cache = SharedCache(cache_settings)
realtime = RealtimeBus(shared_cache, cache_settings)
telemetry = FrontendTelemetryProxy(observability_settings)
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
    runtime_settings_repository,
    cipher=cipher,
    cache=shared_cache,
    cache_settings=cache_settings,
)
oauth_sessions = OAuthSessionService(oauth_session_repository)
snapshots = SnapshotService(snapshot_repository)
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
authorization_access_admin = AuthorizationAccessAdminClient(
    base_url=settings.authorization_internal_url.rstrip("/") + "/internal/access",
    service_token=settings.authorization_admin_service_token,
)
authorization_identity = AuthorizationIdentityClient(
    base_url=settings.authorization_internal_url,
    service_token=settings.authorization_admin_service_token,
)


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
            config = await config_service.get()
            interval_seconds = config.maintenance_interval_minutes * 60
            logger.info(
                "admin_api cleanup scan started retention_days=%d "
                "max_records=%d interval_minutes=%d",
                config.logging_retention_days,
                config.logging_max_records,
                config.maintenance_interval_minutes,
            )
            removed = await audit.cleanup()
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
    if await database.ensure_schema():
        logger.info("admin-api PostgreSQL schema initialized missing tables")
    await config_service.get()
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
        await authorization_access_admin.close()
        await authorization_identity.close()
        await database.dispose()


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
            authorization_access=authorization_access_admin,
            authorization_identity=authorization_identity,
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

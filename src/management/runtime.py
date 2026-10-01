from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware

from common.observability import announce_runtime_started, build_observability
from common.settings import FileSettings, ManagementSettings
from management.application.services import (
    AccountService,
    InvocationAuditService,
    ManagementConfigService,
    OAuthSessionService,
    SnapshotService,
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
    SqlAlchemySnapshotRepository,
)
from management.infrastructure.reverse import ReverseAdminClient
from management.infrastructure.snapshot_worker import SnapshotRefresher
from management.presentation.admin import build_admin
from management.presentation.api import ApiServices, build_internal_router

logger = logging.getLogger(__name__)

settings = ManagementSettings()
settings.validate_bootstrap()
_observability = build_observability("management")
announce_runtime_started(_observability, "management")
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
engine, sessions = create_database(settings.database_url)
if ensure_zero_state_schema(engine):
    logger.info("management schema initialized missing tables")

cipher = FernetCredentialCipher(settings.encryption_key)
account_repository = SqlAlchemyAccountRepository(sessions)
invocation_repository = SqlAlchemyInvocationRepository(sessions)
config_repository = SqlAlchemyManagementConfigRepository(sessions)
oauth_session_repository = SqlAlchemyOAuthSessionRepository(sessions)
snapshot_repository = SqlAlchemySnapshotRepository(sessions)
config_service = ManagementConfigService(config_repository)
oauth_sessions = OAuthSessionService(oauth_session_repository)
snapshots = SnapshotService(snapshot_repository)
config_service.get()
accounts = AccountService(account_repository, cipher, ProviderConnectionVerifier())
audit = InvocationAuditService(invocation_repository)
files = FileAdminStore(FileSettings())
reverse = ReverseAdminClient()
snapshot_refresher = SnapshotRefresher(snapshots, files, reverse)


async def _maintenance_loop() -> None:
    interval_seconds = 3600
    while True:
        try:
            config = await asyncio.to_thread(config_service.get)
            interval_seconds = config.maintenance_interval_minutes * 60
            await asyncio.to_thread(audit.cleanup)
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
            service_token=settings.service_token,
        )
    )
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


admin = build_admin(
    engine,
    settings,
    cipher,
    accounts,
    audit,
    oauth_sessions,
    snapshots,
    config_service,
    files,
    reverse,
)
admin.mount_to(app)

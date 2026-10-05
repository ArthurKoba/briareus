from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.cache import SharedCache
from common.observability import announce_runtime_started, build_observability
from common.settings import AccessServiceSettings, ValkeySettings

from .api import build_access_app
from .database import AccessDatabase
from .repository import AccessRepository
from .service import AccessService

settings = AccessServiceSettings()
settings.validate_bootstrap()
cache_settings = ValkeySettings()
_observability = build_observability("access")
announce_runtime_started(_observability, "access")

database = AccessDatabase(
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
    username=settings.postgres_user,
    password=settings.postgres_password,
)
repository = AccessRepository(database)
cache = SharedCache(cache_settings)
service = AccessService(
    settings=settings,
    repository=repository,
    cache=cache,
    cache_settings=cache_settings,
)
_inner = build_access_app(service, settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await database.ensure_schema()
    try:
        yield
    finally:
        await service.close()
        await database.dispose()


app = FastAPI(
    routes=list(_inner.routes),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette

from common.observability import announce_runtime_started, build_observability
from common.settings import AuthServiceSettings

from .api import build_auth_app
from .database import AuthDatabase
from .provider import LocalOAuthProvider
from .repository import AuthRepository

settings = AuthServiceSettings()
settings.validate_bootstrap()
_observability = build_observability("auth")
announce_runtime_started(_observability, "auth")

database = AuthDatabase(
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
    username=settings.postgres_user,
    password=settings.postgres_password,
)
repository = AuthRepository(database)
provider = LocalOAuthProvider(settings, repository)
_oauth_app = build_auth_app(provider)


@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    await database.ensure_schema()
    await repository.ensure_bootstrap_user(
        settings.bootstrap_username,
        settings.bootstrap_password,
    )
    try:
        yield
    finally:
        await database.dispose()


app = Starlette(routes=list(_oauth_app.routes), lifespan=lifespan)

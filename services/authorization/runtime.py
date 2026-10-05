from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount

from common.cache import SharedCache
from common.observability import announce_runtime_started, build_observability
from common.settings import AuthorizationServiceSettings, ValkeySettings

from .access.api import build_access_app
from .access.database import AccessDatabase
from .access.events import AccessEventPublisher
from .access.repository import AccessRepository
from .access.service import AccessControl
from .api import build_authorization_app
from .database import AuthorizationDatabase
from .provider import LocalOAuthProvider
from .repository import AuthorizationRepository

settings = AuthorizationServiceSettings()
settings.validate_bootstrap()
cache_settings = ValkeySettings()
_observability = build_observability("authorization")
announce_runtime_started(_observability, "authorization")

# OAuth identity and agent-access state are one authorization bounded context and use the
# same PostgreSQL database/role. Separate metadata modules keep the code clear
# without creating a second deployable service.
database = AuthorizationDatabase(
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
    username=settings.postgres_user,
    password=settings.postgres_password,
)
repository = AuthorizationRepository(database)
provider = LocalOAuthProvider(settings, repository)

access_database = AccessDatabase(
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
    username=settings.postgres_user,
    password=settings.postgres_password,
)
access_repository = AccessRepository(access_database)
cache = SharedCache(cache_settings)
access_events = AccessEventPublisher(cache, cache_settings)
access_control = AccessControl(
    settings=settings,
    repository=access_repository,
    cache=cache,
    cache_settings=cache_settings,
    events=access_events,
    revoke_oauth_session=repository.revoke_oauth_session,
)

_oauth_app = build_authorization_app(provider)
_access_app = build_access_app(access_control, settings)


@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    await database.ensure_schema()
    await access_database.ensure_schema()
    await repository.ensure_bootstrap_user(
        settings.bootstrap_username,
        settings.bootstrap_password,
    )
    try:
        yield
    finally:
        await access_control.close()
        await access_database.dispose()
        await database.dispose()


app = Starlette(
    routes=[
        *_oauth_app.routes,
        Mount("/internal/access", app=_access_app),
    ],
    lifespan=lifespan,
)

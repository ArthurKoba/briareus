"""Identity owns briareus_identity and its Alembic startup lifecycle."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from common.owner_runtime import create_owner_app
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from identity._service import IdentityService
from identity._settings import IdentityLinkSettings
from identity.direct_first_user import DirectFirstUserIdentity
from identity.first_user_http_api import build_first_user_http_api

if TYPE_CHECKING:
    from common.owner_runtime import OwnerIngressVerifier
    from common.platform_db import OwnerDatabaseSettings
    from identity._private_current_user import IdentityCurrentUserSource
    from identity._private_onboarding import (
        IdentityPrivateInvitationRegistration,
        RestrictedFirstAdminCodeDelivery,
    )
    from identity.private_login_source import IdentityPrivateLoginSource


app = create_owner_app("identity")
_owner_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _direct_first_user_lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Identity owner migrations precede any direct first-user HTTP operation."""
    async with _owner_lifespan(application):
        settings = OwnerDatabaseSettings(owner="identity")
        database = PlatformDatabase(settings)
        try:
            application.state.first_user = DirectFirstUserIdentity(
                identity=IdentityService(database, IdentityLinkSettings()),
                database=database,
            )
            yield
        finally:
            application.state.first_user = None
            await database.close()


app.router.lifespan_context = _direct_first_user_lifespan
app.include_router(build_first_user_http_api())


def create_trusted_private_identity_app(
    login: IdentityPrivateLoginSource,
    *,
    db_settings: OwnerDatabaseSettings,
    trusted_ingress: OwnerIngressVerifier,
    current_users: IdentityCurrentUserSource,
    registration: IdentityPrivateInvitationRegistration,
    operator_delivery: RestrictedFirstAdminCodeDelivery | None = None,
    operator_listener: socket.socket | None = None,
) -> FastAPI:
    """Source-only private first-login/logout; normal owner app unchanged."""
    from identity.private_login_source import create_unmounted_identity_private_app

    return create_unmounted_identity_private_app(
        login,
        db_settings=db_settings,
        trusted_ingress=trusted_ingress,
        current_users=current_users,
        registration=registration,
        operator_delivery=operator_delivery,
        operator_listener=operator_listener,
    )

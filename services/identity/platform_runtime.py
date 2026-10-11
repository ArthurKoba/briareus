"""Identity owns briareus_identity and its Alembic startup lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from common.owner_runtime import create_owner_app

if TYPE_CHECKING:
    from common.owner_runtime import OwnerIngressVerifier
    from common.platform_db import OwnerDatabaseSettings
    from identity._private_current_user import IdentityCurrentUserSource
    from identity.private_login_source import IdentityPrivateLoginSource


app = create_owner_app("identity")


def create_trusted_private_identity_app(
    login: IdentityPrivateLoginSource,
    *,
    db_settings: OwnerDatabaseSettings,
    trusted_ingress: OwnerIngressVerifier,
    current_users: IdentityCurrentUserSource,
) -> FastAPI:
    """Source-only private first-login/logout; normal owner app unchanged."""
    from identity.private_login_source import create_unmounted_identity_private_app

    return create_unmounted_identity_private_app(
        login, db_settings=db_settings, trusted_ingress=trusted_ingress, current_users=current_users
    )

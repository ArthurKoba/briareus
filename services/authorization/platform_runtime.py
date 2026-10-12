"""Independent Access/Cedar service; never depends on the management API/UI.

The private decision endpoint is fail-closed until Deployment/Runtime wires
verified Rauthy+peer and Project membership ports. Health is not permission.
A successful image build does not activate unconfigured decision trust.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from authorization._decision_api import (
    AuthorizationDecisionReader,
    AuthorizationDecisionService,
    TrustedDecisionAttestor,
    authorization_decision_router,
)
from common.owner_migrations import verify_owner
from common.owner_runtime import OwnerIngressVerifier, create_owner_app
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase


def create_authorization_app(
    decision_service: AuthorizationDecisionService | None = None,
    *,
    trusted_attestor: TrustedDecisionAttestor | None = None,
    trusted_ingress: OwnerIngressVerifier | None = None,
) -> FastAPI:
    app = create_owner_app("access", trusted_ingress=trusted_ingress)
    database: PlatformDatabase | None = None
    owner_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def decision_lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        nonlocal database
        async with owner_lifespan(current_app):
            if trusted_attestor is None or trusted_ingress is None:
                yield
                return
            # Activate a private read pool only after the owner lifespan has
            # migrated and verified its schema and authenticated ingress.
            local = OwnerDatabaseSettings(owner="access")
            read_database = PlatformDatabase(local)
            try:
                await verify_owner(read_database, local)
                database = read_database
                yield
            finally:
                database = None
                await read_database.close()

    app.router.lifespan_context = decision_lifespan

    def verified_service(_request: Request) -> AuthorizationDecisionService | None:
        # A trusted, independently configured process adapter is mandatory.
        # An incomplete OAuth/peer/Project cutover never enables decisions.
        if trusted_attestor is None or trusted_ingress is None:
            return None
        if database is None:
            return None
        return AuthorizationDecisionService(
            trusted_attestor, AuthorizationDecisionReader(database)
        )

    app.include_router(
        authorization_decision_router(decision_service, resolve_service=verified_service)
    )
    return app


app = create_authorization_app()

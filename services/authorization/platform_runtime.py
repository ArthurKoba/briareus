"""Independent Access/Cedar service; never depends on the Control Panel API/UI.

The private decision endpoint is fail-closed until Deployment/Runtime wires
verified Rauthy+peer and Project membership ports. Health is not permission.
A successful image build does not activate unconfigured decision trust.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import SecretStr

from authorization._approval_read_api import (
    ApprovalListReader,
    TrustedApprovalListAttestor,
    private_approval_list_router,
)
from authorization._decision_api import (
    AuthorizationDecisionReader,
    AuthorizationDecisionService,
    TrustedDecisionAttestor,
    authorization_decision_router,
)
from authorization._files_read_decision import FilesReadDecisionService, files_read_decision_router
from authorization._idempotency import IdempotentCommandExecutor
from authorization._rauthy_access_command_api import rauthy_access_command_router
from authorization._rauthy_access_commands import (
    AccessRauthyCommandService,
    TrustedAccessCommandAttestor,
)
from authorization._resource_scope import TrustedResourceOwnerPort
from common.owner_migrations import verify_owner
from common.owner_runtime import OwnerIngressVerifier, create_owner_app
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase


def create_authorization_app(
    decision_service: AuthorizationDecisionService | None = None,
    *,
    trusted_attestor: TrustedDecisionAttestor | None = None,
    trusted_approvals: TrustedApprovalListAttestor | None = None,
    trusted_commands: TrustedAccessCommandAttestor | None = None,
    command_encryption_key: SecretStr | None = None,
    current_resource_owners: TrustedResourceOwnerPort | None = None,
    trusted_ingress: OwnerIngressVerifier | None = None,
) -> FastAPI:
    app = create_owner_app("access", trusted_ingress=trusted_ingress)
    database: PlatformDatabase | None = None
    idempotency: IdempotentCommandExecutor | None = None
    owner_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def decision_lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        nonlocal database, idempotency
        async with owner_lifespan(current_app):
            if trusted_ingress is None or (
                trusted_attestor is None
                and trusted_approvals is None
                and (trusted_commands is None or command_encryption_key is None)
            ):
                yield
                return
            # Activate a private read pool only after the owner lifespan has
            # migrated and verified its schema and authenticated ingress.
            local = OwnerDatabaseSettings(owner="access")
            read_database = PlatformDatabase(local)
            try:
                await verify_owner(read_database, local)
                database = read_database
                if trusted_commands is not None and command_encryption_key is not None:
                    idempotency = IdempotentCommandExecutor(
                        read_database, command_encryption_key.get_secret_value()
                    )
                yield
            finally:
                idempotency = None
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
        return AuthorizationDecisionService(trusted_attestor, AuthorizationDecisionReader(database))

    app.include_router(
        authorization_decision_router(decision_service, resolve_service=verified_service)
    )

    def verified_approval_reader() -> ApprovalListReader | None:
        if database is None or trusted_ingress is None or trusted_approvals is None:
            return None
        return ApprovalListReader(database=database, attestor=trusted_approvals)

    app.include_router(private_approval_list_router(resolve_reader=verified_approval_reader))

    def verified_command_service() -> AccessRauthyCommandService | None:
        if (
            database is None
            or trusted_ingress is None
            or trusted_commands is None
            or idempotency is None
        ):
            return None
        return AccessRauthyCommandService(
            database=database,
            idempotency=idempotency,
            attestor=trusted_commands,
            resource_owner=current_resource_owners,
        )

    app.include_router(rauthy_access_command_router(resolve_service=verified_command_service))

    def verified_files_read_service() -> FilesReadDecisionService | None:
        if (
            database is None
            or trusted_ingress is None
            or trusted_attestor is None
            or current_resource_owners is None
        ):
            return None
        return FilesReadDecisionService(
            attestor=trusted_attestor,
            reader=AuthorizationDecisionReader(database),
            resource_owner=current_resource_owners,
        )

    app.include_router(files_read_decision_router(resolve_service=verified_files_read_service))
    return app


app = create_authorization_app()

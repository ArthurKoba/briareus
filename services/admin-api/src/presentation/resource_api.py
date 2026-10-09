# ruff: noqa: B008  # FastAPI dependencies and Header descriptors
"""Unmounted C1-B Team/Project reusable-resource Admin REST shape.

Build only from build_unmounted_platform_router; no live route is activated.
The verified caller dependency is supplied by the parent and MUST never be
satisfied from unsigned headers or the historical username session cookie.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._platform_permissions import project_permit, team_permit
from authorization._project_access import CallerPrincipal
from common.platform_errors import AccessDenied, InvalidInput
from common.platform_ids import PlatformProjectId, TeamId
from projects._provider_registry import provider_auth_types, provider_names
from projects._resource_domain import (
    EffectiveResource,
    OwnerScope,
    ResourceKind,
    ResourceOwner,
    ResourceScope,
)
from projects._resource_persistence import IntegrationRow, VariableRow
from projects._resource_service import ResourceService, owner_of


class ResourceApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceView(ResourceApiModel):
    resource_id: UUID
    kind: ResourceKind
    name: str
    version: int
    project_access_revision: str | None = None
    team_access_revision: str | None = None
    owner_scope: OwnerScope
    owner_id: UUID
    origin: OwnerScope
    inherited: bool
    is_secret: bool
    masked: bool
    provider: str | None = None
    auth_type: str | None = None
    display_name: str = ""
    provider_settings: dict[str, Any] | None = None
    credential_configured: bool = False
    connection_status: str | None = None
    updated_at: datetime | None = None
    value: str | None = None

    @classmethod
    def from_effective(
        cls,
        resource: EffectiveResource,
        *,
        project_access_revision: str | None = None,
        team_access_revision: str | None = None,
    ) -> ResourceView:
        return cls(
            resource_id=resource.resource_id,
            kind=resource.kind,
            name=resource.name,
            version=resource.version,
            project_access_revision=project_access_revision,
            team_access_revision=team_access_revision,
            owner_scope=resource.owner.scope,
            owner_id=resource.owner.owner_id,
            origin=resource.origin,
            inherited=resource.inherited,
            is_secret=resource.is_secret,
            masked=resource.is_secret,
            provider=resource.provider,
            auth_type=resource.auth_type,
            display_name=resource.display_name,
            provider_settings=resource.provider_settings,
            credential_configured=resource.credential_configured,
            connection_status=resource.connection_status,
            updated_at=resource.updated_at,
            value=None if resource.is_secret else resource.value,
        )


class ProviderCatalogEntry(ResourceApiModel):
    provider: str
    auth_types: list[str]
    connectivity_status: str = "unverified"


class ProviderCatalog(ResourceApiModel):
    providers: list[ProviderCatalogEntry]
    network_verification_available: bool = False


class ResourceOwnerInput(ResourceApiModel):
    owner_scope: OwnerScope
    owner_id: UUID

    def owner(self) -> ResourceOwner:
        return ResourceOwner(self.owner_scope, self.owner_id)


class CreateIntegration(ResourceOwnerInput):
    alias: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=32)
    auth_type: str = Field(min_length=1, max_length=32)
    provider_settings: dict[str, Any] = Field(default_factory=dict)
    credential: SecretStr = Field(min_length=1)


class UpdateIntegration(ResourceApiModel):
    expected_version: int = Field(ge=1)
    alias: str | None = Field(default=None, min_length=1, max_length=128)
    provider_settings: dict[str, Any] | None = None


class RotateIntegration(ResourceApiModel):
    expected_version: int = Field(ge=1)
    credential: SecretStr = Field(min_length=1)


class CreateVariable(ResourceOwnerInput):
    name: str = Field(min_length=1, max_length=128)
    value: SecretStr
    is_secret: bool = True


class UpdateVariable(ResourceApiModel):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)


class RotateVariable(ResourceApiModel):
    expected_version: int = Field(ge=1)
    value: SecretStr
    is_secret: bool = True


class DeleteResource(ResourceApiModel):
    expected_version: int = Field(ge=1)


class RevokedResource(ResourceApiModel):
    resource_id: UUID
    revoked: bool
    new_version: int


def build_unmounted_resource_router(
    *,
    resources: ResourceService,
    commands: IdempotentCommandExecutor,
    verified_caller: Callable[..., Awaitable[CallerPrincipal]],
) -> APIRouter:
    router = APIRouter(tags=["platform-resources-draft"])

    async def command(
        caller: CallerPrincipal,
        payload: ResourceApiModel,
        *,
        key: str | None,
        owner_scope: str,
        operation: str,
        execute: Callable[[AsyncSession], Awaitable[CommandOutcome]],
    ) -> dict[str, Any]:
        if key is None:
            raise InvalidInput("Idempotency-Key required for resource mutation")

        async def reauthorize(tx: AsyncSession) -> None:
            # Every retry is re-authorized at the same locked owner scope
            # before a stored idempotency response is decrypted/replayed.
            selector, _, qualified_id = owner_scope.partition(":")
            try:
                owner_id = UUID(qualified_id)
            except ValueError as exc:
                raise InvalidInput("invalid resource owner selector") from exc
            if selector == "team":
                owner = ResourceOwner(OwnerScope.TEAM, owner_id)
            elif selector == "project":
                owner = ResourceOwner(OwnerScope.PROJECT, owner_id)
            elif selector == "resource":
                if operation.startswith("integration."):
                    record = await tx.scalar(
                        select(IntegrationRow).where(IntegrationRow.id == owner_id)
                    )
                elif operation.startswith("variable."):
                    record = await tx.scalar(select(VariableRow).where(VariableRow.id == owner_id))
                else:
                    raise InvalidInput("unknown scoped resource operation")
                if record is None:
                    raise AccessDenied("resource unavailable")
                owner = owner_of(record)
            else:
                raise InvalidInput("unknown resource owner selector")
            await resources._check_owner(tx, caller, owner, lock=True)

        outcome = await commands.execute(
            actor_scope=str(caller.user_id),
            project_scope=owner_scope,
            operation=operation,
            key=key,
            payload=payload.model_dump(mode="python"),
            command=execute,
            reauthorize=reauthorize,
        )
        return outcome.body

    @router.get("/providers/catalog", response_model=ProviderCatalog)
    async def provider_catalog(
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> ProviderCatalog:
        async with resources.application.db.transaction() as tx:
            await resources.application.current_user(tx, caller)
            return ProviderCatalog(
                providers=[
                    ProviderCatalogEntry(
                        provider=name,
                        auth_types=list(provider_auth_types(name)),
                    )
                    for name in provider_names()
                ],
            )

    @router.get("/projects/{project_id}/integrations", response_model=list[ResourceView])
    async def list_project_integrations(
        project_id: UUID,
        scope: ResourceScope = Query(ResourceScope.ALL),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> object:
        async with resources.application.db.transaction() as tx:
            permit = await project_permit(
                tx, resources.application, caller, PlatformProjectId(project_id)
            )
            items = await resources.list_for_project(
                tx,
                caller,
                PlatformProjectId(project_id),
                ResourceKind.INTEGRATION,
                scope=scope,
            )
            return [
                ResourceView.from_effective(item, project_access_revision=permit.decision_version)
                for item in items
            ]

    @router.get("/projects/{project_id}/variables", response_model=list[ResourceView])
    async def list_project_variables(
        project_id: UUID,
        scope: ResourceScope = Query(ResourceScope.ALL),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> object:
        async with resources.application.db.transaction() as tx:
            permit = await project_permit(
                tx, resources.application, caller, PlatformProjectId(project_id)
            )
            items = await resources.list_for_project(
                tx,
                caller,
                PlatformProjectId(project_id),
                ResourceKind.VARIABLE,
                scope=scope,
            )
            return [
                ResourceView.from_effective(item, project_access_revision=permit.decision_version)
                for item in items
            ]

    @router.get("/teams/{team_id}/integrations", response_model=list[ResourceView])
    async def list_team_integrations(
        team_id: UUID,
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> object:
        async with resources.application.db.transaction() as tx:
            permit = await team_permit(tx, resources.application, caller, TeamId(team_id))
            items = await resources.list_for_team(
                tx, caller, TeamId(team_id), ResourceKind.INTEGRATION
            )
            return [
                ResourceView.from_effective(item, team_access_revision=permit.decision_version)
                for item in items
            ]

    @router.get("/teams/{team_id}/variables", response_model=list[ResourceView])
    async def list_team_variables(
        team_id: UUID,
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> object:
        async with resources.application.db.transaction() as tx:
            permit = await team_permit(tx, resources.application, caller, TeamId(team_id))
            items = await resources.list_for_team(
                tx, caller, TeamId(team_id), ResourceKind.VARIABLE
            )
            return [
                ResourceView.from_effective(item, team_access_revision=permit.decision_version)
                for item in items
            ]

    @router.get("/projects/{project_id}/integrations/resolve", response_model=ResourceView)
    async def resolve_project_integration(
        project_id: UUID,
        name: str | None = None,
        resource_id: UUID | None = None,
        scope: ResourceScope = Query(ResourceScope.ALL),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> object:
        async with resources.application.db.transaction() as tx:
            permit = await project_permit(
                tx, resources.application, caller, PlatformProjectId(project_id)
            )
            resolved = await resources.resolve_for_project(
                tx,
                caller,
                PlatformProjectId(project_id),
                ResourceKind.INTEGRATION,
                resource_id=resource_id,
                name=name,
                scope=scope,
            )
            return ResourceView.from_effective(
                resolved, project_access_revision=permit.decision_version
            )

    @router.get("/projects/{project_id}/variables/resolve", response_model=ResourceView)
    async def resolve_project_variable(
        project_id: UUID,
        name: str | None = None,
        resource_id: UUID | None = None,
        scope: ResourceScope = Query(ResourceScope.ALL),
        caller: CallerPrincipal = Depends(verified_caller),
    ) -> object:
        async with resources.application.db.transaction() as tx:
            permit = await project_permit(
                tx, resources.application, caller, PlatformProjectId(project_id)
            )
            resolved = await resources.resolve_for_project(
                tx,
                caller,
                PlatformProjectId(project_id),
                ResourceKind.VARIABLE,
                resource_id=resource_id,
                name=name,
                scope=scope,
            )
            return ResourceView.from_effective(
                resolved, project_access_revision=permit.decision_version
            )

    @router.post("/integrations", response_model=ResourceView, status_code=201)
    async def create_integration(
        body: CreateIntegration,
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.create_integration(
                tx,
                caller,
                owner=body.owner(),
                alias=body.alias,
                provider=body.provider,
                auth_type=body.auth_type,
                provider_settings=body.provider_settings,
                credential=body.credential.get_secret_value(),
            )
            return CommandOutcome(201, ResourceView.from_effective(item).model_dump(mode="json"))

        return await command(
            caller,
            body,
            key=key,
            owner_scope=f"{body.owner_scope.value}:{body.owner_id}",
            operation="integration.create",
            execute=run,
        )

    @router.patch("/integrations/{resource_id}", response_model=ResourceView)
    async def update_integration(
        resource_id: UUID,
        body: UpdateIntegration,
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.update_integration(
                tx,
                caller,
                resource_id,
                expected_version=body.expected_version,
                alias=body.alias,
                provider_settings=body.provider_settings,
            )
            return CommandOutcome(200, ResourceView.from_effective(item).model_dump(mode="json"))

        return await command(
            caller,
            body,
            key=key,
            owner_scope="resource:" + str(resource_id),
            operation="integration.update",
            execute=run,
        )

    @router.post("/integrations/{resource_id}/rotate", response_model=ResourceView)
    async def rotate_integration(
        resource_id: UUID,
        body: RotateIntegration,
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.rotate_integration(
                tx,
                caller,
                resource_id,
                expected_version=body.expected_version,
                credential=body.credential.get_secret_value(),
            )
            return CommandOutcome(200, ResourceView.from_effective(item).model_dump(mode="json"))

        return await command(
            caller,
            body,
            key=key,
            owner_scope="resource:" + str(resource_id),
            operation="integration.rotate",
            execute=run,
        )

    @router.delete("/integrations/{resource_id}", response_model=RevokedResource)
    async def revoke_integration(
        resource_id: UUID,
        expected_version: int = Header(alias="If-Match-Version", ge=1),
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        body = DeleteResource(expected_version=expected_version)

        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.revoke(
                tx,
                caller,
                resource_id,
                ResourceKind.INTEGRATION,
                expected_version=body.expected_version,
            )
            return CommandOutcome(
                200,
                RevokedResource(
                    resource_id=item.resource_id,
                    revoked=True,
                    new_version=item.version,
                ).model_dump(mode="json"),
            )

        return await command(
            caller,
            body,
            key=key,
            owner_scope="resource:" + str(resource_id),
            operation="integration.revoke",
            execute=run,
        )

    @router.post("/variables", response_model=ResourceView, status_code=201)
    async def create_variable(
        body: CreateVariable,
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.create_variable(
                tx,
                caller,
                owner=body.owner(),
                name=body.name,
                value=body.value.get_secret_value(),
                is_secret=body.is_secret,
            )
            return CommandOutcome(201, ResourceView.from_effective(item).model_dump(mode="json"))

        return await command(
            caller,
            body,
            key=key,
            owner_scope=f"{body.owner_scope.value}:{body.owner_id}",
            operation="variable.create",
            execute=run,
        )

    @router.patch("/variables/{resource_id}", response_model=ResourceView)
    async def update_variable(
        resource_id: UUID,
        body: UpdateVariable,
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.update_variable(
                tx,
                caller,
                resource_id,
                expected_version=body.expected_version,
                name=body.name,
            )
            return CommandOutcome(200, ResourceView.from_effective(item).model_dump(mode="json"))

        return await command(
            caller,
            body,
            key=key,
            owner_scope="resource:" + str(resource_id),
            operation="variable.update",
            execute=run,
        )

    @router.post("/variables/{resource_id}/rotate", response_model=ResourceView)
    async def rotate_variable(
        resource_id: UUID,
        body: RotateVariable,
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.rotate_variable(
                tx,
                caller,
                resource_id,
                expected_version=body.expected_version,
                value=body.value.get_secret_value(),
                is_secret=body.is_secret,
            )
            return CommandOutcome(200, ResourceView.from_effective(item).model_dump(mode="json"))

        return await command(
            caller,
            body,
            key=key,
            owner_scope="resource:" + str(resource_id),
            operation="variable.rotate",
            execute=run,
        )

    @router.delete("/variables/{resource_id}", response_model=RevokedResource)
    async def revoke_variable(
        resource_id: UUID,
        expected_version: int = Header(alias="If-Match-Version", ge=1),
        caller: CallerPrincipal = Depends(verified_caller),
        key: str = Header(alias="Idempotency-Key"),
    ) -> object:
        body = DeleteResource(expected_version=expected_version)

        async def run(tx: AsyncSession) -> CommandOutcome:
            item = await resources.revoke(
                tx,
                caller,
                resource_id,
                ResourceKind.VARIABLE,
                expected_version=body.expected_version,
            )
            return CommandOutcome(
                200,
                RevokedResource(
                    resource_id=item.resource_id,
                    revoked=True,
                    new_version=item.version,
                ).model_dump(mode="json"),
            )

        return await command(
            caller,
            body,
            key=key,
            owner_scope="resource:" + str(resource_id),
            operation="variable.revoke",
            execute=run,
        )

    return router

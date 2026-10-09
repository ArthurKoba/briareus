"""Read-only per-Project Coolify/SigNoz capability, no legacy account fallback."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from modules.project_runtime import (
    ProjectIntegrationRef,
    ProjectIntegrationSelector,
    ProjectInvocation,
)
from modules.project_runtime.credential_use import (
    ProjectProviderCapability,
    ProviderOperationReceipt,
)
from modules.project_runtime.resource_query import ResourceFilter

InfrastructureProvider = Literal["coolify", "signoz"]


class ProjectInfrastructureCapability:
    def __init__(
        self, providers: ProjectProviderCapability, integrations: ProjectIntegrationSelector
    ) -> None:
        self._providers = providers
        self._integrations = integrations

    async def connections(
        self,
        invocation: ProjectInvocation,
        *,
        provider: InfrastructureProvider,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
    ) -> tuple[ProjectIntegrationRef, ...]:
        return await self._integrations.list(
            invocation, provider=provider, scope=scope, owner_id=owner_id
        )

    async def read(
        self,
        invocation: ProjectInvocation,
        *,
        provider: InfrastructureProvider,
        resource_id: UUID,
        capability: str,
        request_id: UUID,
    ) -> ProviderOperationReceipt:
        return await self._providers.execute(
            invocation,
            resource_id=resource_id,
            provider=provider,
            capability=capability,
            operation="read",
            request_id=request_id,
        )

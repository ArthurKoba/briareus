"""Project-owned GitHub capability port; not mounted on legacy GitHub MCP."""

from __future__ import annotations

from uuid import UUID

from modules.project_runtime import (
    ProjectIntegrationRef,
    ProjectIntegrationSelector,
    ProjectInvocation,
)
from modules.project_runtime.credential_use import (
    ProjectProviderCapability,
    ProviderOperation,
    ProviderOperationReceipt,
)
from modules.project_runtime.resource_query import ResourceFilter


class ProjectGitHubCapability:
    def __init__(
        self, providers: ProjectProviderCapability, integrations: ProjectIntegrationSelector
    ) -> None:
        self._providers = providers
        self._integrations = integrations

    async def connections(
        self,
        invocation: ProjectInvocation,
        *,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
    ) -> tuple[ProjectIntegrationRef, ...]:
        return await self._integrations.list(
            invocation, provider="github", scope=scope, owner_id=owner_id
        )

    async def execute(
        self,
        invocation: ProjectInvocation,
        *,
        resource_id: UUID,
        capability: str,
        operation: ProviderOperation,
        request_id: UUID,
    ) -> ProviderOperationReceipt:
        return await self._providers.execute(
            invocation,
            resource_id=resource_id,
            provider="github",
            capability=capability,
            operation=operation,
            request_id=request_id,
        )

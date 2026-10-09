"""Private Team/Project reusable configuration selection (metadata only).

`all` yields the effective authorized collection, including duplicate names
with explicit origin. Even active Team members cannot export raw secrets by
using this selector; credential/value injection is a separate C1-B transport.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from .authorization import (
    ProjectInvocation,
    ProjectPermit,
    ProjectRuntimeAuthority,
    valid_project_revision,
)
from .resource_query import (
    ResourceFilter,
    ResourceQuery,
    ResourceSelectionError,
    effective_collection,
    one_named_resource,
)
from .resource_scope import EffectiveResourceScope, ProjectResourceScopeError

VariableKind = Literal["configuration", "secret"]


class ProjectVariableError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProjectVariableRef:
    scope: EffectiveResourceScope
    variable_id: UUID
    kind: VariableKind
    name: str
    # Never add a plaintext value field to this MCP-visible metadata type.

    @property
    def resource_id(self) -> UUID:
        return self.variable_id


class ProjectVariablePort(Protocol):
    async def resolve_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        variable_id: UUID,
        permit: ProjectPermit,
    ) -> ProjectVariableRef: ...

    async def list_effective_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        permit: ProjectPermit,
    ) -> tuple[ProjectVariableRef, ...]: ...


class ProjectVariableSelector:
    def __init__(
        self,
        authority: ProjectRuntimeAuthority,
        resolver: ProjectVariablePort | None = None,
        *,
        operation_timeout_seconds: float = 15.0,
    ) -> None:
        if not math.isfinite(operation_timeout_seconds) or not 0 < operation_timeout_seconds <= 300:
            raise ValueError("Project variable timeout must be finite and positive")
        self.authority = authority
        self._resolver = resolver
        self._operation_timeout_seconds = operation_timeout_seconds

    @staticmethod
    def _validate(
        record: ProjectVariableRef, *, permit: ProjectPermit, variable_id: UUID | None = None
    ) -> None:
        if (
            not isinstance(record, ProjectVariableRef)
            or not isinstance(record.variable_id, UUID)
            or (variable_id is not None and record.variable_id != variable_id)
            or record.kind not in {"configuration", "secret"}
            or not isinstance(record.name, str)
            or not record.name.strip()
        ):
            raise ProjectVariableError("PROJECT_VARIABLE_ACCESS_DENIED")
        try:
            record.scope.verify_for(permit.project_id)
            if record.scope.project_access_revision != permit.project_access_revision:
                raise ProjectResourceScopeError("RESOURCE_SCOPE_STALE")
        except (ProjectResourceScopeError, AttributeError, TypeError) as exc:
            raise ProjectVariableError("PROJECT_VARIABLE_ACCESS_DENIED") from exc

    async def list_metadata(
        self,
        invocation: ProjectInvocation,
        *,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
    ) -> tuple[ProjectVariableRef, ...]:
        query = ResourceQuery(scope, owner_id)
        permit = await self.authority.require(invocation, "resources.use")
        revision = permit.project_access_revision
        if not isinstance(revision, str) or not valid_project_revision(revision):
            raise ProjectVariableError("PROJECT_RESOURCE_FENCE_UNAVAILABLE")
        if self._resolver is None:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                records = await self._resolver.list_effective_metadata(invocation, permit=permit)
            if not isinstance(records, tuple):
                raise ProjectVariableError("PROJECT_VARIABLE_RESPONSE_INVALID")
            for record in records:
                self._validate(record, permit=permit)
            return effective_collection(
                records,
                project_id=permit.project_id,
                access_revision=revision,
                query=query,
            )
        except (ProjectVariableError, ResourceSelectionError):
            raise
        except Exception as exc:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE") from exc

    async def select_metadata(
        self, invocation: ProjectInvocation, *, variable_id: UUID
    ) -> ProjectVariableRef:
        if not isinstance(variable_id, UUID):
            raise ProjectVariableError("PROJECT_VARIABLE_ID_INVALID")
        permit = await self.authority.require(invocation, "resources.use")
        if self._resolver is None:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                record = await self._resolver.resolve_metadata(
                    invocation, variable_id=variable_id, permit=permit
                )
        except ProjectVariableError:
            raise
        except Exception as exc:
            raise ProjectVariableError("PROJECT_VARIABLE_RESOLVER_UNAVAILABLE") from exc
        self._validate(record, permit=permit, variable_id=variable_id)
        return record

    async def select_by_name(
        self,
        invocation: ProjectInvocation,
        *,
        name: str,
        scope: ResourceFilter = "all",
        owner_id: UUID | None = None,
    ) -> ProjectVariableRef:
        records = await self.list_metadata(invocation, scope=scope, owner_id=owner_id)
        try:
            return one_named_resource(records, name=name)
        except ResourceSelectionError as exc:
            raise ProjectVariableError(exc.code) from exc

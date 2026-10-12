"""Private, explicit effective owner scope for Team/Project reusable resources.

C1-SCOPE accepts exactly one Team or Project resource owner. The *trusted*
backend resolver must attest selected-Project ownership and active membership,
not infer it from a caller-submitted team_id, alias, or provider account name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .authorization import valid_project_revision

ResourceOrigin = Literal["project", "team"]


class ProjectResourceScopeError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EffectiveResourceScope:
    """Backend-verified provenance for one effective Project resource.

    For Team-owned resources, `project_owner_team_id` must equal the resource
    owner's team. A personal Project always has project_owner_team_id=None.
    Revoke/membership/transfer cache invalidation remains backend-owned C1-B.
    """

    effective_project_id: UUID
    owner_project_id: UUID | None
    owner_team_id: UUID | None
    project_owner_team_id: UUID | None
    resource_revision: int
    project_access_revision: str

    @property
    def owner_scope(self) -> ResourceOrigin:
        return self.origin

    @property
    def owner_id(self) -> UUID:
        if self.origin == "team":
            if not isinstance(self.owner_team_id, UUID):
                raise ProjectResourceScopeError("RESOURCE_OWNER_INVALID")
            return self.owner_team_id
        if not isinstance(self.owner_project_id, UUID):
            raise ProjectResourceScopeError("RESOURCE_OWNER_INVALID")
        return self.owner_project_id

    @property
    def inherited(self) -> bool:
        return self.origin == "team"

    @property
    def origin(self) -> ResourceOrigin:
        if self.owner_project_id is not None and self.owner_team_id is None:
            return "project"
        if self.owner_team_id is not None and self.owner_project_id is None:
            return "team"
        raise ProjectResourceScopeError("RESOURCE_OWNER_INVALID")

    def verify_for(self, project_id: UUID) -> None:
        if (
            not isinstance(self.effective_project_id, UUID)
            or self.effective_project_id != project_id
            or type(self.resource_revision) is not int
            or self.resource_revision <= 0
            or not valid_project_revision(self.project_access_revision)
        ):
            raise ProjectResourceScopeError("RESOURCE_SCOPE_DENIED")
        if self.origin == "project":
            if self.owner_project_id != project_id:
                raise ProjectResourceScopeError("RESOURCE_SCOPE_DENIED")
        elif (
            self.owner_team_id is None
            or not isinstance(self.owner_team_id, UUID)
            or self.owner_team_id != self.project_owner_team_id
        ):
            raise ProjectResourceScopeError("RESOURCE_SCOPE_DENIED")

"""Private Team/Project resource selection with explicit origin and ambiguity.

The backend port must provide an already authorized *effective collection* for
one Project. This layer checks every record and never guesses same-name items.
It does not retrieve credentials or expose a new MCP operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from .authorization import valid_project_revision
from .resource_scope import EffectiveResourceScope, ProjectResourceScopeError

ResourceFilter = Literal["all", "team", "project"]


class ResourceSelectionError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ResourceQuery:
    scope: ResourceFilter = "all"
    owner_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.scope not in {"all", "team", "project"}:
            raise ResourceSelectionError("RESOURCE_SCOPE_INVALID")
        if self.owner_id is not None and (
            not isinstance(self.owner_id, UUID) or self.scope == "all"
        ):
            raise ResourceSelectionError("RESOURCE_OWNER_FILTER_INVALID")


class NamedResource(Protocol):
    @property
    def scope(self) -> EffectiveResourceScope: ...

    @property
    def name(self) -> str: ...


def effective_collection[TResource: NamedResource](
    records: tuple[TResource, ...],
    *,
    project_id: UUID,
    access_revision: str,
    query: ResourceQuery,
    max_items: int = 1000,
) -> tuple[TResource, ...]:
    """Validate the entire authorized collection BEFORE filtering or returning it.

    No partial result is leaked if even one item has forged provenance or a
    stale membership version. Duplicate aliases survive (no implicit merge).
    """
    if not valid_project_revision(access_revision):
        raise ResourceSelectionError("RESOURCE_ACCESS_REVISION_INVALID")
    if len(records) > max_items or max_items < 1:
        raise ResourceSelectionError("RESOURCE_COLLECTION_TOO_LARGE")
    visible: list[TResource] = []
    for record in records:
        if not isinstance(record.name, str) or not record.name.strip():
            raise ResourceSelectionError("RESOURCE_METADATA_INVALID")
        try:
            record.scope.verify_for(project_id)
        except (ProjectResourceScopeError, AttributeError, TypeError) as exc:
            raise ResourceSelectionError("RESOURCE_ACCESS_DENIED") from exc
        if record.scope.project_access_revision != access_revision:
            raise ResourceSelectionError("RESOURCE_ACCESS_STALE")
        origin = record.scope.origin
        if query.scope != "all" and query.scope != origin:
            continue
        if query.owner_id is not None and record.scope.owner_id != query.owner_id:
            continue
        visible.append(record)
    return tuple(visible)


def one_named_resource[TResource: NamedResource](
    records: tuple[TResource, ...],
    *,
    name: str,
) -> TResource:
    if not name.strip():
        raise ResourceSelectionError("RESOURCE_NAME_REQUIRED")
    matches = [record for record in records if record.name.casefold() == name.casefold()]
    if not matches:
        raise ResourceSelectionError("RESOURCE_NOT_FOUND")
    if len(matches) > 1:
        raise ResourceSelectionError("RESOURCE_NAME_AMBIGUOUS")
    return matches[0]

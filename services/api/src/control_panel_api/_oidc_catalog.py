"""Cookie-to-Platform scoped Catalog metadata; never an executable Hand grant.

A Catalog resource UUID identifies its owner-managed integration/variable
record, not a repository, browser session, filesystem path or Cedar Permit.
Requesting elevated effects still needs real Hand-resolved canonical selectors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ._api_paths import API_V1_PREFIX
from ._oidc_membership import CurrentPlatformContext

_MAX_ROWS = 50
_KEY = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z", re.ASCII)
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@dataclass(frozen=True, slots=True)
class VerifiedCatalogSummary:
    resource_uuid: UUID
    kind: Literal["integration", "variable"]
    owner_kind: Literal["project", "team"]
    owner_uuid: UUID
    key: str
    version: int


class TrustedCatalogReadPort(Protocol):
    async def list_metadata(
        self,
        *,
        actor: UUID,
        project: UUID,
        kind: Literal["integration", "variable"],
        limit: int,
    ) -> tuple[VerifiedCatalogSummary, ...]:
        """Private authenticated Resource Catalog owner scope, NOT a write."""
        ...


class CatalogReadUnavailable(Exception):
    """Private Catalog owner unavailable or returned invalid source evidence."""


class CatalogReadDenied(Exception):
    """Independent private Catalog actor/Project entitlement rejected."""


def oidc_catalog_router(
    *,
    current_context: CurrentPlatformContext,
    catalog: TrustedCatalogReadPort | None,
) -> APIRouter:
    router = APIRouter()

    def error(status: int, code: str) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": code}},
            status_code=status,
            headers=_NO_STORE,
        )

    @router.get(API_V1_PREFIX + "/catalog")
    async def list_metadata(
        request: Request,
        project_uuid: UUID,
        kind: Literal["integration", "variable"],
    ) -> JSONResponse:
        current = await current_context(request, project_uuid)
        if isinstance(current, JSONResponse):
            return current
        session, proof = current
        if project_uuid.version != 4:
            return error(422, "CATALOG_PROJECT_INVALID")
        owned = tuple(
            item
            for item in proof.projects
            if item.project_uuid == project_uuid and "use_resources" in item.permissions
        )
        if len(owned) != 1:
            return error(403, "CATALOG_PROJECT_PERMISSION_DENIED")
        if catalog is None:
            return error(503, "CATALOG_SOURCE_UNAVAILABLE")
        try:
            items = await catalog.list_metadata(
                actor=proof.user_uuid,
                project=project_uuid,
                kind=kind,
                limit=_MAX_ROWS,
            )
        except CatalogReadDenied:
            return error(403, "CATALOG_PROJECT_PERMISSION_DENIED")
        except Exception:
            return error(503, "CATALOG_SOURCE_UNAVAILABLE")
        if not isinstance(items, tuple) or len(items) > _MAX_ROWS:
            return error(503, "CATALOG_SOURCE_INVALID_RESPONSE")
        seen: set[UUID] = set()
        response: list[dict[str, object]] = []
        project = owned[0]
        for item in items:
            if (
                not isinstance(item, VerifiedCatalogSummary)
                or not isinstance(item.resource_uuid, UUID)
                or item.resource_uuid.version != 4
                or item.resource_uuid in seen
                or item.kind != kind
                or item.owner_kind not in {"team", "project"}
                or not isinstance(item.owner_uuid, UUID)
                or item.owner_uuid.version != 4
                or type(item.version) is not int
                or item.version < 1
                or not isinstance(item.key, str)
                or _KEY.fullmatch(item.key) is None
                or (item.owner_kind == "project" and item.owner_uuid != project_uuid)
                or (
                    item.owner_kind == "team"
                    and (
                        project.owner_kind != "team"
                        or project.owner_uuid != item.owner_uuid
                        or not any(team.team_uuid == item.owner_uuid for team in proof.teams)
                    )
                )
            ):
                return error(503, "CATALOG_SOURCE_INVALID_RESPONSE")
            seen.add(item.resource_uuid)
            response.append(
                {
                    "resource_uuid": str(item.resource_uuid),
                    "kind": item.kind,
                    "owner": {"kind": item.owner_kind, "id": str(item.owner_uuid)},
                    "key": item.key,
                    "version": item.version,
                }
            )
        # An owner request may wait while its cookie/Platform proof expires.
        # Never release read results from a stale authenticated context.
        if min(session.expires_at, proof.expires_at) <= datetime.now(UTC):
            return error(503, "CATALOG_PROOF_EXPIRED")
        return JSONResponse(
            {"items": response},
            headers=_NO_STORE,
        )

    return router

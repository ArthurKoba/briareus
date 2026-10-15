"""Rauthy-only, signed private Project/Team Catalog metadata inventory.

Resource Catalog keeps credentials and variable values inside its own DB.
A Project+Team owner proof comes from a separate authenticated Platform
service: neither browser UUIDs nor a Rauthy user JWT grants raw Catalog rows.
Results are NOT executable Hand resource grants; exact runtime ownership is
a separate Resource/Hand attestation at each effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select

from common.platform_db import PlatformDatabase
from projects._resource_persistence import IntegrationRow, VariableRow

_MAX_ITEMS = 50


class CatalogListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    kind: Literal["integration", "variable"]
    limit: int = Field(ge=1, le=_MAX_ITEMS)

    @field_validator("project_uuid")
    @classmethod
    def project_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("current Catalog Project must be UUIDv4")
        return value


@dataclass(frozen=True, slots=True)
class VerifiedCatalogViewer:
    """Freshly verified current Rauthy User and Platform Project/Team owner."""

    actor_uuid: UUID
    project_uuid: UUID
    team_uuid: UUID | None
    can_use_resources: bool
    issuer: Literal["rauthy"]
    audience: Literal["briareus:resources"]
    expires_at: datetime


class TrustedCatalogReaderAttestor(Protocol):
    async def verify(self, request: Request, query: CatalogListQuery) -> VerifiedCatalogViewer:
        """Verify signed actor, private service peer and current owner scope."""
        ...


class CatalogMetadataOwnerUnavailable(Exception):
    """Cannot obtain a fresh private owner/source proof."""


class CatalogMetadataOwnerDenied(Exception):
    """Current Project/Team resource scope not authorized."""


class CatalogMetadataReader:
    """Bounded Catalog SQL-only projection of nonsecret resource metadata."""

    def __init__(
        self, *, database: PlatformDatabase, attestor: TrustedCatalogReaderAttestor
    ) -> None:
        if database.engine.url.database != "briareus_resources" or attestor is None:
            raise ValueError("Rauthy catalog reader requires its own DB and trusted owner")
        self._db = database
        self._attestor = attestor

    async def list(self, request: Request, query: CatalogListQuery) -> list[dict[str, object]]:
        if (
            len(request.headers.getlist("authorization")) != 1
            or request.headers.getlist("cookie")
            or request.headers.getlist("origin")
            or request.headers.getlist("content-type") != ["application/json"]
        ):
            raise CatalogMetadataOwnerDenied("private Catalog service peer required")
        try:
            actor = await self._attestor.verify(request, query)
        except CatalogMetadataOwnerDenied:
            raise
        except Exception:
            raise CatalogMetadataOwnerUnavailable("catalog actor/source unavailable") from None
        now = datetime.now(UTC)
        if (
            not isinstance(actor, VerifiedCatalogViewer)
            or not isinstance(actor.actor_uuid, UUID)
            or actor.actor_uuid.version != 4
            or actor.project_uuid != query.project_uuid
            or (
                actor.team_uuid is not None
                and (not isinstance(actor.team_uuid, UUID) or actor.team_uuid.version != 4)
            )
            or actor.can_use_resources is not True
            or actor.issuer != "rauthy"
            or actor.audience != "briareus:resources"
            or not isinstance(actor.expires_at, datetime)
            or actor.expires_at.tzinfo is None
            or not now < actor.expires_at <= now + timedelta(seconds=30)
        ):
            raise CatalogMetadataOwnerDenied("current Project resources denied")

        model = IntegrationRow if query.kind == "integration" else VariableRow
        conditions = [model.owner_project_id == query.project_uuid]
        if actor.team_uuid is not None:
            conditions.append(model.owner_team_id == actor.team_uuid)
        statement = (
            select(model)
            .where(or_(*conditions), model.deleted_at.is_(None))
            .order_by(model.id)
            .limit(query.limit + 1)
        )
        try:
            async with self._db.transaction() as tx:
                rows = list(await tx.scalars(statement))
        except Exception:
            raise CatalogMetadataOwnerUnavailable("Catalog owner SQL unavailable") from None
        if len(rows) > query.limit:
            raise CatalogMetadataOwnerUnavailable("Catalog source exceeds bounded page")
        result: list[dict[str, object]] = []
        seen: set[UUID] = set()
        for row in rows:
            if (
                not isinstance(row, model)
                or not isinstance(row.id, UUID)
                or row.id.version != 4
                or row.id in seen
                or row.deleted_at is not None
                or type(row.version) is not int
                or row.version < 1
                or (row.owner_project_id is None) == (row.owner_team_id is None)
                or (row.owner_project_id is not None and row.owner_project_id != query.project_uuid)
                or (
                    row.owner_team_id is not None
                    and (actor.team_uuid is None or row.owner_team_id != actor.team_uuid)
                )
            ):
                raise CatalogMetadataOwnerUnavailable("unverified Catalog row")
            owner_kind = "project" if row.owner_project_id is not None else "team"
            owner_uuid = row.owner_project_id or row.owner_team_id
            alias = row.alias_key if isinstance(row, IntegrationRow) else row.name_key
            if not isinstance(alias, str) or not 1 <= len(alias) <= 128:
                raise CatalogMetadataOwnerUnavailable("invalid Catalog display key")
            seen.add(row.id)
            result.append(
                {
                    "resource_uuid": str(row.id),
                    "kind": query.kind,
                    "owner": {"kind": owner_kind, "id": str(owner_uuid)},
                    "key": alias,
                    "version": row.version,
                }
            )
        if actor.expires_at <= datetime.now(UTC):
            raise CatalogMetadataOwnerUnavailable("Catalog scope expired during owner read")
        return result


def private_catalog_reader_router(
    *,
    reader: CatalogMetadataReader | None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/resources/catalog", tags=["resources-private"])

    @router.post("/list", include_in_schema=False)
    async def list_resources(query: CatalogListQuery, request: Request) -> JSONResponse:
        if reader is None:
            return JSONResponse(
                {"error": {"code": "CATALOG_SOURCE_UNAVAILABLE"}},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        try:
            items = await reader.list(request, query)
        except CatalogMetadataOwnerDenied:
            return JSONResponse(
                {"error": {"code": "CATALOG_PROJECT_DENIED"}},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return JSONResponse(
                {"error": {"code": "CATALOG_SOURCE_UNAVAILABLE"}},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            {"items": items}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
        )

    return router

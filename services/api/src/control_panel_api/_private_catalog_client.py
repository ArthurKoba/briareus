"""Fixed private Catalog metadata reader with signed Rauthy/Platform actor.

The private transport and short-lived delegation MUST come from an
independently authenticated service peer; this code never trusts browser
resource IDs, reads Catalog SQL or handles provider credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from ._oidc_catalog import (
    CatalogReadDenied,
    CatalogReadUnavailable,
    VerifiedCatalogSummary,
)

_DESTINATION = "http://briareus-resources:8000/internal/v1/resources/catalog/list"
_MAX_BODY = 32_768


@dataclass(frozen=True, slots=True)
class VerifiedCatalogTransport:
    client: httpx.AsyncClient
    transport: Literal["mtls", "unix-peer"]
    audience: Literal["briareus:resources"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedCatalogDelegation:
    issuer: Literal["rauthy"]
    actor_uuid: UUID
    project_uuid: UUID
    kind: Literal["integration", "variable"]
    bearer: SecretStr
    audience: Literal["briareus:resources"]
    expires_at: datetime


class TrustedCatalogPeerPort(Protocol):
    async def current_transport(self) -> VerifiedCatalogTransport:
        """Authenticated private Resource Catalog service peer."""
        ...

    async def signed_catalog_delegation(
        self,
        *,
        actor_uuid: UUID,
        project_uuid: UUID,
        kind: Literal["integration", "variable"],
    ) -> VerifiedCatalogDelegation:
        """Fresh signer decision, not caller-supplied Rauthy claims."""
        ...


class _Owner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["project", "team"]
    id: UUID


class _CatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_uuid: UUID
    kind: Literal["integration", "variable"]
    owner: _Owner
    key: str = Field(min_length=1, max_length=128)
    version: int = Field(strict=True, ge=1)


class _CatalogList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[_CatalogItem, ...] = Field(max_length=50)


class PrivateCatalogMetadataClient:
    def __init__(self, *, trusted_peer: TrustedCatalogPeerPort) -> None:
        if trusted_peer is None:
            raise ValueError("Catalog read needs trusted private actor peer")
        self._peer = trusted_peer

    async def list_metadata(
        self,
        *,
        actor: UUID,
        project: UUID,
        kind: Literal["integration", "variable"],
        limit: int,
    ) -> tuple[VerifiedCatalogSummary, ...]:
        if (
            not isinstance(actor, UUID)
            or actor.version != 4
            or not isinstance(project, UUID)
            or project.version != 4
            or kind not in {"integration", "variable"}
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise CatalogReadDenied("invalid Project Catalog read selector")
        try:
            connection = await self._peer.current_transport()
            delegation = await self._peer.signed_catalog_delegation(
                actor_uuid=actor, project_uuid=project, kind=kind
            )
        except Exception:
            raise CatalogReadUnavailable("trusted Catalog service peer unavailable") from None
        now = datetime.now(UTC)
        if (
            not isinstance(connection, VerifiedCatalogTransport)
            or connection.transport not in {"mtls", "unix-peer"}
            or connection.audience != "briareus:resources"
            or not isinstance(connection.expires_at, datetime)
            or connection.expires_at.tzinfo is None
            or not now < connection.expires_at <= now + timedelta(seconds=30)
            or not isinstance(delegation, VerifiedCatalogDelegation)
            or delegation.issuer != "rauthy"
            or delegation.actor_uuid != actor
            or delegation.project_uuid != project
            or delegation.kind != kind
            or delegation.audience != "briareus:resources"
            or not isinstance(delegation.expires_at, datetime)
            or delegation.expires_at.tzinfo is None
            or not now < delegation.expires_at <= connection.expires_at
        ):
            raise CatalogReadUnavailable("Catalog actor/peer attestation not current")
        credential = delegation.bearer.get_secret_value()
        if (
            not 40 <= len(credential) <= 8192
            or not credential.isascii()
            or any(char.isspace() for char in credential)
        ):
            raise CatalogReadUnavailable("private Catalog bearer malformed")
        try:
            async with connection.client.stream(
                "POST",
                _DESTINATION,
                json={"project_uuid": str(project), "kind": kind, "limit": limit},
                headers={
                    "Authorization": "Bearer " + credential,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                follow_redirects=False,
            ) as response:
                if response.status_code in {401, 403}:
                    raise CatalogReadDenied("private Catalog Project denied")
                if response.status_code != 200:
                    raise CatalogReadUnavailable("Catalog source currently unavailable")
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise CatalogReadUnavailable("unexpected Catalog response MIME")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > _MAX_BODY:
                        raise CatalogReadUnavailable("Catalog response over maximum")
                    raw.extend(chunk)
        except (httpx.HTTPError, TimeoutError):
            raise CatalogReadUnavailable("Catalog transport unavailable") from None
        if delegation.expires_at <= datetime.now(UTC):
            raise CatalogReadUnavailable("Catalog signed actor expired during read")
        try:
            source = _CatalogList.model_validate_json(raw)
        except (ValidationError, ValueError):
            raise CatalogReadUnavailable("untrusted private Catalog result") from None
        seen: set[UUID] = set()
        summaries: list[VerifiedCatalogSummary] = []
        for item in source.items:
            if (
                item.kind != kind
                or item.resource_uuid.version != 4
                or item.resource_uuid in seen
                or item.owner.id.version != 4
            ):
                raise CatalogReadUnavailable("Catalog item kind/owner invalid")
            seen.add(item.resource_uuid)
            summaries.append(
                VerifiedCatalogSummary(
                    resource_uuid=item.resource_uuid,
                    kind=item.kind,
                    owner_kind=item.owner.kind,
                    owner_uuid=item.owner.id,
                    key=item.key,
                    version=item.version,
                )
            )
        return tuple(summaries)

"""Project Files quota reservation with durable owner-side accounting port.

A per-file cap is not an aggregate Project disk quota. The Backend-owned port
must transactionally reserve bytes across all Files/HTTP/Reverse writers and
serialize cap changes/deletions. Without it, the private bulk-write consumer
refuses new writes; no in-memory counter is used as authority.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from .authorization import ProjectPermit, valid_project_revision


class ProjectQuotaError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProjectQuotaReservation:
    reservation_id: UUID
    project_id: UUID
    actor_id: UUID
    session_uuid: UUID
    requested_bytes: int
    operation_uuid: UUID
    destination: str
    expected_sha256: str
    expires_at: datetime
    owner_revision: str


class ProjectQuotaPort(Protocol):
    async def reserve(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        session_uuid: UUID,
        operation_uuid: UUID,
        maximum_bytes: int,
        destination: str,
        expected_sha256: str,
    ) -> ProjectQuotaReservation: ...

    async def finalize(self, *, reservation_id: UUID, committed_bytes: int) -> None: ...

    async def release(self, *, reservation_id: UUID) -> None: ...


class ProjectQuotaGuard:
    def __init__(
        self,
        port: ProjectQuotaPort | None = None,
        *,
        operation_timeout_seconds: float = 10.0,
    ) -> None:
        if not math.isfinite(operation_timeout_seconds) or not 0 < operation_timeout_seconds <= 300:
            raise ValueError("Project quota timeout must be finite and positive")
        self._port = port
        self._operation_timeout_seconds = operation_timeout_seconds

    async def reserve(
        self,
        permit: ProjectPermit,
        *,
        maximum_bytes: int,
        destination: str,
        expected_sha256: str,
        operation_uuid: UUID | None = None,
    ) -> ProjectQuotaReservation:
        if self._port is None:
            raise ProjectQuotaError("FILE_QUOTA_AUTHORITY_UNAVAILABLE")
        if permit.action != "files.write" or type(maximum_bytes) is not int or maximum_bytes < 0:
            raise ProjectQuotaError("FILE_QUOTA_REQUEST_INVALID")
        if not valid_project_revision(permit.project_access_revision):
            # Project permissions and quota owner revision cannot be inferred
            # from a session grant/UUID; require one comparable backend fence.
            raise ProjectQuotaError("FILE_QUOTA_OWNER_REVISION_UNAVAILABLE")
        if not isinstance(operation_uuid, UUID) or operation_uuid.version != 4:
            raise ProjectQuotaError("FILE_IDEMPOTENCY_UUID_REQUIRED")
        if (
            not isinstance(destination, str)
            or not destination
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise ProjectQuotaError("FILE_QUOTA_FINGERPRINT_INVALID")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                reserved = await self._port.reserve(
                    project_id=permit.project_id,
                    actor_id=permit.actor_id,
                    session_uuid=permit.session_uuid,
                    operation_uuid=operation_uuid,
                    maximum_bytes=maximum_bytes,
                    destination=destination,
                    expected_sha256=expected_sha256,
                )
        except Exception as exc:
            # The backend might have committed a reservation before its reply
            # disappeared. Only the SAME operation_uuid may be reconciled.
            raise ProjectQuotaError("FILE_QUOTA_RESERVATION_OUTCOME_UNKNOWN") from exc
        if (
            not isinstance(reserved, ProjectQuotaReservation)
            or reserved.project_id != permit.project_id
            or reserved.actor_id != permit.actor_id
            or reserved.session_uuid != permit.session_uuid
            or reserved.requested_bytes != maximum_bytes
            or reserved.operation_uuid != operation_uuid
            or reserved.destination != destination
            or reserved.expected_sha256 != expected_sha256
            or not isinstance(reserved.reservation_id, UUID)
            or not valid_project_revision(reserved.owner_revision)
            or not isinstance(reserved.expires_at, datetime)
            or reserved.expires_at.tzinfo is None
            or reserved.expires_at <= datetime.now(UTC)
        ):
            raise ProjectQuotaError("FILE_QUOTA_RESERVATION_INVALID")
        if reserved.owner_revision != permit.project_access_revision:
            # A different current Project owner/resource revision invalidates
            # this reservation. Do not create files using a stale quota grant.
            await self.release(reserved)
            raise ProjectQuotaError("FILE_QUOTA_OWNER_REVISION_STALE")
        return reserved

    @staticmethod
    def require_active(reservation: ProjectQuotaReservation) -> None:
        if not isinstance(reservation, ProjectQuotaReservation):
            raise ProjectQuotaError("FILE_QUOTA_RESERVATION_INVALID")
        if reservation.expires_at <= datetime.now(UTC):
            raise ProjectQuotaError("FILE_QUOTA_RESERVATION_EXPIRED")

    async def finalize(self, reservation: ProjectQuotaReservation, *, count: int) -> None:
        if self._port is None:
            raise ProjectQuotaError("FILE_QUOTA_AUTHORITY_UNAVAILABLE")
        if not 0 <= count <= reservation.requested_bytes or reservation.expires_at <= datetime.now(
            UTC
        ):
            raise ProjectQuotaError("FILE_QUOTA_COMMIT_UNCERTAIN")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                await self._port.finalize(
                    reservation_id=reservation.reservation_id, committed_bytes=count
                )
        except Exception as exc:
            # File might already exist; never tell the caller to retry a write.
            raise ProjectQuotaError("FILE_QUOTA_COMMIT_UNCERTAIN") from exc

    async def release(self, reservation: ProjectQuotaReservation) -> None:
        if self._port is None:
            raise ProjectQuotaError("FILE_QUOTA_AUTHORITY_UNAVAILABLE")
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                await self._port.release(reservation_id=reservation.reservation_id)
        except Exception as exc:
            raise ProjectQuotaError("FILE_QUOTA_RELEASE_UNCERTAIN") from exc

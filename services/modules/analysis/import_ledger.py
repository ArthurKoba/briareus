"""Private idempotency port for native analysis import and result reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

ClaimState = Literal["claimed", "recorded", "in_progress", "unknown"]


@dataclass(frozen=True, slots=True)
class NativeImportIdentity:
    operation_uuid: UUID
    actor_id: UUID
    project_id: UUID
    session_uuid: UUID
    native_project_id: str
    source_sha256: str
    size_bytes: int
    auto_analyze: bool


@dataclass(frozen=True, slots=True)
class NativeImportClaim:
    identity: NativeImportIdentity
    state: ClaimState
    revision: int


@dataclass(frozen=True, slots=True)
class NativeImportReconciliation:
    """Trusted native-side inspection result; never inferred from an HTTP timeout."""

    identity: NativeImportIdentity
    state: Literal["recorded", "unknown", "no_effect"]
    revision: int
    result_sha256: str | None
    native_evidence_verified: bool


class NativeImportLedgerPort(Protocol):
    async def claim(self, identity: NativeImportIdentity) -> NativeImportClaim: ...

    async def mark_dispatched(self, claim: NativeImportClaim) -> None: ...

    async def record_success(self, claim: NativeImportClaim, *, result_sha256: str) -> None: ...

    async def record_pre_dispatch_failure(self, claim: NativeImportClaim) -> None: ...

    async def record_unknown(self, claim: NativeImportClaim) -> None: ...

    async def reconcile_unknown(
        self, *, project_id: UUID, operation_uuid: UUID
    ) -> NativeImportReconciliation: ...

"""Unmounted, fully typed B20 source handlers for CURRENT and ORIGINAL inspect.

No Host/Origin/CSRF/bearer cookie or TLS identity is accepted from a body;
physical C2 must provide the independently verified ingress adapter. There
is NO URL/router or permissive fallback. Default Admin ASGI remains health
only until D4/private-issuer review and explicit public installation.
"""

from __future__ import annotations

import asyncio
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from common.owner_bff_models import VerifiedAdminCaller
from common.owner_bff_signed import canonical_original_identity

from .owner_bff_evidence import (
    BffEffectEvidence,
    BffOwnerEvidence,
    BffScope,
    OriginalCommandBinding,
    OwnerBffEvidenceSource,
)


class PrivateBffRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scope: BffScope


class PrivateBffOriginalInspect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scope: BffScope
    binding: OriginalCommandBinding
    idempotencyKey: str = Field(min_length=36, max_length=36)
    operationUuid: UUID

    @model_validator(mode="after")
    def bound_original(self) -> PrivateBffOriginalInspect:
        canonical_original_identity(self.operationUuid, self.idempotencyKey)
        if self.scope.kind == "project" and (
            self.binding.target.kind in {"project", "project_resource"}
            and self.binding.target.id != self.scope.projectId
        ):
            raise ValueError("Project command scope/target must be identical")
        if self.scope.kind == "team" and (
            self.binding.target.kind == "team" and self.binding.target.id != self.scope.teamId
        ):
            raise ValueError("Team command scope/target must be identical")
        return self


class TrustedBffAdmissionError(Exception):
    """ONLY the injected trusted C2 layer may distinguish deny categories."""

    def __init__(self, reason: Literal["authentication", "permission"]) -> None:
        self.reason = reason
        super().__init__(reason)


class PrivateBffUnavailable(Exception):
    """Safe HTTP-style outcome; not a claim of a failed original mutation."""

    def __init__(
        self,
        *,
        status_code: Literal[401, 403, 503],
        code: Literal["AUTHENTICATION_REQUIRED", "SCOPE_DENIED", "OWNER_SOURCE_UNAVAILABLE"],
        original_outcome_unknown: bool,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.original_outcome_unknown = original_outcome_unknown
        super().__init__(code)


class TrustedBffRequestAdmission(Protocol):
    async def require_current_caller(
        self, *, evidence: object, purpose: Literal["read", "original_inspect"]
    ) -> VerifiedAdminCaller:
        """C2 checks current Identity bearer+JTI, HTTPS Host/Origin/CSRF,

        trusted proxy/TLS client and the BFF release-pinned service recipient.
        Header strings alone may NEVER create a caller. Fails on missing C2.
        """
        ...

    async def require_current_scope(
        self,
        *,
        caller: VerifiedAdminCaller,
        scope: BffScope,
        purpose: Literal["read", "original_inspect"],
    ) -> None:
        """Current Identity+Control+Access scope/AgentSession proof. No WS grant."""
        ...


class PrivateOwnerBffHandlers:
    def __init__(
        self,
        *,
        ingress: TrustedBffRequestAdmission,
        source: OwnerBffEvidenceSource,
    ) -> None:
        if ingress is None or source is None:
            raise RuntimeError("private BFF requires accepted physical ingress and signed owners")
        self.ingress = ingress
        self.source = source

    async def _caller(
        self,
        *,
        evidence: object,
        scope: BffScope,
        purpose: Literal["read", "original_inspect"],
    ) -> VerifiedAdminCaller:
        try:
            async with asyncio.timeout(3):
                caller = await self.ingress.require_current_caller(
                    evidence=evidence, purpose=purpose
                )
                if (
                    not isinstance(caller, VerifiedAdminCaller)
                    or caller.source != "verified-admin-bearer"
                    or caller.user_id.version != 4
                ):
                    raise TrustedBffAdmissionError("authentication")
                await self.ingress.require_current_scope(
                    caller=caller, scope=scope, purpose=purpose
                )
                return caller
        except TrustedBffAdmissionError as exc:
            if exc.reason == "authentication":
                raise PrivateBffUnavailable(
                    status_code=401,
                    code="AUTHENTICATION_REQUIRED",
                    original_outcome_unknown=purpose == "original_inspect",
                ) from None
            raise PrivateBffUnavailable(
                status_code=403,
                code="SCOPE_DENIED",
                original_outcome_unknown=purpose == "original_inspect",
            ) from None
        except Exception:
            # Unknown physical C2 failure must never become anonymous access,
            # 401-by-assumption or a signed DENIED after an irreversible effect.
            raise PrivateBffUnavailable(
                status_code=503,
                code="OWNER_SOURCE_UNAVAILABLE",
                original_outcome_unknown=purpose == "original_inspect",
            ) from None

    async def current(
        self, *, source_evidence: object, request: PrivateBffRead
    ) -> BffOwnerEvidence:
        caller = await self._caller(evidence=source_evidence, scope=request.scope, purpose="read")
        try:
            async with asyncio.timeout(5):
                return await self.source.current(caller, request.scope)
        except Exception:
            raise PrivateBffUnavailable(
                status_code=503,
                code="OWNER_SOURCE_UNAVAILABLE",
                original_outcome_unknown=False,
            ) from None

    async def inspect_original(
        self, *, source_evidence: object, request: PrivateBffOriginalInspect
    ) -> BffEffectEvidence:
        caller = await self._caller(
            evidence=source_evidence, scope=request.scope, purpose="original_inspect"
        )
        try:
            async with asyncio.timeout(5):
                return await self.source.inspect_original(
                    caller,
                    request.scope,
                    request.binding,
                    request.idempotencyKey,
                    request.operationUuid,
                )
        except Exception:
            # A denied HTTP transport response is NEVER proof of native
            # rollback or safe replay under a different UUID/Idempotency-Key.
            raise PrivateBffUnavailable(
                status_code=503,
                code="OWNER_SOURCE_UNAVAILABLE",
                original_outcome_unknown=True,
            ) from None

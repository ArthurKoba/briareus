"""Authoritative current User/JTI verifier in Identity's OWN PostgreSQL.

No Admin/API/Gateway SQL access, unsigned proxy-user header, or arbitrary JWT
claim object grants an account. Requires its own current mTLS/Unix peer
verification, pinned Ed25519 bearer and fresh Identity row/revocation checks.
Source-only: never registered on the published default ASGI application.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import SecretStr
from sqlalchemy import select

from common.owner_bff_models import VerifiedAdminCaller
from common.owner_contracts import (
    OwnerAuthorityUnavailable,
    TrustedOwnerServicePeerPort,
    VerifiedOwnerServicePeer,
)
from common.platform_db import PlatformDatabase
from common.platform_ids import UserId
from common.private_user_token import (
    IdentityCredentialRejected,
    PrivateUserTokenClaims,
    jti_digest,
    require_pinned_current_user_token,
)
from identity._persistence import AdminTokenRevocationRow
from identity._repository import IdentityRepository


class IdentityCurrentUserSource:
    """Fresh owner-local current User source, never a bearer issuer."""

    def __init__(
        self,
        *,
        database: PlatformDatabase,
        peer_verifier: TrustedOwnerServicePeerPort,
        bearer_public_key: Ed25519PublicKey,
        trusted_issuer: str,
        trusted_audience: str,
        admin_service_id: UUID,
        admin_instance_uuid: UUID,
    ) -> None:
        if (
            database.engine.url.database != "briareus_identity"
            or peer_verifier is None
            or not isinstance(bearer_public_key, Ed25519PublicKey)
            or not trusted_issuer.startswith("briareus:")
            or not trusted_audience.startswith("briareus:")
            or admin_service_id.version != 4
            or admin_instance_uuid.version != 4
        ):
            raise ValueError("Identity current User requires scoped DB, release pin and peer")
        self.db = database
        self.peers = peer_verifier
        self.key = bearer_public_key
        self.issuer = trusted_issuer
        self.audience = trusted_audience
        self.admin_service_id = admin_service_id
        self.admin_instance_uuid = admin_instance_uuid
        self.repo = IdentityRepository()

    async def require_current(
        self, *, bearer: SecretStr, peer_evidence: object
    ) -> VerifiedAdminCaller:
        """No identity lookup based on caller-supplied parsed JWT claims."""
        try:
            peer = self.peers.verify_peer(peer_evidence)
        except Exception:
            raise OwnerAuthorityUnavailable("Identity private C2 peer not attested") from None
        if (
            not isinstance(peer, VerifiedOwnerServicePeer)
            or peer.service_id != self.admin_service_id
            or peer.instance_uuid != self.admin_instance_uuid
            or peer.audience != "briareus:identity"
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise OwnerAuthorityUnavailable("wrong Identity status source recipient")
        if not isinstance(bearer, SecretStr):
            raise IdentityCredentialRejected("current signed Identity bearer required")
        try:
            claims: PrivateUserTokenClaims = require_pinned_current_user_token(
                bearer.get_secret_value(),
                pinned_public_key=self.key,
                trusted_issuer=self.issuer,
                trusted_audience=self.audience,
            )
        except OwnerAuthorityUnavailable:
            raise IdentityCredentialRejected("signed Identity bearer rejected") from None
        # A proven invalid token/disabled user/revoked JTI is 401. A network
        # or SQL failure is NOT an authenticated denial, and stays 503.
        async with self.db.transaction() as tx:
            row = await self.repo.get_user(tx, UserId(claims.sub))
            if (
                row is None
                or row.deleted_at is not None
                or not row.enabled
                or row.credential_version != claims.credential_version
            ):
                raise IdentityCredentialRejected("Identity user no longer active")
            revoked = await tx.scalar(
                select(AdminTokenRevocationRow.jti_digest).where(
                    AdminTokenRevocationRow.jti_digest == jti_digest(claims.jti)
                )
            )
            if revoked is not None:
                raise IdentityCredentialRejected("Identity bearer JTI revoked")
            return VerifiedAdminCaller(
                user_id=claims.sub,
                credential_version=row.credential_version,
                source="verified-admin-bearer",
            )


def build_unmounted_identity_current_router(source: IdentityCurrentUserSource) -> APIRouter:
    """Internal status only, and only with an actual attested C2 source."""
    if not isinstance(source, IdentityCurrentUserSource):
        raise ValueError("trusted Identity reader required")
    router = APIRouter(prefix="/internal/v1/identity", tags=["identity-current-private"])

    @router.post("/current", response_model=VerifiedAdminCaller)
    async def current_user(request: Request, response: Response) -> VerifiedAdminCaller:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        authorization = request.headers.get("authorization", "")
        if (
            not authorization.startswith("Bearer ")
            or authorization.count(" ") != 1
            or request.headers.get("cookie") is not None
        ):
            raise HTTPException(401, detail="current signed User bearer required")
        try:
            return await source.require_current(
                bearer=SecretStr(authorization[7:]), peer_evidence=request
            )
        except IdentityCredentialRejected:
            raise HTTPException(401, detail="current Identity user not authorized") from None
        except Exception:
            raise HTTPException(503, detail="current Identity source unavailable") from None

    return router

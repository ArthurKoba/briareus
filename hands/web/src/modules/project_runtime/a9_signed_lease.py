"""Independent A9 Ed25519 RuntimeLeaseReceipt verifier (private source port).

An accepted Backend JWS attests a COMMITTED SQL ledger snapshot and nonce;
it is neither a command bearer nor proof a Linux cgroup/Browser was reaped.
The public key is pinned by trusted C2 service transport, never MCP input,
process ENV/JWKS discovery, previous untrusted receipts or synthetic UUIDs.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .authorization import ProjectPermit

_ATTESTATION_TYPE = "briareus-runtime-lease+jwt"
_PURPOSE = "runtime-ledger-attestation-v1"
_ISSUER = "briareus-authorization"
_KIND_AUDIENCE = {
    "files": "files",
    "terminal": "terminal",
    "web_managed": "web",
    "web_remote": "web",
    "reverse": "reverse",
}
_SHA = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class A9SignedLeaseUntrusted(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RuntimeLeaseReceipt(BaseModel):
    """FIELD-EXACT accepted A9 Backend `_runtime_lease_attestation` DTO."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    runtime_session_uuid: UUID
    project_id: UUID
    agent_session_uuid: UUID
    actor_user_id: UUID
    owner_service_id: UUID
    owner_instance_uuid: UUID
    lease_nonce: UUID
    kind: Literal["files", "terminal", "web_managed", "web_remote", "reverse"]
    state: Literal["active", "lost", "expired", "revoked", "closed"]
    revision: int = Field(ge=1)
    idle_expires_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime
    cleanup_state: Literal["not_needed", "pending", "confirmed", "unknown"]


class SignedRuntimeLeaseReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    lease: RuntimeLeaseReceipt
    attestation_jws: str = Field(min_length=100, max_length=8192)
    attestation_expires_at: datetime


class A9PinnedRuntimeKeyPort(Protocol):
    """Resolve one operator-approved A9 signing key from actual C2 trust.

    Never accept a key supplied by an MCP tool, client/header, unsigned JWS
    `kid`, arbitrary HTTP/JWKS URL, or Backend response body. The private
    signing key never exists in this Runtime process.
    """

    async def pinned_backend_lease_key(
        self,
        *,
        expected_service_id: UUID,
        expected_instance_uuid: UUID,
    ) -> Ed25519PublicKey: ...


def _uuid4(value: object) -> bool:
    return isinstance(value, UUID) and value.version == 4


def _key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def verify_a9_signed_lease(
    response: SignedRuntimeLeaseReceipt,
    *,
    trusted_public_key: Ed25519PublicKey,
    expected_service_id: UUID,
    expected_instance_uuid: UUID,
    expected_audience: Literal["files", "terminal", "web", "reverse"],
    permit: ProjectPermit,
    expected_runtime_session_uuid: UUID,
    expected_kind: Literal["files", "terminal", "web_managed", "web_remote", "reverse"],
) -> RuntimeLeaseReceipt:
    """Verify A9 issuer/recipient/kid, scope/JWS, nonce, TTL and full DTO.

    Caller supplies only expectations derived from its separately authenticated
    service peer plus FRESH User/Project/AgentSession backend grant. The JWS
    itself never authorizes heartbeat/job/process creation without a fresh
    separately signed per-effect request and live Backend SQL decision.
    """
    if (
        not isinstance(response, SignedRuntimeLeaseReceipt)
        or not isinstance(trusted_public_key, Ed25519PublicKey)
        or not all(
            _uuid4(u)
            for u in (
                expected_service_id,
                expected_instance_uuid,
                permit.project_id,
                permit.session_uuid,
                permit.actor_id,
                expected_runtime_session_uuid,
            )
        )
        or _KIND_AUDIENCE.get(expected_kind) != expected_audience
        or type(permit.decision_version) is not int
        or permit.decision_version < 1
        or not isinstance(permit.project_access_revision, str)
        or _SHA.fullmatch(permit.project_access_revision) is None
        or permit.expires_at.tzinfo is None
        or permit.expires_at <= datetime.now(UTC)
    ):
        raise A9SignedLeaseUntrusted("A9_LEASE_TRUSTED_EXPECTATIONS_INVALID")
    try:
        header = jwt.get_unverified_header(response.attestation_jws)
        if (
            header.get("alg") != "EdDSA"
            or header.get("typ") != _ATTESTATION_TYPE
            or header.get("kid") != _key_id(trusted_public_key)
            or header.get("crit")
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_KEY_OR_HEADER_UNTRUSTED")
        claims = jwt.decode(
            response.attestation_jws,
            trusted_public_key,
            algorithms=["EdDSA"],
            audience=f"runtime-lease:{expected_audience}",
            issuer=_ISSUER,
            options={
                "require": [
                    "iss",
                    "aud",
                    "purpose",
                    "jti",
                    "iat",
                    "nbf",
                    "exp",
                    "recipient_service_id",
                    "recipient_instance_uuid",
                    "project_access_revision",
                    "agent_session_version",
                    "lease",
                ]
            },
            leeway=0,
        )
        now = datetime.now(UTC)
        jti = UUID(claims["jti"])
        if (
            not _uuid4(jti)
            or claims["purpose"] != _PURPOSE
            or claims["recipient_service_id"] != str(expected_service_id)
            or claims["recipient_instance_uuid"] != str(expected_instance_uuid)
            or claims["project_access_revision"] != permit.project_access_revision
            or type(claims["agent_session_version"]) is not int
            or claims["agent_session_version"] != permit.decision_version
            or not isinstance(claims["lease"], dict)
            or type(claims["iat"]) is not int
            or type(claims["exp"]) is not int
            or type(claims["nbf"]) is not int
            or not 0 < claims["exp"] - claims["iat"] <= 30
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_CLAIMS_SCOPE_MISMATCH")
        signed = RuntimeLeaseReceipt.model_validate_json(
            json.dumps(claims["lease"], sort_keys=True, separators=(",", ":"))
        )
        if (
            signed != response.lease
            or signed.project_id != permit.project_id
            or signed.agent_session_uuid != permit.session_uuid
            or signed.actor_user_id != permit.actor_id
            or signed.owner_service_id != expected_service_id
            or signed.runtime_session_uuid != expected_runtime_session_uuid
            or signed.kind != expected_kind
            or not all(
                _uuid4(u)
                for u in (
                    signed.runtime_session_uuid,
                    signed.lease_nonce,
                    signed.owner_instance_uuid,
                )
            )
            or _KIND_AUDIENCE.get(signed.kind) != expected_audience
            or not isinstance(response.attestation_expires_at, datetime)
            or response.attestation_expires_at.tzinfo is None
            or int(response.attestation_expires_at.timestamp()) != claims["exp"]
            or not all(
                d.tzinfo is not None
                for d in (
                    signed.idle_expires_at,
                    signed.hard_expires_at,
                    signed.lease_expires_at,
                )
            )
            or (signed.state == "active" and signed.hard_expires_at <= now)
            or signed.lease_expires_at > signed.hard_expires_at
            or (signed.state == "active" and signed.lease_expires_at <= now)
            or (
                signed.state == "active"
                and claims["exp"] > int(signed.lease_expires_at.timestamp())
            )
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
        if expected_instance_uuid != signed.owner_instance_uuid and (
            signed.state not in {"lost", "expired", "revoked", "closed"}
            or signed.cleanup_state != "confirmed"
        ):
            raise A9SignedLeaseUntrusted("A9_LEASE_TAKEOVER_WITHOUT_OS_CLEANUP")
        return signed
    except A9SignedLeaseUntrusted:
        raise
    except (
        jwt.PyJWTError,
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:
        raise A9SignedLeaseUntrusted("A9_LEASE_ATTESTATION_INVALID") from exc

"""Short-lived Ed25519 attestation of Backend-owned Runtime lease state.

An attestation proves what a committed Backend ledger said about a lease.
It is NOT an authorization bearer, not proof that an OS process was killed,
and cannot substitute for the independently signed service+User+Project
operation authorization that is required on EVERY Runtime ledger command.

Runtime consumers must pin the Backend's signing public key via the trusted
C2 transport. Never derive lease_nonce from runtime UUID, PID or client input.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common.platform_errors import AccessDenied, AuthenticationRequired
from projects._runtime_ledger import KIND_ACTION, RuntimeLease

from ._service_identity import DELEGATION_ISSUER, ServiceAuthorizationDecision

_ATTESTATION_TYPE = "briareus-runtime-lease+jwt"
_ATTESTATION_PURPOSE = "runtime-ledger-attestation-v1"
_ATTESTATION_TTL = timedelta(seconds=30)


class RuntimeLeaseReceipt(BaseModel):
    """Immutable, exact Project/AgentSession/service owner + nonce snapshot."""

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

    @classmethod
    def from_ledger(cls, lease: RuntimeLease) -> RuntimeLeaseReceipt:
        # Strict DTO validation is an intentional additional boundary against
        # an invalid/forged persisted runtime kind, state or cleanup status.
        return cls.model_validate(
            {
                "runtime_session_uuid": lease.runtime_session_uuid,
                "project_id": lease.project_id,
                "agent_session_uuid": lease.agent_session_uuid,
                "actor_user_id": lease.actor_user_id,
                "owner_service_id": lease.owner_service_id,
                "owner_instance_uuid": lease.owner_instance,
                "lease_nonce": lease.lease_nonce,
                "kind": lease.kind,
                "state": lease.status,
                "revision": lease.version,
                "idle_expires_at": lease.idle_expires_at,
                "hard_expires_at": lease.hard_expires_at,
                "lease_expires_at": lease.lease_expires_at,
                "cleanup_state": lease.cleanup_state,
            }
        )


class SignedRuntimeLeaseReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    lease: RuntimeLeaseReceipt
    attestation_jws: str = Field(min_length=100, max_length=8192)
    attestation_expires_at: datetime


def _key_id(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def _validate_receipt_scope(
    lease: RuntimeLeaseReceipt, decision: ServiceAuthorizationDecision
) -> None:
    allowed = KIND_ACTION.get(lease.kind)
    if (
        allowed is None
        or allowed != (decision.audience, decision.operation)
        or decision.project_id != lease.project_id
        or decision.session_uuid != lease.agent_session_uuid
        or decision.actor_id != lease.actor_user_id
        or decision.service_id != lease.owner_service_id
        or decision.expires_at <= datetime.now(UTC)
        or lease.lease_nonce.version != 4
        or lease.runtime_session_uuid.version != 4
        or lease.owner_instance_uuid.version != 4
    ):
        raise AccessDenied("Runtime lease cannot be attested for this signed operation")
    # The signed lease never substitutes for independent OS cleanup evidence.
    if decision.instance_uuid != lease.owner_instance_uuid and (
        lease.state not in {"lost", "expired", "revoked", "closed"}
        or lease.cleanup_state != "confirmed"
    ):
        raise AccessDenied("replacement instance has no verified old-owner custody")


def issue_signed_runtime_lease(
    lease: RuntimeLease,
    *,
    decision: ServiceAuthorizationDecision,
    authority_signer: Ed25519PrivateKey,
) -> SignedRuntimeLeaseReceipt:
    """Called only after the authenticated ledger UoW successfully commits."""
    receipt = RuntimeLeaseReceipt.from_ledger(lease)
    _validate_receipt_scope(receipt, decision)
    now = datetime.now(UTC)
    expires = min(now + _ATTESTATION_TTL, decision.expires_at)
    if receipt.state == "active":
        expires = min(expires, receipt.lease_expires_at)
    if expires <= now:
        raise AccessDenied("Runtime owner authorization has expired before attestation")
    header = {
        "alg": "EdDSA",
        "typ": _ATTESTATION_TYPE,
        "kid": _key_id(authority_signer.public_key()),
    }
    claims = {
        "iss": DELEGATION_ISSUER,
        "aud": f"runtime-lease:{decision.audience}",
        "purpose": _ATTESTATION_PURPOSE,
        "jti": str(uuid4()),
        "recipient_service_id": str(decision.service_id),
        "recipient_instance_uuid": str(decision.instance_uuid),
        "project_access_revision": decision.decision_version,
        "agent_session_version": decision.session_version,
        "lease": receipt.model_dump(mode="json"),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    encoded = jwt.encode(claims, authority_signer, algorithm="EdDSA", headers=header)
    return SignedRuntimeLeaseReceipt(
        lease=receipt,
        attestation_jws=encoded,
        attestation_expires_at=expires,
    )


def verify_signed_runtime_lease(
    response: SignedRuntimeLeaseReceipt,
    *,
    trusted_public_key: Ed25519PublicKey,
    expected_service_id: UUID,
    expected_instance_uuid: UUID,
    expected_audience: str,
    expected_project_id: UUID,
    expected_session_uuid: UUID,
    expected_actor_user_id: UUID,
    expected_runtime_session_uuid: UUID,
    expected_project_access_revision: str,
    expected_agent_session_version: int,
) -> RuntimeLeaseReceipt:
    """Pure R11 source contract: verify issuer/recipient/scope/nonces and JWS.

    A caller cannot use this receipt alone to execute a Runtime/OS command.
    Revalidate current Team/Project/User/AgentSession/service every time.
    """
    if (
        expected_service_id.version != 4
        or expected_instance_uuid.version != 4
        or expected_project_id.version != 4
        or expected_session_uuid.version != 4
        or expected_actor_user_id.version != 4
        or expected_runtime_session_uuid.version != 4
        or expected_agent_session_version < 1
        or not re.fullmatch(r"[0-9a-f]{64}", expected_project_access_revision)
        or expected_audience not in {"files", "terminal", "web", "reverse"}
    ):
        raise AuthenticationRequired("invalid expected trusted Runtime recipient")
    try:
        header = jwt.get_unverified_header(response.attestation_jws)
        if (
            header.get("alg") != "EdDSA"
            or header.get("typ") != _ATTESTATION_TYPE
            or header.get("kid") != _key_id(trusted_public_key)
            or header.get("crit")
        ):
            raise AuthenticationRequired("untrusted Runtime lease attestation key/algorithm")
        claims = jwt.decode(
            response.attestation_jws,
            trusted_public_key,
            algorithms=["EdDSA"],
            audience=f"runtime-lease:{expected_audience}",
            issuer=DELEGATION_ISSUER,
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
            jti.version != 4
            or claims["purpose"] != _ATTESTATION_PURPOSE
            or claims["recipient_service_id"] != str(expected_service_id)
            or claims["recipient_instance_uuid"] != str(expected_instance_uuid)
            or claims["project_access_revision"] != expected_project_access_revision
            or claims["agent_session_version"] != expected_agent_session_version
            or not isinstance(claims["agent_session_version"], int)
            or claims["agent_session_version"] < 1
            or not isinstance(claims["lease"], dict)
            or not isinstance(claims["exp"], int)
            or not isinstance(claims["iat"], int)
            or claims["exp"] - claims["iat"] > int(_ATTESTATION_TTL.total_seconds())
        ):
            raise AuthenticationRequired("Runtime lease attestation scope invalid")
        lease = RuntimeLeaseReceipt.model_validate_json(
            json.dumps(claims["lease"], sort_keys=True, separators=(",", ":"))
        )
        if (
            lease != response.lease
            or lease.owner_service_id != expected_service_id
            or lease.project_id != expected_project_id
            or lease.agent_session_uuid != expected_session_uuid
            or lease.actor_user_id != expected_actor_user_id
            or lease.runtime_session_uuid != expected_runtime_session_uuid
            or lease.lease_nonce.version != 4
            or lease.owner_instance_uuid.version != 4
            or (lease.state == "active" and lease.lease_expires_at <= now)
            or (lease.state == "active" and claims["exp"] > int(lease.lease_expires_at.timestamp()))
            or int(response.attestation_expires_at.timestamp()) != claims["exp"]
        ):
            raise AuthenticationRequired("Runtime lease receipt differs from signed ledger")
        allowed = KIND_ACTION.get(lease.kind)
        if allowed is None or allowed[0] != expected_audience:
            raise AuthenticationRequired("Runtime lease audience does not match kind")
        if expected_instance_uuid != lease.owner_instance_uuid and (
            lease.state not in {"lost", "expired", "revoked", "closed"}
            or lease.cleanup_state != "confirmed"
        ):
            raise AuthenticationRequired("new instance has no attested cleanup")
        return lease
    except AuthenticationRequired:
        raise
    except (jwt.PyJWTError, ValidationError, ValueError, TypeError, KeyError) as exc:
        raise AuthenticationRequired("invalid signed Runtime lease receipt") from exc

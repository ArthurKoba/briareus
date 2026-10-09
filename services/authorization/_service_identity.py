"""Private Ed25519 service identity and backend-issued actor delegation.

Two independent proofs are required for runtime authorization: a service's
own registered asymmetric key and a separate short-lived Backend delegation
bound to a verified human, Project, AgentSession, operation and audience.
No public route or cross-runtime transport is registered in this module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_errors import AccessDenied, AuthenticationRequired, Conflict, InvalidInput
from common.platform_ids import AgentSessionUuid, PlatformProjectId, TeamId, UserId
from common.settings import ProcessSettings
from identity._domain import UserRole
from projects._resource_domain import ResourceKind
from projects._resource_service import ResourceService

from ._platform_application import PlatformApplication
from ._platform_auth import PlatformAdminBearerAuth
from ._project_access import AuthenticationMethod, CallerPrincipal
from ._project_decisions import ProjectActionAuthorizer
from ._project_sessions import SUPPORTED_GRANTS, ProjectSessionService
from ._service_identity_persistence import ConsumedAssertionRow, ServiceKeyRow
from ._session_persistence import ProjectAgentSessionRow

if TYPE_CHECKING:
    from projects._runtime_ledger import RuntimeLease

    from ._runtime_lease_attestation import SignedRuntimeLeaseReceipt

AUTHORIZATION_AUDIENCE = "platform-authorization"
DELEGATION_ISSUER = "briareus-authorization"
ALLOWED_AUDIENCES = frozenset(
    {
        "gateway",
        "files",
        "terminal",
        "web",
        "reverse",
        "svc",
        "infrastructure",
    }
)
# Audience and operation MUST be checked as a pair. A signed Files caller
# cannot request Terminal execution merely because its human has that grant.
ACTION_AUDIENCES: dict[str, frozenset[str]] = {
    "files.read": frozenset({"files"}),
    "files.write": frozenset({"files"}),
    "project.metadata.read": frozenset({"gateway"}),
    "terminal.execute": frozenset({"terminal"}),
    "web.access": frozenset({"web"}),
    "analysis.import": frozenset({"reverse"}),
    "agents.manage": frozenset({"gateway"}),
    "integrations.use": frozenset({"svc", "infrastructure"}),
    "variables.use": frozenset({"svc", "infrastructure"}),
}
SERVICE_LIFETIME = timedelta(seconds=30)
DELEGATION_LIFETIME = timedelta(seconds=45)


class ServiceReplayDetected(Conflict):
    code = "service_replay_detected"


class ServiceIdentitySettings(ProcessSettings):
    delegation_private_key: SecretStr = Field(validation_alias="DELEGATION_SIGNING_PRIVATE_KEY")


class ServiceAssertionClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iss: str
    aud: str
    jti: UUID
    service_id: UUID
    instance_uuid: UUID
    key_version: int = Field(ge=1)
    target_audience: str
    project_id: UUID
    session_uuid: UUID
    operation: str
    resource_id: UUID | None
    delegation_jti: UUID
    correlation_id: UUID
    request_fingerprint: str
    purpose: str
    iat: int
    nbf: int
    exp: int


class DelegationClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")
    iss: str
    aud: str
    jti: UUID
    service_id: UUID
    actor_id: UUID
    instance_uuid: UUID
    actor_credential_version: int = Field(ge=1)
    actor_admin_jti_digest: str
    project_id: UUID
    session_uuid: UUID
    operation: str
    resource_id: UUID | None
    decision_version: str
    session_version: int = Field(ge=1)
    request_fingerprint: str
    purpose: str
    iat: int
    nbf: int
    exp: int


@dataclass(frozen=True, slots=True)
class VerifiedService:
    service_id: UUID
    audience: str
    key_version: int


@dataclass(frozen=True, slots=True)
class IssuedDelegation:
    bearer: SecretStr
    jti: UUID
    expires_at: datetime
    service_id: UUID
    instance_uuid: UUID
    project_id: PlatformProjectId


@dataclass(frozen=True, slots=True)
class ServiceAuthorizationDecision:
    actor_id: UserId
    service_id: UUID
    instance_uuid: UUID
    audience: str
    project_id: PlatformProjectId
    session_uuid: AgentSessionUuid
    operation: str
    resource_id: UUID | None
    correlation_id: UUID
    decision_version: str
    session_version: int
    agent_session_hard_expires_at: datetime
    expires_at: datetime
    actor_credential_version: int
    actor_admin_jti_digest: str
    service_key_id: UUID
    service_key_version: int
    service_assertion_jti_digest: str
    delegation_jti_digest: str
    proof_mac: str = ""


class AuthorizedOperationReceipt(BaseModel):
    """Non-secret, source-only JSON response for a verified runtime service."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["authorized"] = "authorized"
    actor_user_id: UUID
    service_id: UUID
    instance_uuid: UUID
    audience: str
    project_id: UUID
    session_uuid: UUID
    operation: str
    resource_id: UUID | None
    correlation_id: UUID
    project_access_revision: str
    expected_session_version: int = Field(ge=1)
    session_hard_expires_at: datetime
    expires_at: datetime

    @classmethod
    def from_verified(cls, decision: ServiceAuthorizationDecision) -> AuthorizedOperationReceipt:
        return cls(
            actor_user_id=decision.actor_id,
            service_id=decision.service_id,
            instance_uuid=decision.instance_uuid,
            audience=decision.audience,
            project_id=decision.project_id,
            session_uuid=decision.session_uuid,
            operation=decision.operation,
            resource_id=decision.resource_id,
            correlation_id=decision.correlation_id,
            project_access_revision=decision.decision_version,
            expected_session_version=decision.session_version,
            session_hard_expires_at=decision.agent_session_hard_expires_at,
            expires_at=decision.expires_at,
        )


class CurrentServiceDecisionValidator(Protocol):
    async def verify_live_decision(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
    ) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _validate_time(claims: ServiceAssertionClaims | DelegationClaims, max_seconds: int) -> None:
    now = int(_utcnow().timestamp())
    if (
        claims.jti.version != 4
        or claims.exp <= now
        or claims.nbf > now
        or claims.iat > now
        or claims.exp - claims.iat > max_seconds
        or claims.iat > claims.nbf
    ):
        raise AuthenticationRequired("signed service assertion expired or invalid")


def _public_key(encoded: str) -> Ed25519PublicKey:
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) != 32:
            raise ValueError("Ed25519 key must be 32 bytes")
        return Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise InvalidInput("service public key must be base64 encoded Ed25519") from exc


def _digest(value: UUID) -> str:
    return hashlib.sha256(str(value).encode("ascii")).hexdigest()


class ServiceIdentityAuthority:
    """Owner-private service key registry, signed delegation and replay gate."""

    def __init__(
        self,
        application: PlatformApplication,
        sessions: ProjectSessionService,
        resources: ResourceService,
        admin_auth: PlatformAdminBearerAuth,
        settings: ServiceIdentitySettings,
    ) -> None:
        raw = settings.delegation_private_key.get_secret_value()
        try:
            key = serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("delegation signer must be an Ed25519 private key")
            self._signer = key
            material = key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            self._decision_key = hashlib.sha256(material + b"platform-decision-proof-v1").digest()
        except (ValueError, TypeError) as exc:
            raise ValueError("DELEGATION_SIGNING_PRIVATE_KEY must be Ed25519 PEM") from exc
        self.app = application
        self.sessions = sessions
        self.resources = resources
        self.admin_auth = admin_auth
        self.project_actions = ProjectActionAuthorizer(application, sessions)

    async def register_key(
        self,
        tx: AsyncSession,
        actor: CallerPrincipal,
        *,
        service_id: UUID,
        name: str,
        audience: str,
        public_key_b64: str,
    ) -> VerifiedService:
        user = await self.app.current_user(tx, actor, lock=True)
        if user.role is not UserRole.SUPERUSER:
            raise AccessDenied("current superuser required to provision a runtime")
        if audience not in ALLOWED_AUDIENCES:
            raise InvalidInput("unregistered target service audience")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,79}", name, flags=re.ASCII):
            raise InvalidInput("invalid service name")
        if service_id.version != 4:
            raise InvalidInput("service_id must be UUIDv4")
        _public_key(public_key_b64)
        key_bytes = base64.b64decode(public_key_b64, validate=True)
        existing = await tx.scalar(
            select(func.max(ServiceKeyRow.key_version)).where(
                ServiceKeyRow.service_id == service_id,
                ServiceKeyRow.audience == audience,
            )
        )
        version = int(existing or 0) + 1
        row = ServiceKeyRow(
            key_id=uuid4(),
            service_id=service_id,
            service_name=name,
            audience=audience,
            key_version=version,
            public_key_b64=public_key_b64,
            public_key_fingerprint=hashlib.sha256(key_bytes).hexdigest(),
            issued_by_user_id=actor.user_id,
            enabled=True,
        )
        tx.add(row)
        await tx.flush()
        self.app._audit(
            tx,
            actor=actor.user_id,
            project=None,
            action="security.service_key_registered",
            target=row.key_id,
            event={"service_id": str(service_id), "audience": audience, "version": version},
        )
        return VerifiedService(service_id, audience, version)

    async def revoke_key(
        self,
        tx: AsyncSession,
        actor: CallerPrincipal,
        key_id: UUID,
    ) -> None:
        user = await self.app.current_user(tx, actor, lock=True)
        if user.role is not UserRole.SUPERUSER:
            raise AccessDenied("superuser required to revoke service key")
        row = await tx.scalar(
            select(ServiceKeyRow).where(ServiceKeyRow.key_id == key_id).with_for_update()
        )
        if row is None:
            raise AccessDenied("service key unavailable")
        if row.enabled:
            row.enabled = False
            row.revoked_at = _utcnow()
            self.app._audit(
                tx,
                actor=actor.user_id,
                project=None,
                action="security.service_key_revoked",
                target=key_id,
                event={"service_id": str(row.service_id), "audience": row.audience},
            )

    async def issue_delegation(
        self,
        tx: AsyncSession,
        *,
        original_admin_bearer: str,
        service_id: UUID,
        instance_uuid: UUID,
        audience: str,
        project_id: PlatformProjectId,
        session_uuid: AgentSessionUuid,
        operation: str,
        request_fingerprint: str,
        resource_id: UUID | None = None,
    ) -> IssuedDelegation:
        """Create actor proof only after verifying the ORIGINAL signed User bearer.

        No UI-submitted principal or OAuth legacy identity may mint delegation.
        This port remains in-process; external minting is a future C2 decision.
        """
        if audience not in ALLOWED_AUDIENCES or audience not in ACTION_AUDIENCES.get(
            operation, frozenset()
        ):
            raise AccessDenied("service audience is not authorized for this action")
        if not isinstance(instance_uuid, UUID) or instance_uuid.version != 4:
            raise InvalidInput("service instance UUIDv4 required")
        self._check_fingerprint(request_fingerprint)
        claims = self.admin_auth._verified_claims(original_admin_bearer)
        if claims is None:
            raise AuthenticationRequired("a verified local Admin bearer is required")
        caller = CallerPrincipal(
            user_id=UserId(claims.sub),
            authentication_method=AuthenticationMethod.LOCAL_LOGIN,
            credential_version=claims.rev,
            admin_jti_digest=_digest(claims.jti),
        )
        await self.app.current_user(tx, caller, lock=True)
        service = await tx.scalar(
            select(ServiceKeyRow)
            .where(
                ServiceKeyRow.service_id == service_id,
                ServiceKeyRow.audience == audience,
                ServiceKeyRow.enabled.is_(True),
            )
            .order_by(ServiceKeyRow.key_version.desc())
            .limit(1)
        )
        if service is None:
            raise AccessDenied("target runtime service is unavailable")
        decision = await self.project_actions.authorize(
            tx, caller, project_id, session_uuid, operation
        )
        await self._validate_resource(tx, caller, project_id, operation, resource_id)
        now = _utcnow()
        expires = min(now + DELEGATION_LIFETIME, decision.session_hard_expires_at)
        if expires <= now:
            raise AccessDenied("AgentSession grant already expired")
        jti = uuid4()
        payload = {
            "iss": DELEGATION_ISSUER,
            "aud": audience,
            "jti": str(jti),
            "service_id": str(service_id),
            "instance_uuid": str(instance_uuid),
            "actor_id": str(caller.user_id),
            "actor_credential_version": claims.rev,
            "actor_admin_jti_digest": _digest(claims.jti),
            "project_id": str(project_id),
            "session_uuid": str(session_uuid),
            "operation": operation,
            "resource_id": str(resource_id) if resource_id else None,
            "decision_version": decision.project_access_revision,
            "session_version": decision.agent_session_version,
            "request_fingerprint": request_fingerprint,
            "purpose": "project-operation",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires.timestamp()),
        }
        token = jwt.encode(
            payload,
            self._signer,
            algorithm="EdDSA",
            headers={"typ": "platform-delegation+jwt", "kid": "platform"},
        )
        self.app._audit(
            tx,
            actor=caller.user_id,
            project=project_id,
            action="security.delegation_issued",
            target=jti,
            event={"audience": audience, "service_id": str(service_id), "operation": operation},
        )
        return IssuedDelegation(
            bearer=SecretStr(token),
            jti=jti,
            expires_at=expires,
            service_id=service_id,
            instance_uuid=instance_uuid,
            project_id=project_id,
        )

    @staticmethod
    def _check_fingerprint(fingerprint: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint, flags=re.ASCII):
            raise InvalidInput("request fingerprint must be canonical SHA-256")

    async def _validate_resource(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        operation: str,
        resource_id: UUID | None,
    ) -> None:
        if operation == "integrations.use":
            if resource_id is None:
                raise AccessDenied("integration ID required for credential operation")
            await self.resources.resolve_for_project(
                tx,
                caller,
                project_id,
                ResourceKind.INTEGRATION,
                resource_id=resource_id,
            )
        elif operation == "variables.use":
            if resource_id is None:
                raise AccessDenied("variable ID required for secret operation")
            await self.resources.resolve_for_project(
                tx,
                caller,
                project_id,
                ResourceKind.VARIABLE,
                resource_id=resource_id,
            )
        elif resource_id is not None:
            # A resource-specific operation cannot use a generic grant to
            # bypass the Integration/Variable explicit resource checks.
            raise AccessDenied("this operation does not accept a resource ID")

    @staticmethod
    def _header(token: str, *, typ: str) -> dict[str, object]:
        if not 64 <= len(token) <= 8192:
            raise AuthenticationRequired("service assertion is malformed")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthenticationRequired("invalid signed service assertion") from exc
        if header.get("alg") != "EdDSA" or header.get("typ") != typ or header.get("crit"):
            raise AuthenticationRequired("service assertion header rejected")
        return header

    async def consume_service_operation(
        self,
        tx: AsyncSession,
        *,
        service_assertion: str,
        backend_delegation: str,
        expected_audience: str,
        expected_instance_uuid: UUID,
        expected_project_id: PlatformProjectId,
        expected_session_uuid: AgentSessionUuid,
        expected_action: str,
        expected_fingerprint: str,
        expected_resource_id: UUID | None = None,
    ) -> ServiceAuthorizationDecision:
        """Verify TWO signed factors, current DB rights and one-use JTI ledger.

        The caller must bind expected_* to its own trusted request routing,
        not read them from untrusted JWT claims. This internal port is not an
        HTTP handler and does not execute a remote operation.
        """
        if expected_audience not in ALLOWED_AUDIENCES:
            raise AuthenticationRequired("unexpected target service audience")
        if not isinstance(expected_instance_uuid, UUID) or expected_instance_uuid.version != 4:
            raise AuthenticationRequired("verified runtime instance UUIDv4 required")
        if expected_action not in SUPPORTED_GRANTS or expected_audience not in ACTION_AUDIENCES.get(
            expected_action, frozenset()
        ):
            raise AccessDenied("runtime operation not supported for service audience")
        self._check_fingerprint(expected_fingerprint)
        header = self._header(service_assertion, typ="platform-service+jwt")
        try:
            key_id = UUID(str(header["kid"]))
            if key_id.version != 4:
                raise ValueError("not a UUIDv4 key")
        except (KeyError, ValueError, TypeError) as exc:
            raise AuthenticationRequired("unregistered service key identity") from exc
        row = await tx.scalar(select(ServiceKeyRow).where(ServiceKeyRow.key_id == key_id))
        if row is None or not row.enabled or row.revoked_at is not None:
            raise AuthenticationRequired("service key revoked or unavailable")
        if row.audience != expected_audience:
            raise AuthenticationRequired("service key audience mismatch")
        verified_key_b64 = row.public_key_b64
        verified_service_id = row.service_id
        verified_key_version = row.key_version
        try:
            raw_assertion = jwt.decode(
                service_assertion,
                _public_key(verified_key_b64),
                algorithms=["EdDSA"],
                audience=AUTHORIZATION_AUDIENCE,
                issuer=f"service:{verified_service_id}",
                options={
                    "require": [
                        "iss",
                        "aud",
                        "jti",
                        "service_id",
                        "instance_uuid",
                        "key_version",
                        "target_audience",
                        "project_id",
                        "session_uuid",
                        "operation",
                        "resource_id",
                        "delegation_jti",
                        "correlation_id",
                        "request_fingerprint",
                        "purpose",
                        "iat",
                        "nbf",
                        "exp",
                    ]
                },
                leeway=0,
            )
            assertion = ServiceAssertionClaims.model_validate(raw_assertion)
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError) as exc:
            raise AuthenticationRequired("runtime service assertion invalid") from exc
        _validate_time(assertion, int(SERVICE_LIFETIME.total_seconds()))
        if (
            assertion.service_id != row.service_id
            or assertion.instance_uuid != expected_instance_uuid
            or assertion.key_version != row.key_version
            or assertion.target_audience != expected_audience
            or assertion.aud != AUTHORIZATION_AUDIENCE
            or assertion.purpose != "authorize-project-operation"
        ):
            raise AuthenticationRequired("runtime service assertion does not match key")
        self._header(backend_delegation, typ="platform-delegation+jwt")
        try:
            raw_delegation = jwt.decode(
                backend_delegation,
                self._signer.public_key(),
                algorithms=["EdDSA"],
                issuer=DELEGATION_ISSUER,
                audience=expected_audience,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "jti",
                        "service_id",
                        "instance_uuid",
                        "actor_id",
                        "actor_credential_version",
                        "actor_admin_jti_digest",
                        "project_id",
                        "session_uuid",
                        "operation",
                        "resource_id",
                        "decision_version",
                        "session_version",
                        "request_fingerprint",
                        "purpose",
                        "iat",
                        "nbf",
                        "exp",
                    ]
                },
                leeway=0,
            )
            delegation = DelegationClaims.model_validate(raw_delegation)
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError) as exc:
            raise AuthenticationRequired("backend actor delegation invalid") from exc
        _validate_time(delegation, int(DELEGATION_LIFETIME.total_seconds()))
        if (
            assertion.delegation_jti != delegation.jti
            or delegation.service_id != row.service_id
            or delegation.instance_uuid != expected_instance_uuid
            or assertion.project_id != expected_project_id
            or delegation.project_id != expected_project_id
            or assertion.session_uuid != expected_session_uuid
            or delegation.session_uuid != expected_session_uuid
            or assertion.operation != expected_action
            or delegation.operation != expected_action
            or assertion.resource_id != expected_resource_id
            or delegation.resource_id != expected_resource_id
            or assertion.request_fingerprint != expected_fingerprint
            or delegation.request_fingerprint != expected_fingerprint
            or delegation.purpose != "project-operation"
            or not re.fullmatch(r"[0-9a-f]{64}", delegation.actor_admin_jti_digest)
        ):
            raise AuthenticationRequired("service and delegation scopes disagree")
        caller = CallerPrincipal(
            UserId(delegation.actor_id),
            AuthenticationMethod.LOCAL_LOGIN,
            delegation.actor_credential_version,
            delegation.actor_admin_jti_digest,
        )
        await self.app.current_user(tx, caller, lock=True)
        locked_key = await tx.scalar(
            select(ServiceKeyRow)
            .where(ServiceKeyRow.key_id == key_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            locked_key is None
            or not locked_key.enabled
            or locked_key.revoked_at is not None
            or locked_key.service_id != verified_service_id
            or locked_key.key_version != verified_key_version
            or locked_key.key_version != assertion.key_version
            or locked_key.public_key_b64 != verified_key_b64
        ):
            raise AuthenticationRequired("runtime service key revoked or changed")
        decision = await self.project_actions.authorize(
            tx,
            caller,
            expected_project_id,
            expected_session_uuid,
            expected_action,
        )
        if (
            decision.project_access_revision != delegation.decision_version
            or decision.agent_session_version != delegation.session_version
        ):
            raise AccessDenied("Project/AgentSession grant revision changed since delegation")
        await self._validate_resource(
            tx,
            caller,
            expected_project_id,
            expected_action,
            expected_resource_id,
        )
        # A consumed JTI is durable and single-use across every project call.
        # Never insert before all current-state security checks pass.
        for kind, issuer_id, jti, expires in (
            ("service", row.service_id, assertion.jti, assertion.exp),
            ("delegation", delegation.actor_id, delegation.jti, delegation.exp),
        ):
            inserted = await tx.scalar(
                insert(ConsumedAssertionRow)
                .values(
                    id=uuid4(),
                    kind=kind,
                    issuer_id=issuer_id,
                    jti_digest=_digest(jti),
                    project_id=expected_project_id,
                    session_uuid=expected_session_uuid,
                    expires_at=datetime.fromtimestamp(expires, UTC),
                )
                .on_conflict_do_nothing(constraint="uq_assertion_single_use")
                .returning(ConsumedAssertionRow.id)
            )
            if inserted is None:
                raise ServiceReplayDetected("signed service assertion already consumed")
        self.app._audit(
            tx,
            actor=caller.user_id,
            project=expected_project_id,
            action="security.service_operation_authorized",
            target=assertion.correlation_id,
            event={
                "audience": expected_audience,
                "operation": expected_action,
                "service_id": str(row.service_id),
            },
        )
        return self._seal_decision(
            ServiceAuthorizationDecision(
                actor_id=caller.user_id,
                service_id=row.service_id,
                instance_uuid=expected_instance_uuid,
                audience=expected_audience,
                project_id=expected_project_id,
                session_uuid=expected_session_uuid,
                operation=expected_action,
                resource_id=expected_resource_id,
                correlation_id=assertion.correlation_id,
                decision_version=decision.project_access_revision,
                session_version=decision.agent_session_version,
                agent_session_hard_expires_at=decision.session_hard_expires_at,
                actor_credential_version=delegation.actor_credential_version,
                actor_admin_jti_digest=delegation.actor_admin_jti_digest,
                service_key_id=key_id,
                service_key_version=assertion.key_version,
                service_assertion_jti_digest=_digest(assertion.jti),
                delegation_jti_digest=_digest(delegation.jti),
                expires_at=min(
                    datetime.fromtimestamp(assertion.exp, UTC),
                    datetime.fromtimestamp(delegation.exp, UTC),
                    decision.session_hard_expires_at,
                ),
            )
        )

    def _decision_mac(self, decision: ServiceAuthorizationDecision) -> str:
        """Private authenticated permit evidence (not a public bearer)."""
        from dataclasses import fields

        body = {
            field.name: getattr(decision, field.name)
            for field in fields(decision)
            if field.name != "proof_mac"
        }
        encoded = json.dumps(body, sort_keys=True, default=str, separators=(",", ":")).encode()
        return hmac.new(self._decision_key, encoded, hashlib.sha256).hexdigest()

    def _seal_decision(
        self,
        decision: ServiceAuthorizationDecision,
    ) -> ServiceAuthorizationDecision:
        return replace(decision, proof_mac=self._decision_mac(decision))

    async def verify_live_decision(
        self,
        tx: AsyncSession,
        decision: ServiceAuthorizationDecision,
    ) -> None:
        """Recheck EVERYTHING before each independent ledger UoW.

        The service JWT/delegation consumption MUST already be committed.
        Only an unexpired, HMAC-stamped permit from this authority may enter
        Runtime/Files/Reverse UoWs. No UUID-only construction is trusted.
        """
        now = _utcnow()
        if (
            decision.expires_at <= now
            or decision.agent_session_hard_expires_at <= now
            or decision.operation not in SUPPORTED_GRANTS
            or decision.audience not in ACTION_AUDIENCES.get(decision.operation, frozenset())
            or decision.service_key_id.version != 4
            or not hmac.compare_digest(decision.proof_mac, self._decision_mac(decision))
        ):
            raise AuthenticationRequired("expired or unsigned service decision")
        caller = CallerPrincipal(
            decision.actor_id,
            AuthenticationMethod.LOCAL_LOGIN,
            decision.actor_credential_version,
            decision.actor_admin_jti_digest,
        )
        # User -> service key -> Project -> AgentSession lock order mirrors
        # key-revoke/admin-write flows, avoiding a service-key/User deadlock.
        await self.app.current_user(tx, caller, lock=True)
        key = await tx.scalar(
            select(ServiceKeyRow)
            .where(
                ServiceKeyRow.key_id == decision.service_key_id,
            )
            .with_for_update()
        )
        if (
            key is None
            or not key.enabled
            or key.revoked_at is not None
            or key.service_id != decision.service_id
            or key.key_version != decision.service_key_version
            or key.audience != decision.audience
        ):
            raise AuthenticationRequired("runtime service key no longer active")
        for kind, issuer, digest in (
            ("service", decision.service_id, decision.service_assertion_jti_digest),
            ("delegation", decision.actor_id, decision.delegation_jti_digest),
        ):
            record = await tx.scalar(
                select(ConsumedAssertionRow.id).where(
                    ConsumedAssertionRow.kind == kind,
                    ConsumedAssertionRow.issuer_id == issuer,
                    ConsumedAssertionRow.jti_digest == digest,
                    ConsumedAssertionRow.project_id == decision.project_id,
                    ConsumedAssertionRow.session_uuid == decision.session_uuid,
                    ConsumedAssertionRow.expires_at > now,
                )
            )
            if record is None:
                raise AuthenticationRequired("uncommitted or revoked service assertion")
        # Lock Project and owning Team after User/service key and before
        # AgentSession to fence ownership/member transfers and session revoke.
        project = await self.app.projects.get(tx, decision.project_id, lock=True)
        if project is None:
            raise AccessDenied("Project no longer available")
        if project.owner_team_id is not None:
            team = await self.app.teams.get(tx, TeamId(project.owner_team_id), lock=True)
            if team is None:
                raise AccessDenied("Project owning Team unavailable")
        session_row = await tx.scalar(
            select(ProjectAgentSessionRow)
            .where(ProjectAgentSessionRow.session_uuid == decision.session_uuid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        actual_grants: object = (
            session_row.grants.get("operations") if session_row is not None else None
        )
        if (
            session_row is None
            or session_row.project_id != decision.project_id
            or session_row.status != "active"
            or session_row.hard_expires_at <= now
            or session_row.version != decision.session_version
            or not isinstance(actual_grants, list)
            or decision.operation not in actual_grants
        ):
            raise AccessDenied("Project AgentSession grant revoked or expired")
        current = await self.project_actions.authorize(
            tx,
            caller,
            decision.project_id,
            decision.session_uuid,
            decision.operation,
        )
        if (
            current.project_access_revision != decision.decision_version
            or current.agent_session_version != decision.session_version
            or current.session_hard_expires_at != decision.agent_session_hard_expires_at
        ):
            raise AccessDenied("Project, Team or AgentSession grant revision changed")
        await self._validate_resource(
            tx, caller, decision.project_id, decision.operation, decision.resource_id
        )

    async def consume_committed_operation(
        self,
        *,
        service_assertion: str,
        backend_delegation: str,
        expected_audience: str,
        expected_instance_uuid: UUID,
        expected_project_id: PlatformProjectId,
        expected_session_uuid: AgentSessionUuid,
        expected_action: str,
        expected_fingerprint: str,
        expected_resource_id: UUID | None = None,
    ) -> ServiceAuthorizationDecision:
        """Consume both JWTs in one committed UoW BEFORE returning a permit."""
        async with self.app.db.transaction() as tx:
            result = await self.consume_service_operation(
                tx,
                service_assertion=service_assertion,
                backend_delegation=backend_delegation,
                expected_audience=expected_audience,
                expected_instance_uuid=expected_instance_uuid,
                expected_project_id=expected_project_id,
                expected_session_uuid=expected_session_uuid,
                expected_action=expected_action,
                expected_fingerprint=expected_fingerprint,
                expected_resource_id=expected_resource_id,
            )
        return result  # noqa: RET504 - return only after transaction commit

    def sign_verified_runtime_lease(
        self,
        lease: RuntimeLease,
        decision: ServiceAuthorizationDecision,
    ) -> SignedRuntimeLeaseReceipt:
        """Restricted internal signer; caller verifies live SQL proof separately.

        This signs a typed Backend ledger snapshot only, never arbitrary
        client JSON. A JWS is an attestation, not an OS permit or grant.
        """
        from ._runtime_lease_attestation import issue_signed_runtime_lease

        return issue_signed_runtime_lease(lease, decision=decision, authority_signer=self._signer)

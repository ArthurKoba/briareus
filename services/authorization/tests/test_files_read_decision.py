"""Private Files read-decision integration with controlled authority sources.

JWT signature verification, the body-bound peer resolver/replay contract,
routers, SQLAlchemy selectors and Cedar are real code. TLS provenance,
Platform/Files owner facts and SQL storage below are test fixtures only.
Nothing is mounted in the running stack; no real User or filesystem is read.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import unittest
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response
from starlette.responses import Response as StarletteResponse
from test_files_decision_scope import CurrentPrivateSources, SingleSessionSQL
from test_panel_session_detail import future, session_row

from authorization._decision_api import (
    AuthorizationDecisionReader,
    AuthorizedCurrentGrant,
    VerifiedDecisionCaller,
)
from authorization._decision_peer_transport import (
    TransportAuthenticatedDecisionPeerResolver,
    VerifiedTransportPeerRequest,
)
from authorization._files_read_decision import (
    FilesReadDecisionCommand,
    FilesReadDecisionService,
    files_read_decision_router,
)
from authorization._rauthy_decision_attestor import RauthyDecisionAttestor
from authorization._rauthy_jwks import RauthyJwksVerifier
from authorization._resource_scope import EffectResource, VerifiedResourceOwnerProof
from authorization.platform_runtime import create_authorization_app

_PATH = "/internal/v1/authorization/files/read-decision"


class ReplayFixture:
    def __init__(self) -> None:
        self.used: set[tuple[str, str]] = set()

    async def consume(self, *, source_audience: str, nonce: str, body_sha256: str) -> bool:
        assert len(body_sha256) == 64
        key = (source_audience, nonce)
        if key in self.used:
            return False
        self.used.add(key)
        return True


class CurrentFilesOwnerFixture:
    def __init__(self, command: FilesReadDecisionCommand) -> None:
        self.calls = 0
        self.change_on_second = False
        self.proof: VerifiedResourceOwnerProof | None = VerifiedResourceOwnerProof(
            project_uuid=command.project_uuid,
            hand="files",
            tool="read_file",
            action="files.read",
            resource=command.resource,
            revision=command.expected_resource_revision,
            expires_at=future(15),
        )

    def verify_current_scope(
        self, *, project_uuid: UUID, scope: dict[str, object]
    ) -> VerifiedResourceOwnerProof | None:
        assert project_uuid.version == 4 and scope["hand"] == "files"
        self.calls += 1
        if self.change_on_second and self.calls == 2 and self.proof is not None:
            self.proof = replace(self.proof, revision=self.proof.revision + 1)
        return self.proof


class FilesReadDecisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.issuer = "https://source-fixture.invalid/auth/v1/"
        self.audience = "https://source-fixture.invalid/hands/files/mcp"
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        public.update(kid="ephemeral-read-decision-test", alg="RS256", use="sig")
        verifier = RauthyJwksVerifier(
            issuer=self.issuer,
            resource_audience=self.audience,
            oauth_client_id="source-panel",
            trusted_jwks={"keys": [public]},
        )
        actor, project = uuid4(), uuid4()
        self.row = session_row(actor, project, revision=4)
        resource = EffectResource(
            kind="workspace_path", id=f"project-path-v1:{project}:" + "a" * 64
        )
        self.command = FilesReadDecisionCommand(
            protocol="files-read-decision-v1",
            operation_uuid=uuid4(),
            phase="before_read",
            project_uuid=project,
            agent_session_uuid=self.row.session_uuid,
            expected_grant_revision=4,
            expected_resource_revision=7,
            max_bytes=4096,
            hand="files",
            tool="read_file",
            action="files.read",
            resource=resource,
        )
        self.row.grants = {
            "operations": ["files.read"],
            "resources": [
                {
                    "hand": "files",
                    "tool": "read_file",
                    "action": "files.read",
                    "resource": resource.model_dump(),
                }
            ],
        }
        self.db = SingleSessionSQL([self.row])
        self.membership = CurrentPrivateSources(self.command, actor, self.issuer)
        self.resource = CurrentFilesOwnerFixture(self.command)
        self.replay = ReplayFixture()
        attestor = RauthyDecisionAttestor(
            bearer_verifier=verifier,
            peer_resolver=TransportAuthenticatedDecisionPeerResolver(replay_guard=self.replay),
            membership_resolver=self.membership,
        )
        self.service = FilesReadDecisionService(
            attestor=attestor,
            reader=AuthorizationDecisionReader(self.db),
            resource_owner=self.resource,
        )
        self.app = FastAPI()
        self.app.include_router(files_read_decision_router(resolve_service=lambda: self.service))
        self.install_transport_proof = True
        self.bad_digest = False
        self.transport_nonce: str | None = None

        @self.app.middleware("http")
        async def test_only_trusted_ingress(
            request: Request, call_next: Callable[[Request], Awaitable[StarletteResponse]]
        ) -> StarletteResponse:
            # Explicit fixture for a TLS/Unix adapter, never production
            # certificate verification or trust derived from browser headers.
            if self.install_transport_proof:
                body = await request.body()
                now = datetime.now(UTC)
                request.scope["briareus.verified_private_peer.v1"] = VerifiedTransportPeerRequest(
                    transport="mtls",
                    consumer="hand",
                    source_audience="files",
                    target_audience="briareus:access",
                    http_body_sha256="0" * 64
                    if self.bad_digest
                    else hashlib.sha256(body).hexdigest(),
                    resolved_effect_key=self.command.effect_key(),
                    nonce=self.transport_nonce or secrets.token_hex(16),
                    authenticated_at=now,
                    expires_at=now + timedelta(seconds=15),
                    verified_peer=True,
                )
            return await call_next(request)

    def token(self, **changes: object) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": self.issuer,
                "aud": ["source-panel", self.audience],
                "typ": "Bearer",
                "azp": "source-panel",
                "jti": "ephemeral-resource-fixture",
                "nbf": now,
                "sub": self.membership.member.rauthy_subject,
                "iat": now,
                "exp": now + 60,
                **changes,
            },
            self.key,
            algorithm="RS256",
            headers={"kid": "ephemeral-read-decision-test"},
        )

    async def decide(
        self,
        *,
        phase: str = "before_read",
        token: str | None = None,
        changes: dict[str, object] | None = None,
        app: FastAPI | None = None,
    ) -> Response:
        body = {**self.command.model_dump(mode="json"), "phase": phase, **(changes or {})}
        async with AsyncClient(
            transport=ASGITransport(app=app or self.app), base_url="http://local-access-owner"
        ) as client:
            return await client.post(
                _PATH,
                json=body,
                headers={"Authorization": "Bearer " + (token or self.token())},
            )

    async def test_both_phases_recheck_current_sources_without_legacy_identity(
        self,
    ) -> None:
        for phase in ("before_read", "after_read"):
            result = await self.decide(phase=phase)
            self.assertEqual(result.status_code, 200, result.text)
            receipt = result.json()
            self.assertEqual(receipt["phase"], phase)
            self.assertEqual(receipt["operation_uuid"], str(self.command.operation_uuid))
            self.assertEqual(receipt["actor_uuid"], str(self.row.created_by_principal_id))
            self.assertEqual(receipt["resource"], self.command.resource.model_dump())
            self.assertEqual(receipt["grant_revision"], 4)
            self.assertEqual(receipt["resource_revision"], 7)
            self.assertEqual(receipt["max_bytes"], 4096)
            checked = datetime.fromisoformat(receipt["checked_at"])
            expiry = datetime.fromisoformat(receipt["expires_at"])
            self.assertTrue(checked < expiry <= checked + timedelta(seconds=5))
            self.assertEqual(result.headers["cache-control"], "no-store")
            for absent in ("identity_epoch", "owner_fence", "token", "path", "root"):
                self.assertNotIn(absent, receipt)
        self.assertEqual(len(self.db.queries), 2)
        self.assertEqual(len(self.replay.used), 2)
        self.assertEqual(self.resource.calls, 4)

    async def test_after_read_denies_revocation_resource_change_and_lost_membership(
        self,
    ) -> None:
        accepted = await self.decide()
        self.assertEqual(accepted.status_code, 200)
        self.row.status = "revoked"
        self.row.version = 5
        self.assertEqual((await self.decide(phase="after_read")).status_code, 403)
        self.row.status = "active"
        self.row.version = 4
        original = self.resource.proof
        self.resource.proof = replace(original, revision=8)
        self.assertEqual((await self.decide(phase="after_read")).status_code, 403)
        self.resource.proof = original
        self.membership.member = replace(self.membership.member, project_uuid=uuid4())
        self.assertEqual((await self.decide(phase="after_read")).status_code, 403)

    async def test_default_unavailable_and_missing_resource_owner_never_issue_receipt(self) -> None:
        default = await self.decide(app=create_authorization_app())
        self.assertEqual(default.status_code, 503, default.text)
        self.resource.proof = None
        missing = await self.decide()
        self.assertEqual(missing.status_code, 503, missing.text)
        self.assertFalse(self.db.queries)

    async def test_nonce_replay_and_bad_exact_body_denied(self) -> None:
        self.transport_nonce = "a" * 32
        self.assertEqual((await self.decide()).status_code, 200)
        # Phase changes cannot reuse the attested nonce, even though the
        # opaque operation UUID must stay the same for this logical read.
        replay = await self.decide(phase="after_read")
        self.assertEqual(replay.status_code, 403, replay.text)
        self.transport_nonce = None
        self.bad_digest = True
        self.assertEqual((await self.decide()).status_code, 403)
        self.assertEqual(len(self.db.queries), 1)

    async def test_identity_and_original_resource_proof_required_before_sql(self) -> None:
        self.assertEqual((await self.decide(token=self.token(aud="source-panel"))).status_code, 401)
        self.install_transport_proof = False
        self.assertEqual((await self.decide()).status_code, 503)
        self.install_transport_proof = True
        self.resource.proof = replace(self.resource.proof, expires_at=future(-1))
        self.assertEqual((await self.decide()).status_code, 403)
        self.assertFalse(self.db.queries)

    async def test_original_short_proof_bounds_receipt_and_post_sql_change_denies(self) -> None:
        assert self.resource.proof is not None
        bound = future(2)
        self.resource.proof = replace(self.resource.proof, expires_at=bound)
        result = await self.decide()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertLessEqual(datetime.fromisoformat(result.json()["expires_at"]), bound)
        self.resource.calls = 0
        self.resource.change_on_second = True
        changed = await self.decide(phase="after_read")
        self.assertEqual(changed.status_code, 403, changed.text)
        self.assertNotIn("allowed", changed.json())

    async def test_current_grant_expiration_on_transaction_exit_never_returns_proof(self) -> None:
        clock = datetime.now(UTC)

        class Clock(datetime):
            @classmethod
            def now(cls, tz: object = None) -> datetime:
                del tz
                return clock

        class DelayedTransactionExit(SingleSessionSQL):
            @asynccontextmanager
            async def transaction(self) -> AsyncIterator[DelayedTransactionExit]:
                nonlocal clock
                yield self
                clock += timedelta(minutes=5)

        reader = AuthorizationDecisionReader(DelayedTransactionExit([self.row]))
        caller = VerifiedDecisionCaller(
            actor_uuid=self.row.created_by_principal_id,
            project_uuid=self.row.project_id,
            agent_session_uuid=self.row.session_uuid,
            consumer="hand",
            authority="rauthy",
            verified_peer_audience="briareus:access",
            proof_expires_at=clock + timedelta(seconds=15),
            attested_effect_key=self.command.effect_key(),
        )
        with patch("authorization._decision_api.datetime", Clock):
            grant = await reader.current_grant(self.command, caller)
        self.assertIsNone(grant)

    async def test_changed_or_malformed_reader_grant_never_becomes_files_permit(self) -> None:
        """The concrete Access reader is safe, but future private adapters
        must not turn a foreign/expired grant into an allowed Files receipt.
        """

        class ControlledGrantReader:
            def __init__(self, grant: object) -> None:
                self.grant = grant

            async def current_grant(self, command: object, caller: object) -> object:
                del command, caller
                return self.grant

        base = AuthorizedCurrentGrant(
            actor_uuid=self.row.created_by_principal_id,
            project_uuid=self.command.project_uuid,
            agent_session_uuid=self.command.agent_session_uuid,
            grant_revision=self.command.expected_grant_revision,
            expires_at=future(4),
        )
        baseline_reader = self.service._reader
        try:
            for grant in (
                None,
                object(),
                replace(base, actor_uuid=uuid4()),
                replace(base, project_uuid=uuid4()),
                replace(base, agent_session_uuid=uuid4()),
                replace(base, grant_revision=base.grant_revision + 1),
                replace(base, grant_revision=True),
                replace(base, expires_at=future(-1)),
                replace(base, expires_at=future(180)),
                replace(base, expires_at=datetime.now(UTC).replace(tzinfo=None)),
            ):
                with self.subTest(grant_type=repr(grant)[:150]):
                    self.service._reader = ControlledGrantReader(grant)
                    response = await self.decide()
                    self.assertEqual(response.status_code, 403, response.text)
                    self.assertNotIn("allowed", response.json())
        finally:
            self.service._reader = baseline_reader

    async def test_attested_files_caller_scope_must_match_before_resource_lookup(self) -> None:
        class ControlledAttestor:
            def __init__(self, result: object) -> None:
                self.result = result

            async def verify(self, request: Request, command: object) -> object:
                del request, command
                return self.result

        valid = VerifiedDecisionCaller(
            actor_uuid=self.row.created_by_principal_id,
            project_uuid=self.command.project_uuid,
            agent_session_uuid=self.command.agent_session_uuid,
            consumer="hand",
            authority="rauthy",
            verified_peer_audience="briareus:access",
            proof_expires_at=future(12),
            attested_effect_key=self.command.effect_key(),
        )
        baseline_attestor = self.service._attestor
        try:
            for caller in (
                object(),
                replace(valid, consumer="gateway"),
                replace(valid, authority="unknown"),
                replace(valid, verified_peer_audience="untrusted-other-peer"),
                replace(valid, actor_uuid=uuid4(), project_uuid=uuid4()),
                replace(valid, agent_session_uuid=uuid4()),
                replace(valid, attested_effect_key="unrelated-effect"),
                replace(valid, proof_expires_at=future(-1)),
                replace(valid, proof_expires_at=datetime.now(UTC).replace(tzinfo=None)),
            ):
                with self.subTest(caller_type=repr(caller)[:150]):
                    self.resource.calls = 0
                    self.service._attestor = ControlledAttestor(caller)
                    response = await self.decide()
                    self.assertEqual(response.status_code, 401, response.text)
                    self.assertEqual(self.resource.calls, 0)
                    self.assertNotIn("allowed", response.json())
        finally:
            self.service._attestor = baseline_attestor

    async def test_strict_read_contract_and_no_previous_receipt_as_input(self) -> None:
        for changes in (
            {"max_bytes": True},
            {"max_bytes": 262145},
            {"max_bytes": 0},
            {"expected_resource_revision": "7"},
            {"phase": "release"},
            {"operation_uuid": "00000000-0000-1000-8000-000000000001"},
            {"previous_receipt": {"allowed": True}},
            {"path": "/etc/passwd"},
            {"resource": {"kind": "workspace_path", "id": "owner:/old-path"}},
            {"project_uuid": str(uuid4())},
            {"hand": "web"},
        ):
            response = await self.decide(changes=changes)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertFalse(self.db.queries)
        self.assertEqual(self.resource.calls, 0)


if __name__ == "__main__":
    unittest.main()

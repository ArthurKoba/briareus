"""Lost-response reconciliation through real owner code and synthetic SQL/trust.

The command executor and Cedar library are real; persistence/peer identity
are deliberately in-memory fixtures. This does not assert live DB atomicity.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from control_panel_api._access_management_client import VerifiedAccessTransport
from control_panel_api._access_management_write import (
    PrivateAccessManagementBundle,
    PrivateAccessManagementWriter,
    VerifiedAccessWriteDelegation,
)
from control_panel_api._oidc_approvals import OwnerManagementUnavailable
from control_panel_api._oidc_membership import platform_membership_router
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncBaseTransport, AsyncClient, MockTransport, ReadError, Response
from httpx import Request as HttpRequest
from pydantic import SecretStr
from sqlalchemy.sql import Select
from test_panel_session_detail import (
    ActorFixture,
    BrowserSessionFixture,
    PlatformFixture,
    PrivatePeerFixture,
    ReadOnlySQLFixture,
    future,
    session_row,
)

from authorization._access_cedar import permits_current_project_grant
from authorization._approval_read_api import ApprovalListReader, private_approval_list_router
from authorization._idempotency import IdempotentCommandExecutor
from authorization._platform_persistence import IdempotencyRow, OutboxRow, SecurityAuditRow
from authorization._rauthy_access_command_api import rauthy_access_command_router
from authorization._rauthy_access_commands import (
    AccessRauthyCommandService,
    RevokeSessionCommand,
    VerifiedAccessCommandActor,
)
from authorization._resource_scope import EffectResource

_ORIGIN = "https://briareus.koba-nexus.ru"
_BEARER = "source-only-write-proof-" + "T" * 48


class CommandSQLFixture(ReadOnlySQLFixture):
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        super().__init__(rows)
        self.ledger: list[IdempotencyRow] = []
        self.effects: list[SecurityAuditRow | OutboxRow] = []
        self.children: dict[UUID, list[UUID]] = {}

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[CommandSQLFixture]:
        before_ledger, before_effects = self.ledger[:], self.effects[:]
        previous = [row.__dict__.copy() for row in self.rows]
        try:
            yield self
        except Exception:
            self.ledger, self.effects = before_ledger, before_effects
            for row, value in zip(self.rows, previous, strict=True):
                row.__dict__.clear()
                row.__dict__.update(value)
            raise

    async def scalar(self, query: Select) -> object | None:
        params = query.compile().params
        sql = str(query)
        assert "FOR UPDATE" in sql
        if "access.commands" in sql:
            return next(
                (
                    row
                    for row in self.ledger
                    if all(
                        getattr(row, key) == params[key + "_1"]
                        for key in ("actor_scope", "project_scope", "operation", "key")
                    )
                ),
                None,
            )
        assert "sessions.agent_sessions" in sql
        return next(
            (row for row in self.rows if row.session_uuid == params["session_uuid_1"]), None
        )

    async def scalars(self, query: Select) -> list:
        if "sessions.approvals" in str(query):
            params = query.compile().params
            assert "FOR UPDATE" in str(query)
            return self.children.get(params["session_uuid_1"], [])
        return await super().scalars(query)

    def add(self, row: IdempotencyRow | SecurityAuditRow | OutboxRow) -> None:
        if isinstance(row, IdempotencyRow):
            self.ledger.append(row)
        else:
            self.effects.append(row)

    async def flush(self) -> None:
        return None


class DroppedRevokeResponse(AsyncBaseTransport):
    def __init__(self, app: FastAPI) -> None:
        self.upstream = ASGITransport(app=app)
        self.drop_once = True

    async def handle_async_request(self, request: HttpRequest) -> Response:
        response = await self.upstream.handle_async_request(request)
        if (
            request.url.path.endswith("/sessions/revoke")
            and self.drop_once
            and response.status_code == 200
        ):
            self.drop_once = False
            await response.aread()
            await response.aclose()
            raise ReadError("simulated lost reply AFTER owner command returned", request=request)
        return response

    async def aclose(self) -> None:
        await self.upstream.aclose()


class CommandPeerFixture(PrivatePeerFixture):
    proof: VerifiedAccessWriteDelegation | None = None
    may_mutate = True

    async def signed_command_delegation(self, **command: object) -> VerifiedAccessWriteDelegation:
        self.proof = VerifiedAccessWriteDelegation(
            issuer="rauthy",
            actor_uuid=command["actor_uuid"],
            project_uuid=command["project_uuid"],
            operation_uuid=command["operation_uuid"],
            action=command["action"],
            body_sha256=command["body_sha256"],
            bearer=SecretStr(_BEARER),
            audience="briareus:access",
            expires_at=future(15),
        )
        return self.proof

    async def verify(
        self, request: Request, command: RevokeSessionCommand, action: str
    ) -> VerifiedAccessCommandActor:
        proof = self.proof
        assert proof is not None and proof.actor_uuid == self.actor
        assert request.headers["authorization"] == "Bearer " + _BEARER
        assert proof.body_sha256 == hashlib.sha256(await request.body()).hexdigest()
        assert proof.project_uuid == command.project_uuid
        assert proof.operation_uuid == command.operation_uuid and proof.action == action
        return VerifiedAccessCommandActor(
            self.actor,
            command.project_uuid,
            command.operation_uuid,
            action,
            True,
            self.may_mutate,
            "rauthy",
            "briareus:access",
            future(10),
        )


class SessionReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_revoke_reply_detail_read_and_idempotent_retry(self) -> None:
        actor, project = uuid4(), uuid4()
        base, child = session_row(actor, project), session_row(actor, project, revision=3)
        child.is_elevated = True
        child.elevation_policy = "fixed"
        resource = EffectResource(kind="workspace_path", id="owner:/readme")
        child.grants = {
            "operations": ["files.read"],
            "resources": [
                {
                    "hand": "files",
                    "tool": "read_file",
                    "action": "files.read",
                    "resource": {"kind": resource.kind, "id": resource.id},
                }
            ],
        }
        db = CommandSQLFixture([base, child])
        db.children[base.session_uuid] = [child.session_uuid]
        private_app = FastAPI()
        async with AsyncClient(
            transport=DroppedRevokeResponse(private_app),
            base_url="http://briareus-authorization:8000",
        ) as upstream:
            peer = CommandPeerFixture(upstream, actor, True)
            commands = AccessRauthyCommandService(
                database=db,
                idempotency=IdempotentCommandExecutor(db, Fernet.generate_key().decode()),
                attestor=peer,
            )
            reader = ApprovalListReader(database=db, attestor=ActorFixture(actor, True))
            private_app.include_router(
                rauthy_access_command_router(resolve_service=lambda: commands)
            )
            private_app.include_router(private_approval_list_router(resolve_reader=lambda: reader))
            public = FastAPI()
            public.include_router(
                platform_membership_router(
                    BrowserSessionFixture(),
                    source=PlatformFixture(actor, project, True),
                    approval_source=PrivateAccessManagementBundle(trusted_peer=peer),
                )
            )
            async with AsyncClient(transport=ASGITransport(app=public), base_url=_ORIGIN) as client:
                from test_panel_session_detail import _COOKIE

                client.cookies.set(
                    "__Host-briareus_oidc_session",
                    _COOKIE,
                    domain="briareus.koba-nexus.ru",
                    path="/",
                )
                self.assertTrue(
                    permits_current_project_grant(
                        row=child,
                        actor_uuid=actor,
                        project_uuid=project,
                        operation="files.read",
                        expected_version=3,
                        hand="files",
                        tool="read_file",
                        resource=resource,
                    )
                )
                operation = str(uuid4())
                headers = {
                    "Origin": _ORIGIN,
                    "Operation-UUID": operation,
                    "Idempotency-Key": operation,
                }
                payload = {"project_uuid": str(project), "expected_grant_revision": 7}
                path = f"/api/v1/agent-sessions/{base.session_uuid}"
                lost = await client.post(path + "/revoke", headers=headers, json=payload)
                self.assertEqual(lost.status_code, 503, lost.text)
                self.assertEqual(base.status, "revoked")
                self.assertEqual((base.version, child.version), (8, 4))
                self.assertEqual(child.status, "revoked")
                self.assertFalse(
                    permits_current_project_grant(
                        row=child,
                        actor_uuid=actor,
                        project_uuid=project,
                        operation="files.read",
                        expected_version=3,
                        hand="files",
                        tool="read_file",
                        resource=resource,
                    )
                )
                current = await client.get(path, params={"project_uuid": str(project)})
                self.assertEqual(current.status_code, 200, current.text)
                self.assertEqual(current.json()["revision"], 8)
                self.assertEqual(current.json()["status"], "revoked")
                self.assertEqual(current.json()["allowed_actions"], [])
                replay = await client.post(path + "/revoke", headers=headers, json=payload)
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertEqual(replay.json()["revision"], 8)
                self.assertEqual(len(db.effects), 4)  # Parent+child audit and outbox, once each.
                self.assertEqual(len(db.ledger), 1)
                changed = await client.post(
                    path + "/revoke",
                    headers=headers,
                    json={**payload, "expected_grant_revision": 8},
                )
                self.assertEqual(changed.status_code, 409, changed.text)
                peer.may_mutate = False
                revoked_authority = await client.post(
                    path + "/revoke", headers=headers, json=payload
                )
                self.assertEqual(revoked_authority.status_code, 403, revoked_authority.text)
                self.assertEqual(len(db.effects), 4)


class AccessWriteReceiptBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.actor, self.requester, self.project = uuid4(), uuid4(), uuid4()
        self.session, self.approval, self.child = uuid4(), uuid4(), uuid4()

    def receipt(self, **changes: object) -> bytes:
        payload = {
            "id": str(self.approval),
            "project_uuid": str(self.project),
            "agent_session_uuid": str(self.session),
            "requested_by_user_uuid": str(self.requester),
            "status": "pending",
            "version": 1,
            "requested_operations": ["files.read"],
            "requested_resources": [],
            "requested_expires_at": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
            "resolved_by_user_uuid": None,
            "issued_session_uuid": None,
            **changes,
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    def test_approval_lifecycle_and_action_scopes_are_not_inferred_from_owner_json(self) -> None:
        for actor, state, payload in (
            (self.requester, "pending", self.receipt()),
            (
                self.actor,
                "approved",
                self.receipt(
                    status="approved",
                    version=2,
                    resolved_by_user_uuid=str(self.actor),
                    issued_session_uuid=str(self.child),
                ),
            ),
            (
                self.actor,
                "rejected",
                self.receipt(
                    status="rejected",
                    version=2,
                    resolved_by_user_uuid=str(self.actor),
                ),
            ),
        ):
            valid = PrivateAccessManagementWriter._approval(
                payload,
                project=self.project,
                actor=actor,
                state=state,
                expected_approval=self.approval,
            )
            self.assertEqual(valid.status, state)

        for actor, state, changed in (
            (self.requester, "pending", {"resolved_by_user_uuid": str(self.actor)}),
            (self.requester, "pending", {"issued_session_uuid": str(self.child)}),
            (self.requester, "pending", {"version": 2}),
            (
                self.actor,
                "approved",
                {"status": "approved", "version": 2, "resolved_by_user_uuid": str(self.actor)},
            ),
            (
                self.actor,
                "approved",
                {"status": "approved", "version": 2, "issued_session_uuid": str(self.child)},
            ),
            (
                self.actor,
                "approved",
                {
                    "status": "approved",
                    "version": 2,
                    "resolved_by_user_uuid": str(self.actor),
                    "issued_session_uuid": str(self.session),
                },
            ),
            (
                self.actor,
                "rejected",
                {
                    "status": "rejected",
                    "version": 2,
                    "resolved_by_user_uuid": str(self.actor),
                    "issued_session_uuid": str(self.child),
                },
            ),
            (self.actor, "rejected", {"status": "rejected", "version": 2}),
            (self.requester, "pending", {"requested_operations": ["files.read", "files.read"]}),
            (self.requester, "pending", {"requested_operations": ["unregistered.effect"]}),
            (self.requester, "pending", {"requested_resources": [{"action": "files.write"}]}),
        ):
            with (
                self.subTest(state=state, changed=changed),
                self.assertRaises(OwnerManagementUnavailable),
            ):
                PrivateAccessManagementWriter._approval(
                    self.receipt(**changed),
                    project=self.project,
                    actor=actor,
                    state=state,
                    expected_approval=self.approval,
                )

    async def test_ambiguous_or_revised_owner_receipts_never_confirm_commands(self) -> None:
        class SuppliedReply(PrivateAccessManagementWriter):
            def __init__(self, raw: bytes) -> None:
                super().__init__(trusted_peer=object())
                self.raw = raw

            async def _write(self, **_kwargs: object) -> bytes:
                return self.raw

        pending = self.receipt()
        duplicate = pending.replace(
            b'"status":"pending"', b'"status":"pending","status":"approved"'
        )
        self.assertNotEqual(duplicate, pending)
        with self.assertRaises(OwnerManagementUnavailable):
            PrivateAccessManagementWriter._approval(
                duplicate,
                project=self.project,
                actor=self.requester,
                state="pending",
                expected_approval=self.approval,
            )
        issued = self.receipt(
            status="approved",
            version=2,
            resolved_by_user_uuid=str(self.actor),
            issued_session_uuid=str(self.child),
        )
        with self.assertRaises(OwnerManagementUnavailable):
            await SuppliedReply(issued).resolve_elevation(
                actor=self.actor,
                project=self.project,
                approval=self.approval,
                expected_version=2,
                approve=True,
                allowed_operations=None,
                operation=uuid4(),
            )
        with self.assertRaises(OwnerManagementUnavailable):
            await SuppliedReply(
                self.receipt(requested_operations=["files.read", "web.access"])
            ).request_elevation(
                actor=self.requester,
                project=self.project,
                session=self.session,
                operations=("files.read",),
                resources=(),
                seconds=90,
                expected_grant_revision=2,
                operation=self.approval,
            )
        scoped_resource = {
            "hand": "files",
            "tool": "read_file",
            "action": "files.read",
            "resource": {
                "kind": "workspace_path",
                "id": f"project-path-v1:{self.project}:" + "a" * 64,
            },
        }
        original = self.receipt(requested_resources=[scoped_resource])
        with self.assertRaises(OwnerManagementUnavailable):
            await SuppliedReply(original).request_elevation(
                actor=self.requester,
                project=self.project,
                session=self.session,
                operations=("files.read",),
                resources=(),
                seconds=90,
                expected_grant_revision=2,
                operation=self.approval,
            )
        matched = await SuppliedReply(original).request_elevation(
            actor=self.requester,
            project=self.project,
            session=self.session,
            operations=("files.read",),
            resources=(scoped_resource,),
            seconds=90,
            expected_grant_revision=2,
            operation=self.approval,
        )
        self.assertEqual(matched.approval_uuid, self.approval)
        opened_raw = json.dumps(
            {
                "session_uuid": str(self.session),
                "project_uuid": str(self.project),
                "revision": 1,
                "status": "active",
                "is_elevated": False,
                "elevation_policy": "requestable",
                "hard_expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                "operations": ["files.read", "project.metadata.read"],
                "resources": [],
            },
            separators=(",", ":"),
        ).encode()
        with self.assertRaises(OwnerManagementUnavailable):
            await SuppliedReply(
                opened_raw.replace(b'"revision":1', b'"revision":1,"revision":999')
            ).open_normal(
                actor=self.actor,
                project=self.project,
                elevation_policy="requestable",
                label=None,
                operation=uuid4(),
            )
        elevated_rev = 9
        revocation = json.dumps(
            {
                "session_uuid": str(self.session),
                "project_uuid": str(self.project),
                "status": "revoked",
                "revision": elevated_rev + 2,
            }
        ).encode()
        with self.assertRaises(OwnerManagementUnavailable):
            await SuppliedReply(revocation).revoke_session(
                actor=self.actor,
                project=self.project,
                session=self.session,
                expected_revision=elevated_rev,
                operation=uuid4(),
            )
        valid_revocation = json.dumps(
            {
                "session_uuid": str(self.session),
                "project_uuid": str(self.project),
                "status": "revoked",
                "revision": elevated_rev + 1,
            }
        ).encode()
        self.assertEqual(
            (
                await SuppliedReply(valid_revocation).revoke_session(
                    actor=self.actor,
                    project=self.project,
                    session=self.session,
                    expected_revision=elevated_rev,
                    operation=uuid4(),
                )
            ).revision,
            elevated_rev + 1,
        )

    async def test_owner_attestation_timeout_is_unavailable_not_an_implicit_retry(self) -> None:
        class SlowPeer:
            calls = 0

            async def current_transport(self) -> None:
                self.calls += 1
                await asyncio.sleep(0.15)

        peer = SlowPeer()
        writer = PrivateAccessManagementWriter(trusted_peer=peer)
        with (
            patch("control_panel_api._access_management_write._OWNER_DEADLINE_SECONDS", 0.025),
            self.assertRaises(OwnerManagementUnavailable),
        ):
            await writer.open_normal(
                actor=self.actor,
                project=self.project,
                elevation_policy="requestable",
                label="source-test",
                operation=uuid4(),
            )
        self.assertEqual(peer.calls, 1)

    async def test_owner_reply_timeout_returns_uncertain_not_successful_write(self) -> None:
        actor, project = self.actor, self.project
        nonce = uuid4()
        called = 0

        async def slow_handler(request: HttpRequest) -> Response:
            nonlocal called
            called += 1
            self.assertEqual(request.headers["operation-uuid"], str(nonce))
            self.assertEqual(request.headers["idempotency-key"], str(nonce))
            await asyncio.sleep(0.15)
            return Response(201, json={})

        class PrivatePeer:
            def __init__(self, client: AsyncClient) -> None:
                self.client = client

            async def current_transport(self) -> VerifiedAccessTransport:
                return VerifiedAccessTransport(self.client, "mtls", "briareus:access", future(20))

            async def signed_command_delegation(
                self, **selectors: object
            ) -> VerifiedAccessWriteDelegation:
                return VerifiedAccessWriteDelegation(
                    issuer="rauthy",
                    actor_uuid=actor,
                    project_uuid=project,
                    operation_uuid=nonce,
                    action="session.open",
                    body_sha256=selectors["body_sha256"],
                    bearer=SecretStr("source-only-command-bearer-" + "Z" * 48),
                    audience="briareus:access",
                    expires_at=future(15),
                )

        async with AsyncClient(transport=MockTransport(slow_handler)) as client:
            writer = PrivateAccessManagementWriter(trusted_peer=PrivatePeer(client))
            with (
                patch("control_panel_api._access_management_write._OWNER_DEADLINE_SECONDS", 0.025),
                self.assertRaises(OwnerManagementUnavailable),
            ):
                await writer.open_normal(
                    actor=actor,
                    project=project,
                    elevation_policy="requestable",
                    label=None,
                    operation=nonce,
                )
        # Owner commit status is unknown after a dropped/delayed HTTP response;
        # the BFF never manufactures success or retries with another UUID.
        self.assertEqual(called, 1)


if __name__ == "__main__":
    unittest.main()

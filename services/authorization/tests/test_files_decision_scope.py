"""Runtime-compatible Files selector and signed decision source integration.

JWT signatures and Cedar evaluation use their actual libraries. Rauthy keys,
private peers, Platform membership and SQL are isolated synthetic fixtures;
no test token, file operation, live User or privileged service is published.
"""

from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.sql import Select
from test_panel_session_detail import ReadOnlySQLFixture, future, session_row

from authorization._access_cedar import permits_current_project_grant
from authorization._decision_api import (
    AuthorizationDecisionReader,
    AuthorizationDecisionService,
    DecisionCommand,
    authorization_decision_router,
)
from authorization._rauthy_access_commands import RequestElevationCommand
from authorization._rauthy_decision_attestor import RauthyDecisionAttestor, VerifiedDecisionPeer
from authorization._rauthy_jwks import RauthyJwksVerifier
from authorization._rauthy_membership_contract import VerifiedProjectMembership
from authorization._resource_scope import (
    EffectResource,
    VerifiedResourceOwnerProof,
    matches_current_owner,
    normalized_resource_grants,
)


class FilesSelectorContractTests(unittest.TestCase):
    """Versioned Runtime naming, not a live Files grant or owner signature."""

    def setUp(self) -> None:
        self.project = UUID("bdcc31e6-6b45-4fe7-a603-e9f7950b9d2e")
        self.actor = uuid4()
        # Captured by executing Runtime FilesReadSelector read-only for
        # README.md, docs/пример.txt and a 3399-byte canonical relative path.
        self.digests = (
            "91d6cd003c4304591703178f48a2021d5e46a908d5e16dc11f7ad1be0bdd56d1",
            "fcf684e245014ac46c356ac56f65293af93becacf2993443f1c91e63171c5d72",
            "01ec5be506bbc95285eace7bb57902a60ac1e32c86736781a899d134cc2d1527",
        )
        self.row = session_row(self.actor, self.project, revision=3)
        self.row.is_elevated = True
        self.resource = self.resource_for(self.project)
        self.scope = {
            "hand": "files",
            "tool": "read_file",
            "action": "files.read",
            "resource": self.resource.model_dump(),
        }
        self.row.grants = {"operations": ["files.read"], "resources": [self.scope]}

    def resource_for(self, project: UUID, digest_index: int = 0) -> EffectResource:
        return EffectResource(
            kind="workspace_path",
            id=f"project-path-v1:{project}:{self.digests[digest_index]}",
        )

    def decision(self, resource: EffectResource, **changed: object) -> DecisionCommand:
        return DecisionCommand.model_validate(
            {
                "project_uuid": self.project,
                "agent_session_uuid": self.row.session_uuid,
                "action": "files.read",
                "expected_grant_revision": 3,
                "hand": "files",
                "tool": "read_file",
                "resource": resource.model_dump(),
                **changed,
            }
        )

    def test_runtime_vectors_and_strict_decision_revision(self) -> None:
        for index in range(len(self.digests)):
            resource = self.resource_for(self.project, index)
            decision = self.decision(resource)
            self.assertEqual(len(resource.id), 117)
            self.assertTrue(resource.id.isascii())
            self.assertEqual(decision.resource, resource)
        for revision in (True, "3", 3.0, 0, 2**63):
            with self.assertRaises(ValidationError):
                self.decision(self.resource, expected_grant_revision=revision)

    def test_cross_project_and_malformed_namespace_rejected_before_decision(self) -> None:
        other = self.resource_for(uuid4())
        invalid_ids = (
            other.id,
            self.resource.id.replace("project-path-v1:", "project-path-v2:"),
            self.resource.id[:-1],
            self.resource.id + "a",
            self.resource.id.replace(str(self.project), str(self.project).upper()),
            self.resource.id.replace(self.digests[0], self.digests[0].upper()),
            self.resource.id.replace(str(self.project), "00000000-0000-1000-8000-000000000001"),
        )
        for identifier in invalid_ids:
            with self.assertRaises(ValidationError):
                self.decision(EffectResource(kind="workspace_path", id=identifier))
        with self.assertRaises(ValidationError):
            self.decision(
                EffectResource(kind="repository", id=self.resource.id),
                hand="svc",
                action="integrations.use",
            )

    def test_approval_request_and_stored_scope_use_exact_project(self) -> None:
        command = {
            "project_uuid": str(self.project),
            "operation_uuid": str(uuid4()),
            "agent_session_uuid": str(self.row.session_uuid),
            "expected_grant_revision": 3,
            "operations": ["files.read"],
            "resources": [self.scope],
            "seconds": 120,
        }
        self.assertEqual(RequestElevationCommand.model_validate(command).project_uuid, self.project)
        with self.assertRaises(ValidationError):
            RequestElevationCommand.model_validate({**command, "project_uuid": str(uuid4())})
        with self.assertRaises(ValueError):
            normalized_resource_grants(
                [self.scope], allowed_actions={"files.read"}, project_uuid=uuid4()
            )

    def test_selector_does_not_replace_matching_current_owner_proof(self) -> None:
        proof = VerifiedResourceOwnerProof(
            project_uuid=self.project,
            hand="files",
            tool="read_file",
            action="files.read",
            resource=self.resource,
            revision=1,
            expires_at=future(15),
        )
        self.assertTrue(matches_current_owner(proof, project_uuid=self.project, scope=self.scope))
        self.assertFalse(matches_current_owner(None, project_uuid=self.project, scope=self.scope))
        self.assertFalse(matches_current_owner(proof, project_uuid=uuid4(), scope=self.scope))
        forged_projection = VerifiedResourceOwnerProof(
            project_uuid=self.project,
            hand="files",
            tool="read_file",
            action="files.read",
            resource=self.resource_for(uuid4()),
            revision=1,
            expires_at=future(15),
        )
        other_scope = {**self.scope, "resource": forged_projection.resource.model_dump()}
        self.assertFalse(
            matches_current_owner(forged_projection, project_uuid=self.project, scope=other_scope)
        )

    def test_current_grant_cedar_never_allows_other_path_or_embedded_project(self) -> None:
        def permitted(resource: EffectResource) -> bool:
            return permits_current_project_grant(
                row=self.row,
                actor_uuid=self.actor,
                project_uuid=self.project,
                operation="files.read",
                expected_version=3,
                hand="files",
                tool="read_file",
                resource=resource,
            )

        self.assertTrue(permitted(self.resource))
        self.assertFalse(permitted(self.resource_for(self.project, 1)))
        foreign = self.resource_for(uuid4())
        self.row.grants["resources"] = [{**self.scope, "resource": foreign.model_dump()}]
        # Even a malformed row containing the same foreign selector denies.
        self.assertFalse(permitted(foreign))
        self.row.grants["resources"] = [self.scope]
        self.row.status = "revoked"
        self.assertFalse(permitted(self.resource))


class SingleSessionSQL(ReadOnlySQLFixture):
    async def scalar(self, query: Select) -> object | None:
        params = query.compile().params
        self.queries.append(params)
        return next(
            (
                row
                for row in self.rows
                if row.project_id == params["project_id_1"]
                and row.session_uuid == params["session_uuid_1"]
            ),
            None,
        )


class CurrentPrivateSources:
    def __init__(self, command: DecisionCommand, actor: UUID, issuer: str) -> None:
        self.peer = VerifiedDecisionPeer(
            "hand", "files", "briareus:access", future(15), command.effect_key()
        )
        self.member = VerifiedProjectMembership(
            issuer, "test-subject-from-ephemeral-issuer", actor, command.project_uuid, future(15)
        )

    async def verify_peer(self, request: Request) -> VerifiedDecisionPeer:
        assert request.url.path == "/internal/v1/authorization/decide"
        return self.peer

    async def current_member(
        self, *, rauthy_issuer: str, rauthy_subject: str, project_uuid: UUID
    ) -> VerifiedProjectMembership:
        assert rauthy_issuer and rauthy_subject and project_uuid
        return self.member


class SignedFilesDecisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.issuer = "https://source-fixture.invalid/auth/v1/"
        self.audience = "https://source-fixture.invalid/hands/files/mcp"
        self.client_id = "source-fixture-control-panel"
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        public_jwk.update(kid="ephemeral-files-test", alg="RS256", use="sig")
        verifier = RauthyJwksVerifier(
            issuer=self.issuer,
            resource_audience=self.audience,
            oauth_client_id=self.client_id,
            trusted_jwks={"keys": [public_jwk]},
        )
        self.actor, self.project = uuid4(), uuid4()
        self.row = session_row(self.actor, self.project, revision=3)
        resource = EffectResource(
            kind="workspace_path", id=f"project-path-v1:{self.project}:" + "a" * 64
        )
        self.command = DecisionCommand(
            project_uuid=self.project,
            agent_session_uuid=self.row.session_uuid,
            action="files.read",
            expected_grant_revision=3,
            hand="files",
            tool="read_file",
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
        self.sources = CurrentPrivateSources(self.command, self.actor, self.issuer)
        service = AuthorizationDecisionService(
            attestor=RauthyDecisionAttestor(
                bearer_verifier=verifier,
                peer_resolver=self.sources,
                membership_resolver=self.sources,
            ),
            reader=AuthorizationDecisionReader(self.db),
        )
        self.app = FastAPI()
        self.app.include_router(authorization_decision_router(service))

    def token(self, **changes: object) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "sub": self.sources.member.rauthy_subject,
            "aud": [self.client_id, self.audience],
            "typ": "Bearer",
            "azp": self.client_id,
            "jti": "ephemeral-resource-fixture",
            "nbf": now,
            "iat": now,
            "exp": now + 120,
            **changes,
        }
        return jwt.encode(
            claims, self.key, algorithm="RS256", headers={"kid": "ephemeral-files-test"}
        )

    async def request_decision(self, token: str) -> int:
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://local-access-owner"
        ) as client:
            response = await client.post(
                "/internal/v1/authorization/decide",
                json=self.command.model_dump(mode="json"),
                headers={"Authorization": "Bearer " + token},
            )
            if response.status_code == 200:
                self.assertEqual(response.json(), {"allowed": True})
            return response.status_code

    async def test_signed_resource_audience_exact_peer_owner_and_revoke(self) -> None:
        bearer = self.token()
        self.assertEqual(await self.request_decision(bearer), 200)
        self.assertEqual(len(self.db.queries), 1)
        self.row.status = "revoked"
        self.row.version = 4
        self.assertEqual(await self.request_decision(bearer), 403)

    async def test_client_audience_and_expired_or_wrong_issuer_tokens_denied_before_sql(
        self,
    ) -> None:
        for token in (
            self.token(aud=self.client_id),
            self.token(iss="https://foreign-issuer.invalid/"),
            self.token(exp=int(time.time()) - 1),
        ):
            self.assertEqual(await self.request_decision(token), 401)
        self.assertFalse(self.db.queries)

    async def test_signed_non_access_purposes_and_bound_tokens_deny_before_sql(self) -> None:
        for changed in (
            {"typ": "Id"},
            {"typ": "Refresh"},
            {"typ": "DPoP"},
            {"typ": None},
            {"cnf": {"jkt": "required-proof-not-provided"}},
            {"azp": None},
            {"azp": "bad client"},
            {"jti": ""},
            {"iat": str(int(time.time()))},
            {"nbf": False},
            {"aud": [self.audience, self.audience]},
        ):
            self.assertEqual(await self.request_decision(self.token(**changed)), 401, changed)
        self.assertFalse(self.db.queries)

    async def test_resource_audience_is_not_a_single_browser_client_allowlist(self) -> None:
        # Rauthy owns client enrollment. Access still evaluates the same signed
        # User's current Project/resource grant for another issuer-approved client.
        self.assertEqual(
            await self.request_decision(
                self.token(
                    azp="source-fixture-mcp-client",
                    aud=["source-fixture-mcp-client", self.audience],
                )
            ),
            200,
        )

    async def test_signed_user_cannot_replace_current_peer_effect_or_membership(self) -> None:
        bearer = self.token()
        initial = self.sources.peer
        self.sources.peer = replace(initial, source_audience="svc")
        self.assertEqual(await self.request_decision(bearer), 403)
        self.sources.peer = replace(initial, attested_effect_key='["files","different_tool"]')
        self.assertEqual(await self.request_decision(bearer), 403)
        self.sources.peer = initial
        self.sources.member = replace(self.sources.member, project_uuid=uuid4())
        self.assertEqual(await self.request_decision(bearer), 403)
        self.assertFalse(self.db.queries)


if __name__ == "__main__":
    unittest.main()

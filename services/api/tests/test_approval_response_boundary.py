"""Control Panel approval contract: invalid owner replies never become UI truth."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from control_panel_api._oidc_approvals import ApprovalSnapshot, approval_management_router
from control_panel_api._oidc_browser import PanelOidcSession
from control_panel_api._oidc_membership import PlatformProjectContext, ResolvedPlatformUser
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

_ORIGIN = "https://briareus.koba-nexus.ru"


class ApprovalOwnerFixture:
    def __init__(self, items: tuple[ApprovalSnapshot, ...]) -> None:
        self.items = items
        self.calls = 0

    async def list_approvals(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[ApprovalSnapshot, ...]:
        assert actor.version == project.version == 4 and limit == 50
        self.calls += 1
        return self.items

    async def request_elevation(self, **command: object) -> ApprovalSnapshot:
        assert command["actor"] and command["project"]
        self.calls += 1
        return self.items[0]

    async def resolve_elevation(self, **command: object) -> ApprovalSnapshot:
        assert command["actor"] and command["project"]
        self.calls += 1
        return self.items[0]


class ApprovalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.actor = uuid4()
        self.project = uuid4()
        self.request = ApprovalSnapshot(
            approval_uuid=uuid4(),
            project_uuid=self.project,
            agent_session_uuid=uuid4(),
            requested_by_user_uuid=self.actor,
            status="pending",
            version=1,
            requested_operations=("files.read",),
            requested_resources=(),
            requested_expires_at=datetime.now(UTC) + timedelta(minutes=2),
        )

    def app(self, owner: ApprovalOwnerFixture, *, approver: bool = False) -> FastAPI:
        async def verified_context(
            request: Request,
            project_uuid: UUID | None = None,
        ) -> tuple[PanelOidcSession, ResolvedPlatformUser]:
            assert request.url.path.startswith("/api/v1/")
            assert project_uuid == self.project
            issuer = _ORIGIN + "/auth/v1/"
            expires = datetime.now(UTC) + timedelta(seconds=15)
            session = PanelOidcSession(issuer, "source-only-sub", "panel", expires)
            # Already-verified context is a fixture, NOT an IdP login result.
            permissions = ("approve_agent_session",) if approver else ("use_resources",)
            proof = ResolvedPlatformUser(
                issuer,
                "source-only-sub",
                self.actor,
                True,
                "user",
                expires,
                (),
                (PlatformProjectContext(self.project, 1, "user", self.actor, permissions),),
            )
            return session, proof

        result = FastAPI()
        result.include_router(
            approval_management_router(current_context=verified_context, owner=owner)
        )
        return result

    async def test_regular_actor_cannot_observe_an_overbroad_or_duplicate_owner_list(self) -> None:
        for items in (
            (replace(self.request, requested_by_user_uuid=uuid4()),),
            (self.request, self.request),
        ):
            owner = ApprovalOwnerFixture(items)
            async with AsyncClient(
                transport=ASGITransport(app=self.app(owner)), base_url=_ORIGIN
            ) as client:
                result = await client.get(
                    "/api/v1/approvals", params={"project_uuid": str(self.project)}
                )
                self.assertEqual(result.status_code, 503)
                self.assertNotIn(str(self.request.approval_uuid), result.text)
                self.assertEqual(result.headers["cache-control"], "no-store")

    async def test_inconsistent_approval_lifecycle_is_not_exposed(self) -> None:
        invalid = (
            replace(self.request, resolved_by_user_uuid=uuid4()),
            replace(self.request, status="approved", resolved_by_user_uuid=uuid4()),
            replace(
                self.request,
                status="rejected",
                resolved_by_user_uuid=uuid4(),
                issued_session_uuid=uuid4(),
            ),
            replace(
                self.request,
                status="approved",
                resolved_by_user_uuid=self.actor,
                issued_session_uuid=uuid4(),
            ),
            replace(self.request, requested_operations=("files.read", "files.read")),
            replace(self.request, requested_resources=({"unexpected": "private"},)),
        )
        for item in invalid:
            owner = ApprovalOwnerFixture((item,))
            async with AsyncClient(
                transport=ASGITransport(app=self.app(owner)), base_url=_ORIGIN
            ) as client:
                result = await client.get(
                    "/api/v1/approvals", params={"project_uuid": str(self.project)}
                )
                self.assertEqual(result.status_code, 503, result.text)
                self.assertNotIn(str(item.approval_uuid), result.text)

    async def test_valid_pending_resolved_and_self_action_hints(self) -> None:
        for state in ("pending", "approved", "rejected"):
            item = (
                self.request
                if state == "pending"
                else replace(
                    self.request,
                    status=state,
                    version=2,
                    resolved_by_user_uuid=uuid4(),
                    issued_session_uuid=uuid4() if state == "approved" else None,
                )
            )
            async with AsyncClient(
                transport=ASGITransport(app=self.app(ApprovalOwnerFixture((item,)))),
                base_url=_ORIGIN,
            ) as client:
                result = await client.get(
                    "/api/v1/approvals", params={"project_uuid": str(self.project)}
                )
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["items"][0]["status"], state)
                self.assertEqual(result.json()["items"][0]["allowed_actions"], [])

    async def test_approval_mutation_requires_exact_boolean_and_integer_revision(self) -> None:
        owner = ApprovalOwnerFixture((self.request,))
        operation = str(uuid4())
        headers = {"Origin": _ORIGIN, "Operation-UUID": operation, "Idempotency-Key": operation}
        async with AsyncClient(
            transport=ASGITransport(app=self.app(owner, approver=True)), base_url=_ORIGIN
        ) as client:
            body = {
                "project_uuid": str(self.project),
                "approve": False,
                "expected_approval_version": 1,
            }
            for delta in (
                {"approve": "true"},
                {"approve": 1},
                {"expected_approval_version": True},
                {"expected_approval_version": 1.0},
                {"expected_approval_version": "1"},
            ):
                result = await client.post(
                    f"/api/v1/approvals/{self.request.approval_uuid}/resolve",
                    json={**body, **delta},
                    headers=headers,
                )
                self.assertEqual(result.status_code, 422, result.text)
            self.assertEqual(owner.calls, 0)

    async def test_pending_receipt_matches_original_operation_and_exact_resources(self) -> None:
        first = {
            "hand": "files",
            "tool": "read_file",
            "action": "files.read",
            "resource": {"kind": "workspace_path", "id": "owner:/first"},
        }
        second = {
            **first,
            "resource": {"kind": "workspace_path", "id": "owner:/second"},
        }
        other = {
            **first,
            "resource": {"kind": "workspace_path", "id": "owner:/other"},
        }
        operation = self.request.approval_uuid
        # Order may be normalized by the owner, but contents cannot change.
        expected = replace(self.request, requested_resources=(second, first))
        for receipt, status in (
            (expected, 202),
            (replace(expected, requested_resources=(first,)), 503),
            (replace(expected, requested_resources=(first, other)), 503),
            (replace(expected, requested_resources=(first, second, other)), 503),
            (replace(expected, requested_resources=(first, first)), 503),
            (replace(expected, approval_uuid=uuid4()), 503),
        ):
            owner = ApprovalOwnerFixture((receipt,))
            async with AsyncClient(
                transport=ASGITransport(app=self.app(owner)), base_url=_ORIGIN
            ) as client:
                response = await client.post(
                    "/api/v1/approvals",
                    headers={
                        "Origin": _ORIGIN,
                        "Operation-UUID": str(operation),
                        "Idempotency-Key": str(operation),
                    },
                    json={
                        "project_uuid": str(self.project),
                        "agent_session_uuid": str(self.request.agent_session_uuid),
                        "operations": ["files.read"],
                        "resources": [first, second],
                        "seconds": 120,
                        "expected_grant_revision": 7,
                    },
                )
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(owner.calls, 1)

    async def test_resolution_checks_current_actor_and_exact_cas_revision(self) -> None:
        valid = replace(
            self.request,
            requested_by_user_uuid=uuid4(),
            status="rejected",
            version=4,
            resolved_by_user_uuid=self.actor,
        )
        for item, status in (
            (valid, 200),
            (replace(valid, version=5), 503),
            (replace(valid, resolved_by_user_uuid=uuid4()), 503),
        ):
            owner = ApprovalOwnerFixture((item,))
            operation = str(uuid4())
            async with AsyncClient(
                transport=ASGITransport(app=self.app(owner, approver=True)), base_url=_ORIGIN
            ) as client:
                result = await client.post(
                    f"/api/v1/approvals/{self.request.approval_uuid}/resolve",
                    json={
                        "project_uuid": str(self.project),
                        "approve": False,
                        "expected_approval_version": 3,
                    },
                    headers={
                        "Origin": _ORIGIN,
                        "Operation-UUID": operation,
                        "Idempotency-Key": operation,
                    },
                )
                self.assertEqual(result.status_code, status, result.text)


if __name__ == "__main__":
    unittest.main()

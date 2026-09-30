from __future__ import annotations

from starlette.testclient import TestClient

from auth_service.api import build_auth_app


class FakeProvider:
    def get_routes(self, mcp_path: str | None = None):
        assert mcp_path == "/mcp"
        return []


def test_auth_app_exposes_health_without_internal_verify_endpoint() -> None:
    app = build_auth_app(FakeProvider())  # type: ignore[arg-type]

    with TestClient(app) as client:
        health = client.get("/health")
        verify = client.post("/internal/verify")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert verify.status_code == 404

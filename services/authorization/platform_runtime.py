"""Independent Access/Cedar service; never depends on the management API/UI.

The private decision endpoint is fail-closed until Deployment/Runtime wires
verified Rauthy+peer and Project membership ports. Health is not permission.
"""

from __future__ import annotations

from fastapi import FastAPI

from authorization._decision_api import AuthorizationDecisionService, authorization_decision_router
from common.owner_runtime import create_owner_app


def create_authorization_app(
    decision_service: AuthorizationDecisionService | None = None,
) -> FastAPI:
    app = create_owner_app("access")
    app.include_router(authorization_decision_router(decision_service))
    return app


app = create_authorization_app()

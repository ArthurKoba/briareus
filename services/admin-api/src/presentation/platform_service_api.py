"""C1-B2 private source transport, deliberately unmounted in every runtime.

It requires a real injected TLS/Unix peer verifier AND independently signed
service assertion + Backend delegation. No header may assert its own service
identity; service JWTs are never returned to the UI or echoed in errors.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request, Response
from pydantic import SecretStr

from authorization._service_identity import AuthorizedOperationReceipt
from authorization._service_transport import (
    PrivateServiceAuthorizationController,
    ServiceAuthorizationHeaders,
    ServiceAuthorizeInput,
    ServiceOperationIntent,
)


def build_unmounted_private_service_router(
    controller: PrivateServiceAuthorizationController,
) -> APIRouter:
    router = APIRouter(tags=["private-project-auth-source"])

    @router.post(
        "/internal/v1/authorize-project-operation",
        response_model=AuthorizedOperationReceipt,
    )
    async def authorize_project_operation(
        request: Request,
        response: Response,
        intent: ServiceOperationIntent,
        service_assertion: str = Header(
            alias="X-Platform-Service-Assertion", min_length=64, max_length=8192
        ),
        delegation: str = Header(
            alias="X-Platform-Actor-Delegation", min_length=64, max_length=8192
        ),
    ) -> AuthorizedOperationReceipt:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        # Never pass source headers or client-declared TLS fields as trusted
        # peer identity; the injected controller's peer verifier MUST examine
        # an independently attested Request transport connection.
        envelope = ServiceAuthorizeInput(
            intent=intent,
            proof=ServiceAuthorizationHeaders(
                service_assertion=SecretStr(service_assertion),
                backend_delegation=SecretStr(delegation),
            ),
        )
        return await controller.authorize_project_operation(
            envelope,
            peer_evidence=request,
        )

    return router

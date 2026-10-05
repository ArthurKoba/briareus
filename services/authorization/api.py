from __future__ import annotations

import hmac
import html

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .provider import LocalOAuthProvider


def _login_page(
    *,
    transaction_id: str,
    client_name: str,
    resource: str,
    error: str = "",
) -> str:
    error_html = (
        f'<p style="color:#b42318">{html.escape(error)}</p>' if error else ""
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sign in</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 10vh auto;
           padding: 24px; }}
    label {{ display:block; margin: 14px 0 6px; }}
    input {{ width:100%; box-sizing:border-box; padding:10px; }}
    button {{ margin-top:18px; padding:10px 16px; }}
    .muted {{ color:#667085; font-size:13px; overflow-wrap:anywhere; }}
  </style>
</head>
<body>
  <h1>MCP Bridge</h1>
  <p>Authorize {html.escape(client_name)}.</p>
  <p class="muted">{html.escape(resource)}</p>
  {error_html}
  <form method="post" action="/authorization/login">
    <input type="hidden" name="transaction" value="{html.escape(transaction_id)}">
    <label for="username">Username</label>
    <input id="username" name="username" autocomplete="username" required autofocus>
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Authorize</button>
  </form>
</body>
</html>"""


def build_authorization_app(provider: LocalOAuthProvider) -> Starlette:
    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def jwks(_request: Request) -> Response:
        return JSONResponse(provider.jwks, headers={"Cache-Control": "public, max-age=300"})

    async def user_by_username_internal(request: Request) -> Response:
        expected = f"Bearer {provider.settings.admin_service_token}"
        authorization = request.headers.get("authorization")
        if authorization is None or not hmac.compare_digest(authorization, expected):
            return Response(status_code=401)
        username = request.path_params["username"]
        user = await provider.repository.get_user_by_username(username)
        if user is None:
            return Response(status_code=404)
        return JSONResponse(
            {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "enabled": user.enabled,
            },
            headers={"Cache-Control": "no-store"},
        )



    async def authenticate_internal(request: Request) -> Response:
        expected = f"Bearer {provider.settings.admin_service_token}"
        authorization = request.headers.get("authorization")
        if authorization is None or not hmac.compare_digest(authorization, expected):
            return Response(status_code=401)
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"detail": "invalid request"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid request"}, status_code=400)
        username = str(payload.get("username") or "")
        password = str(payload.get("password") or "")
        user = await provider.repository.authenticate_user(username, password)
        if user is None:
            return Response(status_code=401)
        return JSONResponse(
            {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "enabled": user.enabled,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def login_get(request: Request) -> Response:
        transaction_id = request.query_params.get("transaction", "")
        context = await provider.login_context(transaction_id)
        if context is None:
            return HTMLResponse("Authorization request expired or invalid.", status_code=400)
        return HTMLResponse(
            _login_page(
                transaction_id=transaction_id,
                client_name=context["client_name"],
                resource=context["resource"],
            ),
            headers={"Cache-Control": "no-store"},
        )

    async def login_post(request: Request) -> Response:
        form = await request.form()
        transaction_id = str(form.get("transaction") or "")
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        context = await provider.login_context(transaction_id)
        if context is None:
            return HTMLResponse("Authorization request expired or invalid.", status_code=400)
        redirect = await provider.complete_login(
            transaction_id=transaction_id,
            username=username,
            password=password,
        )
        if redirect is None:
            return HTMLResponse(
                _login_page(
                    transaction_id=transaction_id,
                    client_name=context["client_name"],
                    resource=context["resource"],
                    error="Invalid username or password.",
                ),
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        return RedirectResponse(redirect, status_code=302, headers={"Cache-Control": "no-store"})

    routes = list(provider.get_routes(mcp_path="/mcp"))
    routes.extend(
        [
            Route("/authorization/login", login_get, methods=["GET"]),
            Route("/authorization/login", login_post, methods=["POST"]),
            Route("/.well-known/jwks.json", jwks, methods=["GET"]),
            Route(
                "/internal/v1/authenticate",
                authenticate_internal,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/users/by-username/{username}",
                user_by_username_internal,
                methods=["GET"],
            ),
            Route("/health", health, methods=["GET"]),
        ]
    )
    return Starlette(routes=routes)

from __future__ import annotations

import hmac

from starlette.requests import Request
from starlette_admin.auth import AdminUser, AuthProvider, LoginFailed

from common.settings import ManagementSettings

SESSION_KEY = "management_admin"


def credentials_valid(settings: ManagementSettings, username: str, password: str) -> bool:
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(
        password, settings.admin_password
    )


def authenticated_username(request: Request, settings: ManagementSettings) -> str | None:
    username = request.session.get(SESSION_KEY)
    if not isinstance(username, str) or not username:
        return None
    if not hmac.compare_digest(username, settings.admin_username):
        request.session.clear()
        return None
    return username


def establish_session(request: Request, settings: ManagementSettings) -> str:
    request.session[SESSION_KEY] = settings.admin_username
    return settings.admin_username


class ManagementAuthProvider(AuthProvider):
    def __init__(self, settings: ManagementSettings) -> None:
        super().__init__()
        self.settings = settings

    async def login(
        self,
        username: str,
        password: str,
        remember_me: bool,
        request: Request,
    ) -> None:
        del remember_me
        if not credentials_valid(self.settings, username, password):
            raise LoginFailed("Invalid username or password")
        establish_session(request, self.settings)

    async def authenticate(self, request: Request) -> AdminUser | None:
        username = authenticated_username(request, self.settings)
        return AdminUser(username=username) if username else None

    async def logout(self, request: Request) -> None:
        request.session.clear()

from __future__ import annotations

from common.admin_api_client import AdminApiClient
from common.observability import announce_runtime_started, build_observability
from common.settings import AdminApiClientSettings, AuthServiceSettings

from .api import build_auth_app
from .provider import MultiResourceGitHubProvider

settings = AuthServiceSettings()
settings.validate_bootstrap()
_observability = build_observability("auth")
announce_runtime_started(_observability, "auth")

admin_api = AdminApiClient(AdminApiClientSettings())
provider = MultiResourceGitHubProvider(settings, admin_api)
app = build_auth_app(provider)

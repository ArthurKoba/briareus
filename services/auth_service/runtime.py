from __future__ import annotations

from common.management_client import ManagementClient
from common.observability import announce_runtime_started, build_observability
from common.settings import AuthServiceSettings, ManagementClientSettings

from .api import build_auth_app
from .provider import MultiResourceGitHubProvider

settings = AuthServiceSettings()
settings.validate_bootstrap()
_observability = build_observability("auth")
announce_runtime_started(_observability, "auth")

management = ManagementClient(ManagementClientSettings())
provider = MultiResourceGitHubProvider(settings, management)
app = build_auth_app(provider)

from __future__ import annotations

from common.observability import announce_runtime_started, build_observability
from common.settings import AuthServiceSettings

from .api import build_auth_app
from .provider import MultiResourceGitHubProvider

settings = AuthServiceSettings()
settings.validate_bootstrap()
_observability = build_observability("auth")
announce_runtime_started(_observability, "auth")

provider = MultiResourceGitHubProvider(settings)
app = build_auth_app(provider)

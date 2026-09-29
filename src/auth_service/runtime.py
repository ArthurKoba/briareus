from __future__ import annotations

from common.settings import AuthServiceSettings

from .api import build_auth_app
from .provider import MultiResourceGitHubProvider

settings = AuthServiceSettings()
settings.validate_bootstrap()

provider = MultiResourceGitHubProvider(settings)
app = build_auth_app(provider, settings)

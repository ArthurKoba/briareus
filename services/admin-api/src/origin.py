from __future__ import annotations

from urllib.parse import urlsplit


def origin_allowed(origin: str, public_host: str, admin_ui_origin: str) -> bool:
    if not origin:
        return True

    parsed = urlsplit(origin)
    if parsed.netloc.casefold() == public_host.casefold():
        return True

    configured = admin_ui_origin.strip().rstrip("/")
    return bool(configured and origin.rstrip("/").casefold() == configured.casefold())

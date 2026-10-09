"""Identity-only operator setting: externally configured Admin UI link origin."""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field, field_validator

from common.settings import ProcessSettings


class IdentityLinkSettings(ProcessSettings):
    admin_ui_public_url: str | None = Field(default=None, validation_alias="ADMIN_UI_PUBLIC_URL")

    @field_validator("admin_ui_public_url")
    @classmethod
    def _url(cls, raw: str | None) -> str | None:
        if raw is None or not raw.strip():
            return None
        candidate = raw.strip()
        parsed = urlsplit(candidate)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or len(candidate) > 2048
            or not parsed.hostname
        ):
            raise ValueError("ADMIN_UI_PUBLIC_URL must be a public origin without userinfo/query")
        if parsed.scheme == "https":
            return candidate.rstrip("/")
        if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return candidate.rstrip("/")
        raise ValueError("ADMIN_UI_PUBLIC_URL must use HTTPS (except local loopback)")

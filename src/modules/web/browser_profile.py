from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrowserDesktopProfile:
    """Browser-visible desktop identity kept inside the Web runtime."""

    headless: bool = False
    viewport_width: int = 1440
    viewport_height: int = 900
    locale: str = "ru-RU"
    posix_locale: str = "ru_RU.UTF-8"
    accept_language: str = "ru-RU,ru,en-US,en"
    display: str = ":99"
    color_depth: int = 24
    xvfb_enabled: bool = True


DEFAULT_BROWSER_DESKTOP_PROFILE = BrowserDesktopProfile()

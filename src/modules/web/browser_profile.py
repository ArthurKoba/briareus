from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def resolve_chromium_gpu_args(dri_root: Path = Path("/dev/dri")) -> tuple[str, ...]:
    """Prefer a real DRM render node; use SwiftShader only when none is available."""
    if dri_root.is_dir() and any(dri_root.glob("renderD*")):
        return (
            "--use-gl=angle",
            "--use-angle=vulkan",
            "--enable-features=Vulkan,DefaultANGLEVulkan,VulkanFromANGLE",
            "--ignore-gpu-blocklist",
        )
    return (
        "--use-gl=angle",
        "--use-angle=swiftshader",
    )


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

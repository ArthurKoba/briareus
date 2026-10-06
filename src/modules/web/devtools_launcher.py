from __future__ import annotations

import os

from common.settings import BrowserSettings

from .devtools_target import DevToolsTarget, chrome_devtools_connection_args, load_target


def _command(settings: BrowserSettings, target: DevToolsTarget) -> list[str]:
    return [
        "node",
        str(settings.devtools_mcp_script_path),
        *chrome_devtools_connection_args(target),
        "--category-extensions=true",
        "--memory-debugging=true",
        "--workspace=/workspace",
        "--performance-crux=false",
        "--usage-statistics=false",
    ]


def main() -> None:
    settings = BrowserSettings()
    target = load_target()
    command = _command(settings, target)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()

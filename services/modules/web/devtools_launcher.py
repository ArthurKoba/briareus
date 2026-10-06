from __future__ import annotations

import os

from common.settings import BrowserSettings

from .devtools_target import chrome_devtools_connection_args, load_target


def main() -> None:
    settings = BrowserSettings()
    target = load_target()
    command = [
        "node",
        str(settings.devtools_mcp_script_path),
        *chrome_devtools_connection_args(target),
        "--category-extensions=true",
        "--memory-debugging=true",
        "--workspace=/workspace",
        "--file-navigations=false",
        "--performance-crux=false",
        "--usage-statistics=false",
    ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()

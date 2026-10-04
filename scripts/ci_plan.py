from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

FULL_TRIGGERS = (
    ".github/workflows/",
    "Dockerfile",
    "docker-compose.yaml",
    "pyproject.toml",
    "uv.lock",
    "docker-entrypoint.sh",
    "scripts/ci_plan.py",
    "services/common/",
)


@dataclass(frozen=True)
class Area:
    source_prefixes: tuple[str, ...]
    mypy_paths: tuple[str, ...]


AREAS: dict[str, Area] = {
    "auth": Area(("services/auth_service/",), ("services/auth_service",)),
    "gateway": Area(("services/bridge/",), ("services/bridge",)),
    "management": Area(("services/management/",), ("services/management",)),
    "github": Area(("services/modules/github/",), ("services/modules/github",)),
    "gitlab": Area(("services/modules/gitlab/",), ("services/modules/gitlab",)),
    "files": Area(("services/modules/files/",), ("services/modules/files",)),
    "web": Area(("services/modules/web/",), ("services/modules/web",)),
    "terminal": Area(("services/modules/terminal/",), ("services/modules/terminal",)),
    "analysis": Area(("services/modules/analysis/",), ("services/modules/analysis",)),
    "ghidra": Area(("services/modules/ghidra/",), ("services/modules/ghidra",)),
    "observability": Area(
        ("services/modules/signoz/", "services/modules/coolify/", "services/modules/observability/"),
        ("services/modules/signoz", "services/modules/coolify", "services/modules/observability"),
    ),
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix)


def plan(changed_paths: list[str], *, force_full: bool = False) -> dict[str, object]:
    paths: list[str] = []
    for raw_path in changed_paths:
        value = raw_path.strip()
        if not value:
            continue
        paths.append(value[2:] if value.startswith("./") else value)
    full = force_full or not paths or any(
        _matches(path, trigger) for path in paths for trigger in FULL_TRIGGERS
    )

    matched_areas: list[str] = []
    unknown_code = False
    for path in paths:
        area_match = None
        for name, area in AREAS.items():
            if any(_matches(path, prefix) for prefix in area.source_prefixes):
                area_match = name
                break
        if area_match and area_match not in matched_areas:
            matched_areas.append(area_match)
        elif path.startswith("services/") and not area_match:
            unknown_code = True

    # Cross-cutting or unknown code changes are safer as a full gate.
    if unknown_code or len(matched_areas) >= 4:
        full = True

    if full:
        return {
            "full": True,
            "areas": ["full"],
            "mypy_paths": ["src"],
            "ruff_paths": ["src", "scripts"],
        }

    mypy_paths: list[str] = []
    for name in matched_areas:
        area = AREAS[name]
        mypy_paths.extend(area.mypy_paths)

    changed_python = [path for path in paths if path.endswith(".py") and Path(path).parts]
    return {
        "full": False,
        "areas": matched_areas or ["non-code"],
        "mypy_paths": _unique(mypy_paths),
        "ruff_paths": _unique(changed_python),
    }


def _emit_github_output(result: dict[str, object], output_file: Path) -> None:
    lines = []
    for key, value in result.items():
        rendered = (
            json.dumps(value, separators=(",", ":"))
            if not isinstance(value, bool)
            else str(value).lower()
        )
        lines.append(f"{key}={rendered}")
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--force-full", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = plan(args.paths, force_full=args.force_full)
    if args.github_output:
        _emit_github_output(result, args.github_output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

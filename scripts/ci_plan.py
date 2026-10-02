from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

ALL_DOCKER_TARGETS = (
    "auth",
    "gateway",
    "management",
    "github",
    "gitlab",
    "files",
    "curl",
    "terminal",
    "analysis",
    "ghidra",
    "observability",
)

FULL_TRIGGERS = (
    ".github/workflows/",
    "Dockerfile",
    "docker-compose.yaml",
    "pyproject.toml",
    "uv.lock",
    "docker-entrypoint.sh",
    "src/common/",
    "tests/common/",
    "tests/test_architecture_boundaries.py",
    "tests/test_runtime_entrypoints.py",
)


@dataclass(frozen=True)
class Area:
    source_prefixes: tuple[str, ...]
    test_paths: tuple[str, ...]
    docker_targets: tuple[str, ...]
    mypy_paths: tuple[str, ...]


AREAS: dict[str, Area] = {
    "auth": Area(("src/auth_service/",), ("tests/auth_service",), ("auth",), ("src/auth_service",)),
    "gateway": Area(("src/bridge/",), ("tests/bridge",), ("gateway",), ("src/bridge",)),
    "management": Area(
        ("src/management/",),
        ("tests/management",),
        ("management",),
        ("src/management",),
    ),
    "github": Area(
        ("src/modules/github/",),
        ("tests/modules/github",),
        ("github",),
        ("src/modules/github",),
    ),
    "gitlab": Area(
        ("src/modules/gitlab/",),
        ("tests/modules/gitlab",),
        ("gitlab",),
        ("src/modules/gitlab",),
    ),
    "files": Area(
        ("src/modules/files/",),
        ("tests/modules/files",),
        ("files", "management", "analysis", "curl"),
        ("src/modules/files",),
    ),
    "curl": Area(
        ("src/modules/curl/",),
        ("tests/modules/curl",),
        ("curl",),
        ("src/modules/curl",),
    ),
    "terminal": Area(
        ("src/modules/terminal/",),
        ("tests/modules/terminal",),
        ("terminal",),
        ("src/modules/terminal",),
    ),
    "analysis": Area(
        ("src/modules/analysis/",),
        ("tests/modules/analysis",),
        ("analysis",),
        ("src/modules/analysis",),
    ),
    "ghidra": Area(
        ("src/modules/ghidra/",),
        ("tests/modules/ghidra",),
        ("ghidra",),
        ("src/modules/ghidra",),
    ),
    "observability": Area(
        ("src/modules/signoz/", "src/modules/coolify/", "src/modules/observability/"),
        ("tests/modules/coolify", "tests/common/test_observability.py"),
        ("observability",),
        ("src/modules/signoz", "src/modules/coolify", "src/modules/observability"),
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
            if any(_matches(path, prefix) for prefix in area.source_prefixes) or any(
                _matches(path, test_path) for test_path in area.test_paths
            ):
                area_match = name
                break
        if area_match and area_match not in matched_areas:
            matched_areas.append(area_match)
        elif path.startswith(("src/", "tests/")) and not area_match:
            unknown_code = True

    # Cross-cutting or unknown code changes are safer as a full gate.
    if unknown_code or len(matched_areas) >= 4:
        full = True

    if full:
        return {
            "full": True,
            "areas": ["full"],
            "pytest_paths": ["tests"],
            "mypy_paths": ["src"],
            "ruff_paths": ["src", "tests", "scripts"],
            "docker_targets": list(ALL_DOCKER_TARGETS),
        }

    pytest_paths: list[str] = []
    mypy_paths: list[str] = []
    docker_targets: list[str] = []
    for name in matched_areas:
        area = AREAS[name]
        pytest_paths.extend(area.test_paths)
        mypy_paths.extend(area.mypy_paths)
        docker_targets.extend(area.docker_targets)

    changed_python = [path for path in paths if path.endswith(".py") and Path(path).parts]
    return {
        "full": False,
        "areas": matched_areas or ["non-code"],
        "pytest_paths": _unique(pytest_paths),
        "mypy_paths": _unique(mypy_paths),
        "ruff_paths": _unique(changed_python),
        "docker_targets": _unique(docker_targets),
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

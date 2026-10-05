from __future__ import annotations

import argparse
import json
from pathlib import Path

# Integration suites are intentionally narrower than static validation. Ruff,
# mypy and unit tests run for the whole backend; expensive PostgreSQL/Valkey
# suites run only when their runtime contract or test/provisioning inputs change.
INTEGRATION_SUITES: dict[str, tuple[str, ...]] = {
    "authorization": (
        "services/authorization/",
        "tests/test_postgres_authorization_access.py",
        "scripts/provision_authorization_database.py",
    ),
}

# These inputs can affect every integration suite regardless of service owner.
CROSS_CUTTING_INTEGRATION_TRIGGERS = (
    ".github/workflows/mvp-backend.yaml",
    "Jenkinsfile",
    "pyproject.toml",
    "uv.lock",
    "scripts/ci_plan.py",
    "services/common/",
)


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix)


def _normalize(changed_paths: list[str]) -> list[str]:
    paths: list[str] = []
    for raw_path in changed_paths:
        value = raw_path.strip()
        if not value:
            continue
        paths.append(value[2:] if value.startswith("./") else value)
    return list(dict.fromkeys(paths))


def plan(changed_paths: list[str], *, force_full: bool = False) -> dict[str, object]:
    paths = _normalize(changed_paths)
    run_all_integrations = force_full or not paths or any(
        _matches(path, trigger)
        for path in paths
        for trigger in CROSS_CUTTING_INTEGRATION_TRIGGERS
    )

    integration_suites: list[str] = []
    for suite, triggers in INTEGRATION_SUITES.items():
        if run_all_integrations or any(
            _matches(path, trigger) for path in paths for trigger in triggers
        ):
            integration_suites.append(suite)

    return {
        "changed_paths": paths,
        "integration_suites": integration_suites,
        "run_authorization_integration": "authorization" in integration_suites,
    }


def _emit_github_output(result: dict[str, object], output_file: Path) -> None:
    lines: list[str] = []
    for key, value in result.items():
        if isinstance(value, bool):
            rendered = str(value).lower()
        else:
            rendered = json.dumps(value, separators=(",", ":"))
        lines.append(f"{key}={rendered}")
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--paths-file", type=Path)
    parser.add_argument("--force-full", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    paths = list(args.paths)
    if args.paths_file:
        paths.extend(args.paths_file.read_text(encoding="utf-8").splitlines())
    result = plan(paths, force_full=args.force_full)
    if args.github_output:
        _emit_github_output(result, args.github_output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""One read-only, source-based acceptance gate for the flat Coolify migration.

This is not a test suite, deploy client, or a provider of fake OAuth grants.
No Coolify API queries or writes are performed; validation does not accept live cutover.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/operations/flat-batch-cutover.json"
SCOPE = ROOT / "docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md"


def watch_paths(text: str) -> list[str]:
    rows = text.splitlines()
    try:
        start = rows.index("x-watch-path-coolify:") + 1
    except ValueError:
        raise ValueError("missing native x-watch-path-coolify mapping") from None
    watched: list[str] = []
    decoder = json.JSONDecoder()
    for line in rows[start:]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        if line.startswith("  - "):
            raw = line[4:].strip()
            name, end = decoder.raw_decode(raw)
            remaining = raw[end:].strip()
            if not isinstance(name, str) or (remaining and not remaining.startswith("#")):
                raise ValueError(f"invalid watch item: {line}")
            watched.append(name)
    return watched


def run(*, compose: bool, uv_locks: bool) -> int:
    plan = json.loads(MANIFEST.read_text())
    errors: list[str] = []
    expected = {
        "project": "3xshlpoghb9wcyhjgktlqzzp",
        "environment": "naibrku1omovvmw5o0bcnp5c",
        "repository": "ArthurKoba/briareus",
    }
    if plan.get("scope") != expected:
        errors.append("scope does not match authorized Briareus Development")
    candidates = plan["candidates"]
    held = plan["held"]
    planned = candidates + held
    uuids = [item["uuid"] for item in planned]
    if len(uuids) != 14 or len(set(uuids)) != 14:
        errors.append("expected 14 different explicitly allowlisted applications")
    scope_uuids = set(
        re.findall(r"\| ([a-z][\w-]*) \| [^|]+ \| ([a-z0-9]{24}) \|", SCOPE.read_text())
    )
    # Each tuple is (slug, uuid); prevents relabeling unrelated application IDs.
    if {(v["slug"], v["uuid"]) for v in planned} != scope_uuids:
        errors.append("manifest UUID/slug pairs differ from the approved Dev allowlist")
    print(f"Flat migration source candidates={len(candidates)}, held={len(held)}")
    for unit in candidates:
        slug, folder = unit["slug"], unit["folder"]
        prefix = f"{slug}: "
        path = ROOT / folder
        required = ("Dockerfile", "docker-compose.yaml", "docker-compose.coolify.yaml")
        errors.extend(
            prefix + f"missing {file}" for file in required if not (path / file).is_file()
        )
        if not all((path / file).is_file() for file in required):
            continue
        if (
            unit["base_directory"] != "/" + folder
            or unit["compose_location"] != "/docker-compose.coolify.yaml"
        ):
            errors.append(prefix + "incorrect Coolify Base or Compose path")
        manifest = (path / "docker-compose.coolify.yaml").read_text()
        portable = (path / "docker-compose.yaml").read_text()
        dockerfile = (path / "Dockerfile").read_text()
        try:
            actual = watch_paths(manifest)
            if actual != unit["watch_paths"]:
                errors.append(
                    prefix + f"watch mismatch expected={unit['watch_paths']}, actual={actual}"
                )
            if len(set(actual)) != len(actual):
                errors.append(prefix + "duplicate watch patterns")
            if any(
                pattern in ("**", "shared/**", "hands/**", "services/**", "deploy/**")
                for pattern in actual
            ):
                errors.append(prefix + "unscoped watch path")
        except (ValueError, json.JSONDecodeError) as error:
            errors.append(prefix + f"watch parsing failed: {error}")
        if not re.search(r"(?m)^\s+context:\s+\.\./\.\.\s*$", portable):
            errors.append(prefix + "build context is not the repository root")
        if f"dockerfile: {folder}/Dockerfile" not in portable:
            errors.append(prefix + "portable Compose points to another Dockerfile")
        if f"COPY {folder}/" not in dockerfile and unit["toolchain"] != "upstream":
            errors.append(prefix + "Dockerfile lacks local source/lock COPY")
        if unit["toolchain"] == "python" and not all(
            (path / f).is_file() for f in ("pyproject.toml", "uv.lock")
        ):
            errors.append(prefix + "missing uv project/lock")
        if unit["toolchain"] == "bun" and not all(
            (path / f).is_file() for f in ("package.json", "bun.lock")
        ):
            errors.append(prefix + "missing Bun project/lock")
        if folder.startswith("hands/"):
            if unit["watch_paths"] != [f"{folder}/**", "shared/hand_runtime/**"]:
                errors.append(prefix + "Hand shared imports must be selective")
            if "read_only: true" not in portable or "cap_drop: [ALL]" not in portable:
                errors.append(
                    prefix + "transitional Hand missing explicit unprivileged process bounds"
                )
            if "COPY shared/hand_runtime/" not in dockerfile:
                errors.append(prefix + "selected shared module missing from Docker image")
        if uv_locks and unit["toolchain"] == "python":
            result = subprocess.run(
                ["uv", "lock", "--check", "--project", folder],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                errors.append(
                    prefix + "uv lock mismatch: " + (result.stderr or result.stdout)[-340:]
                )
        if compose:
            command = [
                "docker",
                "compose",
                "--project-directory",
                str(path),
                "-f",
                str(path / "docker-compose.coolify.yaml"),
                "config",
                "--no-interpolate",
                "--quiet",
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            if result.returncode:
                errors.append(
                    prefix
                    + "Docker Compose config failed: "
                    + (result.stderr or result.stdout)[-500:]
                )
        print("CHECKED", slug, folder)
    for item in held:
        if item.get("action", "").find("preserve") < 0:
            errors.append(
                item["slug"] + ": held application must preserve its existing configuration"
            )
        print("HELD", item["slug"], item["reason"])
    for error in errors:
        print("ERROR", error, file=sys.stderr)
    print("BATCH_SOURCE_GATE", "PASS" if not errors else "FAIL", f"errors={len(errors)}")
    return 0 if not errors else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compose", action="store_true", help="validate every Compose input with Docker Compose"
    )
    parser.add_argument(
        "--uv-locks", action="store_true", help="verify all Python package lockfiles"
    )
    args = parser.parse_args()
    raise SystemExit(run(compose=args.compose, uv_locks=args.uv_locks))

#!/usr/bin/env python3
"""One read-only, source-based acceptance gate for the flat Coolify migration.

This is not a test suite, deploy client, or a provider of fake OAuth grants.
No Coolify API queries or writes are performed; validation does not accept live cutover.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
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


def control_panel_upstream_errors() -> list[str]:
    """Require the fixed proxy targets used by the canonical owner Compose files."""
    path = ROOT / "services/gateway/src/bridge/thin_gateway.py"
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return ["gateway: fixed Control Panel upstream source cannot be parsed"]
    configured = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    expected = {
        "_API_UPSTREAM": "http://briareus-control-panel-api:8000",
        "_PANEL_UPSTREAM": "http://briareus-control-panel-ui:8080",
    }
    errors = [
        f"gateway: {name} must match canonical target {target}"
        for name, target in expected.items()
        if configured.get(name) != target
    ]
    if any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(old in node.value for old in ("briareus-admin-api", "briareus-admin-ui"))
        for node in ast.walk(tree)
    ):
        errors.append("gateway: retired Control Panel DNS remains in target/host literals")
    return errors


def startup_boundary_errors(folder: str, portable: str) -> list[str]:
    """Keep cross-application startup and Core secrets out of execution Compose.

    A physical Coolify Application is a separate Compose project. Declaring
    another application's service in depends_on cannot synchronize startup.
    Never confuse a statically validated topology with runtime/readiness proof.
    """
    errors: list[str] = []
    if folder == "services/external":
        # Existing vendor stack is the sole current shared Compose unit.
        # Rauthy must wait for the reconciled owner DB, not PG TCP alone.
        rauthy = portable.partition("  briareus-rauthy:")[2]
        if (
            not rauthy
            or re.search(
                (
                    r"(?m)^    depends_on:\n      briareus-postgres:"
                    r"\n        condition: service_healthy$"
                ),
                rauthy,
            )
            is None
        ):
            errors.append("data: Rauthy must depend on same-stack Postgres readiness")
        return errors
    if re.search(r"(?m)^    depends_on:\s*$", portable):
        errors.append(
            folder + ": independent Coolify app cannot order external apps via depends_on"
        )
    if folder == "services/gateway" or folder.startswith("hands/"):
        # This is not yet physical network isolation: these applications
        # currently share briareus-net. Protect the Core secrets meanwhile.
        forbidden = re.findall(
            r"(?m)^      (POSTGRES_(?:HOST|DB|USER|PASSWORD)|RAUTHY_ADMIN_API_KEY|"
            r"OIDC_SESSION_VALKEY_PASSWORD):",
            portable,
        )
        if forbidden:
            errors.append(folder + ": execution app must not receive Core credentials")
    return errors


def bun_image_config_errors(folder: str, path: Path, dockerfile: str) -> list[str]:
    """Check local Vite config imports actually bundled into the UI image.

    An ordinary repository-root Vite build sees files that a restrictive
    Docker COPY + Dockerfile.dockerignore might omit. This checks the exact
    known Config relative import only when the committed vite.config uses it.
    It is not an image-build or TypeScript acceptance substitute.
    """
    if folder != "services/ui":
        return []
    try:
        config = (path / "vite.config.ts").read_text()
    except OSError:
        return ["control-panel-ui: Vite config missing from tracked source"]
    if re.search(r"from\s+['\"]\./local-http-proxy['\"]", config) is None:
        return []
    errors: list[str] = []
    if not (path / "local-http-proxy.ts").is_file():
        errors.append("control-panel-ui: required relative Vite config module absent")
    if "COPY services/ui/local-http-proxy.ts" not in dockerfile:
        errors.append("control-panel-ui: Dockerfile omits local Vite config dependency")
    ignore = path / "Dockerfile.dockerignore"
    if ignore.is_file():
        lines = [line.strip() for line in ignore.read_text().splitlines()]
        if "**" in lines and "!services/ui/local-http-proxy.ts" not in lines:
            errors.append("control-panel-ui: Dockerfile.dockerignore excludes Vite module")
    return errors


def saved_coolify_errors(
    snapshot: object,
    plan: dict[str, object],
    *,
    targets: frozenset[str] | None = None,
) -> list[str]:
    """Validate a bounded, read-only exact-UUID Dev snapshot, never query Coolify.

    Saved Coolify Watch Paths are runtime state, NOT the same thing as Git
    Compose x-watch-path-coolify. Reject unknown UUIDs or unexpected fields
    (including credentials) without echoing untrusted values to logs.
    """
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "scope",
        "captured_at_utc",
        "applications",
        "lookup_errors",
    }:
        return ["Coolify snapshot: invalid bounded metadata envelope"]
    if snapshot["scope"] != plan["scope"]:
        return ["Coolify snapshot: authorized project/environment/repository mismatch"]
    stamp = snapshot["captured_at_utc"]
    try:
        if not isinstance(stamp, str):
            raise ValueError("invalid timestamp type")
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError("missing timezone")
        age = datetime.now(UTC) - when
        if not -timedelta(minutes=2) <= age <= timedelta(hours=1):
            raise ValueError("stale or future snapshot")
    except (ValueError, OverflowError):
        return ["Coolify snapshot: timestamp missing, future or older than one hour"]
    apps = snapshot["applications"]
    if not isinstance(apps, list) or len(apps) > 14:
        return ["Coolify snapshot: application list must be scoped and bounded"]
    allowed_fields = {
        "slug",
        "uuid",
        "name",
        "status",
        "watch_paths",
        "base_directory",
        "docker_compose_location",
        "git_repository",
        "git_branch",
    }
    actual: dict[tuple[str, str], dict[str, str]] = {}
    for item in apps:
        if (
            not isinstance(item, dict)
            or set(item) != allowed_fields
            or any(not isinstance(value, str) for value in item.values())
        ):
            return ["Coolify snapshot: unexpected/missing field or non-string metadata"]
        key = (item["slug"], item["uuid"])
        if key in actual:
            return ["Coolify snapshot: duplicate Application slug/UUID"]
        actual[key] = item
    desired = plan["candidates"] + plan["held"]
    expected_ids = {(item["slug"], item["uuid"]) for item in desired}
    if not set(actual) <= expected_ids:
        return ["Coolify snapshot: unapproved or mislabeled Application UUID"]
    missing = expected_ids - set(actual)
    # Failed exact-UUID reads are evidence of an UNVERIFIED application, not
    # proof of deletion and certainly not permission to recreate it.
    failed = snapshot["lookup_errors"]
    if not isinstance(failed, list) or len(failed) > 14:
        return ["Coolify snapshot: invalid scoped lookup error list"]
    failures: set[tuple[str, str]] = set()
    for item in failed:
        if (
            not isinstance(item, dict)
            or set(item) != {"slug", "uuid", "error_type"}
            or any(not isinstance(value, str) for value in item.values())
            or item["error_type"] not in {"http_404", "timeout", "unavailable"}
        ):
            return ["Coolify snapshot: invalid bounded lookup-error record"]
        key = (item["slug"], item["uuid"])
        if key not in missing or key in failures:
            return ["Coolify snapshot: error must match one unavailable approved UUID"]
        failures.add(key)
    if failures != missing:
        return ["Coolify snapshot: missing approved Application without read evidence"]
    errors: list[str] = [
        slug + ": approved Dev Application metadata unverified (exact UUID)"
        for slug, _ in sorted(missing)
        if targets is None or slug in targets
    ]
    for item in plan["candidates"]:
        slug = item["slug"]
        if targets is not None and slug not in targets:
            continue
        app = actual.get((slug, item["uuid"]))
        if app is None:
            continue
        for field, expected in (
            ("base_directory", item["base_directory"]),
            ("docker_compose_location", item["compose_location"]),
            ("git_repository", plan["scope"]["repository"]),
            ("git_branch", "main"),
        ):
            if app[field] != expected:
                errors.append(slug + ": saved Coolify " + field + " differs from source")
        watch = [part.strip() for part in app["watch_paths"].splitlines() if part.strip()]
        expected_watches = item["watch_paths"]
        if len(watch) != len(set(watch)):
            errors.append(slug + ": duplicate persisted Watch Paths")
        # Print only expected paths from reviewed Git, never untrusted values.
        errors.extend(
            slug + ": saved Watch Paths missing " + name
            for name in expected_watches
            if name not in watch
        )
        if len(set(watch) - set(expected_watches)):
            # Do not print values from the externally collected snapshot.
            errors.append(slug + ": unreviewed persisted Watch Paths present")
    # Held Identity is deliberately retained; validating presence/UUID is not
    # authority to change its Base, Watch, Compose, network or configuration.
    return errors


def _unique_snapshot_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    item: dict[str, object] = {}
    for key, value in pairs:
        if key in item:
            raise ValueError("duplicate snapshot JSON property")
        item[key] = value
    return item


def run(
    *,
    compose: bool,
    uv_locks: bool,
    coolify_snapshot: Path | None = None,
    targets: frozenset[str] | None = None,
) -> int:
    plan = json.loads(MANIFEST.read_text())
    errors: list[str] = []
    expected = {
        "project": "3xshlpoghb9wcyhjgktlqzzp",
        "environment": "naibrku1omovvmw5o0bcnp5c",
        "repository": "KobaProduction/briareus",
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
    accepted_targets = {item["slug"] for item in candidates}
    if targets is not None and (not targets or not targets.issubset(accepted_targets)):
        errors.append("target gate accepts only named approved candidate modules")
        for error in errors:
            print("ERROR", error, file=sys.stderr)
        print("BATCH_SOURCE_GATE FAIL", f"errors={len(errors)}")
        return 1
    if targets is None or "gateway" in targets:
        errors.extend(control_panel_upstream_errors())
    if coolify_snapshot is not None:
        snapshot_errors: list[str] = []
        try:
            if coolify_snapshot.stat().st_size > 131072:
                raise ValueError("oversized read-only metadata snapshot")
            snapshot = json.loads(
                coolify_snapshot.read_text(), object_pairs_hook=_unique_snapshot_fields
            )
        except (OSError, ValueError, json.JSONDecodeError):
            snapshot_errors.append("Coolify snapshot: unreadable or invalid JSON metadata")
        else:
            snapshot_errors.extend(saved_coolify_errors(snapshot, plan, targets=targets))
        errors.extend(snapshot_errors)
        print(
            "COOLIFY_SAVED_CONFIG_GATE",
            "PASS" if not snapshot_errors else "FAIL",
            f"errors={len(snapshot_errors)}",
        )
    if targets is None:
        print(f"Flat migration source candidates={len(candidates)}, held={len(held)}")
    else:
        print(f"Development target-only source candidates={len(targets)}, held=0")
        print("PARTIAL_DEV_MODULE_GATE: not a 13-app or Product acceptance")
    for unit in candidates:
        slug, folder = unit["slug"], unit["folder"]
        if targets is not None and slug not in targets:
            continue
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
        errors.extend(startup_boundary_errors(folder, portable))
        errors.extend(bun_image_config_errors(folder, path, dockerfile))
        try:
            actual = watch_paths(manifest)
            if actual != unit["watch_paths"]:
                errors.append(
                    prefix + f"watch mismatch expected={unit['watch_paths']}, actual={actual}"
                )
            required_watches = {f"{folder}/**", "services/external/**"}
            if not required_watches.issubset(actual):
                errors.append(prefix + "module and shared External directory watches required")
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
            if set(unit["watch_paths"]) != {
                f"{folder}/**",
                "shared/hand_runtime/**",
                "services/external/**",
            }:
                errors.append(prefix + "Hand watches require own, shared runtime and External only")
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
    if targets is None:
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
    parser.add_argument(
        "--coolify-snapshot",
        type=Path,
        help="optional read-only exact-UUID saved app metadata (fresh <= 1 hour)",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="repeatable candidate slug for independent Development module checks",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            compose=args.compose,
            uv_locks=args.uv_locks,
            coolify_snapshot=args.coolify_snapshot,
            targets=frozenset(args.target) if args.target else None,
        )
    )

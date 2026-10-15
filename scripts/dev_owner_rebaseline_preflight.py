#!/usr/bin/env python3
"""Bounded, read-only source preflight for the approved Briareus Dev rebaseline.

Owner-approved disposable SERVICE data is not a permission to reset Rauthy,
PGDATA, Valkey, Files roots, or another Coolify environment. This command
prints the immutable targeted source mapping and outstanding real-world
evidence; it NEVER executes SQL, updates a runtime or reports reset approval.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SCOPE = {
    "project": "3xshlpoghb9wcyhjgktlqzzp",
    "environment": "naibrku1omovvmw5o0bcnp5c",
    "repository": "KobaProduction/briareus",
}
_TARGETS = {
    "access": (
        "authorization",
        "briareus_access",
        "access_20261015_0001",
        "95podguiawtnf2tvlemvk3ef",
    ),
    "platform": (
        "platform",
        "briareus_platform",
        "platform_20261015_0001",
        "uvr5zfb9729ptfyfuxo3htmc",
    ),
    "resources": (
        "resources",
        "briareus_resources",
        "resources_20261015_0001",
        "6vdxwespr1ufxeohy6xpa7wg",
    ),
}
_PROTECTED = frozenset(
    {
        "briareus_rauthy",
        "briareus_identity",
        "briareus_dev",
        "briareus_files",
        "briareus_runtime",
        "briareus_reverse",
    }
)
_PINNED_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)


def _git_blob(ref: str, path: str, *, repo: Path = ROOT) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", ref + ":" + path],
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )
    return result.stdout if result.returncode == 0 and len(result.stdout) < 140000 else None


def _revisions(source: str) -> dict[str, tuple[str, ...]]:
    for item in ast.parse(source).body:
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and item.target.id == "_REVIEWED_VERSIONS"
        ):
            value = ast.literal_eval(item.value)
            if isinstance(value, dict):
                return value
    raise ValueError("reviewed owner revision map absent")


def _baseline_revision(source: str) -> str | None:
    for item in ast.parse(source).body:
        if (
            isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and item.targets[0].id == "revision"
        ):
            value = ast.literal_eval(item.value)
            return value if isinstance(value, str) else None
    return None


def inspect(ref: str, *, repo: Path = ROOT) -> dict[str, object]:
    """Static source mapping only: no remote discovery or secret access."""
    if not _PINNED_SHA.fullmatch(ref):
        return {"state": "INVALID_CANDIDATE_REF", "release_authorized": False}
    manifest = json.loads((repo / "docs/operations/flat-batch-cutover.json").read_text())
    external = json.loads((repo / "services/external/config/owner-databases.json").read_text())
    errors: list[str] = []
    if manifest.get("scope") != _SCOPE:
        errors.append("Development project/environment/repository scope differs")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
        errors.append("approved Dev Application list missing")
    targets = {x.get("slug"): x for x in candidates if isinstance(x, dict)}
    providers = external.get("protected_provider_databases")
    if not isinstance(providers, list) or providers != ["briareus_rauthy"]:
        errors.append("Rauthy provider protected set must remain exact")
    initial = external.get("initial")
    if not isinstance(initial, list):
        initial = []
        errors.append("PostgreSQL logical DB owner inventory unavailable")
    allowed_databases = {x.get("database") for x in initial if isinstance(x, dict)}
    if allowed_databases != {value[1] for value in _TARGETS.values()} | {"briareus_rauthy"}:
        errors.append("External DB owner inventory differs from exactly approved four names")

    owner_code = _git_blob(ref, "services/common/owner_migrations.py", repo=repo)
    try:
        revision_registry = _revisions(owner_code) if owner_code is not None else {}
    except (ValueError, SyntaxError, TypeError, MemoryError):
        revision_registry = {}
    if not revision_registry:
        errors.append("exact candidate reviewed owner migration registry unavailable")

    reports: list[dict[str, str]] = []
    for owner, (service, database, expected_head, expected_uuid) in _TARGETS.items():
        expected_app = targets.get(service)
        if not isinstance(expected_app, dict) or expected_app.get("uuid") != expected_uuid:
            errors.append(service + ": not an approved exact Development Application UUID")
        compose = _git_blob(ref, f"services/{service}/docker-compose.yaml", repo=repo)
        dockerfile = _git_blob(ref, f"services/{service}/Dockerfile", repo=repo)
        ignored = _git_blob(ref, f"services/{service}/Dockerfile.dockerignore", repo=repo)
        baseline_path = f"services/{service}/migrations/versions/0001_{owner}_baseline.py"
        migration = _git_blob(ref, baseline_path, repo=repo)
        expected = revision_registry.get(owner)
        if expected != (expected_head,):
            errors.append(service + ": expected greenfield one-revision epoch unavailable")
        if (
            not isinstance(compose, str)
            or len(
                re.findall(rf'(?m)^\s+POSTGRES_DB:\s*["\']{re.escape(database)}["\']\s*$', compose)
            )
            != 1
        ):
            errors.append(service + ": owner logical database differs or is not uniquely pinned")
        if not isinstance(migration, str) or _baseline_revision(migration) != expected_head:
            errors.append(service + ": greenfield baseline revision not pinned")
        if not isinstance(dockerfile, str) or (
            f"COPY {baseline_path} "
            f"/app/src/common/alembic_owners/{owner}/versions/0001_{owner}_baseline.py"
            not in dockerfile
        ):
            errors.append(service + ": current migration baseline is absent from Docker image")
        if not isinstance(ignored, str) or (
            "**" in ignored.splitlines() and f"!{baseline_path}" not in ignored.splitlines()
        ):
            errors.append(service + ": current migration excluded from Docker build context")
        reports.append(
            {
                "owner": owner,
                "application_slug": service,
                "application_uuid": str(expected_app.get("uuid"))
                if isinstance(expected_app, dict)
                else "",
                "logical_database": database,
                "expected_new_revision": expected_head,
            }
        )
    if any(x["logical_database"] in _PROTECTED for x in reports):
        errors.append("protected provider/legacy/root database included in reset targets")

    return {
        "state": "SOURCE_REBASELINE_CONTRADICTED"
        if errors
        else "SOURCE_CONTRACT_OK_LIVE_RESET_BLOCKED",
        "target_backend_commit": ref,
        "scope": _SCOPE,
        "affected_only": reports,
        "always_protected_databases": sorted(_PROTECTED),
        "protected_filesystem": [
            "existing Project Files root bytes and mounts",
            "owner-authorized Files root mappings until independently reconciled",
        ],
        "runtime_preconditions_unverified": [
            "current scoped owner inspector: database, role, Alembic version and row counts",
            "actual owner rows, sessions, approvals and Project/Files root mapping inventory",
            "recoverable owner-only DB snapshots and verified restore; provider protected",
            "approved exact Coolify app stop/restart capability plus dependency-deny plan",
            "actual Rauthy and shared PGDATA/Valkey/Files-storage protection after any reset",
            "candidate Backend image SHA, Compose parity and post-start schema verification",
        ],
        "source_findings": errors,
        "source_contract_pass": not errors,
        "release_authorized": False,
        "sql_executed": False,
        "coolify_mutated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-sha", required=True, help="exact committed backend git SHA")
    opts = parser.parse_args()
    try:
        report = inspect(opts.backend_sha)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        report = {"state": "SOURCE_REBASELINE_UNVERIFIED", "release_authorized": False}
    print(json.dumps(report, indent=2))
    return 2 if report.get("source_contract_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())

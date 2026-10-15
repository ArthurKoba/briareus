#!/usr/bin/env python3
"""Non-mutating, source-only compatibility fence for deployed owner schemas.

Compare the EXACT git revision shipped by a known Development Application
with a proposed git revision before updating it. A previous image may have
executed any migration it includes: never claim compatibility when the new
image has removed it or rewritten its immutable baseline. This does NOT read
public.alembic_version or authorize a DB downgrade, stamp or reset.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Literal

_OWNER_TO_REGISTRY = {"platform": "platform", "resources": "resources", "authorization": "access"}
_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_PACKAGE = re.compile(r"COPY\s+services/([a-z-]+)/migrations/versions/([A-Za-z0-9_]+\.py)\b")


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=12, check=False
    )
    return result.stdout if result.returncode == 0 and len(result.stdout) < 300000 else None


def _read(root: Path, sha: str, path: str) -> str | None:
    return _git(root, "show", f"{sha}:{path}")


def _history(source: str | None, owner: str) -> tuple[str, ...] | None:
    if source is None:
        return None
    try:
        tree = ast.parse(source)
        for item in tree.body:
            if (
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.target.id == "_REVIEWED_VERSIONS"
            ):
                mapping = ast.literal_eval(item.value)
                value = mapping.get(owner)
                if isinstance(value, tuple) and value and all(isinstance(v, str) for v in value):
                    return value
    except (ValueError, TypeError, SyntaxError, MemoryError):
        pass
    return None


def _packaged(source: str | None, owner: str) -> tuple[str, ...] | None:
    if source is None:
        return None
    return tuple(name for name_owner, name in _PACKAGE.findall(source) if name_owner == owner)


def inspect_owner(root: Path, *, owner: str, previous: str, candidate: str) -> dict[str, object]:
    if owner not in _OWNER_TO_REGISTRY:
        raise ValueError("unknown, non-allowlisted owner")
    if not _SHA.fullmatch(previous) or not _SHA.fullmatch(candidate):
        raise ValueError("pinned exact 40-digit git SHA required")
    if _git(root, "rev-parse", "--verify", previous + "^{commit}") is None:
        raise ValueError("previous deployment git commit is not locally available")
    if _git(root, "rev-parse", "--verify", candidate + "^{commit}") is None:
        raise ValueError("candidate git commit is not locally available")
    previous_source = _read(root, previous, "services/common/owner_migrations.py")
    candidate_source = _read(root, candidate, "services/common/owner_migrations.py")
    prior_chain = _history(previous_source, _OWNER_TO_REGISTRY[owner])
    current_chain = _history(candidate_source, _OWNER_TO_REGISTRY[owner])
    previous_docker = _read(root, previous, f"services/{owner}/Dockerfile")
    candidate_docker = _read(root, candidate, f"services/{owner}/Dockerfile")
    previous_package = _packaged(previous_docker, owner)
    current_package = _packaged(candidate_docker, owner)
    issues: list[str] = []
    status: Literal["SOURCE_COMPATIBLE", "SOURCE_INCOMPATIBLE", "UNVERIFIED"]
    if None in (prior_chain, current_chain, previous_package, current_package):
        status = "UNVERIFIED"
        issues.append("historical_or_current_owner_source_or_packaged_image_unavailable")
    elif not prior_chain or not current_chain:
        status = "UNVERIFIED"
        issues.append("owner_migration_history_cannot_be_established")
    else:
        status = "SOURCE_COMPATIBLE"
        old_actual_packaged = tuple(name for name in previous_package if name.endswith(".py"))
        issues.extend(
            "previously_reviewed_revision_removed:" + revision
            for revision in prior_chain
            if revision not in current_chain
        )
        if current_chain[: len(prior_chain)] != prior_chain:
            issues.append("candidate_revision_chain_is_not_forward_extension")
        for relative in old_actual_packaged:
            filename = f"services/{owner}/migrations/versions/{relative}"
            before = _read(root, previous, filename)
            after = _read(root, candidate, filename)
            if after is None:
                issues.append("previously_packaged_migration_removed:" + relative)
            elif before is None or before != after:
                issues.append("previously_packaged_migration_rewritten:" + relative)
        if any(x not in current_package for x in old_actual_packaged):
            issues.append("candidate_image_drops_historical_migration_copy")
        if len(current_package) != len(current_chain):
            issues.append("candidate_image_migration_count_differs_from_reviewed_chain")
        if issues:
            status = "SOURCE_INCOMPATIBLE"
    return {
        "owner": owner,
        "previous_deployed_source_sha": previous,
        "candidate_source_sha": candidate,
        "previous_reviewed_versions": list(prior_chain or ()),
        "candidate_reviewed_versions": list(current_chain or ()),
        "previous_image_migrations": list(previous_package or ()),
        "candidate_image_migrations": list(current_package or ()),
        "state": status,
        "findings": sorted(set(issues)),
        "live_database_alembic_version_verified": False,
        "live_data_migration_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", choices=sorted(_OWNER_TO_REGISTRY), required=True)
    parser.add_argument("--previous-deployed-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    opts = parser.parse_args()
    try:
        data = inspect_owner(
            opts.repo,
            owner=opts.owner,
            previous=opts.previous_deployed_sha,
            candidate=opts.candidate_sha,
        )
    except (ValueError, OSError, subprocess.SubprocessError):
        print(
            json.dumps(
                {"state": "UNVERIFIED", "findings": ["invalid_exact_commit_or_read_failure"]}
            )
        )
        return 2
    print(json.dumps(data, indent=2))
    return {"SOURCE_COMPATIBLE": 0, "SOURCE_INCOMPATIBLE": 1, "UNVERIFIED": 2}[data["state"]]


if __name__ == "__main__":
    raise SystemExit(main())

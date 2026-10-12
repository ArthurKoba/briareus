#!/usr/bin/env python3
"""Emit source-digest release METADATA only; does not package/build a wheel.

Used inside an existing Coolify Docker BUILD *after* copying the exact
service-owned source files. Immutable source digest is computed from actual
bytes in that image, not from a mutable environment or a remote artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SERVICES = {
    "admin-api", "identity", "authorization", "platform", "resources",
    "gateway", "files", "terminal", "web", "svc", "infrastructure", "reverse",
}


def write_source_metadata(module: str, source: Path, site_packages: Path) -> tuple[str, int]:
    if module not in SERVICES:
        raise ValueError("unexpected first-party service name")
    if not source.is_dir() or not site_packages.is_dir():
        raise ValueError("missing source or existing uv dependency environment")
    paths = sorted(source.rglob("*.py"))
    if not paths:
        raise ValueError("source-only Briareus image contains no Python code")
    evidence: list[tuple[str, str]] = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError("unexpected Python source type")
        evidence.append(
            (path.relative_to(source).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        )
    digest = hashlib.sha256(json.dumps(evidence, separators=(",", ":")).encode()).hexdigest()
    version = f"0.1.0+{module.replace('-', '')}.s{digest[:12]}"
    if not re.fullmatch(r"0\.1\.0\+[a-z]+\.s[0-9a-f]{12}", version):
        raise ValueError("noncanonical service release digest")
    metadata = site_packages / f"briareus-{version}.dist-info" / "METADATA"
    if any(site_packages.glob("briareus-*.dist-info/METADATA")):
        raise ValueError("first-party distribution unexpectedly installed in dependency layer")
    metadata.parent.mkdir(parents=True, exist_ok=False)
    metadata.write_text(f"Metadata-Version: 2.4\nName: briareus\nVersion: {version}\n")
    return version, len(paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", choices=sorted(SERVICES))
    parser.add_argument("--source-root", type=Path, default=Path("/app/src"))
    parser.add_argument(
        "--site-packages", type=Path, default=Path("/app/.venv/lib/python3.13/site-packages")
    )
    args = parser.parse_args()
    version, count = write_source_metadata(args.module, args.source_root, args.site_packages)
    print("BRIAREUS_UV_SOURCE_VERSION",args.module,version,count)

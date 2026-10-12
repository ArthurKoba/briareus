"""Exact source-file closure and per-owner Hatch wheel staging for D5.

One common ABI wheel and four independently versioned, source-derived owner
wheels. Generated artifacts live in local/ OUTSIDE Git. No Docker, DB, CI,
credentials, network access, published release, or foreign-owned source edits.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import shutil
import sys
import tomllib
from pathlib import Path
from typing import TypedDict, cast

_OWNER_ENTRY = {
    "identity": "identity.platform_runtime",
    "access": "authorization.platform_runtime",
    "platform": "projects.control_runtime",
    "resources": "projects.catalog_runtime",
}
_OWNED_ROOTS = {"common", "identity", "authorization", "projects", "agents", "teams"}
_IMPORT_DISTS: dict[str, tuple[str, ...]] = {
    "alembic": ("alembic",),
    "cryptography": ("cryptography",),
    "fastapi": ("fastapi",),
    "jwt": ("pyjwt",),
    "opentelemetry": ("opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http"),
    "pydantic": ("pydantic",),
    "pydantic_settings": ("pydantic-settings",),
    "sqlalchemy": ("sqlalchemy",),
    "starlette": ("fastapi",),
    "valkey": ("valkey",),
}
_OWNER_RUNTIME_DISTS = frozenset({"asyncpg", "uvicorn"})

_OWNER_SOURCE_SURFACES: dict[str, tuple[str, ...]] = {
    "identity": (
        "identity._service",
        "identity._account_source",
        "identity._user_delete_source",
        "identity._owner_proof_reader",
        "identity._effect_issuer",
        "identity.private_login_source",
        "identity._private_user_session",
        "identity._private_current_user",
        "identity._private_onboarding",
    ),
    "access": (
        "authorization._access_source",
        "authorization._access_proof_reader",
        "authorization._effect_issuer",
        "authorization._session_bootstrap_issuer",
        "authorization._team_access_issuer",
        "common.private_c2_operation",
    ),
    "platform": (
        "projects._control_source",
        "projects._team_source",
        "projects._control_proof_reader",
        "projects._effect_issuer",
        "projects._team_proof_reader",
        "projects._control_bff_source",
        "projects._scoped_owner_source",
    ),
    "resources": ("projects._catalog_source", "projects._catalog_lifecycle"),
}
_OWNER_ALLOWED_ROOTS: dict[str, frozenset[str]] = {
    "identity": frozenset({"common", "identity"}),
    "access": frozenset({"common", "authorization"}),
    "platform": frozenset({"common", "projects", "teams", "agents"}),
    "resources": frozenset({"common", "projects"}),
}


class SourceFile(TypedDict):
    path: str
    sha256: str


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_modules(root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted((root / "services").glob("**/*.py")):
        relative = path.relative_to(root / "services")
        if relative.parts[0] not in _OWNED_ROOTS:
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError("unsafe Python source path")
        parts = relative.with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        if name in modules:
            raise ValueError(f"ambiguous Python owner module {name}")
        modules[name] = path
    return modules


def _dynamic_model_modules(root: Path) -> dict[str, tuple[str, ...]]:
    """Parse owner_registry literal registration: NO model import execution."""
    text = (root / "services/common/owner_registry.py").read_text(encoding="utf-8")
    result: dict[str, tuple[str, ...]] = {}
    for statement in ast.parse(text).body:
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name) or statement.target.id != "_OWNER_MODELS":
            continue
        if not isinstance(statement.value, ast.Dict):
            break
        for key, pair in zip(statement.value.keys, statement.value.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise ValueError("dynamic owner key is not reviewed literal")
            if not isinstance(pair, ast.Tuple) or len(pair.elts) != 2:
                raise ValueError("dynamic owner model registration changed")
            value = pair.elts[1]
            if not isinstance(value, ast.Tuple):
                raise ValueError("dynamic owner model imports changed")
            parsed = tuple(ast.literal_eval(n) for n in value.elts)
            if any(not isinstance(item, str) for item in parsed):
                raise ValueError("unknown dynamic owner import")
            result[key.value] = parsed
    if not set(_OWNER_ENTRY) <= set(result):
        raise ValueError("missing explicit owner SQL model source registrations")
    return result


def _imports(path: Path, name: str, known: set[str]) -> tuple[set[str], set[str]]:
    """AST import closure excluding annotations guarded by TYPE_CHECKING."""
    found: set[str] = set()
    external: set[str] = set()
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]

    def accept(module: str) -> None:
        if module in known:
            found.add(module)
        elif module.split(".", 1)[0] in _OWNED_ROOTS:
            raise ValueError(f"{name} references absent owner module {module}")
        else:
            external.add(module.split(".", 1)[0])

    class Imports(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING") or (
                isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING"
            ):
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            for value in node.names:
                accept(value.name)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            root = (
                importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module or ""
            )
            if not root:
                raise ValueError(f"invalid import in {name}")
            accept(root)
            for imported in node.names:
                if f"{root}.{imported.name}" in known:
                    found.add(f"{root}.{imported.name}")

    Imports().visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return found, {
        name
        for name in external
        if name not in sys.stdlib_module_names and name not in sys.builtin_module_names
    }


def source_closure(root: Path) -> dict[str, object]:
    known = _source_modules(root)
    models = _dynamic_model_modules(root)
    closures: dict[str, set[str]] = {}
    external: dict[str, list[str]] = {}
    for owner, entry in _OWNER_ENTRY.items():
        pending = [entry, *models[owner], *_OWNER_SOURCE_SURFACES[owner]]
        selected: set[str] = set()
        third: set[str] = set()
        while pending:
            name = pending.pop()
            if name in selected:
                continue
            if name not in known:
                raise ValueError(f"{owner} dynamic source missing: {name}")
            selected.add(name)
            dependencies, third_party = _imports(known[name], name, set(known))
            third.update(third_party)
            pending.extend(dependencies - selected)
            # Native Python loads parent __init__.py before a child module.
            for parts in range(1, len(name.split("."))):
                parent = ".".join(name.split(".")[:parts])
                if parent in known:
                    pending.append(parent)
        forbidden = sorted(
            module
            for module in selected
            if module.split(".", 1)[0] not in _OWNER_ALLOWED_ROOTS[owner]
        )
        if forbidden:
            raise ValueError(f"{owner} imports foreign bounded owner source: {forbidden}")
        closures[owner] = {known[name].relative_to(root).as_posix() for name in selected}
        external[owner] = sorted(third)

    common_files = set.intersection(*(files for files in closures.values()))
    common_files = {path for path in common_files if path.startswith("services/common/")}
    common_files.add("services/common/__init__.py")
    owners: dict[str, set[str]] = {"common": common_files}
    for owner in _OWNER_ENTRY:
        if not common_files <= closures[owner]:
            raise ValueError("shared API has not been reached by all four owners")
        files = closures[owner] - common_files
        directory = root / "scripts/alembic_owners" / owner
        if not (directory / "env.py").is_file():
            raise ValueError(f"{owner} frozen migration history unavailable")
        files.update(
            path.relative_to(root).as_posix()
            for path in directory.rglob("*.py")
            if path.is_file() and not path.is_symlink()
        )
        owners[owner] = files

    inventories: dict[str, list[SourceFile]] = {
        unit: [
            {"path": path, "sha256": _digest((root / path).read_bytes())} for path in sorted(files)
        ]
        for unit, files in owners.items()
    }
    consumers: dict[str, list[str]] = {}
    for unit, entries in inventories.items():
        for item in entries:
            consumers.setdefault(item["path"], []).append(unit)
    # The SOURCE build producer is a true input to every generated wheel.
    # Its change may alter COPY/layout even when domain Python bytes do not.
    producer = "scripts/owner_packages.py"
    consumers[producer] = ["common", *_OWNER_ENTRY]
    # Explicit package boundary acceptance: code specific to one owner must
    # not leak to others, including opaque dynamic SQL registration.
    for path in consumers:
        if path.startswith("scripts/alembic_owners/"):
            unit = path.split("/")[2]
            if consumers[path] != [unit]:
                raise ValueError(f"cross-owner Alembic resource: {path}")
    return {
        "schema": "briareus-owner-source-closure-v1",
        "producer_sha256": _digest((root / producer).read_bytes()),
        "build_input_paths": [producer],
        "entrypoints": _OWNER_ENTRY,
        "private_source_surfaces": _OWNER_SOURCE_SURFACES,
        "dynamic_owner_model_modules": models,
        "third_party_import_roots": external,
        "units": inventories,
        "consumer_impact": consumers,
    }


def _owner_third_party(root: Path, unit: str, files: list[SourceFile]) -> list[str]:
    all_modules = _source_modules(root)
    roots: set[str] = set()
    for item in files:
        path = item["path"]
        if not path.startswith("services/"):
            continue
        relative = Path(path).relative_to("services")
        parts = relative.with_suffix("").parts
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        _, imports = _imports(root / path, module, set(all_modules))
        roots.update(imports)
    expected: set[str] = set()
    for imported in roots:
        if imported not in _IMPORT_DISTS:
            raise ValueError(f"{unit} depends on unmapped third-party module {imported}")
        expected.update(_IMPORT_DISTS[imported])
    if unit != "common":
        expected.update(_OWNER_RUNTIME_DISTS)
    source = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = source["project"]["dependencies"]
    pinned: dict[str, str] = {}
    for requirement in dependencies:
        if not isinstance(requirement, str):
            raise ValueError("invalid root requirement")
        base = requirement.split("[", 1)[0]
        for operator in ("<", ">", "=", "!", "~"):
            base = base.split(operator, 1)[0]
        key = base.strip().lower().replace("_", "-")
        if key in pinned:
            raise ValueError(f"ambiguous requirement {key}")
        pinned[key] = requirement
    if expected - set(pinned):
        raise ValueError(f"{unit} misses root pinned distributions {expected - set(pinned)}")
    return [pinned[name] for name in sorted(expected)]


def _stage(root: Path, destination: Path, graph: dict[str, object]) -> None:
    if destination.exists():
        raise FileExistsError("source package staging is immutable")
    inventories = cast(dict[str, list[SourceFile]], graph["units"])
    destination.mkdir(parents=True)
    producer_sha = str(graph["producer_sha256"])
    common_sha = _digest(
        json.dumps(inventories["common"], sort_keys=True).encode() + producer_sha.encode()
    )
    common_version = f"0.1.0+pkg.s{common_sha[:16]}"
    for unit, files in inventories.items():
        folder = destination / unit
        folder.mkdir()
        source_sha = _digest(json.dumps(files, sort_keys=True).encode() + producer_sha.encode())
        version = common_version if unit == "common" else f"0.1.0+pkg.s{source_sha[:16]}"
        name = "briareus-owner-common" if unit == "common" else f"briareus-owner-{unit}"
        for item in files:
            original = root / item["path"]
            path = Path(item["path"])
            if path.parts[0] == "services":
                inside = Path(*path.parts[1:])
            else:
                if path.parts[:2] != ("scripts", "alembic_owners"):
                    raise ValueError("owner package path outside reviewed source")
                inside = Path("common/alembic_owners", *path.parts[2:])
            final = folder / "src" / inside
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, final)
        requires = _owner_third_party(root, unit, files)
        if unit != "common":
            requires.append(f"briareus-owner-common=={common_version}")
        lines = [
            "[project]",
            f'name = "{name}"',
            f'version = "{version}"',
            'requires-python = ">=3.13"',
            f"dependencies = {json.dumps(requires)}",
            "[build-system]",
            'requires = ["hatchling"]',
            'build-backend = "hatchling.build"',
            "[tool.hatch.build.targets.wheel]",
            'only-include = ["src"]',
            "[tool.hatch.build.targets.wheel.sources]",
            '"src" = ""',
        ]
        (folder / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (folder / "release_receipt.json").write_text(
            json.dumps(
                {
                    "distribution": name,
                    "version": version,
                    "source_sha256": source_sha,
                    "source_files": files,
                    "dependencies": requires,
                    "common_dependency": common_version if unit != "common" else None,
                    "published_git_tree": None,
                    "review_state": "SOURCE_ONLY_UNPUBLISHED",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    (destination / "owner_source_graph.json").write_text(
        json.dumps(graph, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--stage", type=Path)
    args = parser.parse_args()
    graph = source_closure(args.root.resolve())
    if args.stage is not None:
        _stage(args.root.resolve(), args.stage.resolve(), graph)
    inventories = cast(dict[str, list[SourceFile]], graph["units"])
    impact = cast(dict[str, list[str]], graph["consumer_impact"])
    print(
        json.dumps(
            {
                "schema": graph["schema"],
                "paths_per_unit": {key: len(items) for key, items in inventories.items()},
                "owner_migrations": [
                    path for path in impact if path.startswith("scripts/alembic_owners/")
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

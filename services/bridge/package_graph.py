"""R18-PKG reproducible, conservative Python runtime import-closure authority.

Build-time source auditor, NOT an MCP tool/OS service. D5 independently
consumes the manifest for Docker COPY, per-service uv installs, and native
Coolify watch generation. Unknown dynamic imports are reported explicitly,
not quietly omitted. Imports nested in runtime functions are included, while
TYPE_CHECKING imports are not executed. No live service is imported here.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

_SERVICE_ENTRYPOINTS: dict[str, tuple[str, ...]] = {
    "gateway": ("bridge.server",),
    "files": ("modules.files.runtime",),
    "terminal": ("modules.terminal.runtime",),
    "web": ("modules.web.runtime",),
    # One private ASGI shell. Both source-owned GitHub/GitLab registries are
    # bundled for a future C2-authenticated composition but not mounted.
    "svc": ("modules.svc.runtime",),
    "infrastructure": ("modules.observability.runtime",),
    "reverse": ("modules.analysis.runtime",),
}
_VALID_RUNTIME = frozenset(_SERVICE_ENTRYPOINTS)
_OWNER_PACKAGE: dict[str, str] = {
    "gateway": "bridge",
    "files": "modules.files",
    "terminal": "modules.terminal",
    "web": "modules.web",
    "svc": "modules.svc;modules.github;modules.gitlab",
    "infrastructure": "modules.observability",
    "reverse": "modules.analysis",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_name(path: Path, source: Path) -> str:
    parts = list(path.relative_to(source).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _type_only(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"
    )


@dataclass(frozen=True)
class Unit:
    name: str
    entrypoints: tuple[str, ...]
    source_paths: tuple[str, ...]
    runtime_package_paths: tuple[str, ...]
    shared_source_paths: tuple[str, ...]
    transitive_foreign_source_paths: tuple[str, ...]
    external_import_roots: tuple[str, ...]
    dynamic_imports: tuple[str, ...]
    hash_sha256: str


class _Imports(ast.NodeVisitor):
    def __init__(
        self, module: str, *, is_package: bool, lazy_exports: dict[str, dict[str, str]]
    ) -> None:
        self.module = module
        self.base = module if is_package else module.rpartition(".")[0]
        self.lazy_exports = lazy_exports
        self._function: str | None = None
        self.names: set[str] = set()
        self.dynamic: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        previous = self._function
        self._function = node.name
        self.generic_visit(node)
        self._function = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        previous = self._function
        self._function = node.name
        self.generic_visit(node)
        self._function = previous

    def visit_If(self, node: ast.If) -> None:
        if not _type_only(node.test):
            for item in node.body:
                self.visit(item)
        for item in node.orelse:
            self.visit(item)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        prefix = self.base.split(".")
        if node.level:
            count = node.level - 1
            if count >= len(prefix):
                self.dynamic.add(f"{self.module}:invalid_relative_import:{node.lineno}")
                return
            prefix = prefix[: len(prefix) - count] if count else prefix
            base = ".".join((*prefix, *(node.module.split(".") if node.module else ())))
        else:
            base = node.module or ""
        if base:
            self.names.add(base)
        for item in node.names:
            if item.name == "*":
                self.dynamic.add(f"{self.module}:star_import:{base}:{node.lineno}")
                continue
            self.names.add(f"{base}.{item.name}")
            # Both accepted Runtime and A16 Backend packages implement
            # explicit literal lazy export tables. Only the IMPORTED symbol
            # loads its owner module, not every Project/Catalog model.
            mapping = self.lazy_exports.get(base)
            if mapping is not None:
                mapped = mapping.get(item.name)
                if mapped is None:
                    self.dynamic.add(f"{self.module}:unmapped_lazy_symbol:{base}.{item.name}")
                else:
                    self.names.add(mapped)

    def visit_Call(self, node: ast.Call) -> None:
        name = ast.unparse(node.func)
        if name in {"import_module", "importlib.import_module", "__import__"}:
            if (
                self.module in self.lazy_exports
                and self._function == "__getattr__"
                and name == "import_module"
            ):
                # The accepted __getattr__ implementations consult bounded
                # literal module maps, resolved at the importing call-site.
                pass
            elif (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                item = node.args[0].value
                if item.startswith(".") and len(node.args) > 1:
                    self.dynamic.add(f"{self.module}:relative_dynamic_import:{node.lineno}")
                elif not item.startswith("."):
                    self.names.add(item)
            else:
                self.dynamic.add(f"{self.module}:nonliteral_dynamic_import:{node.lineno}")
        self.generic_visit(node)


def _lazy_exports(source: Path) -> dict[str, dict[str, str]]:
    """Resolve only signed-source literal Runtime and A16 Project exports.

    A17 may change these interfaces: an unknown dynamic module must remain
    unresolved rather than inventing an import graph or copying all ORMs.
    """
    result: dict[str, dict[str, str]] = {}
    specifications = (
        ("modules.project_runtime", "modules/project_runtime/__init__.py", "_EXPORT_MODULE"),
        ("projects", "projects/__init__.py", "_OWNER_PUBLIC_EXPORTS"),
    )
    for module_name, relative, variable in specifications:
        path = source / relative
        if not path.is_file():
            if module_name == "modules.project_runtime":
                raise ValueError("Runtime Project public contract is missing")
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        values = [
            node.value
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == variable
        ]
        if not values:
            if module_name == "modules.project_runtime":
                raise ValueError("Runtime typed lazy exports missing")
            continue  # pre-A16 eager Project namespace: analyze imports normally
        if len(values) != 1 or values[0] is None:
            raise ValueError(f"ambiguous dynamic exports in {module_name}")
        raw = ast.literal_eval(values[0])
        if not isinstance(raw, dict) or not raw:
            raise ValueError(f"unbounded public export map in {module_name}")
        names = [
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            )
        ]
        if len(names) != 1 or set(ast.literal_eval(names[0])) != set(raw):
            raise ValueError(f"export ABI mismatch in {module_name}")
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__getattr__"
            for node in tree.body
        ):
            raise ValueError(f"export source missing verified lazy resolver in {module_name}")
        mapped: dict[str, str] = {}
        for public, destination in raw.items():
            if not isinstance(public, str) or not public.isidentifier():
                raise ValueError("invalid literal public symbol")
            if module_name == "projects":
                if not (
                    isinstance(destination, tuple)
                    and len(destination) == 2
                    and all(isinstance(item, str) for item in destination)
                    and destination[1] == public
                ):
                    raise ValueError("A16 Project owner symbol binding is not literal")
                module_path = destination[0]
            else:
                if not isinstance(destination, str):
                    raise ValueError("Runtime typed public export is not literal")
                module_path = f"{module_name}.{destination}"
            if (
                not module_path.startswith(module_name + ".")
                or not (source / (module_path.replace(".", "/") + ".py")).is_file()
            ):
                raise ValueError(f"dynamic owner export target missing: {module_path}")
            mapped[public] = module_path
        result[module_name] = mapped
    return result


def _runtime_owner_ledger_candidates(source: Path) -> dict[str, str]:
    """Report candidates, NOT a resolved per-service DB/runtime dependency."""
    path = source / "common/owner_transactions.py"
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_OWNED_LEDGERS"
            and node.value is not None
        ):
            candidates = ast.literal_eval(node.value)
            if not isinstance(candidates, dict) or not all(
                isinstance(owner, str) and isinstance(module, str)
                for owner, module in candidates.items()
            ):
                raise ValueError("unbounded Backend owner-ledger registry")
            return candidates
    return {}


def _svc_source_handlers(source: Path) -> dict[str, dict[str, str]]:
    """Verify both source registries remain packaged, without importing them."""
    catalog = source / "modules/svc/composition.py"
    if not catalog.is_file():
        raise ValueError("SVC selected app needs its owned source selector")
    tree = ast.parse(catalog.read_text(), filename=str(catalog))
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "SVC_SOURCE_HANDLERS"
        and node.value is not None
    ]
    if len(values) != 1:
        raise ValueError("SVC provider source map must be literal and unique")
    names = ast.literal_eval(values[0])
    if not isinstance(names, dict) or set(names) != {"github", "gitlab"}:
        raise ValueError("SVC GitHub and GitLab private source handlers required")
    source_paths: dict[str, dict[str, str]] = {}
    for provider, binding in names.items():
        if (
            not isinstance(binding, tuple)
            or len(binding) != 2
            or binding != (f"modules.{provider}.runtime", "mcp")
        ):
            raise ValueError("SVC provider binding differs from reviewed owner modules")
        module_path = source / (binding[0].replace(".", "/") + ".py")
        if not module_path.is_file():
            raise ValueError("SVC provider source was removed")
        module_ast = ast.parse(module_path.read_text(), filename=str(module_path))
        if not any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(name, ast.Name) and name.id == "mcp"
                for target in node.targets
                for name in ast.walk(target)
            )
            for node in module_ast.body
        ):
            raise ValueError("SVC provider existing handler export disappeared")
        source_paths[provider] = {"module": binding[0], "handler": binding[1]}
    return source_paths


class PythonImportGraph:
    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root.resolve()
        self.module_files = {
            _module_name(path, self.source_root): path
            for path in sorted(self.source_root.rglob("*.py"))
            if not any(item in path.parts for item in (".venv", "__pycache__"))
        }
        self.lazy_exports = _lazy_exports(self.source_root)
        self._cache: dict[str, _Imports] = {}

    def _ancestors(self, module: str) -> set[str]:
        parts = module.split(".")
        return {
            ".".join(parts[:i])
            for i in range(1, len(parts) + 1)
            if ".".join(parts[:i]) in self.module_files
        }

    def _visit(self, module: str) -> _Imports:
        if module not in self._cache:
            source = self.module_files[module]
            parsed = ast.parse(source.read_text(), filename=str(source))
            visitor = _Imports(
                module,
                is_package=source.name == "__init__.py",
                lazy_exports=self.lazy_exports,
            )
            visitor.visit(parsed)
            self._cache[module] = visitor
        return self._cache[module]

    def unit(self, name: str) -> Unit:
        if name not in _VALID_RUNTIME:
            raise ValueError(f"unknown owner service {name!r}")
        entrypoints = _SERVICE_ENTRYPOINTS[name]
        # Package ALL service-owned source, including optional/lazy native
        # effects, not just startup AST imports. Gateway is exceptional: its
        # retired legacy registry is source-preserved but deliberately not
        # installed while signed public C2 transport remains unaccepted.
        packaged_roots = (
            entrypoints
            if name == "gateway"
            else tuple(
                sorted(
                    module
                    for module in self.module_files
                    if any(
                        module == prefix or module.startswith(prefix + ".")
                        for prefix in _OWNER_PACKAGE[name].split(";")
                    )
                )
            )
        )
        # D5 first-party Docker CMD executes `python -m common.asgi`, whose
        # `ASGI_APP` is a per-image string, not an import statement. Include
        # both the common runner and the exact selected app as source inputs.
        pending = deque((*packaged_roots, "common.asgi"))
        selected: set[str] = set()
        dynamic: set[str] = set()
        external: set[str] = set()
        while pending:
            current = pending.popleft()
            if current in selected:
                continue
            if current not in self.module_files:
                top = current.split(".")[0]
                if top not in sys.stdlib_module_names and top not in sys.builtin_module_names:
                    external.add(top)
                continue
            for ancestor in self._ancestors(current):
                if ancestor not in selected:
                    pending.append(ancestor)
            selected.add(current)
            imports = self._visit(current)
            dynamic.update(imports.dynamic)
            for item in imports.names:
                if item in self.module_files:
                    if item not in selected:
                        pending.append(item)
                elif item.split(".")[0] not in {
                    "bridge",
                    "modules",
                    "common",
                    "authorization",
                    "identity",
                    "teams",
                    "projects",
                    "agents",
                }:
                    top = item.split(".")[0]
                    if top not in sys.stdlib_module_names and top not in sys.builtin_module_names:
                        external.add(top)
                elif any(m.startswith(item + ".") for m in self.module_files):
                    # 'from <namespace> import <symbol>' may resolve a child
                    # module; do not pretend the name is external.
                    for ancestor in self._ancestors(item):
                        if ancestor not in selected:
                            pending.append(ancestor)
                elif item.count(".") == 0:
                    # No local module with that first-party root.
                    dynamic.add(f"{current}:unresolved_first_party_root:{item}")
        paths = tuple(
            sorted(
                self.module_files[n].relative_to(self.source_root.parent).as_posix()
                for n in selected
            )
        )
        owned = tuple(
            x
            for x in paths
            if x.startswith(
                tuple(
                    "services/" + r.replace(".", "/") + "/" for r in _OWNER_PACKAGE[name].split(";")
                )
            )
        )
        shared = tuple(
            x
            for x in paths
            if x.startswith(
                (
                    "services/common/",
                    "services/modules/project_runtime/",
                    "services/modules/workspace_compat/",
                )
            )
        )
        foreign = tuple(
            x
            for x in paths
            if x not in owned and x not in shared and not x.endswith("/modules/__init__.py")
        )
        digest = hashlib.sha256(
            json.dumps(
                [(p, _sha(self.source_root.parent / p)) for p in paths], separators=(",", ":")
            ).encode()
        ).hexdigest()
        return Unit(
            name=name,
            entrypoints=entrypoints,
            source_paths=paths,
            runtime_package_paths=owned,
            shared_source_paths=shared,
            transitive_foreign_source_paths=foreign,
            external_import_roots=tuple(sorted(external)),
            dynamic_imports=tuple(sorted(dynamic)),
            hash_sha256=digest,
        )


def release_manifest(repo: Path) -> dict[str, object]:
    graph = PythonImportGraph(repo / "services")
    units = {name: graph.unit(name) for name in _SERVICE_ENTRYPOINTS}
    imports: dict[str, list[str]] = {}
    for name, unit in units.items():
        for path in unit.source_paths:
            imports.setdefault(path, []).append(name)
    result: dict[str, object] = {
        "schema": "runtime-selective-python-source-graph-v1",
        "source_tool": "services/bridge/package_graph.py",
        "source_tool_sha256": _sha(repo / "services/bridge/package_graph.py"),
        "evidence": "AST_AND_EXPLICIT_LAZY_EXPORTS_ONLY_NO_INSTALLED_DOCKER_OR_C2",
        "release_units": {
            name: {
                "entrypoints": list(unit.entrypoints),
                "startup_loader": "common.asgi",
                "expected_asgi_app": f"{unit.entrypoints[0]}:app",
                "source_paths": list(unit.source_paths),
                "owned_paths": list(unit.runtime_package_paths),
                "shared_paths": list(unit.shared_source_paths),
                "cross_owner_imports": list(unit.transitive_foreign_source_paths),
                "external_import_roots": list(unit.external_import_roots),
                "dynamic_imports_to_review": list(unit.dynamic_imports),
                "dynamic_owner_ledger_candidates_not_included": (
                    _runtime_owner_ledger_candidates(repo / "services")
                    if any(
                        entry.startswith("common.owner_transactions:nonliteral_dynamic_import")
                        for entry in unit.dynamic_imports
                    )
                    else {}
                ),
                "source_content_sha256": unit.hash_sha256,
                "public_transport_accepted": False,
                "has_accepted_unified_entrypoint": True,
                "source_only_transport_pending": name == "svc",
                "source_provider_handlers": (
                    _svc_source_handlers(repo / "services") if name == "svc" else {}
                ),
                "owner_alembic_histories": [],
                "excluded_unaccepted_source": [
                    "services/bridge/legacy_mcp.py",
                    "services/bridge/package_graph.py",
                ]
                if name == "gateway"
                else [],
            }
            for name, unit in units.items()
        },
        "source_reverse_consumers": {k: sorted(v) for k, v in sorted(imports.items())},
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = release_manifest(args.repo.resolve())
    rendered = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(rendered)
    else:
        args.output.write_text(rendered)
    units = manifest["release_units"]
    if not isinstance(units, dict):
        raise ValueError("invalid unit map")
    for name, item in units.items():
        if not isinstance(item, dict):
            continue
        print(
            name,
            "owned",
            len(item["owned_paths"]),
            "shared",
            len(item["shared_paths"]),
            "foreign",
            len(item["cross_owner_imports"]),
            "dynamic",
            len(item["dynamic_imports_to_review"]),
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()

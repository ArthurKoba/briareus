from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DevExtension:
    id: str
    path: str


class BrowserExtensionRegistry:
    """Persistent allowlist of unpacked development extensions."""

    def __init__(self, state_file: Path, workspace_root: Path) -> None:
        self.state_file = state_file.resolve(strict=False)
        self.workspace_root = workspace_root.resolve(strict=False)
        self._extensions: dict[str, DevExtension] = {}
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        items = payload.get("extensions") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            extension_id = item.get("id")
            path_value = item.get("path")
            if not isinstance(extension_id, str) or not isinstance(path_value, str):
                continue
            path = Path(path_value).resolve(strict=False)
            if not path.is_relative_to(self.workspace_root):
                continue
            self._extensions[extension_id] = DevExtension(extension_id, str(path))

    def _persist(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        payload = {
            "extensions": [
                {"id": item.id, "path": item.path}
                for item in sorted(self._extensions.values(), key=lambda item: item.id)
            ]
        }
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.state_file)

    def record(self, extension_id: str, path_value: str) -> None:
        extension_id = extension_id.strip()
        path = Path(path_value).resolve(strict=False)
        if not extension_id:
            raise ValueError("extension id is required")
        if not path.is_relative_to(self.workspace_root):
            raise ValueError("development extension path must stay inside workspace")
        self._extensions[extension_id] = DevExtension(extension_id, str(path))
        self._persist()

    def remove(self, extension_id: str) -> None:
        if self._extensions.pop(extension_id.strip(), None) is not None:
            self._persist()

    def load_paths(self) -> tuple[str, ...]:
        return tuple(
            item.path
            for item in sorted(self._extensions.values(), key=lambda item: item.id)
            if Path(item.path).is_dir()
        )

    def items(self) -> tuple[DevExtension, ...]:
        return tuple(sorted(self._extensions.values(), key=lambda item: item.id))

    def clear(self) -> None:
        self._extensions.clear()
        self.state_file.unlink(missing_ok=True)

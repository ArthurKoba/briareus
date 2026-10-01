from __future__ import annotations

import json
from pathlib import Path

from common.models import JsonObject, JsonValue

from .file_store import FileStore
from .workspace_store import WorkspaceFileStore


def _destination_name(name: str, sha256: str, used: set[str]) -> str:
    clean = Path(name).name.strip() or f"file-{sha256[:12]}"
    candidate = clean
    if candidate not in used:
        used.add(candidate)
        return candidate
    stem = Path(clean).stem
    suffix = Path(clean).suffix
    candidate = f"{stem}__{sha256[:12]}{suffix}"
    index = 2
    while candidate in used:
        candidate = f"{stem}__{sha256[:12]}_{index}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def migrate_legacy_store(
    store: FileStore,
    workspace: WorkspaceFileStore,
    *,
    destination_dir: str = "projects/migrated-files",
    overwrite: bool = True,
) -> JsonObject:
    listing = store.list(offset=0, limit=1000, sort_by="created_at", sort_order="asc")
    raw_items = listing.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    used: set[str] = set()
    migrated: list[JsonValue] = []

    workspace.mkdir(destination_dir)
    for raw in items:
        if not isinstance(raw, dict):
            continue
        file_id = str(raw.get("file_id") or "")
        sha256 = str(raw.get("sha256") or "")
        if not file_id or not sha256:
            continue
        info = store.info(file_id)
        name = str(info.get("name") or "")
        destination_name = _destination_name(name, sha256, used)
        destination = f"{destination_dir.rstrip('/')}/{destination_name}"
        source = store.path_for(file_id)
        placed = workspace.place_file(
            source,
            destination,
            overwrite=overwrite,
            consume=False,
        )
        actual_sha = workspace.sha256(destination)
        if actual_sha != sha256:
            raise RuntimeError(
                f"migration checksum mismatch for {file_id}: "
                f"expected {sha256}, found {actual_sha}"
            )
        raw_size = info.get("size_bytes")
        size_bytes = raw_size if isinstance(raw_size, int) else 0
        migrated.append(
            {
                "old_file_id": file_id,
                "sha256": sha256,
                "name": name,
                "mime_type": str(info.get("mime_type") or ""),
                "size_bytes": size_bytes,
                "created_at": str(info.get("created_at") or ""),
                "aliases": info.get("aliases") if isinstance(info.get("aliases"), list) else [],
                "references": (
                    info.get("references")
                    if isinstance(info.get("references"), list)
                    else []
                ),
                "collections": (
                    info.get("collections")
                    if isinstance(info.get("collections"), list)
                    else []
                ),
                "workspace_path": str(placed.get("path") or destination),
            }
        )

    manifest = {
        "source": "legacy-files-cas",
        "destination_dir": destination_dir,
        "file_count": len(migrated),
        "files": migrated,
    }
    manifest_path = f"{destination_dir.rstrip('/')}/migration-manifest.json"
    workspace.write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        overwrite=True,
    )
    return {
        "migrated": len(migrated),
        "expected": len(items),
        "destination_dir": destination_dir,
        "manifest_path": manifest_path,
        "all_verified": len(migrated) == len(items),
    }

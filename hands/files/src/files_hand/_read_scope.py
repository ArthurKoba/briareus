"""Compact Files resource selector agreed with Authorization V2.

A deterministic selector is NOT a verified resource, grant or signed caller.
This module performs no owner lookup, filesystem access or MCP registration.
It names the existing single Files namespace per Project, preserving long
canonical paths without putting their text into Authorization's 512-char ID.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from modules.files.a6_signed import path_fingerprint

from ._read_adapter import FilesMcpReadUnavailable, FilesReadArguments

FILES_READ_TOOL = "read_file"
FILES_READ_ACTION = "files.read"
FILES_READ_RESOURCE_KIND = "workspace_path"
_SELECTOR_PREFIX = "project-path-v1:"


@dataclass(frozen=True, slots=True)
class FilesReadSelector:
    """Accepted naming contract, requiring independent owner proof before use.

    project_uuid comes from verified server context, not Files tool JSON.
    Its namespace is the current ProjectRootRegistry (<base>/<Project UUID>).
    Storage incarnation/revision and current membership remain separate
    owner checks; identical selectors do not carry those facts.
    """

    project_uuid: UUID
    request: FilesReadArguments

    def __post_init__(self) -> None:
        if (
            not isinstance(self.project_uuid, UUID)
            or self.project_uuid.version != 4
            or not isinstance(self.request, FilesReadArguments)
        ):
            raise FilesMcpReadUnavailable("FILES_READ_SELECTOR_INVALID")

    @property
    def resource_id(self) -> str:
        # Reuse A6's accepted domain-separated UTF-8 canonical path digest.
        # No truncation, URL decoding, case folding or implicit normalization.
        return f"{_SELECTOR_PREFIX}{self.project_uuid}:{path_fingerprint(self.request.path)}"

    def decision_resource(self) -> dict[str, str]:
        return {"kind": FILES_READ_RESOURCE_KIND, "id": self.resource_id}

    @property
    def effect_key(self) -> str:
        """Exact Backend V2 resource-key bytes, still not an owner proof."""
        return json.dumps(
            ["files", FILES_READ_TOOL, FILES_READ_RESOURCE_KIND, self.resource_id],
            ensure_ascii=True,
            separators=(",", ":"),
        )

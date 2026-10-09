"""Produce OFFLINE draft OpenAPI, never a live endpoint or fake identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from presentation.platform_api import VerifiedCallerResolver, build_unmounted_platform_router

from authorization._idempotency import IdempotentCommandExecutor
from authorization._platform_application import PlatformApplication
from authorization._platform_auth import PlatformAdminBearerAuth
from authorization._project_sessions import ProjectSessionService
from identity._service import IdentityService
from projects._resource_service import ResourceService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output: Path = args.output.resolve()
    repo_root = Path(__file__).resolve().parents[1]
    if output.is_relative_to(repo_root):
        raise SystemExit("draft schema output must be outside Git source")
    app = FastAPI(title="MCP Bridge Platform C1-B2-DRAFT", version="0.1.0")
    schema_only = object()
    app.include_router(
        build_unmounted_platform_router(
            application=cast(PlatformApplication, schema_only),
            identity=cast(IdentityService, schema_only),
            sessions=cast(ProjectSessionService, schema_only),
            commands=cast(IdempotentCommandExecutor, schema_only),
            principal_resolver=cast(VerifiedCallerResolver, schema_only),
            resources=cast(ResourceService, schema_only),
            local_auth=cast(PlatformAdminBearerAuth, schema_only),
        )
    )
    schema = app.openapi()
    schema["info"]["description"] = "Offline source draft; C1-B2/C2 public activation blocked."
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, sort_keys=True, indent=2) + "\n")
    print("OpenAPI paths:", len(schema["paths"]))
    print("OpenAPI DTO schemas:", len(schema["components"]["schemas"]))
    print("Artifact:", output)


if __name__ == "__main__":
    main()

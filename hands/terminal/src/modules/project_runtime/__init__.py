"""Typed Project runtime public interface without eager provider imports.

Importing `modules.project_runtime` cannot pull Files, Terminal, Reverse,
Catalog, provider SDKs or unused Team resource selectors into another App.
Historical public symbols remain exact; access loads ONLY their owning
interface module. Service-owned handlers are registered in their entrypoints.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .authorization import (
        ProjectAccessDenied,
        ProjectAccessPort,
        ProjectAction,
        ProjectInvocation,
        ProjectOperationScope,
        ProjectPermit,
        ProjectRuntimeAuthority,
        canonical_request_fingerprint,
    )
    from .integrations import (
        ProjectIntegrationError,
        ProjectIntegrationPort,
        ProjectIntegrationRef,
        ProjectIntegrationSelector,
    )
    from .resource_query import ResourceQuery, ResourceSelectionError
    from .resource_scope import EffectiveResourceScope, ProjectResourceScopeError
    from .variables import ProjectVariableError, ProjectVariableRef, ProjectVariableSelector
    from .workspace_roots import ProjectFileError, ProjectRootRegistry

_EXPORT_MODULE: dict[str, str] = {
    "EffectiveResourceScope": "resource_scope",
    "ProjectAccessDenied": "authorization",
    "ProjectAccessPort": "authorization",
    "ProjectAction": "authorization",
    "ProjectFileError": "workspace_roots",
    "ProjectIntegrationError": "integrations",
    "ProjectIntegrationPort": "integrations",
    "ProjectIntegrationRef": "integrations",
    "ProjectIntegrationSelector": "integrations",
    "ProjectInvocation": "authorization",
    "ProjectOperationScope": "authorization",
    "ProjectPermit": "authorization",
    "ProjectResourceScopeError": "resource_scope",
    "ProjectRootRegistry": "workspace_roots",
    "ProjectRuntimeAuthority": "authorization",
    "ProjectVariableError": "variables",
    "ProjectVariableRef": "variables",
    "ProjectVariableSelector": "variables",
    "ResourceQuery": "resource_query",
    "ResourceSelectionError": "resource_query",
    "canonical_request_fingerprint": "authorization",
}


def __getattr__(name: str) -> object:
    target = _EXPORT_MODULE.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{target}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORT_MODULE))


__all__ = [
    "EffectiveResourceScope",
    "ProjectAccessDenied",
    "ProjectAccessPort",
    "ProjectAction",
    "ProjectFileError",
    "ProjectIntegrationError",
    "ProjectIntegrationPort",
    "ProjectIntegrationRef",
    "ProjectIntegrationSelector",
    "ProjectInvocation",
    "ProjectOperationScope",
    "ProjectPermit",
    "ProjectResourceScopeError",
    "ProjectRootRegistry",
    "ProjectRuntimeAuthority",
    "ProjectVariableError",
    "ProjectVariableRef",
    "ProjectVariableSelector",
    "ResourceQuery",
    "ResourceSelectionError",
    "canonical_request_fingerprint",
]

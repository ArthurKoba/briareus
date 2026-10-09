"""Briareus Project-scoped authorization/resource boundaries; no MCP mounts."""

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

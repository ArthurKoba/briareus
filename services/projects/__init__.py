"""Project/Resource owner namespace: no eager cross-owner domain import.

Control owns Project/InvalidOwnership; Catalog owns resource vocabulary.
Loading one owner-specific module never forces the other's domain/source.
Public names remain import-compatible with the accepted source release.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_OWNER_PUBLIC_EXPORTS: dict[str, tuple[str, str]] = {
    "Project": ("projects._domain", "Project"),
    "InvalidOwnership": ("projects._domain", "InvalidOwnership"),
    "AmbiguousResource": ("projects._resource_domain", "AmbiguousResource"),
    "EffectiveResource": ("projects._resource_domain", "EffectiveResource"),
    "OwnerScope": ("projects._resource_domain", "OwnerScope"),
    "ResourceKind": ("projects._resource_domain", "ResourceKind"),
    "ResourceOwner": ("projects._resource_domain", "ResourceOwner"),
    "ResourceScope": ("projects._resource_domain", "ResourceScope"),
}
if TYPE_CHECKING:
    from ._domain import InvalidOwnership, Project
    from ._resource_domain import (
        AmbiguousResource,
        EffectiveResource,
        OwnerScope,
        ResourceKind,
        ResourceOwner,
        ResourceScope,
    )

__all__ = [
    "AmbiguousResource",
    "EffectiveResource",
    "InvalidOwnership",
    "OwnerScope",
    "Project",
    "ResourceKind",
    "ResourceOwner",
    "ResourceScope",
]


def __getattr__(name: str) -> object:
    """Resolve public name from its *own* bounded context only on use."""
    source = _OWNER_PUBLIC_EXPORTS.get(name)
    if source is None:
        raise AttributeError(name)
    module, attr = source
    return getattr(import_module(module), attr)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

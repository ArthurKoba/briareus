"""Unmounted Briareus A6 Project runtime composition, no legacy adapters.

Each protected operation requires an authenticated Project+AgentSession UUIDv4,
separate service identity and per-effect signed Backend decision. No public
FastMCP mounts, local RuntimeLeaseRegistry, R6 process reaper, legacy quota,
root fallback or environment-based privilege is created by this component.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .a4_source import (
    A4EffectiveResourcePort,
    A4ProjectProjectionPort,
    A4ProjectVerifier,
    A4ResourceAdapter,
)
from .a5_authorization import A5AuthenticatedServicePort, A5SourceAuthorization
from .a6_provider import (
    A6ProviderPeerPort,
    A6ProviderReadSource,
    A6SignedProviderPort,
)
from .a6_runtime import (
    A6RuntimePeerPort,
    A6RuntimeSignedSource,
    A6SignedRuntimePort,
)
from .a9_signed_lease import A9PinnedRuntimeKeyPort
from .authorization import ProjectAccessPort, ProjectRuntimeAuthority
from .backend_access import CurrentCallerVerifier
from .integrations import ProjectIntegrationSelector
from .variables import ProjectVariableSelector
from .workspace_roots import ProjectRootRegistry

if TYPE_CHECKING:
    from bridge.project_dispatch import ProjectAuthorizationReadinessPort, ProjectGatewayDispatch
    from modules.analysis.a6_native import (
        A6NativeInventoryPort,
        A6ReversePeerPort,
        A6SignedNativeClient,
        A6SignedNativePort,
    )
    from modules.files.a6_signed import (
        SignedFilesBackendPort,
        TrustedFilesStoragePort,
        VerifiedFilesPeerPort,
    )
    from modules.files.project_explorer import ProjectFileExplorer
    from modules.files.project_files import ProjectFilesService
    from modules.terminal.project_isolation import ProjectIsolationInspector
    from modules.terminal.project_terminal import ProjectTerminalRuntime
    from modules.web.project_runtime import ProjectWebRuntime


@dataclass(slots=True)
class PrivateProjectRuntime:
    """Verified-source Project gateway/Files/Terminal and resource composition.

    This object is not a server-side proof or transport. Source ports cannot
    be derived from client-supplied MCP args, JSON receipts or Session UUID.
    Absent C1-B2/C2 verified service/OS ports fail before any external effect.
    """

    roots: ProjectRootRegistry
    access: ProjectAccessPort | None = None
    resource_source: A4EffectiveResourcePort | None = None
    files_peer: VerifiedFilesPeerPort | None = None
    files_backend: SignedFilesBackendPort | None = None
    files_observer: TrustedFilesStoragePort | None = None
    runtime_peer: A6RuntimePeerPort | None = None
    runtime_backend: A6SignedRuntimePort | None = None
    runtime_pinned_key: A9PinnedRuntimeKeyPort | None = None
    provider_peer: A6ProviderPeerPort | None = None
    provider_backend: A6SignedProviderPort | None = None
    native_peer: A6ReversePeerPort | None = None
    native_backend: A6SignedNativePort | None = None
    native_inventory: A6NativeInventoryPort | None = None
    authority: ProjectRuntimeAuthority = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.roots, ProjectRootRegistry):
            raise ValueError("A6 Project root registry must be explicit")
        self.authority = ProjectRuntimeAuthority(self.access)

    @classmethod
    def from_accepted_a6_sources(
        cls,
        *,
        roots: ProjectRootRegistry,
        authenticated_service: A5AuthenticatedServicePort,
        caller_verifier: CurrentCallerVerifier,
        project_source: A4ProjectProjectionPort,
        files_peer: VerifiedFilesPeerPort | None = None,
        files_backend: SignedFilesBackendPort | None = None,
        files_observer: TrustedFilesStoragePort | None = None,
        runtime_peer: A6RuntimePeerPort | None = None,
        runtime_backend: A6SignedRuntimePort | None = None,
        runtime_pinned_key: A9PinnedRuntimeKeyPort | None = None,
        provider_peer: A6ProviderPeerPort | None = None,
        provider_backend: A6SignedProviderPort | None = None,
        native_peer: A6ReversePeerPort | None = None,
        native_backend: A6SignedNativePort | None = None,
        native_inventory: A6NativeInventoryPort | None = None,
        resource_source: A4EffectiveResourcePort | None = None,
    ) -> PrivateProjectRuntime:
        """Current accepted signed A6 source; no new public OAuth/OS bypass.

        The provider ports are injected ONLY after distinct Backend/C2
        authentication. They are Protocols, not usable network connections.
        A6 Files refuses reserve without a verified peer, Backend service
        identity and separate independently attested storage supervisor.
        """
        access = A5SourceAuthorization(
            service=authenticated_service,
            caller=caller_verifier,
            project=A4ProjectVerifier(project_source),
        )
        return cls(
            roots=roots,
            access=access,
            resource_source=resource_source,
            files_peer=files_peer,
            files_backend=files_backend,
            files_observer=files_observer,
            runtime_peer=runtime_peer,
            runtime_backend=runtime_backend,
            runtime_pinned_key=runtime_pinned_key,
            provider_peer=provider_peer,
            provider_backend=provider_backend,
            native_peer=native_peer,
            native_backend=native_backend,
            native_inventory=native_inventory,
        )

    def _resources(self) -> A4ResourceAdapter | None:
        return (
            A4ResourceAdapter(self.authority, self.resource_source)
            if self.resource_source is not None
            else None
        )

    def files(self, *, max_file_bytes: int) -> ProjectFilesService:
        # Files package is optional in Gateway/Terminal-only container images.
        from modules.files.a6_signed import A6SignedFilesFlow
        from modules.files.project_files import ProjectFilesService

        return ProjectFilesService(
            self.authority,
            self.roots,
            max_file_bytes=max_file_bytes,
            a6_quota=A6SignedFilesFlow(
                self.authority,
                peer_port=self.files_peer,
                backend=self.files_backend,
                observer=self.files_observer,
            ),
        )

    @staticmethod
    def explorer(*, files: ProjectFilesService) -> ProjectFileExplorer:
        from modules.files.project_explorer import ProjectFileExplorer

        return ProjectFileExplorer(files)

    def terminal(
        self, *, isolation: ProjectIsolationInspector | None = None
    ) -> ProjectTerminalRuntime:
        """Terminal metadata boundary; OS execution blocked until A9/C2."""
        from modules.terminal.project_terminal import ProjectTerminalRuntime

        return ProjectTerminalRuntime(
            authority=self.authority,
            roots=self.roots,
            isolation=isolation,
        )

    def web(self, *, files: ProjectFilesService) -> ProjectWebRuntime:
        """Public-HTTPS→A6-Files transfer, no R6 browser/process lifecycle."""
        from modules.web.project_runtime import ProjectWebRuntime

        return ProjectWebRuntime(authority=self.authority, files=files)

    def gateway(
        self,
        *,
        files: ProjectFilesService | None = None,
        readiness: ProjectAuthorizationReadinessPort | None = None,
    ) -> ProjectGatewayDispatch:
        """Private A6 allowlisted dispatcher. This NEVER mounts FastMCP."""
        # Gateway images do not import the Files implementation eagerly.
        from bridge.project_dispatch import ProjectGatewayDispatch
        from bridge.project_services import (
            PrivateProjectModuleForwarder,
            PrivateProjectToolClassifier,
        )

        return ProjectGatewayDispatch(
            self.authority,
            classifier=PrivateProjectToolClassifier(),
            readiness=readiness,
            forwarder=PrivateProjectModuleForwarder(
                self.authority,
                files=files,
                integrations=self.integrations(),
                variables=self.variables(),
            ),
        )

    def integrations(self) -> ProjectIntegrationSelector:
        return ProjectIntegrationSelector(self.authority, self._resources())

    def variables(self) -> ProjectVariableSelector:
        return ProjectVariableSelector(self.authority, self._resources())

    def a6_runtime(self) -> A6RuntimeSignedSource:
        """Signed A6 metadata only, NEVER a process/Browser owner."""
        return A6RuntimeSignedSource(
            self.authority,
            peer=self.runtime_peer,
            backend=self.runtime_backend,
            pinned_key=self.runtime_pinned_key,
        )

    def a6_native(self) -> A6SignedNativeClient:
        """Ghidra intent/UNKNOWN ledger; success needs trusted inventory."""
        from modules.analysis.a6_native import A6SignedNativeClient

        return A6SignedNativeClient(
            self.authority,
            peer=self.native_peer,
            backend=self.native_backend,
            inventory=self.native_inventory,
        )

    def a6_provider(self) -> A6ProviderReadSource:
        """Exact resource-ID provider read; never export SecretStr."""
        return A6ProviderReadSource(
            self.authority,
            self.integrations(),
            peer=self.provider_peer,
            backend=self.provider_backend,
        )

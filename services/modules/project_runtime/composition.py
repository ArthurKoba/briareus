"""Explicit private Project runtime construction for independently built modules.

Composition does not mount FastMCP or start jobs. Each domain is imported
only when its owning image contains that module. No implicit Project root,
local user, auth port or environment-based privilege is supplied.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from .a4_source import (
    A4EffectiveResourcePort,
    A4ProjectProjectionPort,
    A4ProjectVerifier,
    A4ResourceAdapter,
)
from .a5_authorization import A5AuthenticatedServicePort, A5SourceAuthorization
from .a5_provider import A5ProviderCapability, A5TrustedProviderPort
from .a5_runtime import (
    A5DomainCleanupVerifier,
    A5JobExecutionVerifier,
    A5RuntimeLedgerClient,
    A5TrustedRuntimeLedgerPort,
)
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
from .authorization import ProjectAccessPort, ProjectRuntimeAuthority
from .backend_access import (
    BackendServiceVerifier,
    BackendSessionVerifier,
    BackendSourceAccessAdapter,
    CurrentCallerVerifier,
)
from .credential_use import BackendCredentialUsePort, ProjectProviderCapability
from .durable_leases import (
    DurableLeasePort,
    ProjectRuntimeJournal,
    RuntimeRecoveryVerifier,
)
from .integrations import ProjectIntegrationPort, ProjectIntegrationSelector
from .runtime_owner import ProjectRuntimeOwner
from .sessions import RuntimeLease, RuntimeLeaseRegistry, RuntimeSessionError
from .storage_quota import ProjectQuotaGuard, ProjectQuotaPort
from .variables import ProjectVariablePort, ProjectVariableSelector
from .workspace_roots import ProjectRootRegistry

if TYPE_CHECKING:
    from modules.analysis.a5_native import (
        A5NativeImportClient,
        A5TrustedGhidraInventory,
        A5TrustedNativeImportPort,
    )
    from modules.analysis.a6_native import (
        A6NativeInventoryPort,
        A6ReversePeerPort,
        A6SignedNativeClient,
        A6SignedNativePort,
    )
    from modules.analysis.import_ledger import NativeImportLedgerPort
    from modules.analysis.project_transfer import (
        BackendCall,
        GhidraProjectPort,
        NativeStageVerifier,
        ProjectReverseTransfer,
    )
    from modules.files.a5_quota import A5TrustedFileQuotaPort
    from modules.files.a6_signed import (
        SignedFilesBackendPort,
        TrustedFilesStoragePort,
        VerifiedFilesPeerPort,
    )
    from modules.files.project_explorer import ProjectFileExplorer
    from modules.files.project_files import ProjectFilesService
    from modules.terminal.project_isolation import ProjectIsolationInspector
    from modules.terminal.project_terminal import ProjectTerminalRuntime
    from modules.web.project_runtime import (
        InternalBrowserFactory,
        ProjectWebRuntime,
        RemoteBrowserConnector,
    )


@dataclass(slots=True)
class PrivateProjectRuntime:
    """One explicit source-composed private runtime, not an exposed service."""

    roots: ProjectRootRegistry
    a5_mode: bool = False
    a6_mode: bool = False
    access: ProjectAccessPort | None = None
    integration_port: ProjectIntegrationPort | None = None
    variable_port: ProjectVariablePort | None = None
    credential_port: BackendCredentialUsePort | None = None
    a4_resource_source: A4EffectiveResourcePort | None = None
    a5_quota_source: A5TrustedFileQuotaPort | None = None
    a6_files_peer: VerifiedFilesPeerPort | None = None
    a6_files_backend: SignedFilesBackendPort | None = None
    a6_files_observer: TrustedFilesStoragePort | None = None
    a6_runtime_peer: A6RuntimePeerPort | None = None
    a6_runtime_backend: A6SignedRuntimePort | None = None
    a6_provider_peer: A6ProviderPeerPort | None = None
    a6_provider_backend: A6SignedProviderPort | None = None
    a6_native_peer: A6ReversePeerPort | None = None
    a6_native_backend: A6SignedNativePort | None = None
    a6_native_inventory: A6NativeInventoryPort | None = None
    a5_authenticated_service: A5AuthenticatedServicePort | None = None
    a5_runtime_source: A5TrustedRuntimeLedgerPort | None = None
    a5_native_source: A5TrustedNativeImportPort | None = None
    a5_native_inventory: A5TrustedGhidraInventory | None = None
    a5_provider_source: A5TrustedProviderPort | None = None
    a5_cleanup_verifier: A5DomainCleanupVerifier | None = None
    a5_job_verifier: A5JobExecutionVerifier | None = None
    quota_port: ProjectQuotaPort | None = None
    lease_port: DurableLeasePort | None = None
    recovery_verifier: RuntimeRecoveryVerifier | None = None
    leases: RuntimeLeaseRegistry = field(default_factory=RuntimeLeaseRegistry)
    authority: ProjectRuntimeAuthority = field(init=False)
    journal: ProjectRuntimeJournal = field(init=False)
    owner: ProjectRuntimeOwner = field(init=False)

    def __post_init__(self) -> None:
        self.authority = ProjectRuntimeAuthority(self.access)
        self.journal = ProjectRuntimeJournal(
            self.lease_port, recovery_verifier=self.recovery_verifier
        )
        self.owner = ProjectRuntimeOwner(self.leases, self.journal)

    @classmethod
    def from_accepted_a4_sources(
        cls,
        *,
        roots: ProjectRootRegistry,
        service_verifier: BackendServiceVerifier,
        caller_verifier: CurrentCallerVerifier,
        session_verifier: BackendSessionVerifier,
        project_source: A4ProjectProjectionPort,
        resource_source: A4EffectiveResourcePort | None = None,
        quota_port: ProjectQuotaPort | None = None,
        lease_port: DurableLeasePort | None = None,
        recovery_verifier: RuntimeRecoveryVerifier | None = None,
        credential_port: BackendCredentialUsePort | None = None,
    ) -> PrivateProjectRuntime:
        """Source-typed ONLY: callers must inject authenticated Backend ports.

        This factory creates no credentials, HTTP client, fallback superuser,
        public MCP endpoint, PostgreSQL store or Terminal process. A missing
        public C1-B2 transport is therefore still a strict activation gate.
        """
        access = BackendSourceAccessAdapter(
            caller_verifier=caller_verifier,
            service_verifier=service_verifier,
            session_verifier=session_verifier,
            project_verifier=A4ProjectVerifier(project_source),
        )
        return cls(
            roots=roots,
            access=access,
            a4_resource_source=resource_source,
            quota_port=quota_port,
            lease_port=lease_port,
            recovery_verifier=recovery_verifier,
            credential_port=credential_port,
        )

    @classmethod
    def from_accepted_a5_sources(
        cls,
        *,
        roots: ProjectRootRegistry,
        authenticated_service: A5AuthenticatedServicePort,
        caller_verifier: CurrentCallerVerifier,
        project_source: A4ProjectProjectionPort,
        resource_source: A4EffectiveResourcePort | None = None,
        quota_source: A5TrustedFileQuotaPort | None = None,
        runtime_source: A5TrustedRuntimeLedgerPort | None = None,
        native_source: A5TrustedNativeImportPort | None = None,
        native_inventory: A5TrustedGhidraInventory | None = None,
        provider_source: A5TrustedProviderPort | None = None,
        cleanup_verifier: A5DomainCleanupVerifier | None = None,
        job_verifier: A5JobExecutionVerifier | None = None,
        lease_port: DurableLeasePort | None = None,
        recovery_verifier: RuntimeRecoveryVerifier | None = None,
        credential_port: BackendCredentialUsePort | None = None,
    ) -> PrivateProjectRuntime:
        """Private A5 exact operation/audience consumer composition.

        The trusted service port must consume BOTH verified signed proofs via
        Backend and commit replay ledger before this access adapter returns a
        permit. It is NOT a synthesized REST connection; unbound downstream
        quota/runtime/native ledgers refuse protected mutation by default.
        """
        # A5 SQL RuntimeSession/nonce/version is independent of the previous
        # R6 per-process lease CAS, and A5 one-use credentials differ from R6.
        # Never attach either older adapter to an A5 source composition.
        if lease_port is not None or recovery_verifier is not None or credential_port is not None:
            raise RuntimeSessionError("A5_LEGACY_RUNTIME_PORT_MIX_FORBIDDEN")
        access = A5SourceAuthorization(
            service=authenticated_service,
            caller=caller_verifier,
            project=A4ProjectVerifier(project_source),
        )
        return cls(
            roots=roots,
            a5_mode=True,
            access=access,
            a4_resource_source=resource_source,
            a5_quota_source=quota_source,
            a5_authenticated_service=authenticated_service,
            a5_runtime_source=runtime_source,
            a5_native_source=native_source,
            a5_native_inventory=native_inventory,
            a5_provider_source=provider_source,
            a5_cleanup_verifier=cleanup_verifier,
            a5_job_verifier=job_verifier,
            lease_port=None,
            recovery_verifier=None,
            credential_port=None,
        )

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
        provider_peer: A6ProviderPeerPort | None = None,
        provider_backend: A6SignedProviderPort | None = None,
        native_peer: A6ReversePeerPort | None = None,
        native_backend: A6SignedNativePort | None = None,
        native_inventory_port: A6NativeInventoryPort | None = None,
        resource_source: A4EffectiveResourcePort | None = None,
        runtime_source: A5TrustedRuntimeLedgerPort | None = None,
        native_source: A5TrustedNativeImportPort | None = None,
        native_inventory: A5TrustedGhidraInventory | None = None,
        provider_source: A5TrustedProviderPort | None = None,
        cleanup_verifier: A5DomainCleanupVerifier | None = None,
        job_verifier: A5JobExecutionVerifier | None = None,
    ) -> PrivateProjectRuntime:
        """Accepted A6 source boundaries; NO implicit network or OS trust.

        The caller-supplied backend adapter must bind the exact normalized
        signed A6 ServiceOperationIntent to independently attested TLS/Unix
        peer, registered Ed25519 key, Backend delegated User and SQL JTI. The
        Files backend MUST execute actual SignedFilesAuthority per phase.
        A6 without a real peer/observer remains unmounted and fail-closed.
        R6/R8 local owner, A5 quota and secret transports are not reused.
        """
        access = A5SourceAuthorization(
            service=authenticated_service,
            caller=caller_verifier,
            project=A4ProjectVerifier(project_source),
        )
        return cls(
            roots=roots,
            a5_mode=True,  # disables legacy R6 owner/reaper/credential route
            a6_mode=True,
            access=access,
            a4_resource_source=resource_source,
            a6_files_peer=files_peer,
            a6_files_backend=files_backend,
            a6_files_observer=files_observer,
            a6_runtime_peer=runtime_peer,
            a6_runtime_backend=runtime_backend,
            a6_provider_peer=provider_peer,
            a6_provider_backend=provider_backend,
            a6_native_peer=native_peer,
            a6_native_backend=native_backend,
            a6_native_inventory=native_inventory_port,
            a5_authenticated_service=authenticated_service,
            a5_runtime_source=runtime_source,
            a5_native_source=native_source,
            a5_native_inventory=native_inventory,
            a5_provider_source=provider_source,
            a5_cleanup_verifier=cleanup_verifier,
            a5_job_verifier=job_verifier,
        )

    def _resources(self) -> A4ResourceAdapter | None:
        if self.a4_resource_source is None:
            return None
        return A4ResourceAdapter(self.authority, self.a4_resource_source)

    def files(self, *, max_file_bytes: int) -> ProjectFilesService:
        # Files package is optional in Gateway/Terminal-only container images.
        from modules.files.a5_quota import A5FileQuotaFlow
        from modules.files.a6_signed import A6SignedFilesFlow
        from modules.files.project_files import ProjectFilesService

        return ProjectFilesService(
            self.authority,
            self.roots,
            max_file_bytes=max_file_bytes,
            quota=ProjectQuotaGuard(self.quota_port),
            a5_quota=(
                A5FileQuotaFlow(self.authority, self.a5_quota_source)
                if not self.a6_mode and (self.a5_mode or self.a5_quota_source is not None)
                else None
            ),
            a6_quota=(
                A6SignedFilesFlow(
                    self.authority,
                    peer_port=self.a6_files_peer,
                    backend=self.a6_files_backend,
                    observer=self.a6_files_observer,
                )
                if self.a6_mode
                else None
            ),
        )

    def explorer(self, *, files: ProjectFilesService) -> ProjectFileExplorer:
        """Typed A4/B7-compatible local projection; no HTTP route or URL."""
        from modules.files.project_explorer import ProjectFileExplorer

        return ProjectFileExplorer(files)

    def terminal(
        self, *, isolation: ProjectIsolationInspector | None = None
    ) -> ProjectTerminalRuntime:
        from modules.terminal.project_terminal import ProjectTerminalRuntime

        return ProjectTerminalRuntime(
            authority=self.authority,
            roots=self.roots,
            leases=self.leases,
            owner=None if self.a5_mode else self.owner,
            isolation=isolation,
        )

    def web(
        self,
        *,
        files: ProjectFilesService,
        internal_factory: InternalBrowserFactory | None = None,
        remote_connector: RemoteBrowserConnector | None = None,
    ) -> ProjectWebRuntime:
        from modules.web.project_runtime import ProjectWebRuntime

        return ProjectWebRuntime(
            authority=self.authority,
            roots=self.roots,
            files=files,
            leases=self.leases,
            owner=None if self.a5_mode else self.owner,
            internal_factory=internal_factory,
            remote_connector=remote_connector,
        )

    def reverse(
        self,
        *,
        files: ProjectFilesService,
        native_projects: GhidraProjectPort | None = None,
        backend_call: BackendCall | None = None,
        ledger: NativeImportLedgerPort | None = None,
        stage_verifier: NativeStageVerifier | None = None,
    ) -> ProjectReverseTransfer:
        if self.a5_mode:
            raise RuntimeSessionError("A5_GHIDRA_NATIVE_LEDGER_REQUIRED")
        from modules.analysis.project_transfer import ProjectReverseTransfer

        return ProjectReverseTransfer(
            authority=self.authority,
            files=files,
            native_projects=native_projects,
            backend_call=backend_call,
            ledger=ledger,
            stage_verifier=stage_verifier,
        )

    def integrations(self) -> ProjectIntegrationSelector:
        return ProjectIntegrationSelector(
            self.authority, self.integration_port or self._resources()
        )

    def variables(self) -> ProjectVariableSelector:
        return ProjectVariableSelector(self.authority, self.variable_port or self._resources())

    def a6_runtime(self) -> A6RuntimeSignedSource:
        """A6 source-only signed DB intent, NEVER process adoption."""
        return A6RuntimeSignedSource(
            self.authority,
            peer=self.a6_runtime_peer,
            backend=self.a6_runtime_backend,
        )

    def a6_native(self) -> A6SignedNativeClient:
        """A6 signed native intents; backend inventory proof required."""
        from modules.analysis.a6_native import A6SignedNativeClient

        return A6SignedNativeClient(
            self.authority,
            peer=self.a6_native_peer,
            backend=self.a6_native_backend,
            inventory=self.a6_native_inventory,
        )

    def a6_provider(self) -> A6ProviderReadSource:
        """A6 signed, result-hash-only provider READ; never plaintext keys."""
        return A6ProviderReadSource(
            self.authority,
            self.integrations(),
            peer=self.a6_provider_peer,
            backend=self.a6_provider_backend,
        )

    def a5_runtime(self) -> A5RuntimeLedgerClient:
        """DB-only A5 lease/job intent; never a shell or browser factory."""
        if self.a6_mode:
            raise RuntimeSessionError("A6_RUNTIME_A5_LEDGER_INCOMPATIBLE")
        return A5RuntimeLedgerClient(
            self.authority,
            self.a5_runtime_source,
            owner_instance_uuid=self.journal.instance_uuid,
            cleanup_verifier=self.a5_cleanup_verifier,
            job_verifier=self.a5_job_verifier,
        )

    def a5_native(self) -> A5NativeImportClient:
        """A5 Files-backed native import intent; no Ghidra OS side effect."""
        if self.a6_mode:
            raise RuntimeSessionError("A6_NATIVE_A5_LEDGER_INCOMPATIBLE")
        from modules.analysis.a5_native import A5NativeImportClient

        return A5NativeImportClient(
            self.authority,
            self.a5_native_source,
            inventory=self.a5_native_inventory,
        )

    def a5_provider(self) -> A5ProviderCapability:
        """Resource-ID-bound read only; no raw secret or write grant."""
        if self.a6_mode:
            raise RuntimeSessionError("A6_PROVIDER_A5_RECEIPT_INCOMPATIBLE")
        return A5ProviderCapability(
            self.authority,
            self.integrations(),
            service=self.a5_authenticated_service,
            provider_backend=self.a5_provider_source,
        )

    def provider_capability(self) -> ProjectProviderCapability:
        if self.a5_mode:
            raise RuntimeSessionError("A5_PROVIDER_EFFECT_LEDGER_REQUIRED")
        return ProjectProviderCapability(
            self.authority, self.integrations(), backend=self.credential_port
        )

    @asynccontextmanager
    async def lifespan(
        self,
        *,
        sweep_interval_seconds: float = 1.0,
        previous_instance_uuid: UUID | None = None,
        recovery_service_evidence: object | None = None,
    ) -> AsyncIterator[PrivateProjectRuntime]:
        """Start the private TTL reaper, then close owned resources on exit.

        A missing Backend CAS port prevents lifecycle startup. No privileged
        Terminal/browser child is started simply by entering this context.
        Unexpected reaper failure propagates; its TaskGroup cancels the owner
        context rather than silently leaving active leases unswept.
        """
        if self.a5_mode:
            raise RuntimeSessionError("A5_OS_REAPER_SUPERVISOR_UNAVAILABLE")
        self.owner.require_available()
        if previous_instance_uuid is not None:
            await self.journal.reconcile_previous_instance(
                previous_instance_uuid,
                service_evidence=recovery_service_evidence,
            )
        stop = asyncio.Event()
        try:
            async with asyncio.TaskGroup() as workers:
                workers.create_task(
                    self.owner.run_reaper(stop, interval_seconds=sweep_interval_seconds)
                )
                try:
                    yield self
                finally:
                    stop.set()
        finally:
            # Cleanup concerns only local owned lease callbacks. It does not
            # kill personal Chrome or recreate an OS worker after restart.
            await self.owner.shutdown()

    async def close(self) -> list[RuntimeLease]:
        """Orderly R6 cleanup; A5 requires its own OS/DB owner supervisor."""
        if self.a5_mode:
            raise RuntimeSessionError("A5_OS_REAPER_SUPERVISOR_UNAVAILABLE")
        return list(await self.owner.shutdown())

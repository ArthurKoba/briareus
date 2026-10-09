"""Composition for a fresh, dedicated greenfield PostgreSQL-backed core.

Factory only. Existing Authorization/Admin runtimes are NOT switched over.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic import Field
from sqlalchemy import MetaData

from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from common.settings import ProcessSettings
from identity._service import IdentityService
from projects._file_quota import FileQuotaLedger
from projects._native_import_ledger import NativeImportLedger
from projects._resource_service import ResourceService, ResourceSettings
from projects._runtime_ledger import RuntimeLedger

from ._external_operations import ExternalOperationLedger
from ._files_vertical import SignedFilesAuthority
from ._idempotency import IdempotentCommandExecutor
from ._mtls_peer import PinnedMTLSPeerVerifier, PinnedServiceCertificate
from ._native_vertical import SignedNativeImportAuthority
from ._outbox import OutboxDispatcher
from ._platform_application import PlatformApplication
from ._platform_auth import AdminBearerSettings, PlatformAdminBearerAuth
from ._project_sessions import ProjectSessionService
from ._provider_vertical import SignedProviderReadAuthority
from ._resource_leases import ResourceCredentialUse
from ._runtime_vertical import SignedRuntimeAuthority
from ._scoped_events import ScopedEventFeed, ScopedOutboxSink
from ._service_identity import ServiceIdentityAuthority, ServiceIdentitySettings
from ._service_transport import PrivateServiceAuthorizationController


def platform_metadata() -> MetaData:
    """Import domain-owned ORM models into shared metadata (offline-safe)."""
    from agents import _persistence as _agents
    from authorization import _platform_persistence as _authorization
    from authorization import _scoped_events_persistence as _events
    from authorization import _service_identity_persistence as _service_ids
    from authorization import _session_persistence as _sessions
    from identity import _persistence as _identity
    from projects import _file_quota_persistence as _files
    from projects import _native_import_persistence as _native
    from projects import _persistence as _projects
    from projects import _resource_persistence as _resources
    from projects import _runtime_persistence as _runtime
    from teams import _persistence as _teams

    # Module imports register declarations on PlatformBase.metadata.
    _ = (
        _agents,
        _authorization,
        _sessions,
        _identity,
        _projects,
        _resources,
        _runtime,
        _native,
        _files,
        _teams,
        _service_ids,
        _events,
    )
    from common.platform_db import PlatformBase

    return PlatformBase.metadata


class ServiceIdentityToggle(ProcessSettings):
    enabled: bool = Field(False, validation_alias="PLATFORM_SERVICE_IDENTITY_ENABLED")


@dataclass(frozen=True)
class PlatformServices:
    database: PlatformDatabase
    identity: IdentityService
    application: PlatformApplication
    sessions: ProjectSessionService
    commands: IdempotentCommandExecutor
    resources: ResourceService
    credential_use: ResourceCredentialUse
    admin_auth: PlatformAdminBearerAuth
    external_operations: ExternalOperationLedger
    service_identity: ServiceIdentityAuthority | None
    service_transport: PrivateServiceAuthorizationController
    signed_files: SignedFilesAuthority
    signed_runtime: SignedRuntimeAuthority
    signed_native_imports: SignedNativeImportAuthority
    signed_provider_reads: SignedProviderReadAuthority
    runtimes: RuntimeLedger
    file_quotas: FileQuotaLedger
    native_imports: NativeImportLedger
    scoped_events: ScopedEventFeed
    scoped_outbox: OutboxDispatcher


def compose_platform(settings: PlatformDatabaseSettings) -> PlatformServices:
    platform_metadata()
    database = PlatformDatabase(settings)
    application = PlatformApplication(database)
    idempotency_key = settings.idempotency_key.get_secret_value()
    resource_settings = ResourceSettings()
    resources = ResourceService(
        application,
        encryption_key=resource_settings.encryption_key.get_secret_value(),
    )
    sessions = ProjectSessionService(application)
    identity = IdentityService(database, settings)
    admin_auth = PlatformAdminBearerAuth(identity, AdminBearerSettings())
    toggles = ServiceIdentityToggle()
    service_identity = (
        ServiceIdentityAuthority(
            application, sessions, resources, admin_auth, ServiceIdentitySettings()
        )
        if toggles.enabled
        else None
    )
    # No verified mTLS/Unix peer attestor or OS/Files/Ghidra/provider adapter
    # is available in this source lane. These ports are intentionally
    # composed fail-closed, not silently reachable from existing runtimes.
    service_transport = PrivateServiceAuthorizationController(service_identity)
    credentials = ResourceCredentialUse(
        application, resources, sessions, validator=service_identity
    )
    external_operations = ExternalOperationLedger(
        application,
        sessions,
        resources,
        signing_key=idempotency_key.encode(),
        validator=service_identity,
    )
    runtimes = RuntimeLedger(
        application,
        signing_key=idempotency_key.encode(),
        validator=service_identity,
    )
    file_quotas = FileQuotaLedger(
        application,
        signing_key=idempotency_key.encode(),
        validator=service_identity,
    )
    native_imports = NativeImportLedger(
        application,
        signing_key=idempotency_key.encode(),
        validator=service_identity,
    )
    scoped_events = ScopedEventFeed(application, validator=service_identity)
    scoped_outbox = OutboxDispatcher(database, ScopedOutboxSink(database, scoped_events))
    return PlatformServices(
        database=database,
        identity=identity,
        application=application,
        sessions=sessions,
        commands=IdempotentCommandExecutor(database, idempotency_key),
        resources=resources,
        credential_use=credentials,
        admin_auth=admin_auth,
        external_operations=external_operations,
        service_identity=service_identity,
        service_transport=service_transport,
        signed_files=SignedFilesAuthority(service_transport, file_quotas),
        signed_runtime=SignedRuntimeAuthority(service_transport, runtimes),
        signed_native_imports=SignedNativeImportAuthority(service_transport, native_imports),
        signed_provider_reads=SignedProviderReadAuthority(
            service_transport, resources, credentials, external_operations
        ),
        runtimes=runtimes,
        file_quotas=file_quotas,
        native_imports=native_imports,
        scoped_events=scoped_events,
        scoped_outbox=scoped_outbox,
    )


def bind_explicit_dev_mtls(
    services: PlatformServices,
    *,
    pins: tuple[PinnedServiceCertificate, ...],
) -> PlatformServices:
    """Opt-in service transport composition after independent D1 trust review.

    The pins MUST be supplied by an authenticated infrastructure supervisor
    from its trusted release configuration. No operator/browser/controller
    request body, proxy headers or unauthenticated environment value may
    create a trusted service binding. This neither binds an HTTP listener nor
    mounts private/project routes; external activation remains C1-B2/C2.
    """
    if services.service_identity is None:
        raise ValueError("DEV service identity is not enabled with trusted signing material")
    verifier = PinnedMTLSPeerVerifier(pins)
    controller = PrivateServiceAuthorizationController(
        services.service_identity, peer_authenticator=verifier
    )
    return replace(
        services,
        service_transport=controller,
        signed_files=SignedFilesAuthority(controller, services.file_quotas),
        signed_runtime=SignedRuntimeAuthority(controller, services.runtimes),
        signed_native_imports=SignedNativeImportAuthority(controller, services.native_imports),
        signed_provider_reads=SignedProviderReadAuthority(
            controller, services.resources, services.credential_use, services.external_operations
        ),
    )

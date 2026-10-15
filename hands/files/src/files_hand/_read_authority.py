"""Concrete two-phase read orchestration over separately trusted owner ports.

Neither port has a default transport/credential/mapping implementation. This
adapter replaces test-specific scope assembly; it cannot turn caller JSON,
a bearer string or a Files FD into identity or permission. No MCP mount.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from ._fd_snapshot import FilesNodeStamp, FilesReadObservation, observe_root
from ._lease_deadline import ReadLeaseDeadline
from ._native_read import NativeFilesReadRequest
from ._read_adapter import FilesMcpReadUnavailable
from ._read_decision import (
    FilesReadDecisionReceipt,
    FilesReadDecisionRequest,
    decode_private_read_decision,
)


@dataclass(frozen=True, slots=True)
class PrivateReadReply:
    status: int
    body: bytes = field(repr=False)


class AuthenticatedReadChannel(Protocol):
    """Supervisor-verified caller and connection, never an MCP-supplied object.

    Entry verifies the ORIGINAL signed Rauthy resource token and binds the
    immutable invocation. Each call attests exact bytes/effect with its own
    fresh nonce to the fixed private files/read-decision endpoint. Responses
    are returned only after authenticating that endpoint. Tokens/keys stay
    inside the implementation, are never copied into these DTOs or logs.
    """

    request_fingerprint: str
    actor_uuid: UUID
    expires_at: datetime

    async def decide(self, *, body: bytes, effect_key: str) -> PrivateReadReply: ...


class TrustedReadChannelPort(Protocol):
    def open_channel(
        self, request: NativeFilesReadRequest
    ) -> AbstractAsyncContextManager[AuthenticatedReadChannel]: ...


class CurrentFilesRoot(Protocol):
    """Existing owner-held mapping lease; no caller-selected absolute root.

    Mapping revision comes from the Files owner, NOT dev/inode or fabricated
    Identity epochs. The descriptor is held by this context until exit.
    validate_current/exit reject changed Project mapping/incarnation/revision.
    """

    request_fingerprint: str
    project_uuid: UUID
    owner_revision: int
    root_fd: int
    root_observation: FilesNodeStamp
    expires_at: datetime

    async def validate_current(self) -> None: ...


class TrustedFilesRootPort(Protocol):
    def hold_root(
        self, *, request: NativeFilesReadRequest, actor_uuid: UUID
    ) -> AbstractAsyncContextManager[CurrentFilesRoot]: ...


def _live_deadline(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value <= datetime.now(UTC):
        raise FilesMcpReadUnavailable("FILES_OWNER_AUTHORITY_EXPIRED")


def _channel_matches(channel: AuthenticatedReadChannel, request: NativeFilesReadRequest) -> None:
    if (
        channel.request_fingerprint != request.request_fingerprint
        or not isinstance(channel.actor_uuid, UUID)
        or channel.actor_uuid.version != 4
    ):
        raise FilesMcpReadUnavailable("FILES_CALLER_BINDING_INVALID")
    _live_deadline(channel.expires_at)


@dataclass(frozen=True, slots=True)
class _RootBinding:
    request_fingerprint: str
    project_uuid: UUID
    owner_revision: int
    root_fd: int
    observation: FilesNodeStamp
    expires_at: datetime


def _root_binding(root: CurrentFilesRoot, request: NativeFilesReadRequest) -> _RootBinding:
    if (
        root.request_fingerprint != request.request_fingerprint
        or root.project_uuid != request.project_uuid
        or type(root.owner_revision) is not int
        or not 1 <= root.owner_revision <= 2**63 - 1
        or type(root.root_fd) is not int
        or root.root_fd < 0
        or not isinstance(root.root_observation, FilesNodeStamp)
    ):
        raise FilesMcpReadUnavailable("FILES_ROOT_OWNER_BINDING_INVALID")
    _live_deadline(root.expires_at)
    return _RootBinding(
        root.request_fingerprint,
        root.project_uuid,
        root.owner_revision,
        root.root_fd,
        root.root_observation,
        root.expires_at,
    )


class _BoundReadScope:
    def __init__(
        self,
        request: NativeFilesReadRequest,
        channel: AuthenticatedReadChannel,
        root: CurrentFilesRoot,
        before: FilesReadDecisionReceipt,
    ) -> None:
        self.request = request
        self.root_fd, self.root_observation = root.root_fd, root.root_observation
        self.owner_revision = root.owner_revision
        self.expires_at = min(before.expires_at, channel.expires_at, root.expires_at)
        self.final_expiry: datetime | None = None
        self._initial_lease = ReadLeaseDeadline.capture(self.expires_at, maximum_seconds=5)
        self._final_lease: ReadLeaseDeadline | None = None
        self._channel, self._root, self._before = channel, root, before
        self._original_root = _root_binding(root, request)
        self._original_channel = (channel.actor_uuid, channel.expires_at)
        self._claimed = False
        self._retired = False

    def check_original_binding(self) -> None:
        self._initial_lease.check()
        _channel_matches(self._channel, self.request)
        if (
            _root_binding(self._root, self.request) != self._original_root
            or (self._channel.actor_uuid, self._channel.expires_at) != self._original_channel
        ):
            raise FilesMcpReadUnavailable("FILES_READ_OWNER_CHANGED")
        _live_deadline(self.expires_at)

    async def revalidate(self, observation: FilesReadObservation) -> None:
        if self._claimed or self._retired or observation.root != self.root_observation:
            raise FilesMcpReadUnavailable("FILES_READ_PHASE_INVALID")
        self._claimed = True  # Failed/uncertain replies cannot reuse a phase.
        self.check_original_binding()
        if await self._root.validate_current() is not None:
            raise FilesMcpReadUnavailable("FILES_ROOT_REVALIDATION_INVALID")
        command = FilesReadDecisionRequest(self.request, self.owner_revision, "after_read")
        reply = await self._channel.decide(
            body=command.wire_body(),
            effect_key=self.request.selector.effect_key,
        )
        if type(reply) is not PrivateReadReply:
            raise FilesMcpReadUnavailable("FILES_READ_PEER_REPLY_INVALID")
        receipt = decode_private_read_decision(
            command=command,
            status=reply.status,
            body=reply.body,
            expected_actor_uuid=self._original_channel[0],
        )
        deadline = receipt.final_deadline(self._before, now=datetime.now(UTC))
        final_lease = ReadLeaseDeadline.capture(deadline, maximum_seconds=5)
        if await self._root.validate_current() is not None:
            raise FilesMcpReadUnavailable("FILES_ROOT_REVALIDATION_INVALID")
        self.check_original_binding()
        self.final_expiry = min(deadline, self.expires_at)
        self._final_lease = final_lease
        final_lease.check()
        _live_deadline(self.final_expiry)


class BoundFilesReadAuthority:
    """Connect genuine private channel and root owner; missing either denies."""

    def __init__(
        self,
        *,
        channels: TrustedReadChannelPort | None = None,
        roots: TrustedFilesRootPort | None = None,
    ) -> None:
        self._channels, self._roots = channels, roots

    @asynccontextmanager
    async def open_read(self, request: NativeFilesReadRequest) -> AsyncIterator[_BoundReadScope]:
        if self._channels is None or self._roots is None:
            raise FilesMcpReadUnavailable("FILES_NATIVE_OWNER_PORTS_UNAVAILABLE")
        if not isinstance(request, NativeFilesReadRequest):
            raise FilesMcpReadUnavailable("FILES_NATIVE_CONTEXT_INVALID")
        finished = False
        root_exited = False
        scope: _BoundReadScope | None = None
        async with self._channels.open_channel(request) as channel:
            _channel_matches(channel, request)
            actor, caller_expiry = channel.actor_uuid, channel.expires_at
            caller_lease = ReadLeaseDeadline.capture(caller_expiry)
            async with self._roots.hold_root(request=request, actor_uuid=actor) as root:
                binding = _root_binding(root, request)
                root_lease = ReadLeaseDeadline.capture(binding.expires_at)
                if await root.validate_current() is not None:
                    raise FilesMcpReadUnavailable("FILES_ROOT_REVALIDATION_INVALID")
                if observe_root(root.root_fd) != root.root_observation:
                    raise FilesMcpReadUnavailable("FILES_ROOT_OBSERVATION_CHANGED")
                command = FilesReadDecisionRequest(request, root.owner_revision, "before_read")
                reply = await channel.decide(
                    body=command.wire_body(),
                    effect_key=request.selector.effect_key,
                )
                if type(reply) is not PrivateReadReply:
                    raise FilesMcpReadUnavailable("FILES_READ_PEER_REPLY_INVALID")
                receipt = decode_private_read_decision(
                    command=command,
                    status=reply.status,
                    body=reply.body,
                    expected_actor_uuid=actor,
                )
                _channel_matches(channel, request)
                if (channel.actor_uuid, channel.expires_at) != (actor, caller_expiry):
                    raise FilesMcpReadUnavailable("FILES_CALLER_BINDING_CHANGED")
                if (
                    await root.validate_current() is not None
                    or _root_binding(root, request) != binding
                ):
                    raise FilesMcpReadUnavailable("FILES_ROOT_OWNER_CHANGED")
                caller_lease.check()
                root_lease.check()
                scope = _BoundReadScope(request, channel, root, receipt)
                try:
                    yield scope
                    if scope.final_expiry is None:
                        raise FilesMcpReadUnavailable("FILES_READ_AFTER_PHASE_REQUIRED")
                    scope.check_original_binding()
                    if await root.validate_current() is not None:
                        raise FilesMcpReadUnavailable("FILES_ROOT_REVALIDATION_INVALID")
                    _live_deadline(scope.final_expiry)
                    scope._initial_lease.check()
                    if scope._final_lease is None:
                        raise FilesMcpReadUnavailable("FILES_READ_AFTER_PHASE_REQUIRED")
                    scope._final_lease.check()
                    caller_lease.check()
                    root_lease.check()
                    finished = True
                finally:
                    scope._retired = True
            # Root/channel context exits may deny or suppress exceptions.
            # Suppression may not create success or skip either read phase.
            if not finished or scope is None:
                raise FilesMcpReadUnavailable("FILES_READ_OWNER_EXIT_INVALID")
            root_exited = True
        if not finished or not root_exited or scope is None or scope.final_expiry is None:
            raise FilesMcpReadUnavailable("FILES_READ_OWNER_EXIT_INVALID")
        # Ports have exited and may have invalidated their local handles.
        # Only immutable scope deadlines are read here; live root checks
        # happened before its exit and the consumer retains its OWN FD.
        _live_deadline(scope.expires_at)
        _live_deadline(scope.final_expiry)
        scope._initial_lease.check()
        if scope._final_lease is None:
            raise FilesMcpReadUnavailable("FILES_READ_AFTER_PHASE_REQUIRED")
        scope._final_lease.check()
        caller_lease.check()
        root_lease.check()

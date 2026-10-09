"""Restricted Linux Unix-domain channel for one-time first-superuser setup.

OS peer identity is supplied by the *kernel* SO_PEERCRED on an accepted
server-side AF_UNIX stream connection. Neither a structural Protocol method,
an HTTP header, an arbitrary UUID nor a client JSON body can assert operator
authority. A dedicated non-root human-operator UID/GID distinct from the
Briareus runtime UID must be provisioned and approved by D4.

There is no listener, socket pathname, stdout/stdin CLI or unauthenticated
public bootstrap route in this module. The caller's trusted supervisor owns
its filesystem ACL, socket handoff and code delivery before enabling this.
"""

from __future__ import annotations

import os
import socket
import struct
from dataclasses import dataclass

from common.platform_errors import AccessDenied, InvalidInput

_PEERCRED = struct.Struct("=3i")


@dataclass(frozen=True, slots=True)
class AttestedFirstAdminOperator:
    """Non-secret trusted OS principal; not a bearer to mint another code."""

    pid: int
    uid: int
    gid: int


class UnixFirstAdminOperatorGate:
    """D4-supplied explicit operator principal, NEVER an ENV preview toggle."""

    def __init__(self, *, allowed_uid: int, allowed_gid: int) -> None:
        if (
            not hasattr(socket, "SO_PEERCRED")
            or not isinstance(allowed_uid, int)
            or not isinstance(allowed_gid, int)
            or allowed_uid <= 0
            or allowed_gid <= 0
            or allowed_uid == os.geteuid()
            or allowed_gid == os.getegid()
            or os.geteuid() == 0
        ):
            raise InvalidInput(
                "first-admin operator requires a dedicated non-root UID/GID "
                "different from the non-root Briareus process"
            )
        self._allowed_uid = allowed_uid
        self._allowed_gid = allowed_gid

    def verify_accepted_peer(self, accepted_socket: socket.socket) -> AttestedFirstAdminOperator:
        """Inspect *accepted* kernel credentials; do not trust socket metadata."""
        if (
            not isinstance(accepted_socket, socket.socket)
            or accepted_socket.family != socket.AF_UNIX
            or accepted_socket.type & socket.SOCK_STREAM != socket.SOCK_STREAM
        ):
            raise AccessDenied("connected Unix operator stream required")
        try:
            peer_raw = accepted_socket.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED.size
            )
            pid, uid, gid = _PEERCRED.unpack(peer_raw)
            if (
                pid <= 1
                or uid != self._allowed_uid
                or gid != self._allowed_gid
                or uid == os.geteuid()
            ):
                raise AccessDenied("Unix operator peer UID/GID not authorized")
        except (OSError, ValueError, struct.error) as exc:
            raise AccessDenied("Unix operator kernel attestation unavailable") from exc
        return AttestedFirstAdminOperator(pid=pid, uid=uid, gid=gid)

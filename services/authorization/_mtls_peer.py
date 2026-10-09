"""Verified direct mTLS service peer for a future isolated DEV listener.

Only an actually handshaken, server-side TLS socket/SSLObject is admissible. ASGI
Request objects, forwarded TLS headers, JSON credentials, arbitrary bytes,
reverse-proxy metadata or a client-provided principal are never proof of
the peer. The pinned certificate->service/instance mapping MUST come from
D1-controlled trusted local configuration, not an API request.

This verifier does not start a listener or open a network connection.
"""

from __future__ import annotations

import hashlib
import re
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID

from common.platform_errors import AuthenticationRequired, InvalidInput

from ._service_transport import VerifiedServicePeer


@dataclass(frozen=True, slots=True)
class PinnedServiceCertificate:
    """Trusted infrastructure binding for one exact service process instance."""

    certificate_sha256: str
    service_id: UUID
    key_id: UUID
    instance_uuid: UUID
    audience: str
    valid_until: datetime

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9a-f]{64}", self.certificate_sha256) is None
            or self.service_id.version != 4
            or self.key_id.version != 4
            or self.instance_uuid.version != 4
            or not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", self.audience)
            or self.valid_until.tzinfo is None
            or self.valid_until <= datetime.now(UTC)
        ):
            raise InvalidInput("trusted mTLS service pin configuration invalid")


class PinnedMTLSPeerVerifier:
    """Certificate-pin verifier for direct TLSv1.3 authenticated service IO.

    A server listener must own the socket's handshake. This class only
    introspects the connection's already verified local TLS state.
    """

    def __init__(
        self,
        bindings: tuple[PinnedServiceCertificate, ...],
    ) -> None:
        if not bindings:
            raise InvalidInput("direct mTLS verifier requires explicit DEV pins")
        self._bindings: dict[str, PinnedServiceCertificate] = {}
        for record in bindings:
            if record.certificate_sha256 in self._bindings:
                raise InvalidInput("duplicate trusted TLS certificate identity")
            self._bindings[record.certificate_sha256] = record

    def verify_peer(self, evidence: object) -> VerifiedServicePeer:
        """Never inspect/request a TLS identity from HTTP or proxy headers."""
        if not isinstance(evidence, (ssl.SSLSocket, ssl.SSLObject)):
            raise AuthenticationRequired("direct TLS socket identity required")
        try:
            if (
                not evidence.server_side
                or evidence.context.verify_mode != ssl.CERT_REQUIRED
                or evidence.version() != "TLSv1.3"
                or evidence.cipher() is None
            ):
                raise AuthenticationRequired("TLS peer was not independently authenticated")
            der = evidence.getpeercert(binary_form=True)
            if not isinstance(der, bytes) or not der:
                raise AuthenticationRequired("verified client certificate absent")
            certificate = x509.load_der_x509_certificate(der)
            now = datetime.now(UTC)
            if not (certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc):
                raise AuthenticationRequired("TLS service certificate not currently valid")
            usage = certificate.extensions.get_extension_for_oid(
                ExtensionOID.EXTENDED_KEY_USAGE
            ).value
            if (
                not isinstance(usage, x509.ExtendedKeyUsage)
                or ExtendedKeyUsageOID.CLIENT_AUTH not in usage
            ):
                raise AuthenticationRequired("service certificate cannot authenticate clients")
            basic = certificate.extensions.get_extension_for_oid(
                ExtensionOID.BASIC_CONSTRAINTS
            ).value
            if not isinstance(basic, x509.BasicConstraints) or basic.ca:
                raise AuthenticationRequired("CA certificate cannot be a service identity")
        except AuthenticationRequired:
            raise
        except (ValueError, ssl.SSLError, x509.ExtensionNotFound) as exc:
            raise AuthenticationRequired("verified service certificate rejected") from exc

        fingerprint = hashlib.sha256(der).hexdigest()
        pin = self._bindings.get(fingerprint)
        if pin is None:
            raise AuthenticationRequired("service certificate not registered for DEV")
        expires_at = min(pin.valid_until, certificate.not_valid_after_utc)
        if expires_at <= datetime.now(UTC):
            raise AuthenticationRequired("registered service TLS identity expired")
        return VerifiedServicePeer(
            service_id=pin.service_id,
            key_id=pin.key_id,
            instance_uuid=pin.instance_uuid,
            audience=pin.audience,
            expires_at=expires_at,
            transport="mtls",
        )

"""SSRF-aware HTTPS attachment transport with deployment-owned proxy support.

Only a verified *public* destination IP may be contacted, including through a
configured HTTP CONNECT proxy. Proxy configuration comes from the PROCESS
environment, never an MCP tool argument. The proxy is dialed by a pinned
resolved address and CONNECT uses a validated numeric destination IP (not a
second hostname lookup). TLS SNI and certificate verification use the original
hostname. A proxy unable to support numeric CONNECT fails closed.

HTTPS proxies (TLS to proxy itself) are explicitly unsupported rather than
silently skipped, since wrapping both TLS hops needs a separately reviewed
transport. No request parameters can supply a proxy or override this policy.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import socket
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from types import TracebackType

from .workspace_store import WorkspaceFileError


@dataclass(frozen=True, slots=True)
class _PublicEndpoint:
    uri: urllib.parse.SplitResult
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EgressProxy:
    address: str
    port: int
    pinned_ips: tuple[str, ...]
    tunnel_authorization: str | None = None


def _resolve_addresses(host: str, port: int, *, public_only: bool) -> tuple[str, ...]:
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WorkspaceFileError("attachment hostname cannot be resolved") from exc
    if not results:
        raise WorkspaceFileError("attachment hostname cannot be resolved")
    addresses: set[str] = set()
    for result in results:
        raw = str(result[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise WorkspaceFileError("attachment DNS returned an invalid IP") from exc
        if public_only and not ip.is_global:
            raise WorkspaceFileError("attachment URL resolves to a non-public address")
        addresses.add(str(ip))
    return tuple(sorted(addresses))


def validate_public_attachment_url(value: str) -> _PublicEndpoint:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 8192
        or any(ord(ch) < 32 for ch in value)
    ):
        raise WorkspaceFileError("attachment URL is invalid")
    try:
        uri = urllib.parse.urlsplit(value.strip())
        host = uri.hostname
        port = 443 if uri.port is None else uri.port
        if not 1 <= port <= 65535:
            raise WorkspaceFileError("attachment URL port is invalid")
    except ValueError as exc:
        raise WorkspaceFileError("attachment URL is invalid") from exc
    if (
        uri.scheme.lower() != "https"
        or not host
        or uri.username is not None
        or uri.password is not None
        or uri.fragment
    ):
        raise WorkspaceFileError("attachment URL must be unauthenticated public HTTPS")
    if any(ch in uri.netloc for ch in ("\\", " ")):
        raise WorkspaceFileError("attachment hostname is invalid")
    return _PublicEndpoint(uri, _resolve_addresses(host, port, public_only=True))


def _trusted_proxy(endpoint: _PublicEndpoint) -> _EgressProxy | None:
    host = endpoint.uri.hostname
    assert host is not None
    # One canonical operator-controlled HTTPS egress setting. ALL_PROXY is
    # not a safe implicit alias: it may be inherited from an unrelated
    # service/container, silently changing the target's network trust path.
    # `getproxies_environment` normalizes HTTPS_PROXY and https_proxy safely.
    # NO_PROXY is honored only after target DNS resolves to public IPs.
    proxies = urllib.request.getproxies_environment()
    configured = proxies.get("https")
    if not configured and proxies.get("all"):
        # Never silently turn an intended proxy-only policy into direct
        # internet egress. Operator must choose HTTPS_PROXY explicitly.
        raise WorkspaceFileError("HTTPS_PROXY required; ALL_PROXY is not supported")
    host_port = (
        f"[{host}]:{endpoint.uri.port or 443}"
        if ":" in host
        else (f"{host}:{endpoint.uri.port or 443}")
    )
    # NO_PROXY may contain hostname entries OR explicit hostname:port entries.
    # In both modes, the direct path still uses the pinned public IP.
    if (
        not configured
        or urllib.request.proxy_bypass(host)
        or urllib.request.proxy_bypass(host_port)
    ):
        return None
    try:
        parsed = urllib.parse.urlsplit(
            configured if "://" in configured else "http://" + configured
        )
        port = 80 if parsed.port is None else parsed.port
        if not 1 <= port <= 65535:
            raise WorkspaceFileError("configured HTTPS egress proxy port invalid")
    except ValueError as exc:
        raise WorkspaceFileError("configured HTTPS egress proxy is invalid") from exc
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise WorkspaceFileError("configured HTTPS egress proxy scheme unsupported")
    auth: str | None = None
    if parsed.username is not None:
        username = urllib.parse.unquote_to_bytes(parsed.username)
        password = urllib.parse.unquote_to_bytes(parsed.password or "")
        auth = "Basic " + base64.b64encode(username + b":" + password).decode("ascii")
    return _EgressProxy(
        address=parsed.hostname,
        port=port,
        pinned_ips=_resolve_addresses(parsed.hostname, port, public_only=False),
        tunnel_authorization=auth,
    )


class _PinnedTLSConnection(http.client.HTTPSConnection):
    def __init__(self, endpoint: _PublicEndpoint, proxy: _EgressProxy | None) -> None:
        host = endpoint.uri.hostname
        assert host is not None
        super().__init__(host, port=endpoint.uri.port or 443, timeout=60)
        self._target_addresses = endpoint.addresses
        self._proxy = proxy

    def connect(self) -> None:
        """Dial only vetted addresses; HTTP CONNECT must also target an IP."""
        failure: OSError | None = None
        for target in self._target_addresses:
            attempts = self._proxy.pinned_ips if self._proxy else (target,)
            port = self._proxy.port if self._proxy else self.port
            for address in attempts:
                sock: socket.socket | None = None
                try:
                    sock = socket.create_connection((address, port), timeout=self.timeout)
                    if self._proxy is not None:
                        # An HTTP proxy must NOT resolve the target hostname:
                        # CONNECT directly to the IP already globally vetted.
                        normalized = ipaddress.ip_address(target)
                        numeric = f"[{target}]" if normalized.version == 6 else target
                        headers = (
                            {"Proxy-Authorization": self._proxy.tunnel_authorization}
                            if self._proxy.tunnel_authorization is not None
                            else {}
                        )
                        self.set_tunnel(numeric, port=self.port, headers=headers)
                    self.sock = sock
                    if self._proxy is not None:
                        getattr(self, "_tunnel")()  # noqa: B009
                    self.sock = ssl.create_default_context().wrap_socket(
                        sock, server_hostname=self.host
                    )
                    return
                except OSError as exc:
                    failure = exc
                finally:
                    if self.sock is sock and sock is not None:
                        sock.close()
                        self.sock = None
        raise WorkspaceFileError("attachment HTTPS connection unavailable") from failure


class PinnedAttachmentResponse:
    def __init__(
        self,
        url: str,
        connection: _PinnedTLSConnection,
        response: http.client.HTTPResponse,
    ) -> None:
        self._url = url
        self._connection = connection
        self._response = response
        self.headers = response.headers

    def geturl(self) -> str:
        return self._url

    def read(self, size: int) -> bytes:
        # read1 returns the next buffered/network chunk rather than waiting
        # for an entire requested megabyte from a slow-drip HTTP peer.
        return self._response.read1(size)

    def __enter__(self) -> PinnedAttachmentResponse:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._response.close()
        self._connection.close()


def open_public_attachment(url: str) -> PinnedAttachmentResponse:
    """Read one public HTTPS response with max 5 cross-host redirects.

    Proxy is reselected per-hop, and every redirect is separately verified.
    Credentials are sent only in HTTP proxy CONNECT, never to the target.
    """
    for _ in range(6):
        endpoint = validate_public_attachment_url(url)
        connection = _PinnedTLSConnection(endpoint, _trusted_proxy(endpoint))
        path = endpoint.uri.path or "/"
        if endpoint.uri.query:
            path += "?" + endpoint.uri.query
        try:
            connection.request(
                "GET", path, headers={"User-Agent": "mcp-bridge/0.1 workspace-ingress"}
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                response.close()
                connection.close()
                if not location:
                    raise WorkspaceFileError("attachment redirect missing Location")
                url = urllib.parse.urljoin(url, location)
                continue
            if not 200 <= response.status < 300:
                response.close()
                raise WorkspaceFileError(f"attachment HTTPS status {response.status}")
            return PinnedAttachmentResponse(url, connection, response)
        except BaseException:
            connection.close()
            raise
    raise WorkspaceFileError("attachment exceeded HTTPS redirect limit")

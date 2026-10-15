"""Optional signed Web MCP browser observation, NOT the deployed Web entrypoint.

The normal web_hand.server stays diagnostic-only. A trusted supervisor must
supply an independently authenticated private decision peer, a genuine
Project-owned browser-session resolver, and an isolated browser observer.
Legacy global BrowserManager/CDP and external user's Chrome are never imported.
"""

from __future__ import annotations

import asyncio
import hmac
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token, get_http_request
from hand_runtime import (
    ProtectedHandTools,
    ResolvedEffect,
    ToolEffectBinding,
    TrustedPrivateDecisionPort,
    create_diagnostic_hand_app,
)
from starlette.applications import Starlette

_BROWSER_HANDLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z", re.ASCII)
_MAX_TEXT_CHARS = 4096


@dataclass(frozen=True, slots=True)
class BrowserSnapshotRequest:
    """SDK-verified bearer and original selectors, not browser owner proof."""

    bearer: str
    project_id: UUID
    agent_session_id: UUID
    grant_revision: int
    browser_handle: str
    max_text_chars: int


@dataclass(frozen=True, slots=True)
class BrowserSnapshot:
    """Sanitized, bounded visible text; never arbitrary page HTML or cookies."""

    origin: str
    title: str
    visible_text: str


class TrustedBrowserSnapshotPort(Protocol):
    async def read_snapshot(self, request: BrowserSnapshotRequest) -> BrowserSnapshot:
        """Independently recheck current browser owner/lease and OS isolation."""
        ...


@dataclass(frozen=True, slots=True)
class TrustedWebBrowserPorts:
    """Source-only trusted assembly inputs; no environment or MCP user fallback."""

    effect_resolver: Callable[[dict[str, Any]], Awaitable[ResolvedEffect]]
    private_decision: TrustedPrivateDecisionPort
    snapshots: TrustedBrowserSnapshotPort

    def __post_init__(self) -> None:
        if not all(
            callable(item)
            for item in (
                self.effect_resolver,
                getattr(self.private_decision, "decide", None),
                getattr(self.snapshots, "read_snapshot", None),
            )
        ):
            raise ValueError("browser observation requires all trusted owner ports")


def _canonical_uuid(values: list[str]) -> UUID:
    if len(values) != 1:
        raise ValueError("missing or repeated selector")
    result = UUID(values[0])
    if result.version != 4 or str(result) != values[0]:
        raise ValueError("noncanonical UUIDv4 selector")
    return result


def _request_for_owner(browser_handle: str, max_text_chars: int) -> BrowserSnapshotRequest:
    """Capture original signed actor selectors again after the private PDP.

    The worker is an independent trust boundary: this is its input, not a
    declaration that the browser context actually belongs to the actor.
    """
    if (
        not isinstance(browser_handle, str)
        or _BROWSER_HANDLE.fullmatch(browser_handle) is None
        or type(max_text_chars) is not int
        or not 1 <= max_text_chars <= _MAX_TEXT_CHARS
    ):
        raise ValueError("unverified browser snapshot scope")
    request = get_http_request()
    access = get_access_token()
    if access is None or not isinstance(access.token, str) or not access.token:
        raise ValueError("signed bearer unavailable")
    authorization = request.headers.getlist("authorization")
    if (
        len(authorization) != 1
        or not hmac.compare_digest(authorization[0], "Bearer " + access.token)
        or request.headers.getlist("cookie")
    ):
        raise ValueError("signed actor request mismatch")
    project = _canonical_uuid(request.headers.getlist("x-briareus-project-uuid"))
    agent_session = _canonical_uuid(request.headers.getlist("x-briareus-agent-session-uuid"))
    revisions = request.headers.getlist("x-briareus-grant-revision")
    if len(revisions) != 1 or not revisions[0].isascii() or not revisions[0].isdecimal():
        raise ValueError("missing or repeated revision")
    revision = int(revisions[0])
    if not 1 <= revision <= 2**63 - 1 or str(revision) != revisions[0]:
        raise ValueError("noncanonical revision")
    return BrowserSnapshotRequest(
        access.token, project, agent_session, revision, browser_handle, max_text_chars
    )


def _public_snapshot(snapshot: BrowserSnapshot, max_chars: int) -> dict[str, str]:
    """Never expose raw CDP, storage, cookies, request headers or a full URL."""
    if not isinstance(snapshot, BrowserSnapshot):
        raise ValueError("snapshot port returned an untrusted payload")
    origin = urlsplit(snapshot.origin)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username is not None
        or origin.password is not None
        or snapshot.origin != f"{origin.scheme}://{origin.netloc}"
        or len(snapshot.origin) > 240
        or not isinstance(snapshot.title, str)
        or not isinstance(snapshot.visible_text, str)
        or len(snapshot.title) > 160
        or len(snapshot.visible_text) > max_chars
        or any(ord(ch) < 32 and ch not in "\t\r\n" for ch in snapshot.visible_text)
        or any(ord(ch) < 32 for ch in snapshot.title)
    ):
        raise ValueError("browser snapshot exceeds public safe contract")
    return {
        "origin": snapshot.origin,
        "title": snapshot.title,
        "visible_text": snapshot.visible_text,
    }


def build_protected_web_browser_app(ports: TrustedWebBrowserPorts) -> Starlette:
    """Stage one read-only effect; never called by deployed web_hand.server.

    The resolver must bind the caller handle to a real owner Project,
    browser lease and immutable canonical arguments. The authenticated private
    Cedar port must attest that exact effect. The isolated browser worker MUST
    recheck actor/lease and Project mapping immediately before observation.
    """
    if not isinstance(ports, TrustedWebBrowserPorts):
        raise ValueError("trusted Web ports must be supplied by a supervisor")

    def register(mcp: FastMCP) -> None:
        @mcp.tool(
            name="browser_snapshot",
            title="Read a Project-scoped browser snapshot",
            annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
            run_in_thread=False,
        )
        async def browser_snapshot(
            browser_handle: str, max_text_chars: int = 2048
        ) -> dict[str, str]:
            try:
                signed_request = _request_for_owner(browser_handle, max_text_chars)
                observation = await ports.snapshots.read_snapshot(signed_request)
                return _public_snapshot(observation, max_text_chars)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never expose bearer, Project ID, browser data or worker details.
                raise ToolError("WEB_BROWSER_OWNER_OR_AUTHORIZATION_UNAVAILABLE") from None

    return create_diagnostic_hand_app(
        hand="web",
        source_root=Path(__file__).resolve().parents[1],
        unavailable_code="WEB_OAUTH_AUTHORIZATION_UNAVAILABLE",
        health_fields={"authorization": "owner_ports_injected_unaccepted"},
        protected_tools=ProtectedHandTools(
            register=register,
            effect_bindings={
                "browser_snapshot": ToolEffectBinding(
                    "web.access", "browser_session", ports.effect_resolver
                )
            },
            private_decision=ports.private_decision,
        ),
    )

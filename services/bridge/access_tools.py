from __future__ import annotations

from fastmcp import FastMCP

from common.access_contracts import AccountScope
from common.mcp_surfaces import surface_id
from common.models import JsonObject
from common.runtime_annotations import READ_ONLY_LOCAL, WRITE_LOCAL

from .access_middleware import oauth_context
from .authorization_access_client import AuthorizationAccessClient


def register_access_session_tools(
    mcp: FastMCP,
    *,
    surface: str,
    client: AuthorizationAccessClient,
) -> None:
    resolved_surface_id = int(surface_id(surface))

    @mcp.tool(
        name="access_session_open",
        title="Open agent access session",
        annotations=WRITE_LOCAL,
    )
    async def access_session_open(label: str = "") -> JsonObject:
        """Create a new active read-only agent session for this MCP surface."""
        session = await client.open(
            context=oauth_context(),
            surface_id=resolved_surface_id,
            label=label,
        )
        return session.model_dump(mode="json")

    @mcp.tool(
        name="access_session_status",
        title="Agent access session status",
        annotations=READ_ONLY_LOCAL,
    )
    async def access_session_status(session_id: str) -> JsonObject:
        """Read one agent session owned by this OAuth connection and MCP surface."""
        session = await client.status(
            context=oauth_context(),
            surface_id=resolved_surface_id,
            session_uid=session_id,
        )
        return session.model_dump(mode="json")

    @mcp.tool(
        name="access_session_update",
        title="Update agent access session",
        annotations=WRITE_LOCAL,
    )
    async def access_session_update(session_id: str, label: str = "") -> JsonObject:
        """Update safe session metadata such as its display label."""
        session = await client.update(
            context=oauth_context(),
            surface_id=resolved_surface_id,
            session_uid=session_id,
            label=label,
        )
        return session.model_dump(mode="json")

    @mcp.tool(
        name="access_session_request_extension",
        title="Request agent session extension",
        annotations=WRITE_LOCAL,
    )
    async def access_session_request_extension(
        session_id: str,
        requested_expires_at: int,
    ) -> JsonObject:
        """Request a new session expiry; administration approval is required."""
        pending = await client.request_extension(
            context=oauth_context(),
            surface_id=resolved_surface_id,
            session_uid=session_id,
            requested_expires_at=requested_expires_at,
        )
        result = pending.model_dump(mode="json")
        result["session_id"] = session_id
        result["instructions"] = (
            f"Ask the user to approve extension request {pending.id} in the administration UI."
        )
        return result

    @mcp.tool(
        name="access_session_request_full_access",
        title="Request full MCP access",
        annotations=WRITE_LOCAL,
    )
    async def access_session_request_full_access(
        session_id: str,
        account_scope: AccountScope = "none",
        account_ids: list[str] | None = None,
    ) -> JsonObject:
        """Request mutating access for this MCP surface and optional account scope."""
        pending = await client.request_full_access(
            context=oauth_context(),
            surface_id=resolved_surface_id,
            session_uid=session_id,
            account_scope=account_scope,
            account_ids=account_ids or [],
        )
        result = pending.model_dump(mode="json")
        result["session_id"] = session_id
        result["instructions"] = (
            f"Ask the user to approve full-access request {pending.id} in the administration UI."
        )
        return result

    @mcp.tool(
        name="access_session_close",
        title="Close agent access session",
        annotations=WRITE_LOCAL,
    )
    async def access_session_close(session_id: str) -> JsonObject:
        """Revoke this agent session voluntarily."""
        session = await client.close_session(
            context=oauth_context(),
            surface_id=resolved_surface_id,
            session_uid=session_id,
        )
        return session.model_dump(mode="json")

    @mcp.tool(
        name="access_session_reissue",
        title="Reissue agent access session",
        annotations=WRITE_LOCAL,
    )
    async def access_session_reissue(
        session_id: str,
        label: str = "",
    ) -> JsonObject:
        """Replace an expired/revoked session with a fresh read-only session."""
        session = await client.reissue(
            context=oauth_context(),
            surface_id=resolved_surface_id,
            session_uid=session_id,
            label=label,
        )
        return session.model_dump(mode="json")

from __future__ import annotations

import json
from collections.abc import Sequence

import httpx
import mcp_types as mt
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import InputRequiredToolResult, Tool, ToolResult
from mcp.types import TextContent

from common.access_contracts import OAuthContext, SessionSnapshot
from common.mcp_surfaces import surface_id

from .access_client import AccessServiceClient

_ACCESS_TOOL_PREFIX = "access_session_"
_SAFE_ACCOUNT_DISCOVERY: dict[str, frozenset[str]] = {
    "github": frozenset({"github_accounts"}),
    "gitlab": frozenset({"accounts"}),
    "observability": frozenset({"observability_sources"}),
}
_SAFE_BRIDGE_TOOLS = frozenset(
    {
        "bridge_ping",
        "bridge_build_info",
        "bridge_backends",
        "bridge_tools",
        "bridge_capabilities",
    }
)


def oauth_context() -> OAuthContext:
    token = get_access_token()
    if token is None:
        raise RuntimeError("OAuth access token is unavailable")
    claims = token.claims or {}
    user_id = token.subject or ""
    oauth_session_id = str(claims.get("session_id") or "")
    if not user_id or not token.client_id or not oauth_session_id:
        raise RuntimeError("OAuth token is missing local identity/session claims")
    return OAuthContext(
        user_id=user_id,
        client_id=token.client_id,
        oauth_session_id=oauth_session_id,
    )


def _with_session_parameter(tool: Tool) -> Tool:
    if tool.name.startswith(_ACCESS_TOOL_PREFIX):
        return tool
    parameters = dict(tool.parameters)
    properties = dict(parameters.get("properties") or {})
    if "session_id" not in properties:
        properties["session_id"] = {
            "type": "string",
            "description": (
                "Agent access session UID. Required when session control is enabled "
                "for this MCP surface."
            ),
        }
    parameters["properties"] = properties
    return tool.model_copy(update={"parameters": parameters})


def _session_meta(session: SessionSnapshot | None) -> dict[str, object]:
    if session is None:
        return {}
    return {
        "session_id": session.uid,
        "status": session.status,
        "access_level": session.access_level,
        "expires_at": session.expires_at,
        "account_scope": session.account_scope,
    }


class AccessSessionMiddleware(Middleware):
    def __init__(
        self,
        *,
        surface: str,
        client: AccessServiceClient,
    ) -> None:
        self.surface = surface
        self.surface_id = int(surface_id(surface))
        self.client = client

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        return [_with_session_parameter(tool) for tool in tools]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        if tool_name.startswith(_ACCESS_TOOL_PREFIX):
            return await call_next(context)

        arguments = dict(context.message.arguments or {})
        raw_session_id = arguments.pop("session_id", "")
        session_uid = raw_session_id if isinstance(raw_session_id, str) else ""

        tool = await self._resolve_tool(context, tool_name)
        requires_full_access = not self._is_base_read_only(tool_name, tool)
        account_id_raw = arguments.get("account_id", "")
        account_id = account_id_raw if isinstance(account_id_raw, str) else ""

        try:
            decision = await self.client.validate(
                context=oauth_context(),
                surface_id=self.surface_id,
                session_uid=session_uid,
                tool_name=tool_name,
                requires_full_access=requires_full_access,
                account_id=account_id,
            )
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            return self._error(
                "access_service_unavailable",
                "Access validation is temporarily unavailable.",
                detail=type(exc).__name__,
            )

        if not decision.allowed:
            return self._error(
                decision.code,
                self._message_for_code(decision.code),
                session=decision.session,
                retry_after_seconds=decision.retry_after_seconds,
            )

        forwarded = context.message.model_copy(update={"arguments": arguments})
        result = await call_next(context.copy(message=forwarded))
        return self._with_session_result(result, decision.session)

    async def _resolve_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        tool_name: str,
    ) -> Tool | None:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            return None
        return await fastmcp_context.fastmcp.get_tool(tool_name)

    def _is_base_read_only(self, tool_name: str, tool: Tool | None) -> bool:
        if self.surface == "root" and tool_name in _SAFE_BRIDGE_TOOLS:
            return True
        if tool_name in _SAFE_ACCOUNT_DISCOVERY.get(self.surface, frozenset()):
            return True
        return bool(
            tool is not None
            and tool.annotations is not None
            and tool.annotations.read_only_hint is True
        )

    @staticmethod
    def _with_session_result(
        result: ToolResult, session: SessionSnapshot | None
    ) -> ToolResult:
        if session is None or isinstance(result, InputRequiredToolResult):
            return result
        session_context = _session_meta(session)
        meta = dict(result.meta or {})
        meta["access_session"] = session_context
        content = list(result.content)
        content.append(
            TextContent(
                type="text",
                text=json.dumps(
                    {"access_session": session_context},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        # Rebuild instead of model_copy: proxied ToolResult may retain a private
        # raw MCP result whose wire serialization would otherwise ignore updates.
        return ToolResult(
            content=content,
            structured_content=result.structured_content,
            meta=meta,
            is_error=result.is_error,
        )

    @staticmethod
    def _message_for_code(code: str) -> str:
        messages = {
            "session_required": (
                "A session is required. Call access_session_open and retry with session_id."
            ),
            "session_invalid": "The session is invalid for this OAuth connection or MCP surface.",
            "session_expired": "The session expired. Call access_session_reissue.",
            "session_revoked": "The session was revoked. Call access_session_reissue.",
            "full_access_required": (
                "This action requires full access. Call access_session_request_full_access "
                "and ask the user to approve it in the administration UI."
            ),
            "account_scope_denied": (
                "This session does not have full access to the requested account."
            ),
            "rate_limited": "Too many invalid session attempts. Retry after the backoff period.",
            "oauth_session_revoked": "OAuth authorization was revoked; reconnect this MCP surface.",
        }
        return messages.get(code, "Access denied.")

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        session: SessionSnapshot | None = None,
        retry_after_seconds: int = 0,
        detail: str = "",
    ) -> ToolResult:
        payload: dict[str, object] = {
            "error": code,
            "message": message,
        }
        if retry_after_seconds:
            payload["retry_after_seconds"] = retry_after_seconds
        if detail:
            payload["detail"] = detail
        session_context = _session_meta(session)
        if session_context:
            payload["access_session"] = session_context
        meta = {"access_session": session_context}
        content = [TextContent(type="text", text=message)]
        if session_context:
            content.append(
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"access_session": session_context},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        return ToolResult(
            content=content,
            structured_content=payload,
            meta=meta,
            is_error=True,
        )

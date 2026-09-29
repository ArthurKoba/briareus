from __future__ import annotations

import base64
import json
from contextvars import ContextVar
from urllib.parse import parse_qs, urlsplit

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.providers.github import GitHubProvider
from key_value.aio.adapters.pydantic import PydanticAdapter
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from common.mcp_surfaces import allowed_resource_urls, resource_url
from common.models import StrictModel
from common.settings import AuthServiceSettings

_RESOURCE_BINDING_TTL_SECONDS = 10 * 60
_TRANSACTION_TTL_SECONDS = 15 * 60


class ResourceBinding(StrictModel):
    resource: str


class MultiResourceGitHubProvider(GitHubProvider):
    """One OAuth issuer serving multiple exact MCP resource audiences."""

    def __init__(self, settings: AuthServiceSettings) -> None:
        self.settings = settings
        self._resource_context: ContextVar[str | None] = ContextVar(
            "oauth_resource",
            default=None,
        )
        self._allowed_resources = allowed_resource_urls(settings.public_base_url)
        self._root_resource = resource_url(settings.public_base_url, "root")

        super().__init__(
            client_id=settings.oauth_client_id,
            client_secret=settings.oauth_client_secret,
            base_url=settings.public_base_url,
            issuer_url=settings.public_base_url,
            required_scopes=["read:user"],
            jwt_signing_key=settings.oauth_jwt_signing_key,
            allowed_client_redirect_uris=[
                "https://chatgpt.com/connector_platform_oauth_redirect"
            ],
            require_authorization_consent="external",
            enable_cimd=False,
            forward_resource=False,
            cache_ttl_seconds=settings.github_token_cache_ttl_seconds,
            fallback_refresh_token_expiry_seconds=30 * 24 * 60 * 60,
            fastmcp_access_token_expiry_seconds=30 * 60,
        )

        self._resource_bindings: PydanticAdapter[ResourceBinding] = PydanticAdapter[
            ResourceBinding
        ](
            key_value=self._client_storage,
            pydantic_model=ResourceBinding,
            default_collection="koba-oauth-resource-bindings",
            raise_on_validation_error=True,
        )
        self._resource_issuers = {
            resource: JWTIssuer(
                issuer=str(self.issuer_url),
                audience=resource,
                signing_key=self._jwt_signing_key,
            )
            for resource in self._allowed_resources
        }

    @property
    def allowed_resources(self) -> frozenset[str]:
        return self._allowed_resources

    def issuer_for_resource(self, resource: str | None) -> JWTIssuer:
        return self._resource_issuers[self.canonical_resource(resource)]

    @property
    def jwt_issuer(self) -> JWTIssuer:
        return self.issuer_for_resource(
            self._resource_context.get() or self._root_resource
        )

    def canonical_resource(self, value: str | None) -> str:
        if not value:
            return self._root_resource
        parsed = urlsplit(value)
        candidate = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if candidate not in self._allowed_resources:
            raise ValueError(f"unsupported OAuth resource: {candidate}")
        return candidate

    @staticmethod
    def _transaction_id(url: str) -> str:
        query = parse_qs(urlsplit(url).query)
        for key in ("state", "txn_id"):
            values = query.get(key)
            if values and values[0]:
                return values[0]
        raise RuntimeError("OAuth transaction id missing from authorization redirect")

    @staticmethod
    def _jwt_audience_unverified(token: str) -> str | None:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload).decode())
        except (IndexError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        audience = claims.get("aud") if isinstance(claims, dict) else None
        if isinstance(audience, str):
            return audience
        if (
            isinstance(audience, list)
            and len(audience) == 1
            and isinstance(audience[0], str)
        ):
            return audience[0]
        return None

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        resource = self.canonical_resource(params.resource)
        redirect = await super().authorize(
            client,
            params.model_copy(update={"resource": None}),
        )
        txn_id = self._transaction_id(redirect)
        transaction = await self._transaction_store.get(key=txn_id)
        if transaction is None:
            raise RuntimeError("OAuth transaction disappeared before resource binding")
        await self._transaction_store.put(
            key=txn_id,
            value=transaction.model_copy(update={"resource": resource}),
            ttl=_TRANSACTION_TTL_SECONDS,
        )
        return redirect

    async def _handle_idp_callback(
        self,
        request: Request,
    ) -> HTMLResponse | RedirectResponse:
        txn_id = request.query_params.get("state")
        transaction = (
            await self._transaction_store.get(key=txn_id)
            if txn_id
            else None
        )
        resource = (
            self.canonical_resource(transaction.resource)
            if transaction is not None
            else None
        )

        response = await super()._handle_idp_callback(request)

        if resource and isinstance(response, RedirectResponse):
            location = response.headers.get("location", "")
            codes = parse_qs(urlsplit(location).query).get("code")
            if codes and codes[0]:
                await self._resource_bindings.put(
                    key=codes[0],
                    value=ResourceBinding(resource=resource),
                    ttl=_RESOURCE_BINDING_TTL_SECONDS,
                )
        return response

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        loaded = await super().load_authorization_code(client, authorization_code)
        if loaded is None:
            return None
        binding = await self._resource_bindings.get(key=authorization_code)
        if binding is None:
            return None
        resource = self.canonical_resource(binding.resource)
        return loaded.model_copy(update={"resource": resource})

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        resource = self.canonical_resource(authorization_code.resource)
        token = self._resource_context.set(resource)
        try:
            return await super().exchange_authorization_code(client, authorization_code)
        finally:
            self._resource_context.reset(token)
            await self._resource_bindings.delete(key=authorization_code.code)

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        loaded = await super().load_refresh_token(client, refresh_token)
        if loaded is None:
            return None
        audience = self._jwt_audience_unverified(refresh_token)
        try:
            resource = self.canonical_resource(audience)
        except ValueError:
            return None
        return loaded.model_copy(update={"resource": resource})

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        resource = self.canonical_resource(refresh_token.resource)
        token = self._resource_context.set(resource)
        try:
            return await super().exchange_refresh_token(client, refresh_token, scopes)
        finally:
            self._resource_context.reset(token)

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        audience = self._jwt_audience_unverified(token.token)
        try:
            resource = self.canonical_resource(audience)
        except ValueError:
            return

        context = self._resource_context.set(resource)
        try:
            await super().revoke_token(token)
        finally:
            self._resource_context.reset(context)

    async def load_access_token(self, token: str) -> AccessToken | None:
        audience = self._jwt_audience_unverified(token)
        try:
            resource = self.canonical_resource(audience)
        except ValueError:
            return None

        context = self._resource_context.set(resource)
        try:
            access = await super().load_access_token(token)
        finally:
            self._resource_context.reset(context)

        if access is None:
            return None
        return access.model_copy(
            update={
                "token": token,
                "resource": resource,
            }
        )

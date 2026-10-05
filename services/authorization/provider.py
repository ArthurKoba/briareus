from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

import jwt
from fastmcp.server.auth import AccessToken as FastMCPAccessToken
from fastmcp.server.auth.auth import OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from common.mcp_surfaces import allowed_resource_urls, canonical_public_base_url, resource_url
from common.settings import AuthorizationServiceSettings

from .repository import AuthorizationRepository
from .security import (
    issue_access_token,
    load_private_key,
    public_jwk,
    random_token,
    verify_access_token,
)

_AUTHORIZATION_CODE_TTL_SECONDS = 5 * 60
_TRANSACTION_TTL_SECONDS = 10 * 60
_REQUIRED_SCOPES = ["read:user"]


class LocalOAuthProvider(OAuthProvider):
    def __init__(
        self, settings: AuthorizationServiceSettings, repository: AuthorizationRepository
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.issuer = canonical_public_base_url(settings.public_base_url)
        self._allowed_resources = allowed_resource_urls(self.issuer)
        self._root_resource = resource_url(self.issuer, "root")
        self._allowed_redirect_uris = frozenset(settings.allowed_redirect_uris)
        self._private_key = load_private_key(settings.jwt_private_key_pem)
        self._public_key = self._private_key.public_key()

        super().__init__(
            base_url=self.issuer,
            issuer_url=self.issuer,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=_REQUIRED_SCOPES,
                default_scopes=_REQUIRED_SCOPES,
            ),
            revocation_options=RevocationOptions(enabled=True),
            required_scopes=_REQUIRED_SCOPES,
        )

    @property
    def jwks(self) -> dict[str, object]:
        return {"keys": [public_jwk(self._public_key, kid=self.settings.jwt_key_id)]}

    def canonical_resource(self, value: str | None) -> str:
        if not value:
            return self._root_resource
        parsed = urlsplit(value)
        candidate = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if candidate not in self._allowed_resources:
            raise AuthorizeError(
                error="invalid_target",
                error_description=f"Unsupported OAuth resource: {candidate}",
            )
        return candidate

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await self.repository.get_client(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        redirect_uris = tuple(str(uri) for uri in client_info.redirect_uris or ())
        if not redirect_uris:
            raise RegistrationError(
                "invalid_client_metadata",
                "At least one redirect URI is required",
            )
        invalid = [uri for uri in redirect_uris if uri not in self._allowed_redirect_uris]
        if invalid:
            raise RegistrationError(
                "invalid_redirect_uri",
                f"Redirect URI is not allowed: {invalid[0]}",
            )
        if client_info.scope:
            invalid_scopes = set(client_info.scope.split()) - set(_REQUIRED_SCOPES)
            if invalid_scopes:
                raise RegistrationError(
                    "invalid_client_metadata",
                    f"Unsupported OAuth scopes: {', '.join(sorted(invalid_scopes))}",
                )
        await self.repository.register_client(client_info)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if client.client_id is None:
            raise AuthorizeError("unauthorized_client", "OAuth client ID is required")
        resource = self.canonical_resource(params.resource)
        transaction_id = random_token(24)
        expires_at = datetime.now(UTC) + timedelta(seconds=_TRANSACTION_TTL_SECONDS)
        payload = params.model_copy(update={"resource": resource}).model_dump(mode="json")
        await self.repository.create_transaction(
            transaction_id=transaction_id,
            client_id=client.client_id,
            params=payload,
            expires_at=expires_at,
        )
        return f"{self.issuer}/authorization/login?{urlencode({'transaction': transaction_id})}"

    async def login_context(self, transaction_id: str) -> dict[str, str] | None:
        transaction = await self.repository.load_transaction(transaction_id)
        if transaction is None:
            return None
        client = await self.repository.get_client(transaction.client_id)
        params = AuthorizationParams.model_validate(json.loads(transaction.params_json))
        resource = self.canonical_resource(params.resource)
        return {
            "client_name": (client.client_name if client and client.client_name else "MCP client"),
            "resource": resource,
        }

    async def complete_login(
        self,
        *,
        transaction_id: str,
        username: str,
        password: str,
    ) -> str | None:
        transaction = await self.repository.load_transaction(transaction_id)
        if transaction is None:
            return None
        user = await self.repository.authenticate_user(username, password)
        if user is None:
            return None

        consumed = await self.repository.consume_transaction(transaction_id)
        if consumed is None:
            return None
        params = AuthorizationParams.model_validate(json.loads(consumed.params_json))
        resource = self.canonical_resource(params.resource)
        code = random_token(32)
        await self.repository.create_authorization_code(
            code=code,
            client_id=consumed.client_id,
            user_id=user.id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=list(params.scopes or _REQUIRED_SCOPES),
            resource=resource,
            code_challenge=params.code_challenge,
            expires_at=datetime.now(UTC) + timedelta(seconds=_AUTHORIZATION_CODE_TTL_SECONDS),
        )
        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        record = await self.repository.load_authorization_code(
            client.client_id, authorization_code
        )
        if record is None:
            return None
        return AuthorizationCode(
            code=record.code,
            client_id=record.client_id,
            redirect_uri=AnyUrl(record.redirect_uri),
            redirect_uri_provided_explicitly=record.redirect_uri_provided_explicitly,
            scopes=list(json.loads(record.scopes_json)),
            expires_at=record.expires_at.timestamp(),
            code_challenge=record.code_challenge,
            resource=record.resource,
            subject=record.user_id,
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        if client.client_id is None or authorization_code.subject is None:
            raise TokenError("invalid_grant", "Authorization code is incomplete")
        if not await self.repository.consume_authorization_code(
            client.client_id, authorization_code.code
        ):
            raise TokenError("invalid_grant", "Authorization code is invalid or already used")

        user = await self.repository.get_user(authorization_code.subject)
        if user is None or not user.enabled:
            raise TokenError("invalid_grant", "User is unavailable")

        resource = self.canonical_resource(authorization_code.resource)
        oauth_session = await self.repository.create_oauth_session(
            user_id=user.id,
            client_id=client.client_id,
            resource=resource,
        )
        return await self._issue_token_pair(
            client_id=client.client_id,
            user_id=user.id,
            username=user.username,
            scopes=list(authorization_code.scopes),
            resource=resource,
            session_id=oauth_session.id,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        record = await self.repository.load_refresh_token(client.client_id, refresh_token)
        if record is None:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=record.client_id,
            scopes=list(json.loads(record.scopes_json)),
            expires_at=int(record.expires_at.timestamp()) if record.expires_at else None,
            resource=record.resource,
            subject=record.user_id,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if client.client_id is None:
            raise TokenError("invalid_client", "OAuth client ID is required")
        if not set(scopes).issubset(set(refresh_token.scopes)):
            raise TokenError("invalid_scope", "Requested scopes exceed the refresh token")

        record = await self.repository.rotate_refresh_token(
            client.client_id,
            refresh_token.token,
        )
        if record is None:
            raise TokenError("invalid_grant", "Refresh token is invalid or already used")

        user = await self.repository.get_user(record.user_id)
        if user is None or not user.enabled:
            await self.repository.revoke_oauth_session(record.session_id)
            raise TokenError("invalid_grant", "User is unavailable")

        return await self._issue_token_pair(
            client_id=client.client_id,
            user_id=user.id,
            username=user.username,
            scopes=scopes,
            resource=record.resource,
            session_id=record.session_id,
        )

    async def _issue_token_pair(
        self,
        *,
        client_id: str,
        user_id: str,
        username: str,
        scopes: list[str],
        resource: str,
        session_id: str,
    ) -> OAuthToken:
        access_token, _expires_at = issue_access_token(
            private_key=self._private_key,
            kid=self.settings.jwt_key_id,
            issuer=self.issuer,
            audience=resource,
            subject=user_id,
            username=username,
            client_id=client_id,
            scopes=scopes,
            session_id=session_id,
            ttl_seconds=self.settings.access_token_ttl_seconds,
        )
        refresh_token = random_token(48)
        refresh_expires_at = datetime.now(UTC) + timedelta(
            seconds=self.settings.refresh_token_ttl_seconds
        )
        await self.repository.store_refresh_token(
            token=refresh_token,
            session_id=session_id,
            client_id=client_id,
            user_id=user_id,
            scopes=scopes,
            resource=resource,
            expires_at=refresh_expires_at,
        )
        await self.repository.touch_oauth_session(session_id)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=self.settings.access_token_ttl_seconds,
            refresh_token=refresh_token,
            scope=" ".join(scopes),
        )

    @staticmethod
    def _unverified_audience(token: str) -> str | None:
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return None
        audience = claims.get("aud")
        if isinstance(audience, str):
            return audience
        if (
            isinstance(audience, list)
            and len(audience) == 1
            and isinstance(audience[0], str)
        ):
            return audience[0]
        return None

    async def load_access_token(self, token: str) -> FastMCPAccessToken | None:
        audience = self._unverified_audience(token)
        try:
            resource = self.canonical_resource(audience)
        except AuthorizeError:
            return None
        payload = verify_access_token(
            token,
            public_key=self._public_key,
            issuer=self.issuer,
            audience=resource,
        )
        if payload is None:
            return None

        session_id = str(payload.get("session_id") or "")
        subject = str(payload.get("sub") or "")
        client_id = str(payload.get("client_id") or "")
        if not session_id or not subject or not client_id:
            return None
        if not await self.repository.oauth_session_active(session_id, user_id=subject):
            return None

        scope = payload.get("scope")
        scopes = scope.split() if isinstance(scope, str) else []
        if not set(_REQUIRED_SCOPES).issubset(scopes):
            return None
        await self.repository.touch_oauth_session(session_id)
        return FastMCPAccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(payload["exp"]),
            resource=resource,
            subject=subject,
            claims=payload,
        )

    async def revoke_token(
        self, token: FastMCPAccessToken | RefreshToken
    ) -> None:
        if isinstance(token, RefreshToken):
            await self.repository.revoke_refresh_token(token.token)
            return

        claims = token.claims or {}
        session_id = str(claims.get("session_id") or "")
        if session_id:
            await self.repository.revoke_oauth_session(session_id)

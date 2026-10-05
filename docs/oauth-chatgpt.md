# ChatGPT OAuth flow

The source target uses `https://authorization.mcp.koba-nexus.ru` as the local OAuth authorization server. MCP protected resources remain under `https://mcp.koba-nexus.ru`.

- OAuth Authorization Code + PKCE is provided through FastMCP/MCP SDK protocol routes.
- Dynamic Client Registration (DCR) remains available for compatible clients.
- The default allowed redirect URI is `https://chatgpt.com/connector_platform_oauth_redirect`.
- Platform identity is a local `authorization` user; GitHub/GitLab/provider accounts are integrations, not identity providers.
- Each public MCP URL is a separate RFC 8707 resource/audience.
- Access tokens are short-lived ES256 JWTs signed only by `authorization`.
- Gateway verifies tokens locally with the public key/JWKS and cannot mint tokens.
- Refresh tokens and OAuth session state are durable in the `authorization` PostgreSQL database.

After OAuth succeeds, agent access sessions are a second independent authorization layer inside `authorization`. When session enforcement is enabled for an MCP surface, normal tool calls require the agent session UID in addition to the OAuth bearer token.

The local login form is served at:

```text
https://authorization.mcp.koba-nexus.ru/authorization/login
```

The authorization server exposes its public signing keys at:

```text
https://authorization.mcp.koba-nexus.ru/.well-known/jwks.json
```

See `docs/architecture/authorization-access.md` for the MVP and post-MVP access model.

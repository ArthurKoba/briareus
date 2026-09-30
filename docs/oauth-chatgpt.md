# ChatGPT OAuth flow

The production bridge uses GitHub OAuth through FastMCP with a deliberately narrow client policy:

- Dynamic Client Registration (DCR) is enabled.
- Client ID Metadata Documents (CIMD) are disabled.
- The only allowed OAuth client redirect URI is `https://chatgpt.com/connector_platform_oauth_redirect`.
- GitHub remains the identity provider, and `GITHUB_OAUTH_ALLOWED_USERS` is the final user allowlist.
- Access tokens issued to MCP clients are valid for 24 hours.
- Refresh tokens use a 30-day fallback lifetime when the upstream provider does not provide one.
- Every token is bound to the exact MCP resource audience that requested it.

The public authorization server is the deployment's `MCP_PUBLIC_BASE_URL`. For the current deployment the GitHub OAuth callback is:

```text
https://mcp.koba-nexus.ru/auth/callback
```

The auth runtime owns DCR registrations, authorization transactions, refresh state, and token issuance. Its persistent `/auth` volume must survive container restarts and deployments so reconnects do not discard OAuth state.

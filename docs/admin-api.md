# Admin API

The private `admin-api` runtime owns provider accounts, encrypted credentials, MCP invocation history, Files administration, authenticated sessions, typed frontend APIs and realtime transport. Provider runtimes never open the Admin API database directly.

## Storage

Admin API owns a persistent SQLite database at `/admin-api/admin.sqlite3` on the `admin-api` volume. SQLAlchemy is the persistence adapter. The project is currently deployed under a zero-state pre-production contract. The schema is created from current metadata at startup; if the on-disk Admin API schema is incompatible with current metadata, Admin API initializes its own SQLite tables instead of carrying migration compatibility.

Credentials are encrypted with Fernet before persistence. The master key is a deployment bootstrap secret and is never stored in SQLite.

## Provider accounts

Account roles do not exist. Every account has a stable UUID and a provider-local unique alias. MCP calls select accounts explicitly by UUID or alias.

### GitHub

GitHub has a dedicated account table and admin view. The public API URL is fixed to `https://api.github.com`. Supported auth types are:

- `github_app`: App ID plus encrypted private-key PEM;
- `github_token`: encrypted PAT/user token, with no App ID requirement.

### GitLab

GitLab has a separate account table and admin view. Each account stores its own `base_url`, so `gitlab.com` and self-hosted instances use the same runtime contract. Supported auth types are `private_token`, `bearer` and `job_token`; TLS verification and an optional custom CA PEM are per account.

## MCP account selection and permissions

Provider tool catalogs are static. Adding, disabling or removing an account never adds or removes GitHub/GitLab tools. Account-scoped calls always accept `account_id`; if the selector is missing, disabled, inaccessible or insufficiently privileged, that call returns a runtime/provider error.

Discovery is explicit:

- GitHub: `github_accounts` lists all configured identities (including disabled accounts) and potential capability classes; `github_account_capabilities` reports GitHub-App permission ceilings and optionally repository-effective permissions. User-token account-global permissions are reported as unknown when GitHub does not expose a reliable global map.
- GitLab: `accounts` lists all configured identities (including disabled accounts) and potential capability classes; `account_capabilities` reports PAT scopes when the server exposes `/personal_access_tokens/self` and optionally project-level access. Other token types are explicitly reported as project/resource dependent.

These capability tools are informational. Provider authorization remains authoritative at invocation time.

## Internal API

Private runtimes authenticate with `ADMIN_API_SERVICE_TOKEN`. The internal API lists public account metadata, resolves one credential for an explicit provider/account selector, and accepts invocation events. It does not expose account mutation to MCP runtimes.

## Public Admin API

The `admin-api` service is the versioned administration backend for the standalone Admin UI.
It is published directly at:

```text
https://api.mcp.koba-nexus.ru/v1
```

Canonical frontend-facing surfaces are `/v1/session`, `/v1/login`, `/v1/logout`, dashboard,
accounts, calls, files, terminal, analysis, OAuth, settings, telemetry, `/v1/realtime`, and
`/v1/browser/operator/ws`. The MCP Gateway does not proxy these routes.

The Admin UI is a separate application at `https://admin.mcp.koba-nexus.ru/`. Cross-origin
REST requests use credentials and are restricted by `ADMIN_UI_ORIGIN`; realtime/browser
WebSockets validate the same configured origin and Admin API session.

## Invocation logging

Tool-call logging is best-effort and never makes a successful MCP call depend on Admin API availability. Payload capture is bounded and can be disabled independently. Sensitive structured fields such as authorization headers, cookies, tokens, passwords, secrets, private keys and API keys are redacted before an event is sent to Admin API.

Retention is enforced both while appending events and by the periodic Admin API maintenance task. Logs can also be cleared or retention can be applied immediately through the Admin API.

## Files administration

Admin API mounts the same `/workspace` volume used by Files, Curl and Terminal. The typed
Admin API files surface operates directly on that shared filesystem rather than a second
storage/index implementation.

## Coolify bootstrap

Dynamic provider credentials do not belong in deployment environment variables. Production bootstrap requires:

```text
ADMIN_API_DATABASE_PATH=/admin-api/admin.sqlite3
ADMIN_API_ENCRYPTION_KEY=<Fernet key>
ADMIN_API_SERVICE_TOKEN=<random internal token>
ADMIN_API_USERNAME=admin
ADMIN_API_PASSWORD=<strong password>
ADMIN_API_SESSION_SECRET=<random session secret>
ADMIN_API_SESSION_HTTPS_ONLY=true
```

Gateway OAuth remains deployment configuration (`GITHUB_OAUTH_*`). Provider accounts are created through the Admin API used by the standalone frontend.

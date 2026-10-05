# Authorization and agent access architecture

Status: target architecture
Date: 2026-10-05

## Goal

The platform should have clear security and state boundaries instead of one generic backend service.

The main separation is:

- OAuth answers **who/what is connected to a public MCP surface**.
- Agent access answers **what this concrete agent session may do now**.
- Integrations own external provider accounts and credentials.
- Invocations own MCP call history.
- The administration layer controls and displays these domains but does not own their data.

## Service boundaries

### auth

Owns:

- local users and password authentication;
- OAuth authorization server;
- OAuth clients;
- authorization codes;
- auth sessions;
- refresh-token lifecycle;
- revocation;
- signing keys and JWKS.

Database: `auth`.

The target platform login is local. GitHub, GitLab and other providers are not identity providers for the platform.

The existing FastMCP/MCP SDK OAuth protocol layer should be reused where practical, but GitHub-backed identity and token state must be replaced by our own provider and persistence.

### access

Owns:

- agent sessions;
- access requests;
- capability grants;
- approval decisions;
- account bindings;
- access policies;
- global access modes.

Database: `access`.

This is deliberately separate from `auth`.

An OAuth session may be valid while an agent action is still denied or requires approval.

### integrations

Owns:

- provider accounts;
- encrypted provider credentials;
- provider/account metadata;
- ownership and visibility;
- credential resolution for authorized calls.

Database: `integrations`.

Examples: GitHub, GitLab, SigNoz, Coolify and future providers.

### invocations

Owns:

- MCP call history;
- status and duration;
- safe principal/session/grant/account correlation;
- bounded redacted arguments/results metadata;
- retention and pagination;
- MCP-call realtime events.

Database: `invocations`.

### admin-ui / admin-api

The administration layer is the frontend and its BFF/control-plane API.

It exposes views and controls for:

- users/auth state;
- agent sessions;
- access requests and grants;
- policies;
- integrations;
- MCP calls;
- global modes.

It does not become the source of truth for `auth`, `access`, `integrations` or `invocations`.

If admin-specific durable state is needed later, it may use a small `admin` database.

### gateway

Owns:

- public MCP routing;
- OAuth protected-resource metadata;
- access-token verification;
- propagation of authenticated principal/resource context;
- access enforcement before protected execution.

Gateway has no application database.

### provider runtimes

Provider runtimes execute MCP capabilities.

They do not read platform databases directly.

They receive approved authorization context and resolve provider accounts through platform services.

## Database isolation

One PostgreSQL server is acceptable.

Use separate databases and roles:

```text
auth
access
integrations
invocations
admin        # only if admin-specific state is needed
```

Each service receives credentials only for its own database.

Cross-domain access happens through typed APIs/events, not cross-database queries.

Valkey is cache/coordination/realtime infrastructure, not a security source of truth.

## OAuth model

Public MCP access remains protected by OAuth.

Target flow:

```text
ChatGPT / MCP client
        |
        v
      gateway
        |
        v
       auth
        |
        v
      auth DB
```

The local `auth` service replaces GitHub as the login authority.

No GitHub login, GitHub user allowlist or GitHub refresh token is required for platform authentication.

Provider accounts remain integrations and are independent from user login.

### Local users

The initial user model should support:

- unique local identity;
- login/username;
- password credential;
- enabled/disabled state;
- roles or coarse platform permissions.

Passwords are stored only as strong password hashes, preferably Argon2id.

### Token signing

Use asymmetric signing.

`auth` owns the private signing key.

Gateway and other verifiers receive public keys/JWKS only.

A verifier should not be able to mint a valid platform token.

### Resource audiences

Every public MCP surface remains a distinct OAuth resource/audience.

A token for one MCP resource does not implicitly authorize every other surface.

## Two session layers

There are two independent session concepts.

### Auth session

Owned by `auth`.

Represents authenticated user/client identity and OAuth lifecycle.

### Agent access session

Owned by `access`.

Represents one concrete agent context and the operational authority granted to it.

This is the session the agent asks for and later presents when calling protected capabilities.

## Agent access sessions

An agent can request a session through a common MCP capability.

The response contains:

- an opaque high-entropy session token;
- a short human-readable display code;
- status;
- expiry.

The token is the credential.

The display code exists only so the user can identify the request in the administration UI.

Suggested policy defaults:

```text
default session lifetime: 24 hours
maximum session lifetime: 7 days
pending request lifetime: 30 minutes
```

These are configurable policy defaults.

### Shared ChatGPT accounts

A shared ChatGPT account does not provide reliable per-chat human identity.

The server cannot safely infer which real person is typing from the outer OAuth identity alone.

Therefore:

- the outer OAuth identity establishes the connected principal/client;
- the agent session is separately claimed or approved in the administration UI;
- the approving local user is recorded;
- strong per-person attribution requires separate local users in `auth`.

## Grants

A session is not one large permission blob.

Capabilities are granted independently and can expire before the session.

Example:

```text
session:
  github:repo.read       -> account A, until session expiry

temporary grants:
  github:repo.push       -> account A, 30 minutes
  terminal:privileged    -> 10 minutes
```

A session may remain active after an elevated grant expires.

## Capability model

Policies should use semantic capabilities rather than arbitrary tool names.

Examples:

```text
files:read
files:write

github:repo.read
github:repo.write
github:repo.push
github:workflow.dispatch

gitlab:project.read
gitlab:repo.write
gitlab:pipeline.run

terminal:workspace.exec
terminal:privileged.exec
terminal:system.service

browser:read
browser:interact
browser:developer

infrastructure:read
infrastructure:deploy
infrastructure:restart
```

Each tool maps to one or more capabilities through a versioned registry.

Privileged terminal/system behavior should use explicit privileged boundaries where possible rather than trying to infer danger from arbitrary command text.

## Risk tiers

Capabilities may use a coarse default risk tier:

```text
baseline
write
privileged
critical
```

Typical intent:

- baseline: auto-grant if policy permits;
- write: approval or explicit trust rule;
- privileged: approval by default with shorter lifetime;
- critical: very short or per-operation approval.

The named capability remains authoritative.

## Common MCP access contract

Every public MCP surface should expose the same session/access contract.

Initial shared operations:

```text
access_session_request
access_session_status
access_session_close
access_request
access_request_status
```

The implementation remains centralized in `access`; provider runtimes do not each build their own session system.

When access is insufficient, the agent receives a structured result such as:

```text
approval_required
request code
requested capability
requested account
expiry
safe instruction to ask the user for approval
```

The agent can then tell the user what must be approved and retry after approval.

## Integration-account binding

Grants can bind capabilities to concrete integration accounts.

Example:

```text
requested:
  gitlab:repo.write
  account = personal

approved:
  gitlab:repo.write
  account = work
  TTL = 30 minutes
```

The administrator may:

- approve the requested account;
- choose another eligible account;
- reduce capabilities;
- reduce TTL;
- deny.

Knowing an account ID or alias must not grant access by itself.

Provider credentials are resolved only after an effective account-bound access decision.

## Multi-user model

Integration accounts may be:

- private to one user;
- shared with selected users/roles;
- broadly shared by explicit policy.

The `access` service evaluates ownership/visibility before issuing account-bound grants.

This allows multiple people to use the same MCP surfaces while working through different GitHub, GitLab or other provider accounts.

## Global controls

One boolean switch is not enough.

Two controls are required.

### Session admission

```text
enabled
frozen
```

`enabled` allows new sessions and grants.

`frozen` blocks new sessions and new privilege requests while already-active sessions/grants continue until expiry or revocation.

This is the normal “stop new access but do not interrupt existing work” control.

### Execution mode

```text
normal
privileged_blocked
lockdown
```

`normal` uses normal policy evaluation.

`privileged_blocked` immediately blocks privileged/critical operations, even when a grant already exists.

`lockdown` blocks all protected execution while preserving administration and break-glass recovery.

Admission and execution controls are separate because they solve different operational problems.

## Trust policies

Policies may target:

- all sessions;
- a local user;
- a specific session;
- a capability/capability family;
- an integration account;
- a provider;
- a risk tier.

This supports both:

- precise approval-based access;
- trusted users/sessions with broader automatic authority.

“Full access” is represented as an explicit high-risk policy rule, not as an ambiguous global switch.

## Policy evaluation

Policy evaluation should be deterministic and deny-oriented.

Conceptual precedence:

1. global lockdown/hard deny;
2. explicit deny;
3. invalid/revoked/expired session;
4. invalid/revoked/expired grant;
5. account ownership/visibility restriction;
6. explicit allow policy;
7. active approved grant;
8. baseline auto-policy;
9. approval required;
10. deny by default.

Responses use stable machine-readable reason codes.

## Immediate revocation

Security changes must apply on the next protected request.

Examples:

- session revoked;
- grant revoked;
- user disabled;
- integration account disabled;
- policy changed;
- execution mode changed.

PostgreSQL holds durable authority.

Valkey may accelerate decisions and distribute invalidations, but correctness must not depend on cache TTL.

A security/policy revision should make stale decisions detectable.

## Enforcement model

Authorization should not depend on one check in one process.

### Gateway

Gateway validates:

- OAuth token;
- resource/audience;
- agent session;
- effective access decision.

Denied or approval-required calls stop before provider execution.

### Provider runtime

After an allow decision, the provider runtime receives a short-lived signed internal authorization assertion containing safe context such as:

- session ID;
- principal ID;
- capability;
- approved integration account ID;
- target resource/runtime;
- policy revision;
- expiry.

The runtime validates this before privileged execution.

This prevents internal callers from bypassing the public gateway merely by knowing an account ID.

## Administration UI

The administration UI should provide focused sections for:

### Sessions

Show:

- pending/active/suspended/revoked/expired state;
- owner;
- display code;
- client/resource;
- created/last-used/expiry;
- effective grants.

Actions:

- approve/claim;
- suspend/resume;
- revoke;
- adjust expiry within policy.

### Access requests

Show:

- requesting session;
- requested capabilities;
- requested account;
- requested TTL;
- safe reason;
- risk tier.

Approval may change the account, reduce capability scope or shorten TTL.

### Policies

Support:

- global defaults;
- per-user rules;
- per-session rules;
- per-capability rules;
- per-account rules;
- explicit deny;
- trusted auto-grant rules.

### Global controls

Expose `session_admission` and `execution_mode` separately and update them over admin realtime immediately.

## Realtime

Suggested administration topics:

```text
access.sessions
access.requests
access.grants
access.policy
access.mode
mcp.calls
```

Realtime payloads never contain provider credentials, OAuth tokens or agent session tokens.

## Invocation correlation

The `invocations` service records safe references such as:

- MCP surface;
- tool/capability;
- principal;
- agent session ID;
- grant/decision ID;
- approved integration account;
- status;
- duration;
- trace correlation.

It must never persist:

- OAuth bearer/refresh tokens;
- agent session tokens;
- provider credentials;
- authorization headers;
- terminal secrets;
- browser cookies/form secrets.

## Failure principles

- `access` unavailable: protected operations fail closed.
- `auth` unavailable: no new login/refresh; already-issued tokens may continue only while independent verification remains valid.
- `integrations` unavailable: account-backed calls fail; never silently switch accounts.
- `invocations` unavailable: an otherwise successful authorized action should not fail solely because history recording is temporarily unavailable.
- Valkey unavailable: fall back to durable authorities where practical; do not fail open.

## Migration order

The existing legacy MCP remains untouched until the replacement path is accepted.

Recommended order:

1. Implement local `auth` persistence and users.
2. Replace GitHub-backed login with local OAuth.
3. Add asymmetric signing/JWKS; gateway becomes verifier-only.
4. Validate OAuth end to end with a test client.
5. Implement `access`: sessions, requests, grants, policies and global modes.
6. Add the shared access-session contract to public MCP surfaces.
7. Move provider accounts/credentials into `integrations`.
8. Move MCP Calls/history/realtime ownership into `invocations`.
9. Make `admin-api` aggregate these services rather than own their data.
10. Add administration UI for sessions, approvals, policies, accounts and global controls.
11. Migrate provider MCP surfaces one by one.
12. Reconnect external MCP clients only after auth/access behavior is stable.

## Architectural decisions

- No generic platform “core” service.
- No provider-backed platform login.
- No Keycloak unless future requirements materially exceed this local identity model.
- No direct cross-service database access.
- No provider credentials in `auth` or `access`.
- No MCP call history in `access`.
- No agent privilege state in `auth`.
- No authorization from account ID alone.
- No overloaded single global on/off switch.
- No privilege decision based only on model-supplied free-form text.
- Reuse correct OAuth protocol machinery from FastMCP/MCP SDK instead of rebuilding it unnecessarily.

## Review points before implementation

Before implementation begins, confirm:

- service names and ownership;
- database separation;
- local OAuth identity model;
- asymmetric token signing;
- session lifetime policy;
- capability naming/risk tiers;
- account-bound grant model;
- multi-user account ownership;
- admission and emergency execution controls;
- deterministic policy precedence;
- fail-closed access behavior;
- administration realtime model;
- safe invocation correlation;
- migration order that leaves the legacy MCP untouched until cutover.

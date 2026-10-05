# Authorization and agent access architecture

Status: target architecture with MVP boundary
Date: 2026-10-05

## Goal

The platform must separate identity, agent access, provider integrations and MCP invocation history instead of rebuilding one generic backend service.

The basic security model has two independent layers:

- OAuth answers **which local user/client is connected to a public MCP surface**.
- Agent access answers **whether this concrete agent session may use this concrete MCP surface now**.

The administration layer controls and displays these domains but is not their source of truth.

## Service boundaries

### auth

Owns:

- local users;
- password authentication;
- OAuth authorization server;
- OAuth clients;
- authorization codes;
- auth sessions;
- refresh-token lifecycle;
- revocation;
- signing keys and JWKS.

Database: `auth`.

The platform login is local. GitHub, GitLab and other providers are not identity providers for the platform.

The existing FastMCP/MCP SDK OAuth protocol layer should be reused where practical, while GitHub-backed identity and token persistence are removed.

### access

Owns:

- agent sessions;
- session approval/revocation;
- session runtime state;
- global session-control mode;
- session security events;
- later: granular permission requests, grants and policies.

Database: `access`.

This is deliberately separate from `auth`.

A valid OAuth session does not automatically mean that an agent session is allowed to execute.

### integrations

Owns:

- provider accounts;
- encrypted provider credentials;
- provider/account metadata;
- later: ownership, sharing and visibility;
- credential resolution for authorized calls.

Database: `integrations`.

Examples: GitHub, GitLab, SigNoz, Coolify and future provider accounts.

### invocations

Owns:

- MCP call history;
- call status and duration;
- safe user/session/account correlation;
- bounded redacted request/result metadata;
- retention and pagination;
- MCP-call realtime events.

Database: `invocations`.

### admin-ui / admin-api

The administration layer is the browser frontend and its BFF/control-plane API.

It provides UI and realtime views for:

- authentication state;
- agent sessions;
- access-control mode;
- integrations;
- MCP calls;
- later: users, teams, sharing, granular permission requests and policies.

It does not become the source of truth for `auth`, `access`, `integrations` or `invocations`.

### gateway

Owns:

- public MCP routing;
- OAuth protected-resource metadata;
- access-token verification;
- propagation of authenticated user/resource context;
- access-session enforcement when session control is enabled.

Gateway has no application database.

### provider runtimes

Provider runtimes execute MCP capabilities.

They do not read platform databases directly.

Provider/account credentials are resolved through platform services, not embedded into session identifiers.

## Database isolation

One PostgreSQL server is acceptable.

Use separate databases and roles:

```text
auth
access
integrations
invocations
admin        # only if genuinely admin-specific durable state appears
```

Each service receives credentials only for its own database.

Cross-domain access happens through typed service APIs/events, not cross-database queries.

The project uses Valkey as the Redis-compatible hot-state layer.

PostgreSQL stores durable session/user/account state. Valkey/Redis is used for the session enforcement hot path.

## MVP and later development

The target architecture must allow future expansion, but the first implementation is intentionally narrower.

### MVP

The first working version contains:

- one local user;
- local OAuth login for that user;
- one OAuth identity linked to an MCP connection;
- agent sessions;
- one agent session bound to one MCP surface;
- where applicable, the session is also bound to one integration account;
- binary session state: allowed or denied;
- Redis/Valkey hot-path validation;
- session creation, status, extension/update and revocation;
- administration UI for session approval/revocation and the global control switch;
- current resources migrated to the initial user as owner;
- no teams;
- no resource sharing;
- no granular per-capability grants;
- no policy DSL.

### Later production development

The architecture must allow adding without replacing the MVP model:

- multiple local users;
- service users;
- account/resource ownership;
- targeted sharing with another username;
- teams;
- team-scoped sharing;
- per-resource access to files/projects/workspaces;
- granular capabilities;
- session privilege elevation;
- short-lived privilege grants;
- delegated approvers;
- richer roles;
- MFA/passkeys;
- stronger service-to-service identity;
- signing/encryption key rotation;
- high availability.

The MVP must not hard-code assumptions that make these additions impossible.

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

The user authorizes the MCP connection using a login/password from our own platform.

That OAuth identity determines which local platform user the connection belongs to.

Provider accounts are separate integrations and are not used for platform login.

### Multiple users later

When several local users exist, each OAuth authorization maps the external MCP connection to one local user.

That user then sees only resources and integration accounts owned by or shared with that identity.

The server model supports multiple users independently even if a specific external client UI does not support several simultaneous connections to the same MCP URL. Client UI limitations must not define the server-side identity model.

### Local credentials

Passwords are stored only as strong password hashes. Argon2id is the intended password-hashing algorithm.

### Token signing

Use asymmetric signing.

`auth` owns the private signing key.

Gateway and other verifiers receive public keys/JWKS only.

A verifier should not be able to mint a valid platform OAuth token.

### Resource audiences

Every public MCP surface remains a distinct OAuth resource/audience.

A token for one MCP resource does not implicitly authorize every other surface.

## Two session layers

There are two independent session concepts.

### Auth session

Owned by `auth`.

Represents authenticated local user/client identity and OAuth lifecycle.

### Agent access session

Owned by `access`.

Represents one concrete agent context working through one concrete MCP surface.

The agent access session is the internal session discussed throughout the rest of this document.

## Agent session identifier

The agent session uses one opaque, randomly generated UID as its session credential and identifier.

There is no login/password inside the agent session.

The UID:

- is created by the platform;
- is stored with the durable session record;
- is present in the Redis/Valkey runtime session projection;
- is sent by the agent with MCP calls;
- is returned by MCP responses;
- is bound to its OAuth identity and MCP surface;
- cannot be reused against another MCP surface;
- where relevant, cannot be reused for another integration account.

The UID must have enough randomness that guessing a valid value is computationally impractical.

## Session scope

An agent session is scoped at minimum by:

```text
local user / OAuth subject
MCP surface
session UID
expiry
status
```

For account-backed MCP operations it also includes:

```text
integration account ID
```

Conceptually:

```text
session A
  user: initial-user
  surface: github
  account: github-account-1

session B
  user: initial-user
  surface: github
  account: github-account-2

session C
  user: initial-user
  surface: terminal
  account: none
```

Session A must not work as Session B or Session C.

This is the main MVP authorization granularity.

## Session transport contract

When session control is enabled, every MCP tool call requires a session UID except the minimal session-bootstrap methods needed to create/recover a session.

The session UID is carried explicitly in the MCP request contract.

Every response returns session context again so the agent can continue using the same session.

Conceptually:

```json
request:
{
  "session_id": "<uid>",
  "...": "tool arguments"
}

response:
{
  "session_id": "<uid>",
  "session_status": "active",
  "...": "tool result"
}
```

The exact schema wrapper may be implemented centrally, but the behavior must be consistent across all public MCP surfaces.

OAuth protocol endpoints, health/discovery endpoints and the session-bootstrap operation are outside this requirement.

## Common session operations

Every public MCP surface exposes the same session-lifecycle capabilities through shared infrastructure.

Conceptual operations:

```text
access_session_open
access_session_status
access_session_update
access_session_extend
access_session_close
access_session_reissue
```

These operations belong to `access`, not to `auth`.

`auth` authenticates the outer platform user. `access` manages the inner agent session.

A session update may change safe metadata such as a description/label. Later it may also be the entry point for privilege-elevation requests.

## Session lifecycle

Typical lifecycle:

```text
requested
  -> pending approval
  -> active
  -> expired / revoked / replaced
```

The administration UI may approve, reject, extend or revoke the session.

Suggested initial policy:

```text
default active lifetime: 24 hours
maximum active lifetime: 7 days
pending request lifetime: 30 minutes
```

These are configuration defaults rather than hard-coded protocol limits.

When a session expires or is revoked, the agent receives a structured response telling it that the session is no longer valid and must be reissued.

## Redis/Valkey session hot path

Normal MCP calls must not synchronously read PostgreSQL for every session check.

Session creation/approval/revocation is persisted in PostgreSQL and projected into Valkey/Redis.

The normal enforcement path is:

```text
MCP call
  -> validate OAuth identity
  -> lookup session UID in Redis
  -> validate status + expiry + user + MCP surface + account binding
  -> execute or reject
```

Redis therefore provides the fast runtime validation path.

PostgreSQL keeps durable lifecycle/history.

### Redis miss or loss

In MVP, absence of the required runtime session entry is fail-closed.

The agent is told to reissue the session.

A Redis restart must never silently turn an unknown session into an allowed session.

Later production versions may safely rebuild active Redis projections from PostgreSQL, but that is an optimization, not an MVP requirement.

## Revocation and cancellation

Revocation removes/disables the runtime session immediately.

After revocation:

- no new call using that UID is accepted;
- pending calls waiting for execution are cancelled;
- locally cancellable active work is terminated where the runtime supports cancellation;
- the agent receives a session-expired/revoked result and must obtain a new session.

Examples of cancellable local work include terminal processes/jobs and queued runtime work.

A security boundary cannot undo an external side effect that has already been committed. For example, a remote Git push or provider API mutation already accepted by the provider cannot be rolled back merely by revoking the session.

The system should still cancel any remaining local work and reject all subsequent calls.

## Session abuse protection

Session IDs are not intended to be discoverable by enumeration.

The access layer tracks invalid/unknown session attempts per authenticated OAuth context and MCP surface.

Repeated suspicious attempts trigger protection such as:

- rate limiting;
- temporary blocking;
- invalidation of the current agent sessions;
- requiring OAuth reauthentication for the offending authenticated context when a configured threshold is exceeded.

Protection is scoped to the authenticated context so that one attacker cannot trivially revoke unrelated users.

All such events are written to the access security history.

## MVP access decision

The MVP has intentionally simple semantics.

When session control is enabled, a session is either:

```text
allowed
denied
```

No fine-grained capability matrix is required for the first implementation.

Approval means that this session may use its bound MCP surface and, where applicable, its bound integration account until expiry/revocation.

This lets us implement the complete authorization contour before individually redesigning every MCP permission model.

## Global access-control mode

MVP needs one clear global switch for agent-session enforcement.

Conceptual modes:

```text
unrestricted
session_enforced
```

### unrestricted

This is the current/root-style behavior.

OAuth authentication still applies, but agent access sessions are not required.

For the MVP single-user system this gives the agent the same broad operational access it effectively has today.

In the future multi-user system, unrestricted mode must still respect the authenticated user's ownership/sharing boundaries. It is not a bypass of user isolation.

### session_enforced

Every MCP tool call, except session-bootstrap operations, requires a valid active session bound to that surface/account.

The administration UI controls this mode.

Switching modes takes effect immediately for new calls.

## Future privilege elevation

Granular privileges are explicitly deferred from MVP.

Later, an already-active session can request additional authority without discarding the whole session.

Example future flow:

```text
session already active
  -> agent requests additional permission
  -> request appears in admin UI
  -> administrator approves/edits/denies
  -> same session receives the additional authority
```

Future approval must allow:

- approving only some requested permissions;
- removing requested permissions;
- adding permitted rights;
- reducing duration;
- choosing a different allowed integration account where appropriate.

This later model may use separate grants attached to the same session.

The MVP database/API should not pretend that this granular model already exists.

## Future capabilities

Later access policies can use semantic capabilities such as:

```text
files:read
files:write
github:repo.read
github:repo.push
gitlab:repo.write
terminal:privileged.exec
browser:developer
infrastructure:deploy
```

Capabilities and risk tiers are a later extension point.

They must not be hard-coded into the first binary allow/deny session implementation.

## Integration-account binding

Account-backed sessions are bound to an immutable integration account ID.

Aliases are display/selectors only and must not become authorization identity.

A GitHub/GitLab/observability session for account A cannot be used against account B.

Provider credentials remain inside `integrations`; session records store only the account reference.

## MVP user and ownership model

The first implementation has one local platform user.

During migration, existing resources that later require ownership should be assigned to that initial user.

This includes, as applicable:

- provider integration accounts;
- files/workspaces;
- analysis/Ghidra projects;
- other persistent user-owned resources.

MVP does not implement sharing or team ACLs yet.

It does establish stable user IDs and stable resource/account IDs so that ownership can be added without replacing identifiers later.

## Future users, sharing and teams

The production model must support many local users.

A user can connect their own GitHub, GitLab or other integration accounts.

Those accounts initially belong to that user.

Later the owner may share an account/resource:

- with everyone allowed by policy;
- with a specific local username;
- with selected team members;
- with a team.

The platform must not expose a global directory of all usernames merely to support sharing.

Targeted sharing should allow entering an exact username and resolving it server-side.

Teams are explicitly deferred from MVP but must be addable as a separate ownership/sharing layer.

The same ownership model later applies to files, workspaces, analysis projects and other resources.

## Administration identity

The user who logs into the administration UI is a local `auth` user.

That identity approves or rejects agent sessions belonging to that user's OAuth-connected MCP context.

The current standalone admin credential is transitional/bootstrap behavior, not the target user model.

A future service user may also authenticate through `auth` under a distinct identity type and policy, but that is not required for MVP.

## Access security history

MCP call history and access-security history are different domains.

`invocations` records tool calls.

`access` keeps a small append-only security history for session/access lifecycle events such as:

```text
session requested
session approved
session rejected
session extended
session revoked
session expired
global access mode changed
suspicious invalid-session activity
protective block/reauth triggered
```

This does not require a separate generic audit service for MVP.

Later, if multiple domains require a unified compliance audit system, that can be introduced deliberately.

## Invocations

The `invocations` service records safe references such as:

- MCP surface;
- tool;
- local user;
- internal agent-session record ID;
- integration account ID where relevant;
- status;
- duration;
- trace correlation.

It must never persist:

- OAuth bearer/refresh tokens;
- provider credentials;
- authorization headers;
- terminal secrets;
- browser cookies/form secrets.

The bearer-form session UID remains owned by `access` and is not copied into `invocations`. Invocation history correlates through the internal session record ID.

## Internal service trust

The private Docker network is not sufficient by itself as an authorization model.

MVP internal APIs should use distinct service credentials/identities between major services.

Do not use one universal shared secret for every internal service.

Later this can evolve to stronger workload identity or mTLS without changing domain ownership.

## Failure behavior

### auth unavailable

No new OAuth login/refresh can proceed.

Already-issued OAuth tokens may continue only while their normal local verification remains valid.

### access unavailable

When `session_enforced` is active, protected MCP execution fails closed.

Do not silently fall back to unrestricted behavior.

### Redis/Valkey unavailable

When session enforcement is enabled, session validation fails closed.

MVP may require session reissue after recovery.

### integrations unavailable

Account-backed calls fail.

Do not silently switch to another account.

### invocations unavailable

An otherwise authorized successful provider action should not fail solely because invocation history cannot be recorded.

Use bounded retry/queue behavior rather than turning observability storage into an execution dependency.

## Administration UI for MVP

The first UI does not need a full policy editor.

It needs:

### Session list

Show:

- session UID/display form;
- MCP surface;
- bound account when applicable;
- status;
- created time;
- last activity;
- expiry;
- safe description.

Actions:

- approve;
- reject;
- revoke;
- extend;
- edit safe description.

### Global control

Show the `unrestricted / session_enforced` switch clearly.

The effect must be immediate and visible.

### Realtime

Session state changes should appear in the administration UI without polling-heavy behavior.

Suggested topic:

```text
access.sessions
```

Additional granular access topics can be added when granular permissions are implemented.

## Migration order

The legacy MCP remains untouched until replacement components are accepted.

Recommended order:

1. Implement local `auth` database/users.
2. Replace GitHub-backed platform login with local OAuth.
3. Add asymmetric signing/JWKS; gateway becomes verifier-only.
4. Validate OAuth end to end with the initial local user.
5. Establish stable integration account IDs and initial-user ownership semantics.
6. Implement MVP `access`: binary sessions, Redis hot path, approval/revocation and global mode.
7. Add the common session contract to the new MCP surfaces.
8. Add admin UI for sessions and the global access-control switch.
9. Move provider accounts/credentials into `integrations` as each provider is migrated.
10. Move MCP call history into `invocations`.
11. Assign existing files/workspaces/analysis projects to the initial user during their respective migrations.
12. Migrate MCP/provider surfaces one by one.
13. Only after the binary session model is stable, add granular permissions, sharing and teams.

## MVP acceptance criteria

The MVP authorization contour is accepted when:

- local OAuth no longer depends on GitHub identity;
- one local user can authorize an MCP connection;
- every new MCP surface can request an agent session;
- under `session_enforced`, every normal tool call requires that session UID;
- the session is rejected on another MCP surface;
- an account-bound session is rejected for another integration account;
- normal validation uses Redis/Valkey rather than PostgreSQL per call;
- Redis loss does not fail open;
- revoked/expired sessions stop new calls immediately;
- cancellable active local work is terminated on revocation;
- the agent receives a clear reissue response after expiry/revocation;
- repeated invalid-session attempts are rate-limited and recorded;
- the admin UI can approve, reject, revoke and extend sessions;
- the admin UI can switch between `unrestricted` and `session_enforced`;
- existing migrated resources can be associated with the initial stable user ID;
- no team/granular-permission implementation is required for MVP.

## Deferred production features

Explicitly deferred:

- multiple users in normal operation;
- teams;
- user/resource sharing;
- account sharing;
- granular capabilities;
- privilege-elevation grants;
- resource-level Git repository/project/branch ACLs;
- delegated approval;
- advanced roles/RBAC/ABAC;
- MFA/passkeys;
- automatic Redis session-projection rebuild;
- distributed/high-availability access service;
- KMS/HSM key storage;
- advanced abuse scoring.

These features are expected extensions, not reasons to delay the binary-session MVP.

## Architectural decisions

- No generic platform “core” service.
- No provider-backed platform login.
- No Keycloak for the MVP.
- No direct cross-service database access.
- OAuth identity and agent access session remain separate.
- Agent session uses one opaque UID.
- Agent session is always scoped to one MCP surface.
- Account-backed sessions are additionally scoped to one integration account.
- When session control is enabled, all normal MCP tool calls require a session.
- Redis/Valkey is mandatory for the session validation hot path.
- PostgreSQL stores durable session lifecycle/security history.
- MVP access is binary allow/deny.
- Granular permissions, teams and sharing are later stages.
- Revocation is immediate for new calls and cancels locally cancellable active work.
- The global MVP control is `unrestricted / session_enforced`.
- Existing resources migrate to the initial local user before multi-user sharing is introduced.

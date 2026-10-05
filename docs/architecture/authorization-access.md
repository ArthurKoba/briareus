# Authorization and agent access architecture

Status: target architecture with explicit MVP boundary
Date: 2026-10-05

## Goal

The platform separates identity, agent access, provider integrations and MCP invocation history instead of rebuilding one generic backend service.

The two security layers are different:

- OAuth answers which local user/client is connected to a public MCP surface.
- Agent access answers whether this concrete agent session may use this concrete MCP surface now.

The administration layer displays and controls these domains but is not their source of truth.

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

FastMCP/MCP SDK OAuth protocol machinery should be reused where practical. GitHub-backed identity and GitHub-backed OAuth token state are removed.

### access

Owns:

- agent sessions;
- session lifecycle;
- full-access elevation requests;
- session/account scope;
- per-user/per-MCP enforcement mode;
- session abuse protection;
- session security history;
- later: granular capabilities, grants and policies.

Database: `access`.

A valid OAuth session does not automatically mean that an agent may perform mutating actions.

### integrations

Owns:

- provider accounts;
- encrypted provider credentials;
- provider/account metadata;
- later: ownership, sharing and visibility;
- credential resolution for authorized calls.

Database: `integrations`.

Examples include GitHub, GitLab, SigNoz, Coolify and future providers.

### invocations

Owns:

- MCP call history;
- status and duration;
- safe user/session/account correlation;
- bounded redacted arguments/results metadata;
- retention and pagination;
- MCP-call realtime events.

Database: `invocations`.

### admin-ui / admin-api

The administration layer is the browser frontend and its BFF/control-plane API.

It provides views and controls for:

- authentication state;
- agent sessions;
- elevation requests;
- per-MCP session-control mode;
- integrations;
- MCP calls;
- later: users, teams, sharing and granular policies.

It does not become the source of truth for `auth`, `access`, `integrations` or `invocations`.

### gateway

Owns:

- public MCP routing;
- OAuth protected-resource metadata;
- OAuth access-token verification;
- propagation of authenticated user/resource context;
- access-session enforcement when enabled for a surface.

Gateway has no application database.

### provider runtimes

Provider runtimes execute MCP capabilities.

They do not read platform databases directly.

Provider/account credentials are resolved through platform services and are never embedded into the agent session identifier.

## Database isolation

One PostgreSQL server is acceptable.

Use separate databases and roles:

```text
auth
access
integrations
invocations
admin        # only if genuinely admin-specific durable state appears later
```

Each service receives credentials only for its own database.

Cross-domain access happens through typed APIs/events, not cross-database queries.

Valkey is the Redis-compatible hot-state layer.

PostgreSQL stores durable user/session/account state. Valkey/Redis is used for the agent-session enforcement hot path.

## MVP boundary

The first implementation is intentionally narrower than the long-term architecture.

### MVP includes

- one local user;
- local OAuth login for that user;
- separate OAuth authorization for each concrete MCP surface connection;
- automatic creation of an active read-only agent session;
- one agent session bound to one MCP surface;
- account scope for account-backed surfaces;
- two coarse access levels: `read_only` and `full_access`;
- Redis/Valkey hot-path validation;
- session status/update/reissue/revocation;
- extension and full-access requests approved from the administration UI;
- per-MCP session-control switches;
- existing persistent resources associated with the initial local user;
- no teams;
- no resource sharing;
- no per-tool capability matrix;
- no policy DSL.

### Later production development

The architecture must allow adding without replacing the MVP model:

- multiple local users;
- service users;
- ownership and sharing;
- targeted sharing by username;
- teams;
- team-scoped sharing;
- per-resource ACLs for files/projects/workspaces;
- granular capabilities;
- sensitive-read distinction;
- per-tool mutation permissions;
- session privilege grants;
- delegated approvers;
- richer roles;
- MFA/passkeys;
- stronger workload identity;
- signing/encryption key rotation;
- high availability.

The MVP must not hard-code identifiers or ownership rules that make these additions impossible.

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

The user authorizes the MCP connection using login/password from our own platform.

That OAuth identity determines which local platform user the connection belongs to.

Provider accounts are separate integrations and are not used for platform login.

### OAuth is per MCP surface

Each dedicated MCP surface performs its own OAuth authorization.

For example, an OAuth authorization for Terminal does not authorize GitHub, Web or another MCP surface.

Every public MCP surface therefore remains a distinct OAuth resource/audience.

A token for one resource does not implicitly authorize another resource.

### Bridge/recovery surface

A broad Bridge/recovery MCP may exist as a separate exceptional surface for rare repair scenarios.

It has its own OAuth resource and does not reuse the OAuth authorization of dedicated MCP surfaces.

It is not the normal integration path.

### Local credentials

Passwords are stored only as strong password hashes.

Argon2id is the intended password-hashing algorithm.

### Token signing

Use asymmetric signing.

`auth` owns the private signing key.

Gateway and other verifiers receive public keys/JWKS only.

A verifier should not be able to mint a valid OAuth token.

## Two session layers

There are two independent session concepts.

### Auth session

Owned by `auth`.

Represents authenticated local user/client identity and OAuth lifecycle.

### Agent access session

Owned by `access`.

Represents one concrete agent context working through one concrete MCP surface.

The remainder of this document uses “session” to mean this inner agent access session unless stated otherwise.

## Agent session identifier

The session uses one opaque, randomly generated UID as its credential and identifier.

There is no login/password inside the session.

For MVP the UID is stored directly in the `access` database and directly in the Valkey/Redis runtime projection.

The design relies on:

- strong random generation;
- OAuth binding;
- MCP-surface binding;
- account-scope binding where applicable;
- expiry/revocation;
- abuse detection.

The UID:

- is generated by the platform;
- is sent by the agent with MCP calls;
- is returned by MCP responses;
- is bound to the authenticated local user;
- is bound to one MCP surface;
- cannot be reused on another surface;
- cannot be used outside its approved account scope.

## Stable MCP surface identity

Authorization must not depend on deployment URLs, container names, Coolify IDs or transient infrastructure values.

Use one shared stable MCP-surface registry.

Conceptual symbolic names:

```text
terminal
web
files
github
gitlab
analysis
observability
bridge
```

The implementation may use stable numeric enum codes internally for compact storage/lookup.

Human-facing APIs, logs and administration UI should retain readable symbolic names.

New surfaces are added through the registry rather than through arbitrary free-form text.

## Session scope

Every session is scoped by at least:

```text
local user / OAuth subject
MCP surface ID
session UID
access level
expiry
status
```

For account-backed MCP surfaces it also has an account scope.

### Account-scope model

Use three states:

```text
none
all
selected
```

Meaning:

- `none`: no elevated access to provider accounts;
- `all`: all integration accounts available to this user for this MCP surface;
- `selected`: an explicit set of immutable integration account IDs.

`all` is dynamic.

If another account becomes available to the same user later, an existing `all` scope includes it automatically.

`selected` stores immutable account IDs.

Aliases are for display/selection only and are not authorization identity.

## Session transport contract

When session control is enabled for an MCP surface, every normal MCP tool call requires the session UID.

The only exceptions are the minimal bootstrap/lifecycle methods needed to create or recover a session, plus OAuth/health/discovery protocol endpoints.

The UID is carried explicitly in the MCP request contract.

Every MCP response returns session context again so the agent can continue using the same session.

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
  "access_level": "read_only",
  "...": "tool result"
}
```

The exact wrapper may be implemented centrally, but behavior must be consistent across all public MCP surfaces.

## Common session operations

Every public MCP surface exposes the same session-lifecycle capabilities through shared infrastructure.

Conceptual operations:

```text
access_session_open
access_session_status
access_session_update
access_session_request_extension
access_session_request_full_access
access_session_close
access_session_reissue
```

These operations belong to `access`, not `auth`.

Rules for MVP:

- `open` automatically creates an active read-only session for the authenticated user and MCP surface;
- `status` returns current session state;
- `update` changes only safe metadata such as description/label;
- `request_extension` requests a different expiry but does not approve it itself;
- `request_full_access` requests elevation to full action access and may request account scope;
- `close` voluntarily revokes the session;
- `reissue` creates a completely new session after expiry/revocation; the old session is not downgraded or reused.

Extension and full-access approval happen from the administration layer.

## Session lifecycle

A base session does not require manual approval.

It is created automatically and starts:

```text
active
read_only
```

Typical lifecycle:

```text
open
  -> active/read_only
  -> optional full-access request
       -> pending
       -> approved / rejected
  -> expired / revoked / replaced
```

The administration UI may:

- approve/reject full access;
- change the approved account scope;
- set or change expiry;
- revoke;
- edit safe metadata.

### Expiry

Use:

```text
expires_at = 0        # never expires; manual revocation only
expires_at > 0        # timestamp/epoch expiry
```

The configurable application default for a new session is 1 hour. The administrator may approve practical durations such as minutes, hours, days, a week or no automatic expiry.

If the session expires or is revoked, the session ends. It is not downgraded back to read-only. The agent must create/reissue a new session, which starts again as a fresh read-only session with no carried elevation.

## Redis/Valkey hot path

Normal MCP calls must not synchronously read PostgreSQL for every session check.

Session state is persisted in PostgreSQL and projected into Valkey/Redis.

Normal enforcement:

```text
MCP call
  -> validate OAuth identity
  -> lookup session UID in Redis
  -> validate status
  -> validate expiry
  -> validate local user
  -> validate MCP surface
  -> validate account scope
  -> validate access level required by the tool
  -> execute or reject
```

Redis therefore provides the normal runtime validation path.

PostgreSQL keeps durable lifecycle and security history.

### Redis miss or loss

MVP fails closed if the required runtime session projection is absent.

It must never turn an unknown session into an allowed session.

After a Redis loss/restart, MVP may require sessions to be reissued.

A later production version may rebuild active Redis projections from PostgreSQL without changing the external session protocol.

## MVP access levels

MVP intentionally avoids a full capability matrix.

Every new session starts:

```text
read_only
```

For MVP, each MCP surface owns a static method classification that marks tools as read-only or mutating. Unknown/unclassified tools must not silently gain write authority.

Read-only methods are the methods each MCP surface classifies as non-mutating.

For account-backed surfaces, base read-only access may expose only the safe list of account aliases/IDs available to the authenticated user. Provider details beyond that are considered a future sensitive-read permission and are not part of the MVP contract.

Provider credentials are never exposed.

The only elevated level in MVP is:

```text
full_access
```

Full access permits mutating actions supported by that MCP surface, limited by its account scope where applicable.

Fine-grained distinctions such as:

- sensitive read;
- push;
- delete;
- deploy;
- individual tool grants;

are explicitly deferred.

They will be introduced while each MCP surface is refined after the coarse MVP contour is working. A later administration model may define named access levels (for example level 1/2/3/4) and map tools to those levels dynamically; the MVP static classification must not make that evolution impossible.

## Integration-account interaction

For an account-backed MCP surface, a read-only session may discover the safe aliases/IDs of integration accounts available to the authenticated user.

When requesting full access, the agent may request:

- one account;
- several accounts;
- all accounts.

The administration UI may approve the requested scope or replace it with another valid scope.

Provider credentials remain inside `integrations`.

The session stores only account IDs/scope.

## Per-MCP session-control mode

Session enforcement is configured per local user and per MCP surface.

Each surface has:

```text
unrestricted
session_enforced
```

### unrestricted

OAuth authentication still applies.

The agent-session check is skipped for that MCP surface.

Existing sessions are not deleted, changed or invalidated.

Their expiry and access state continue to exist normally.

### session_enforced

Every normal MCP tool call requires a valid session for the user and surface.

When switching from `unrestricted` back to `session_enforced`, all still-valid sessions immediately become effective again with the same state they had before.

No session reset occurs merely because enforcement was temporarily bypassed.

### Administration UI batch control

There is no separate persistent global session-control mode.

The UI may provide:

- “all unrestricted”;
- “all session-enforced”;

as batch operations that update the individual MCP-surface switches.

The individual per-user/per-surface setting remains the source of truth.

## Revocation and cancellation

Revocation removes/disables the runtime session immediately.

After revocation:

- no new call using that UID is accepted;
- pending calls waiting for execution are cancelled;
- locally cancellable active work is terminated where the runtime supports cancellation;
- the agent receives a revoked/expired response and must reissue the session.

Examples of cancellable local work include terminal jobs/processes and queued runtime work.

A session revocation cannot undo an external side effect that has already been committed.

For example, a provider API mutation or completed Git push cannot be rolled back simply by revoking the session.

## Session abuse protection

Session IDs are not intended to be enumerable.

The access layer tracks invalid/unknown-session attempts per authenticated OAuth context and MCP surface.

Repeated invalid-session attempts use escalating protection rather than one immediate hard failure.

The MVP should maintain a configurable failure counter/backoff per authenticated OAuth context and MCP surface. Conceptually:

- a small number of mistakes are tolerated;
- repeated misses trigger a temporary rate limit/backoff;
- continued attempts after repeated rate-limit windows invalidate the active agent sessions for that OAuth context;
- sustained abuse eventually revokes the offending OAuth session/refresh context and requires full OAuth reauthentication.

Exact thresholds are application settings rather than protocol constants. An initial policy may start throttling after roughly five consecutive invalid-session attempts and use a much higher cumulative threshold before OAuth revocation.

Protection must be scoped to the offending authenticated context so one user cannot trivially revoke another user's sessions.

These events are written to access security history.

## Future granular privilege model

Granular permissions are explicitly deferred from MVP.

Later, the same session can request additional authority without being replaced.

Future approval may support:

- individual capabilities;
- sensitive-read permissions;
- only some requested permissions;
- different TTL per grant;
- account-specific grants;
- provider-resource restrictions;
- removal of existing permissions.

Conceptual later capabilities may include:

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

This later model can attach grants to the existing session.

The MVP database/API should not pretend that this granular model already exists.

## MVP user and ownership model

The first implementation has one local platform user.

During migration, existing persistent resources that later require ownership should be associated with that stable initial user ID.

This includes, as applicable:

- provider integration accounts;
- files/workspaces;
- analysis/Ghidra projects;
- other persistent user-owned resources.

MVP does not implement sharing or teams.

It does establish stable user/resource/account identities so later ownership/sharing does not require replacing identifiers.

## Future users, sharing and teams

The production model must support many local users.

A user can connect their own provider accounts.

Those accounts initially belong to that user.

Later, the owner may share an account/resource:

- with everyone allowed by policy;
- with a specific local username;
- with selected team members;
- with a team.

The platform must not expose a global directory of all usernames simply to support sharing.

Targeted sharing should allow entering an exact username and resolving it server-side.

Teams are deferred from MVP but must be addable as a separate ownership/sharing layer.

The same ownership model later applies to files, workspaces, analysis projects and other resources.

## Administration identity

The user who logs into the administration UI is a local `auth` user.

That identity manages sessions belonging to that user's OAuth-connected MCP contexts.

The current standalone admin credential is transitional/bootstrap behavior, not the target user model.

A future service user may authenticate through `auth` under a distinct identity type and policy.

## Access security history

MCP call history and access-security history are different domains.

`invocations` records tool calls.

`access` keeps append-only security history for lifecycle events such as:

```text
session opened
full-access requested
full-access approved
full-access rejected
session extension requested
session expiry changed
session revoked
session expired
MCP session-control mode changed
suspicious invalid-session activity
protective block / OAuth reauthentication required
```

This does not require a separate generic audit service for MVP.

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

The bearer-form session UID remains owned by `access`.

Invocation history correlates through the internal session record ID rather than copying the session UID.

## Internal service trust

The private Docker network is not sufficient as an authorization model.

MVP internal APIs should use distinct service credentials/identities between major services.

Do not use one universal shared secret for all internal services.

This may later evolve to stronger workload identity or mTLS without changing domain ownership.

## Failure behavior

### auth unavailable

No new OAuth login/refresh can proceed.

Already-issued OAuth tokens may continue only while their normal local verification remains valid.

### access unavailable

For a surface in `session_enforced`, protected execution fails closed.

Do not silently fall back to unrestricted behavior.

### Redis/Valkey unavailable

For a surface in `session_enforced`, session validation fails closed.

MVP may require session reissue after recovery.

### integrations unavailable

Account-backed operations fail.

Do not silently switch to another provider account.

### invocations unavailable

An otherwise authorized successful provider action should not fail solely because invocation history cannot be recorded.

Use bounded retry/queue behavior rather than turning invocation storage into an execution dependency.

## Administration UI for MVP

The first UI does not need a full policy editor.

### Sessions

Show:

- session UID;
- MCP surface;
- account scope;
- access level: read-only/full-access;
- status;
- created time;
- last activity;
- expiry, where `0` means no automatic expiry;
- safe description.

Actions:

- approve/reject full-access request;
- choose/change account scope;
- revoke;
- approve requested extension / set expiry;
- edit safe description.

### MCP session-control switches

For the current user, show every configured MCP surface with its own:

```text
unrestricted / session_enforced
```

switch.

The UI may provide batch actions that update all individual switches in one request.

There is no separate global persistent switch.

Existing sessions remain stored and unchanged while a surface is unrestricted.

### Realtime

Session/elevation/control changes should appear without polling-heavy behavior.

Initial topic:

```text
access.sessions
```

Additional topics can be added when granular permissions are introduced.

## Migration order

The legacy MCP remains untouched until replacement components are accepted.

Recommended order:

1. Implement local `auth` database/users.
2. Replace GitHub-backed platform login with local OAuth.
3. Add asymmetric signing/JWKS; gateway becomes verifier-only.
4. Validate OAuth separately for each MCP resource with the initial local user.
5. Establish stable integration account IDs and initial-user ownership semantics.
6. Implement MVP `access`: automatic read-only sessions, full-access elevation, Redis hot path, revocation and per-MCP control mode.
7. Add the common session contract to new MCP surfaces.
8. Add admin UI for sessions, elevation requests, expiry and per-MCP switches.
9. Move provider accounts/credentials into `integrations` as each provider is migrated.
10. Move MCP call history into `invocations`.
11. Associate existing files/workspaces/analysis projects with the initial user during their migrations.
12. Migrate MCP/provider surfaces one by one.
13. Add granular permissions, sharing and teams only after the coarse session model is stable.

## MVP acceptance criteria

The MVP authorization contour is accepted when:

- local OAuth no longer depends on GitHub identity;
- the initial local user can authorize each dedicated MCP surface independently;
- a new MCP connection can automatically obtain a read-only agent session with a configurable default TTL of 1 hour;
- under `session_enforced`, every normal tool call requires the session UID;
- base sessions allow only methods in the surface's static MVP read-only classification;
- account-backed base access exposes only safe account alias/ID discovery, not sensitive account details;
- mutating methods require approved `full_access`;
- a session is rejected on another MCP surface;
- account-backed full access respects `none/all/selected` account scope;
- `all` automatically includes newly available accounts for the same user/surface;
- normal session validation uses Redis/Valkey rather than PostgreSQL per call;
- Redis loss never fails open;
- revoked/expired sessions stop new calls immediately;
- cancellable active local work is terminated on revocation;
- expiry/revocation never downgrades the old session; reissue creates a fresh read-only session with no carried full-access state;
- repeated invalid-session attempts use configurable escalating backoff/rate limits and can eventually revoke the offending OAuth session;
- the admin UI can approve/reject full-access requests;
- the admin UI can revoke sessions and set/extend expiry;
- `expires_at = 0` supports sessions without automatic expiry;
- each MCP surface has an independent `unrestricted/session_enforced` switch;
- disabling enforcement preserves sessions;
- re-enabling enforcement reuses still-valid sessions without resetting them;
- UI-wide enable/disable controls are batch updates only;
- existing persistent resources can be associated with the initial stable user ID;
- teams/sharing/granular capabilities are not required for MVP.

## Deferred production features

Explicitly deferred:

- multiple users in normal operation;
- teams;
- user/resource sharing;
- account sharing;
- granular capabilities;
- sensitive-read permissions;
- per-tool mutation grants;
- privilege-elevation grant objects;
- resource-level repository/project/branch ACLs;
- delegated approval;
- advanced RBAC/ABAC;
- MFA/passkeys;
- automatic Redis session-projection rebuild;
- distributed/high-availability access service;
- KMS/HSM key storage;
- advanced abuse scoring.

These are expected extensions, not reasons to delay MVP.

## Architectural decisions

- No generic platform core service.
- No provider-backed platform login.
- No Keycloak for MVP.
- No direct cross-service database access.
- OAuth identity and agent access session remain separate.
- OAuth authorization is per dedicated MCP surface.
- Agent session uses one opaque UID stored directly for MVP.
- Agent session is always scoped to one stable MCP surface ID.
- Account-backed sessions use `none/all/selected` account scope.
- New sessions are automatically active and read-only.
- MVP has one elevated level: full access within the MCP/account scope.
- MVP read/write tool classification is static per MCP surface; dynamic named access levels are deferred.
- New sessions default to a configurable 1-hour TTL.
- Expired/revoked sessions are never reused or downgraded; reissue creates a fresh read-only session.
- Granular permissions are deferred.
- When session control is enabled for a surface, all normal calls require a session.
- Valkey/Redis is mandatory for the normal session-validation hot path.
- PostgreSQL stores durable session lifecycle and access-security history.
- Session enforcement is configured independently per user/MCP surface.
- “Enable/disable all” in the UI is a batch operation, not a separate global state.
- Switching enforcement off preserves all sessions and access state.
- Re-enabling enforcement reuses still-valid sessions.
- `expires_at = 0` means no automatic expiry.
- Revocation is immediate for new calls and cancels locally cancellable active work.
- Existing resources migrate to the initial local user before multi-user sharing is introduced.

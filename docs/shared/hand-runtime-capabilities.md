# Private Hand capability and readiness contract (v1)

**Owner:** Runtime, `shared/hand_runtime` and `hands/{files,terminal,web,svc,reverse,infrastructure}`.
This contract supports internal discovery of the source-port state without implying
that a caller may execute any tool. It replaces guessing enabled capabilities
from green Coolify liveness or the Control Panel's source-only module catalog.

## Internal private HTTP endpoints

- `GET /health/live` — HTTP 200 if the **process** is alive, regardless of
  whether MCP, its callers or tools are usable. Existing Coolify liveness uses
  this and must not be interpreted as readiness.
- `GET /health/ready` — HTTP 503, with `state: not_ready` while only
  diagnostics are live and verified identity/AgentSession/Cedar admission is
  absent. Liveness and diagnostic MCP connectivity are not execution readiness.
- `GET /internal/v1/capabilities` — HTTP 200, JSON, private network only, no
  tokens, secret state, user IDs or enabled operations. The JSON shape is:

```json
{
  "schema_version": 1,
  "hand": "files",
  "source": "packaged_tool_declarations",
  "declared_tool_count": 12,
  "interface_format": "python_declaration_not_mcp_json_schema",
  "declared_tools": [
    {
      "name": "file_read",
      "module": "modules.files.file_tools",
      "title": "File read",
      "arguments": [
        {"name": "path", "annotation": "str", "required": true},
        {"name": "offset", "annotation": "int", "required": false, "default": 0},
        {"name": "length", "annotation": "int", "required": false}
      ],
      "return_annotation": "JsonObject",
      "source_annotation_ref": "read_annotations"
    }
  ],
  "mcp_transport": "diagnostic_only",
  "authorization": "not_configured",
  "execution": "disabled"
}
```

The example `declared_tools` array is shortened for documentation; an actual
response includes all parsed declarations. The *count* is the number of
source-level `@mcp.tool(...)` function declarations found in the source tree,
not a claim that a tool is mounted, registered with any consumer or safe to
invoke. Names, static titles, docstrings, return annotations, parameter type
expressions, literal primitive defaults and any source annotation reference
are derived by Python AST without constructing tools or instantiating clients.

**This is a source-signature format, not MCP `tools/list` or a validated input
JSON Schema.** Complex types such as `ClientFile`, `JsonObject`, unions and
Pydantic models are retained as literal annotation expressions, *not* silently
converted into incorrect or permissive JSON schemas. Dynamic default values
are omitted; such parameters may have `required: false` without a `default`
field. Source annotation names such as `read_annotations` are only identifiers,
not current permission grants, verified read-only guarantees or executable
capability flags. Registration and per-effect authorization of each **business** tool are
still needed before invoking that tool. The copied implementation lives inside
the Hand, never imported from `services/` at runtime.

Every response is non-cacheable. The exact private `/mcp` route now mounts a
**real FastMCP 4 Streamable HTTP server** with stateless JSON responses and
an explicit internal Host allowlist. Only two actual diagnostic MCP tools are
registered in `tools/list`: `hand_status` (process, auth, declared-source count,
readiness) and `hand_source_summary` (module-level counts). Both are fixed,
read-only, bounded metadata operations without credentials or provider calls.
Native `initialize` and both `tools/call` methods work on `/mcp` when accessed
from a permitted private host. All historical 216 source-declared business
operations remain unregistered in the live MCP server. Calling a legacy tool
name returns an MCP unknown-tool error; no implicit privileged fallback.
All other private provider HTTP paths still return 503; WebSockets remain
denied. No public domain or Gateway `/hands` route is added. Full availability
still requires real Rauthy issuer/signature/audience and fresh Cedar/AgentSession
checks at the execution boundary and sandbox isolation before enabling effects.

## Staged signed OAuth resource access (LOCAL source, not deployed)

The six independent Hand Compose inputs now forward two **nonsecret**,
per-Application operator trust values with empty defaults:
`MCP_RESOURCE_AUDIENCE` and `MCP_RESOURCE_SIGNING_ALGORITHM`. They must
be supplied **together** only after the Rauthy owner has registered a real
scoped MCP access-token audience and observed the signing algorithm of an
actual issued *access* token. The issuer and JWKS are canonical public
Rauthy facts held as verified code constants, **not redundant environment
settings**. The exact resource audience is strictly
`https://briareus.koba-nexus.ru/hands/<hand>/mcp` for the owning Hand;
Panel client audience and another Hand's URI are refused at startup.
`MCP_RESOURCE_*` does not contain credentials and never permits bypass.

With trust values absent, existing `tools/list` exposes only the two
read-only diagnostics, `mcp_transport=diagnostic_only`, and readiness stays
503. With both values configured, upstream FastMCP `JWTVerifier` supplies
issuer/JWKS/signature/algorithm/audience verification using a JWKS rotation
cache; it is NOT a locally signed OAuth provider. An additional non-effect
`hand_permission_probe` may appear only under this resource-auth stage but
currently returns `MCP_RESOURCE_SCOPE_UNAVAILABLE`, because it has no real
resolved resource owner or per-tool grant. It cannot upgrade an action-only
Permit into access to any legacy business tool. Resource-scoped effects must
bind the true Hand tool, canonical owner resource and signed peer attestation
before the independent Authorization decision can Permit an operation.
An incomplete or wrong audience/algorithm configuration fails startup, not
silently falls back to an unauthorized privileged endpoint.

An explicit per-tool action map is now required by the Hand-side effect PEP.
Files reads and writes use different Cedar actions (files.read versus
files.write), and every tool must obtain its resource from an asynchronous
trusted owner resolver, not from caller JSON. The shared ResolvedEffect validates
the exact Backend V2 Hand/action/kind/resource syntax and computes its canonical
effect key for a FUTURE authenticated service-peer attestor; it never transmits
that key as a caller-provided header. No business resolver is registered yet.
Deny-by-default middleware is installed even without an OAuth verifier so
an accidentally added tool cannot bypass the PEP in diagnostic-only mode.
SDK-verified signed identity and a matching bearer-only HTTP request are checked
BEFORE any resource resolver runs. Canonical lowercase UUIDv4 Project and
AgentSession selectors and an unpadded positive grant revision must also
pass **before any owner I/O**, not only after it. Bearer and original selector
values are checked again after owner resolution and after the private Cedar
reply, so a grant-revision/Project replacement during either await cannot
start the protected tool. The private body and effect resource remain fixed.
Resource resolvers must perform only bounded owner verification, not the
protected effect itself.

A future tool registration must provide an immutable server-side
`ToolEffectBinding(action, kind, resolve)`; action and kind cannot be chosen by
the resolver and cannot be overridden through MCP arguments. Each async
resolver must return `ResolvedEffect` with the verified canonical resource ID
**and the exact executable arguments**. The middleware deep-snapshots bounded
JSON arguments before Authorization, passes only these canonical arguments into
the actual FastMCP tool call, and never reuses the caller's mutable input.
An absent canonical argument object, mismatched action/kind, denied policy,
owner exception or resolver timeout denies the operation with no tool call.
The bounded resolver timeout is for non-effect owner lookup only: side effects
must occur *after* independently attested Cedar Permit. This closes the
parameter-swap risk between scope resolution and protected execution, but
is not a substitute for actual owner-attested resource identity or executor
network isolation. No historical business tool is registered by this
source-only contract.

### Explicit protected-tool composition root (staged, not deployed)

`ProtectedHandTools` permits only a server-owned registration callback,
immutable `ToolEffectBinding` map and injected trusted private Decision
port to be supplied together. It requires a separately configured actual
FastMCP resource JWT verifier; malformed or missing trust refuses factory
construction. The enforcement middleware is registered before any
protected tool; an undeclared tool cannot inherit authorization from
diagnostics. The default six Hand entrypoints supply no protected
registration and still expose only safe diagnostics.

The Files-specific optional `build_protected_files_app` adds one
`read_file(path,max_bytes)` only after all four explicit owner ports have
been supplied by the trusted composition root. It does not construct those
ports, accept them from MCP/ENV or mount the protected tool in the deployed
Files service. Both its effect PEP and its independent original
caller/current-owner, two-phase read authority must pass at runtime.
Injected-but-unaccepted ports are reported as such with readiness 503, not
as authorized execution. Local signed RSA fixtures prove the negative
boundaries, including that a synthetic Cedar Permit cannot substitute
for a trusted Files channel. Real Rauthy/Cedar/Project owner and Dev read
remain unaccepted.

### Parallel six-Hand read-only adapters (staged, not deployed)

The verified-source [six-Hand owner matrix](runtime-six-hand-owner-matrix-20261016.md)
records AST declaration counts, default diagnostic-only entrypoints, staged
read-only candidates, exact existing resource kind/action and the missing
resource-owner interfaces. Web browser_snapshot originates in the separately
reviewed Deployment [draft PR #545](https://github.com/KobaProduction/briareus/pull/545)
and now requires an independent post-read browser-owner/current-lease check
**after** extracting visible text but **before** returning it. No global
BrowserManager, Chromium profile, download, CDP or privileged browser tool
is imported by the staged adapter.

Terminal, SVC, Infrastructure and Reverse use one optional
shared/hand_runtime/_owner_metadata.py factory with per-Hand fixed tool
names. Only an explicitly injected real signed resource verifier, the
current Project/AgentSession scoped effect resolver, a genuine private
Cedar decision port and a fresh owner inspection port can return the narrow
{state,revision} DTO. The ordinary entrypoints remain unchanged, return
two diagnostic tools, and readiness 503. Source-only signed RSA fixtures
prove foreign audiences deny and altered grant revision during owner awaits
denies even with a synthetic Allow. Starlette caches Request.headers;
the PEP's repeated authorization checks now recreate a fresh Request view
over the **current raw ASGI scope** to avoid accepting a stale cached
header wrapper.

The current Backend V2 actions terminal.execute, integrations.use and
analysis.import are broader than read-only inspection. These staged
candidates are **not authorized product read grants**, even with
readOnlyHint: true in tool annotations, until Backend agrees a narrower
per-Hand read vocabulary and matching resource/lease contracts. Neither
the annotation nor a synthetic test Permit can establish real authority.

### Independent private Authorization transport (LOCAL source only)

A signed Rauthy Bearer and fixed internal Docker DNS are NOT a trusted
service identity. The Hand PEP no longer constructs a plain private HTTP
client that automatically forwards Bearer to briareus-authorization. Instead,
a server-injected `TrustedPrivateDecisionPort` must be present BEFORE any
privileged resource owner lookup is initiated. With no port, effects return
`MCP_AUTHORIZATION_UNAVAILABLE` and no credential is forwarded.

A future genuinely authenticated mTLS/Unix adapter must bind actual OS/TLS
service peer identity, a short-lived replay-protected nonce, and the exact
canonical Hand/tool/resource effect key to the precise serialized private
POST body (maximum 8192 bytes). It must send the already SDK-verified access
token only across that independently accepted transport. Backend V2's
`briareus.verified_private_peer.v1` ASGI scope is installed by the
Authorization server's TRUSTED inbound adapter, not produced by a Hand
header or its untrusted JSON. No scope injection, nonce issuer, TLS client,
Unix socket, or authenticated worker has been implemented by this port
contract; there is intentionally NO fallback to plain HTTP. The port's
`PrivateDecisionReply` is interpreted strictly: only 200 with
`{"allowed":true}` may advance, 401 and 403 deny, other states/unavailable
deny. Integer 1 is not a Boolean Permit, and duplicate JSON keys or
unknown fields never grant access. Gateway has an analogous required
TrustedGatewayDecisionPort for coarse admission; it also fails closed
before forwarding a Bearer when no real peer adapter has been provisioned.
See docs/services/gateway/runtime-admission.md for that contract. This
is not evidence of an actual Permit/authorization lifecycle.

The current Backend private `POST /internal/v1/authorization/decide` in
published main defaults HTTP 503 without an independent trusted attestor.
Backend's peer-local proposed resource-scoped DTO is NOT the published/live
contract yet. Source-level HTTP handshake, a certificate/JWKS document or
an action-only 200 are insufficient proof of resource ownership, grant TTL,
revision and revocation. The resource/method/tool binding must be derived
from the actual Hand execution arguments and independently verified by its
trusted peer before any historical effect is registered. Until then all
216 legacy declarations are **source only**, their invocation remains
denied/unregistered and the service stays not-ready for business operations.

Gateway, Control Panel API forwarding and the direct Hand ASGI MCP
boundary now require a canonical single decimal Content-Length where
present: leading zeros and ambiguous framing are rejected before
normalization or private Cedar calls, in agreement with the Backend
Authorization private request parser.

The outer ASGI request preflight caps each MCP JSON body at 1 MiB, 1024
body events, and eight seconds for the complete body read. It accepts only
UTF-8 JSON objects with unique keys at every nesting depth, rejects
Python-specific NaN/Infinity, finite-float overflows, unpaired Unicode
surrogates and invalid/batched JSON, and replays exact unchanged bytes to
FastMCP on success. Body timeouts return 408, oversized
or excessive fragments 413, and malformed/ambiguous JSON 400. Rejections
are sent after exiting the read deadline, preventing a slow response writer
from producing a second HTTP response. Host and Origin are rejected
**before** preflight, token or private Authorization lookups, while
FastMCP's own guard remains active.
Gateway forwards bounded canonical Project/AgentSession/revision selectors
after successful coarse `mcp.connect` admission only; neither header values,
private DNS nor `get_access_token()` alone prove current resource ownership.

## Integration boundary

The **Control Panel UI must not access Hand container URLs directly**. The
Backend owner may eventually expose a narrowly authorized BFF catalog using
this nonsecret internal schema, after it has reviewed the real current owner
contract. No fake active tool status or synthetic capabilities are permitted.
The UI's modules (e.g. GitHub/GitLab under SVC and analysis under Reverse) are
presentation groups, not one-to-one deployment resources. Business operations
remain under existing owner scopes. `shared/hand_runtime` has one Runtime owner;
other independently deployed modules may consume only its explicitly scoped
`shared/hand_runtime/**` Watch input.

### Resource token purpose and original-caller continuity

SDK signature/issuer/audience validation is necessary but not sufficient:
its verified claims may still describe an ID or Refresh token. Before any
resource-owner resolver, the Hand PEP now requires the agreed Rauthy
`typ=Bearer`, bounded `azp`/`jti`, strict integer iat/nbf/exp and unique
resource audiences. Unsupported `cnf`-bound tokens are rejected. The SDK
still owns key selection and cryptography; no additional signer or token
URL is introduced. Generic MCP clients are not restricted to Panel's client.

The original verified bearer is retained across the resolver and private
Authorization await. It is checked again immediately before invocation:
expiry or replacement during a delayed decision cannot start the tool.
A valid token still supplies neither resource ownership nor Cedar Permit.
Real SDK verification with temporary RSA-signed fixtures covered wrong
purposes and proof-bound tokens; controlled decision responses covered
expiry/rebinding during the await. These checks do not establish a real
provider account, private peer, successful business call or public Files
read. Diagnostic registration and readiness remain unchanged.

### Resource bearer delegation and lifetime consistency

SDK-verified access tokens are additionally checked for the
Backend-origin resource purpose ceiling: signed exp-iat must not
exceed 86400 seconds, and unsupported delegated act claims are
rejected alongside proof-bound cnf. The checks precede resource
resolution and cannot transform a signed token into a Cedar Permit.
Temporary RSA-signed inputs and the real FastMCP verifier exercise
these cases without creating a provider account, authorization or
registered Files business effect.

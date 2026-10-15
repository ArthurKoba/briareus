# Private Rauthy-based Files read decisions

Status: local source integration. The normal service factory remains unavailable
until current Rauthy, private ingress, Platform, Access SQL and Files resource-owner
ports are genuinely configured. This is not a deployed Files tool or login result.

## Owners and scope

`POST /internal/v1/authorization/files/read-decision` is a private Authorization
endpoint, not a Control Panel route. It reuses the existing Rauthy resource-audience
verifier, body/effect-bound Files peer with one-use nonce, current Platform Project
membership, and the Access-owned SQL/Cedar evaluator. It additionally requires the
existing `TrustedResourceOwnerPort` to verify the current Files selector/revision.
No Platform or Files tables are read through Access's database connection.

The endpoint deliberately does not construct the legacy A6 `ProjectOwnerFence`,
Identity epochs, service-human assertion signer, filesystem root or directory.
It does not return a JWT, OAuth bearer, A6 FilesReadPermit, file contents, raw path,
root FD or independently transferable permission. An HTTP200 is useful only as a
validated reply to the original request on an independently authenticated private
connection. A copied JSON reply, header, UUID or inode is not that connection.

## Request

JSON fields are required; additional fields are rejected:

```json
{
  "protocol": "files-read-decision-v1",
  "operation_uuid": "<UUIDv4>",
  "phase": "before_read",
  "project_uuid": "<UUIDv4>",
  "agent_session_uuid": "<UUIDv4>",
  "expected_grant_revision": 4,
  "expected_resource_revision": 7,
  "max_bytes": 4096,
  "hand": "files",
  "tool": "read_file",
  "action": "files.read",
  "resource": {
    "kind": "workspace_path",
    "id": "project-path-v1:<canonical Project UUIDv4>:<A6 path digest>"
  }
}
```

`phase` is `before_read` or `after_read`. Revisions are strict positive signed-64-bit
integers; `max_bytes` is a strict integer from 1 through 262144. The compact Files
selector must be canonical and belong to this same Project. The opaque operation
UUID is chosen once by the trusted execution coordinator and retained across the
two phases. It is not a permission or an idempotent write token.

Each phase requires a new authenticated peer request/nonce bound to the **entire
actual JSON body**, including protocol, phase, operation, byte limit and revisions,
not just the resource tuple. The existing `TransportAuthenticatedDecisionPeerResolver`
checks the supervisor-provided ASGI proof; it does not accept equivalent X-headers.
A resource-audience Rauthy token and fresh Platform membership are independently
checked on each phase. No prior receipt is accepted as input or proof.

## Response and failure semantics

A verified response contains `protocol`, `allowed:true`, `operation_uuid`, `phase`,
`actor_uuid`, `project_uuid`, `agent_session_uuid`, `hand`, `tool`, `action`, `resource`,
`grant_revision`, `resource_revision`, `max_bytes`, `checked_at`, and `expires_at`.
The original selectors are checked against actual Access and Files-owner facts,
not merely echoed as permissions. The Files decision service independently
checks the attested Hand caller's audience, signed actor, Project, AgentSession,
exact effect key and deadline BEFORE owner lookup. It also validates the
returned current SQL/Cedar grant type, actor, Project, AgentSession, exact
revision and nonextended expiry. Even a future faulty private adapter returning
a positive grant for another actor/Project/version fails closed. These checks
do NOT confer client-side bearer authority or supersede real attestation.
Expiry is no later than the minimum of the
original identity/peer/Platform proof, current grant expiry, initial and post-SQL
resource proofs, and five seconds after `checked_at`. A later resource proof
cannot extend an already expired original proof. SQL transaction exit is also
inside the freshness boundary, including the ordinary `/decide` path.

Missing signed identity yields 401; scope, revision, expired proof, replay or
current-policy denial yields 403; malformed input yields 422; unconfigured or
unavailable authorities yield 503. Successful responses and explicit service
failures have `Cache-Control: no-store` and `Pragma: no-cache`. There is no fallback
from 503 to a cached Permit or from 403 to old Identity/A6 metadata.

## Runtime consumption

The Files owner first binds the verified execution request to its actual Project
root FD, root incarnation and current mapping revision. The resource revision is
an owner fact, not an integer synthesized from an inode or absent Identity epoch.
The read uses immutable canonical path/max_bytes and the same selector everywhere.

The private adapter requests `before_read`, checks all returned identity, scope,
operation, revision and byte-limit fields, then keeps the root descriptor and
original expiry alive throughout the bounded read. Before bytes can be released,
it calls `after_read` with the **same** operation, selectors, byte limit and original
expected revisions, but fresh signed identity/peer/membership and nonce. A changed
revision is denial, not permission to update the request and release old bytes.
The Files controller separately reopens/rechecks the full relative path beneath
the retained root and confirms root/file observations and ownership. Context exit
must not suppress a denied final check or extend the original lease.

This endpoint is stateless with respect to phase order: `after_read` is a fresh
point-in-time policy decision, not proof that a read occurred. The trusted Runtime
scope must require the complete before/read/after/exit sequence. Both the original
and final proof expiry must still hold at release. Expiry is an upper bound, not
permission to skip the final fresh authorization call. Separate owner observations
do not create a distributed SQL transaction or guarantee against changes after
the final enforcement boundary.

## Validation boundary

Tests exercise real JWT signature and resource-audience checking, actual body-hash
and nonce validation, private routers, Access SQLAlchemy selectors and Cedar on
controlled peer/Platform/Files/SQL fixtures. They cover both phases, revoke between
phases, changed Files owner revision, lost Project membership, wrong audience,
replayed peer nonce, changed body, absent owner, exact DTO limits, short original
expiry, and expiration while leaving the SQL transaction. No actual Rauthy User,
physical PostgreSQL, mTLS identity, Files mapping registry or registered MCP read
is established by those tests.

A separate bounded local integration ran an actual loopback Authorization HTTP
server and the Runtime FD-read consumer in different Python environments. Runtime
source was snapshotted read-only; the file/root were private temporary test data.
The plain HTTP link and injected TLS provenance were test-only, while the actual
JWT/body/replay/Cedar code and filesystem confinement were executed. Matching
before/after decisions released the expected test bytes. A revoked grant or changed
resource revision produced before200/after403 and no bytes; modifying the file
produced two policy200 replies but the independent FD/file recheck still withheld
bytes. All four cases closed their descriptors, and both processes were stopped.
This demonstrates wire/consumer and OS integration, not real Rauthy/mTLS, persistent
Platform/Access/Files ownership, public MCP registration or production readiness.


## Bound Runtime adapter cross-owner acceptance

A later local integration consumes the named Runtime `BoundFilesReadAuthority`
(`b1156e7`, retained in `b0e84f7`), its exact request encoder/reply decoder and
`UnmountedNativeFilesRead`; there is no test-only replacement of the two-phase
scope coordinator. Runtime source is copied read-only into a private snapshot,
and the Access HTTP server and Files reader run in separate owner environments.

Eleven scenarios pass: matching before/after decisions release the temporary
file bytes; grant revoke and resource-revision change deny at after_read;
file-content change denies despite two policy200 replies; ID, Refresh,
unsupported bound credentials and wrong audiences deny before reading; altered
operation UUID, excessive reply expiry and duplicate reply keys deny at the
actual Runtime decoder. No failed scenario releases bytes or leaks descriptors.

The channel/root ports, ephemeral issuer, Platform and SQL remain explicit test
fixtures. Only HTTP, JWT/Cedar code, the real adapter and temporary OS file reads
are exercised. Neither an authenticated mTLS listener nor a genuine Files root
registry or registered MCP tool is implied. No peer source/process is changed.

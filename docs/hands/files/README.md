# Files Hand — independent private service

This folder is the target `hands/files/` module. It owns a locked Python
runtime, small ASGI entrypoint, Dockerfile and two Compose manifests.

- Coolify existing application: the original approved Briareus Development
  application. Do not create another application or expose a public domain.
- Base Directory: `/hands/files`
- Compose location: `/docker-compose.coolify.yaml`
- Watch Paths: `hands/files/**` and `shared/hand_runtime/**`
- Network service alias: `briareus-files` on the existing internal network.

**Diagnostic MCP transition — not authorized business-tool execution.**
`GET /health/live` reports process liveness; `/health/ready` remains 503.
The internal `/mcp` Streamable HTTP endpoint now implements real MCP
`initialize`, `tools/list`, and two bounded, read-only calls: `hand_status`
and `hand_source_summary`. It does **not** register or call the copied
`services/modules/files` privileged tools; all other private provider HTTP
paths still return 503, and WebSockets are denied. Business tool activation
requires verified Rauthy identity/audience, current Cedar AgentSession
permission for each effect, and appropriate sandbox/network isolation.
See `docs/shared/hand-runtime-capabilities.md` for the exact v1 contract.

Existing `deploy/files/` remains a rollback source. Preserve the existing
resource UUID, networks, DNS, variables, release history, storage and app state.

The prior named volume `briareus-files-v1` is **not deleted or migrated**.
This safety shell intentionally does not mount it or start an untrusted
executor; reattachment requires independently validated sandbox isolation.

## Private MCP read selector staging (untrusted, not mounted)

`hands/files/src/files_hand/_mcp_request.py` prepares the next protected
`read_file` call's **untrusted command selectors** from the actual private
`/mcp` Request, rejecting raw URI aliases or query-provided identity. It
accepts one Bearer-syntax header, canonical Project and AgentSession UUIDv4,
one positive canonical grant revision, and the existing `FilesReadArguments`
path/byte-budget contract. It rejects caller
cookies, duplicate/ambiguous selectors, client-supplied actor/root/operation
fields and unsafe paths. The Hand itself mints a fresh UUIDv4 operation
identifier for each attempt; repeated Project+path selectors have the same
canonical resource identity but different command fingerprints.

This helper deliberately does **not** validate a Rauthy JWT, resolve a User,
produce current Project ownership, authenticate an Authorization peer or
read any file. A syntactically staged `NativeFilesReadRequest` remains
untrusted, including when Gateway supplied canonical headers. It is NOT
registered as a FastMCP `read_file` tool. Activation still requires the
SDK-verified per-Hand resource audience, an independently authenticated
private Access/Cedar channel and current owner mapping/root adapter. The
source test `hands/files/tests/test_mcp_staged_read.py` confirms both
strict selector rejection and that staged commands cannot read bytes
through the default unmounted authority.

## Explicit owner-injected Files MCP activation (still unmounted)

The private `files_hand/_mcp_activation.py` factory prepares `read_file` for
the first real signed-resource integration. It is **not imported or called by
the deployed `files_hand/server.py` entrypoint** and introduces no Compose
variables, new applications, credential issuers or storage mounts. Every
trusted port must be injected together by a supervisor: a current owner
effect resolver with immutable executable arguments, an independently
authenticated private Cedar decision port, a signed Rauthy Files read
channel and a current Project-to-Files root mapping port. Configuring an
audience in ENV without these ports cannot mount any business tool.

The shared `ProtectedHandTools` registrar installs the per-tool middleware
BEFORE registering tools. Missing Rauthy resource verifier prevents creation
of an activated instance. For `read_file`, the actual FastMCP middleware
independently validates the signed resource token and current Cedar action
`files.read` for the server-owned canonical path. The handler then stages a
fresh operation UUID from the actual HTTP request and calls
`UnmountedNativeFilesRead(BoundFilesReadAuthority(...))`, whose original
caller and Files root are checked again before and after reading. No local
JSON argument, synthetic Permit or caller header can supply a root FD.

Both optional factory diagnostic output and /health/ready remain
`owner_ports_injected_unaccepted` / HTTP 503 until real signed provider,
current Project mapping, complete two-phase Access, and Dev runtime acceptance.
Failures never expose raw file bytes, private paths, tokens or owner details.
`test_private_mcp_activation.py` proves with an ephemeral genuine RSA
signature that unsigned Bearers fail before owner I/O, a signed fixture can
see the prepared tool without being a real Rauthy User, a missing owner
fails, and even a **synthetic** positive Cedar reply cannot read without
the independent Files channel. This does not satisfy product Permit/Deny/
Revoke acceptance.

## Prepared bounded read consumer (not a public MCP tool)

`hands/files/src/files_hand/_read_adapter.py` supplies the private
`UnmountedFilesReadEffect` for the next Files integration step. Its caller
input is exactly a canonical NFC Project-relative `path` and optional
`max_bytes` (1–262144, default 262144). Traversal, absolute paths, malformed
Unicode, temporary upload names, excess path depth/length and extra
identity/grant fields are rejected. Percent characters are literal
filesystem characters, not URL escapes. Construction and JSON parsing
share the same validation; a frozen argument snapshot preserves path
and limit while asynchronous owner work is pending.

Execution still requires an injected `ProjectFilesService` and a separate
server-provided `ProjectInvocation` whose operation scope matches the
Project, AgentSession and `files.read`. These Python types establish only
structure, not identity or permission. The existing service performs
`ProjectRuntimeAuthority.require`, its A6 signed Files read-permit flow,
descriptor-confined reading and a final current-owner/revocation check.
Missing authority stops before filesystem access. No new SQL, JWT signer,
permission issuer, storage root or alternate authorization port is added.

The result contains bounded Base64 bytes, byte length, canonical path and
SHA-256 only after that service returns. Raw content is excluded from the
result's representation; owner/OS/timeout failures yield one public error
without internal details. Cancellation propagates rather than returning
partial file data. This wrapper does not add the separate A14 snapshot
witness flow: that workflow and the mapping from current Authorization
V2 resource decisions to a server-owned invocation still require the
responsible owners' contract. There is no implicit compatibility claim
between a Cedar decision and the historical A6 protocol.

Focused source checks:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=hands/files/src \
  hands/files/.venv/bin/python hands/files/tests/test_read_adapter.py
```

The real Files service is exercised for missing-authority denial before
storage and for cancellation. Fixture-only cases test byte encoding,
immutable arguments and error redaction; they do **not** prove an
authorized native file read. The entrypoint remains unchanged: MCP
`tools/list` exposes only the two diagnostic tools, and readiness remains
503. Mounting a read tool requires a verified Rauthy resource token,
independent private Authorization peer, current Project/AgentSession
resource decision, and a working Files-owner authority. No positive
Cedar or product acceptance is claimed by these checks.

### Agreed compact Authorization V2 selector

`files_hand/_read_scope.py` holds the agreed naming contract only; it is not a
trusted resource resolver and remains unmounted. Selected tool `read_file`,
action `files.read`, kind `workspace_path` uses:

    project-path-v1:<canonical Project UUIDv4>:<A6 path_fingerprint>

A6 path_fingerprint is the existing SHA-256 of
`b"files-project-relative-v1\0" + canonical_path.encode("utf-8")`.
The ID is always 117 ASCII characters, so long supported Files paths are
not truncated to fit Authorization's 512-character resource-ID limit.
The existing storage registry supplies one Files namespace per Project;
unknown additional workspace namespaces require a different agreed
contract, not a client-selected mount.

The original canonical NFC path and max_bytes remain immutable execution
arguments. Different Projects/path bytes produce different selectors;
changing the byte budget does not name a different file. A digest proves
neither resource existence nor permission. Current storage incarnation,
owner revision, identity and signed operation must still be independently
verified, and V2-to-Files-owner/A6 mapping must be agreed before activation.
Pure encoding vectors (including a 4095-byte path) were accepted by the
actual Backend V2 DTO/resource_key code. This establishes format parity,
not a live grant or completed owner integration.

## Rauthy-native read authority boundary (unmounted successor)

Backend `fa7c67c` confirms that the legacy `ProjectOwnerFence`/A6 read
consumer above cannot be populated from Authorization V2: the old
Identity epochs no longer have an authoritative source. Do not synthesize
zero epochs or treat `{allowed:true}` as a `ProjectPermit`. The existing
legacy consumer and its checks remain unchanged, but are not a fallback
for Rauthy-native execution.

`files_hand/_native_read.py` is a separate, unmounted read consumer using
`NativeFilesReadAuthority.open_read(request)` as its sole private authority
boundary. `_read_authority.BoundFilesReadAuthority` composes its required
private channel and root ports; neither has a default credential, signer,
network permission or mapping authority. Missing ports refuse before IO.
The trusted composition root must
bind genuine Rauthy resource-token verification, current Platform and
Access state, the authenticated private peer, and the actual Files-root
mapping; a caller-created dataclass does none of that.

The proposed private request contains server request UUID, Project UUID,
AgentSession UUID, expected grant revision and frozen canonical path/byte
budget. Its domain-separated request fingerprint binds all these values
and the accepted 117-character selector. It is a binding checksum, not
an authority signature. The private scope supplies a live owner-held root
FD, root observation, authoritative Files mapping revision and original
Access expiry (no more than five seconds). Files mapping revision must come from actual
owner state — never derived from inode/ctime or legacy Identity fields.
An authenticated adapter for those facts is still required.

`files_hand/_fd_snapshot.py` performs only descriptor-relative filesystem
work. It reuses existing Files `openat2` no-cross-mount/no-symlink/beneath,
canonical-component, regular-file, single-link and private-owner-mode
checks. It duplicates the owner root FD, reads at most the requested
256 KiB, compares file metadata before/after, and reopens the full path
from the retained root to detect replacement/renamed ancestors. The
root/file device, inode, uid/mode, link count, size and mtime/ctime are
observed OS facts; they are not a signed receipt or proof of membership.
No root path is selected from MCP arguments and no directory is created.

Bytes remain private until scope revalidation confirms the ORIGINAL
verified actor/token/peer, current Project/AgentSession/grant and same
Files mapping/revision. Authority context exit must maintain the current
state barrier and may still deny. A final descriptor/full-path check runs
AFTER that exit, followed by another proof-expiry check. Only then is the bounded
Base64/SHA-256 DTO returned. A suppressed validation exception cannot
turn into success. Cancellation drains an already-started OS worker
before closing its FDs/exiting the owner scope, then propagates; no
partial bytes escape. The ten-second async authority deadline is not a
claim that an uninterruptible filesystem syscall can be forcibly killed.
Actual storage and executor isolation remain deployment prerequisites.

Focused checks use real private temporary files for filesystem behavior
and explicitly labelled owner fixtures for orchestration. They cover
stable binary reads, repeated FD cleanup, same-size mutations, full-path
replacement, symlink/hardlink/FIFO and unsafe-mode rejection; absent,
stale, mismatched, revoked or malformed scope; owner exit denial and
repeated cancellation. Fixture success is **not** real Access Permit.
The emitted text/binary/empty-file DTOs also pass the pinned Frontend
`2e7d581` decoder; wrong path/hash fails there. No browser Files endpoint
or MCP `read_file` is registered by this work.

Next owner integration: bind the above scope to actual portable
Rauthy/Platform/Access/Files facts and verify pre/post-read authority on
an independently authenticated transport. The FD/stamp stays private to
its Files instance; never serialize a raw FD across services. The prior
A6 epoch mismatch is not bypassed, and a signed read receipt is not yet
implemented or accepted.

### Two-phase Access reply consumption

The native consumer now matches Backend's `files-read-decision-v1`
private endpoint (#6183960367). `_read_decision.py` serializes exact
before/after command bodies and checks an already-authenticated reply
against the original operation, actor, Project, AgentSession, selector,
byte limit, grant and mapping revisions. Additional/duplicate fields,
wrong types, denial, phase mismatch, future/stale timestamps or a lifetime
over five seconds are rejected. The decoder does not verify an HTTP peer
or sign a grant: only the real private adapter may supply these replies.

The after-read phase uses a separate fresh peer nonce and the SAME
expected revisions; it cannot renew a previously expired read. Scope
`final_expiry` comes from the checked after-read receipt; both that expiry
and the original unextended lease are checked again after owner context
exit. No phase or result can be omitted by suppression of an exception.

A Runtime-owned copy of Backend's bounded native integration harness
exercised the actual private router/Cedar code over loopback HTTP and
the new consumer with real temporary FD/file contents in separate Python
environments. Strict Runtime reply decoding was used on both phases:
matching replies200/200 released fixture bytes; revoke or owner-revision
change produced200/403 and no bytes; file mutation produced200/200 but
OS revalidation still denied. All descriptors were closed. Signers,
transport provenance, SQL and Files mapping were explicitly fixtures.
This is cross-owner protocol/OS compatibility, not genuine Rauthy/mTLS,
physical owner data, an authorized public MCP read or Dev acceptance.


### Concrete scope adapter for private channel and Files root

`_read_authority.py::BoundFilesReadAuthority` implements the native scope
orchestration that the earlier integration assembled in its fixture.
A configured `TrustedReadChannelPort` must verify the original signed
resource caller and bind the immutable request BEFORE any root access;
`TrustedFilesRootPort` separately holds the actual current Files mapping,
revision and descriptor. Both ports remain mandatory and have NO default
credential, transport, directory or mapping implementation.

The adapter emits exact before/after `files-read-decision-v1` bodies and
checks authenticated replies using the existing strict decoder. It fixes
actor, original request fingerprint, resource/grant revisions and original
lease throughout the operation. After-read can be claimed only once;
changed mappings, denied replies, uncertain/repeated phases and owner
exit failures withhold bytes. An outer context suppressing an inner
owner-exit exception does not turn it into successful validation. Raw
keys and tokens remain encapsulated by the channel, not passed in tool
arguments or data-class representations.

The adapter was exercised with the actual Backend0301307 private HTTP
handler and temporary file descriptors in separate owner environments.
Matching phases released fixture bytes; revoke/resource change denied
at after-read; mutation denied even when both policy responses were200.
Signers, authenticated-channel provenance, SQL and mapping in that run
were STILL controlled fixtures. No production peer was fabricated, no
MCP tool or browser read route was enabled, and no real signed User read
is inferred from the protocol/OS success.


### Existing Project namespace binding without legacy permits

`_root_registry.RegistryFilesRootPort` implements the physical root side
of that composition. It reuses the existing safe ProjectRootRegistry base
traversal and openat2 child fence for the configured `<base>/<ProjectUUID>`
layout without constructing a legacy ProjectPermit or creating directories.
A separately supplied `TrustedProjectMappingPort` must first verify the
original actor/request, active Project mapping, authoritative resource
revision and deadline. There is no default metadata source and no revision
is derived from an inode. This is not a new Catalog, SQL owner or allow API.

The root port keeps both base and Project descriptors, reopens the complete
configured storage path during validation and detects replacement of the
base itself, Project rename/replacement, symlinks and unsafe directory modes.
The original mapping binding cannot change while workers await. Cancellation
joins the already-started OS worker before descriptors are closed; absence
of mappings refuses before directory access and never creates a namespace.
The existing native reader still requires both Access phases and final FD
checks before releasing bytes. Public MCP/readiness is unchanged.

Targeted checks use real private temporary Project directories plus explicit
mapping/caller/reply fixtures. They establish filesystem/lifecycle behavior,
NOT a live mapping registry, signed User, Cedar decision or MCP invocation.
The prior bound-scope HTTP integration remains separate evidence; the new
physical namespace port has not yet been accepted against genuine private
channel and current mapping-owner services.

### Unextended elapsed-time read leases

UTC expiry is retained, but is no longer the only measure of a held lease.
The native reader, two-phase authority and physical mapping scope capture
an additional monotonic deadline when they first accept each owner lease.
Both UTC and elapsed-time checks must pass. An after-read reply or backward
wall-clock adjustment cannot replenish the observed original budget.
The original and final read receipts retain their five-second limits;
checks run after awaited IO, owner exits and immediately before returning
encoded bytes. Channel/mapping lifetimes are independently retained too.

Failure while constructing a lease after the filesystem opener acquired
its descriptors now uses the same closing path. Mapping changes are
checked before root IO and acquired handles are reclaimed on expiry.
Clock-fault scenarios used controlled clocks/owner replies and real private
temporary files, with no system clock change or FD leak. They establish a
local expiry invariant, not a genuine mapping lease, signed caller, Cedar
Permit or registered MCP operation.

### Core / execution host boundary

The current owner architecture keeps PostgreSQL, Valkey, Rauthy,
Platform, Access/Cedar, Resources and Control Panel in Core. Gateway
and Files/other Hands belong to Execution even while the first MVP is
single-host. RegistryFilesRootPort uses ONLY the owning Files process'
configured local root and OS file descriptors; it has no direct Core DB
pool or assumed same-host service identity. Current Project membership,
Files mapping/revision and resource decisions must arrive through
separately authenticated owner channels, survive deployment on a
different Execution node, and fail closed while Core is unavailable.
No Node Agent or new services are created for the first MVP.

### Core outage while read is in progress

The first single-host release must not make Files' local descriptor or
an already accepted before_read decision a replacement for Core.
Controlled failures of the Access channel both before_read and after_read
now deny the entire read, even if file bytes were already obtained.
A separately simulated current-mapping authority outage during root
revalidation likewise denies. The source acceptance checks verify
that no bytes escape and all owned FDs close. These are deliberate
fault injections, NOT a live loss of PostgreSQL, Rauthy or the actual
Authorization service and not a signed Files read.

### Exact future Files result shape for an owner-authenticated BFF

The existing native Files reader holds payload bytes until *both*
authoritative Access decisions, current mapping/root FD checks, and
post-read expiry/revocation barriers have completed. Once that owner
code returns a FilesReadContent, its new content_payload() method
produces exactly four bounded fields: path, size_bytes, sha256 and
content_base64. Current Frontend read-result decoder expects precisely
these fields and independently validates size, SHA-256 and Base64. No
bearer, OS path, owner revision or private attestation is serialized.

This is a source-only result format. There is still NO publicly mounted
read_file MCP effect or browser content route. The Backend owner must
approve and implement a narrowly scoped management read endpoint with
current signed human/User/Project/AgentSession/resource and same-owner
origin controls. A browser must never call Hand endpoints directly or
promote a UI scope summary to a current Cedar authorization.

### Versioned browser Files content API handoff

The browser-facing owner API is versioned under /api/v1.
Authentication uses /api/v1/auth/*, while the future
POST /api/v1/files/read belongs to Control Panel Backend
and must independently check current signed User/Project/AgentSession,
resource and Files mapping, a private authenticated Access peer,
and read-after-revocation barriers. Gateway only forwards a request;
a browser Files scope display is never a Cedar Permit. The existing
four-field FilesReadContent encoding is a wire-format helper, NOT
an enabled browser route or a direct browser-to-Hand connection.

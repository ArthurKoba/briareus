# Control Panel Files content read — source-only BFF contract

**Owner:** Backend Control Panel API. **State:** source endpoint and typed
private-owner boundary, **NOT** an enabled Files read, current Cedar Permit,
accessible filesystem or live MCP tool. The default runtime provides NO
`TrustedFilesContentOwner`, and always denies file content with HTTP503. The
BFF never opens a Files root, queries Access SQL or becomes part of the
Gateway→Authorization→Hand execution dataplane.

## Browser-facing request and response

`POST /api/v1/files/read` is the fixed same-origin management API.
It requires the existing `__Host-briareus_oidc_session` opaque HttpOnly cookie,
exact Host and `Origin`, JSON Content-Type and bounded Content-Length. It rejects
browser Bearer/peer identity headers, duplicate session cookies, query
parameters, ambiguous chunked framing, duplicate JSON keys, oversized bodies,
noncanonical UUIDs and untrusted paths BEFORE private owner IO.

```json
{
  "project_uuid": "<canonical UUIDv4>",
  "agent_session_uuid": "<canonical UUIDv4>",
  "expected_grant_revision": 3,
  "path": "project-relative/file.txt",
  "max_bytes": 262144
}
```

The `path` is NFC UTF-8 and relative, 4096 bytes maximum; at most 64 components,
each at most 255 bytes. Empty, `.`/`..`, slash-rooted, backslash, control and
reserved upload-temporary components deny. The byte budget is explicitly 1..
262144; no unbounded default or body-supplied Files owner revision. The BFF
creates an unpredictable private `operation_uuid`, and computes the exact
Runtime `project-path-v1:<ProjectUUIDv4>:<sha256>` selector from the validated
UTF-8 bytes with `files-project-relative-v1` + NUL domain separation. It never
accepts an actor, token, root, service peer, resource selector or signed Permit
from browser fields.

**Only an independently verified owner result** may become HTTP200:

```json
{
  "path": "project-relative/file.txt",
  "size_bytes": 12,
  "sha256": "<64 lower-case hex bytes>",
  "content_base64": "<canonical base64 of exactly size_bytes>"
}
```

The four-field shape matches Frontend's bounded `decodeFilesReadResult` and
Runtime's `FilesReadContent`. The BFF recomputes SHA-256 and Base64 from
*owner-returned raw bytes*, never relays a caller-supplied JSON content field.
No User ID, File root, bearer, permission receipt, private errors, service
header or path other than the one requested is included. It sends `no-store`.

HTTP semantics: **401** missing/stale/revoked browser cookie or elapsed proof;
**403** foreign/inactive Project, missing exact Files bearer, verified private
owner Deny or wrong browser origin; **422** malformed/oversized/ambiguous input;
**503** no configured owner, inaccessible Platform/Valkey, untrusted private
service, unverifiable current User/Project/Access/Files authority, bad owner
reply or timed-out read. There is no permissive `404` filesystem enumeration
or fallback to a normal `AgentSession`'s action-only grant.

## Trusted owner port and post-read fences

The *only* route to Bytes is an explicitly injected
`TrustedFilesContentOwner.read(PrivateFilesReadCommand)`. Its command names the
verified current Platform actor, original signed Rauthy issuer/sub, exact
Project and AgentSession, expected durable grant revision, server-generated
operation UUID, canonical selector, bounded path/byte budget and original
private resource Bearer (`SecretStr`, never logged/public). The command's
`proof_expires_at` is the minimum browser/Platform/resource deadline and is
not itself a service-identity or Cedar proof.

The future owner implementation MUST independently authenticate the Panel BFF
service peer, reverify current Rauthy resource bearer/signature/audience,
current enabled Platform User/Project, exact live Access AgentSession and
Cedar `files.read/files/read_file/workspace_path` scope, current Files mapping
revision and the real owner-safe FD read before AND after physical IO. It must
only return bytes after both Authorization read-decision phases, unchanged
root and original read lease and owner context exit succeed. The BFF has no
privilege to manufacture any of these facts or to call a public MCP tool as a
shortcut. This source patch does not supply the private peer/root adapter,
trusted Files transport, or a client/user/provider grant.

Even a valid owner read does not finalize the browser reply. After owner
IO, the BFF now obtains a **second exact current Platform Project proof** and
requires unchanged verified Rauthy subject, Platform actor, role and exact
Project ownership, version and `use_resources` permission. Member revocation,
Project transfer/version change, User rebinding and source outage between the
two reads cannot release bytes. The original minimum proof deadline is
retained and cannot be refreshed by the second lookup. After this awaited
Platform round trip, the browser session and original private resource bearer
are fetched **last**; a logout racing that lookup cannot restore the ticket.

All Panel routes using OIDC transaction, first-factor Init and session tickets
share strict browser Cookie parsing. Duplicate headers, repeated Panel cookie
names, malformed ticket values or ambiguously quoted Panel handles deny before
identity/owner mutation; browser cookies never select a valid token by first-
or last-value wins. The normal logout remains idempotent with no cookie.

Owner replies must echo operation/actor/Project/AgentSession/grant revision,
selector and canonical path and supply bytes with a fresh short bounded
`checked_at`/`expires_at` pair (maximum five seconds). The BFF validates the
echo, length, time bounds and source identity, then REFETCHES the original
browser session **and** private Files credential after owner IO. Logout or
Valkey removal during read cannot release bytes, and a stale or replaced
bearer cannot revive a completed response. `asyncio.CancelledError` remains
propagated so the trusted owner must drain any in-flight filesystem FD work;
this BFF does not claim it can undo a previously delivered response or revoke
a previously copied access token instantaneously.

## Source evidence and release block

The focused ASGI tests drive the actual Platform cookie/current Project router
and Files BFF with a stubbed Valkey store and synthetic owner. They cover
200 four-field bounded output, no-owner503, no-cookie401, revoked/foreign
Project403, owner Deny403, owner transport503, invalid/duplicate input422,
foreign/rebound/oversized/expired owner responses503, owner-read cookie deletion
401 and short original proof elapsed during IO503. No real User, Rauthy JWT
signer, physical Files root, private peer or Cedar authority is claimed. The
actual factory has no owner and remains HTTP503 even if the independent
Rauthy browser session exists. **Frontend must not enable file CONTENT
retrieval from this source contract alone.** Only an independently accepted
private owner port and genuine Core/Execution acceptance can activate it.

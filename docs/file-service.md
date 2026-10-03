# Files service architecture

MCP Bridge uses one shared persistent working filesystem at `/workspace`.

Terminal, Files, Curl and the Management API mount the same Docker volume. A file uploaded
through Files, downloaded by Curl, created by Terminal, or uploaded through the Management API is therefore
the same file at the same path. There is no content-addressed object store, SQLite file
index, collection/reference layer, or `file_id` storage contract.

## Files MCP

Files is a path-based file manager and transport surface over `/workspace`.

The public operations cover:

- filesystem status and free space;
- directory listing and file metadata;
- bounded binary reads;
- SHA-256 calculation;
- UTF-8 text creation/replacement;
- sequential base64 chunk writes for binary files;
- direct ChatGPT/client attachment ingress to a selected path;
- directory creation;
- copy, move/rename and delete.

All paths are resolved under `/workspace`. Traversal and symlink escapes outside the
workspace root are rejected.

## Binary writes

`file_write` is the generic binary transfer primitive. The first call may use
`truncate=true` and `offset=0`; subsequent chunks must use the exact returned
`next_offset`. Sparse and overlapping writes are rejected. This replaces the previous
resumable CAS upload-session API without introducing a second storage system.

## Attachment ingress

`file_ingest` accepts a client attachment through the MCP file parameter and streams it
directly into a caller-selected workspace destination. Partial bytes are written to a
sibling temporary file and published only after configured size and optional SHA-256
validation succeed.

## Curl integration

Curl uses the same workspace. Request bodies may reference `body_workspace_path`.
Downloads and bounded stream captures write directly to workspace paths. When the caller
does not supply a destination, Curl uses ordinary `downloads/` or `captures/`
subdirectories under `/workspace`.

No hidden immutable object is created.

## Terminal integration

Terminal executes directly against the same filesystem. Its named project directories
live under `/workspace/projects/<workspace_id>`, but Files may operate anywhere under the
workspace root.

Terminal job metadata and retained process logs remain under `/home/agent/.terminal` so
normal file-manager operations cannot corrupt job state.

## Ghidra / Analysis boundary

Ghidra project storage remains isolated from `/workspace` and is never exposed to normal
Terminal or Files operations.

Analysis transfers selected inbound workspace files through Ghidra's internal chunked
artifact staging before import. Ghidra project databases remain private. Exported analysis
artifacts must likewise cross an explicit controlled transfer boundary before becoming
normal workspace files; the project store itself is not mounted into the workspace.

## Migration

The former content-addressed Files store was migrated before removal. Existing objects were
copied into `/workspace/projects/migrated-files`, checksum-verified, and accompanied by
`migration-manifest.json` containing the former identifiers and provenance metadata.

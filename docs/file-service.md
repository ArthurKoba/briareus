# Files service architecture

MCP Bridge has two file layers with different purposes:

1. the shared mutable working filesystem at `/workspace`;
2. the immutable content-addressed artifact store at `/files`.

The shared workspace is the normal agent working area. Terminal, Files and Curl see the
same persistent Docker volume. Source checkouts, downloaded files, uploaded attachments,
temporary investigation data and build outputs can therefore be manipulated by path
without copying through an intermediate file ID.

The immutable artifact store remains available for snapshots, reproducibility, deduplication
and integrations such as Ghidra where an explicit immutable source boundary is useful.

## Shared workspace

The Files MCP is the file explorer/transport surface for the same filesystem Terminal uses.

Workspace operations include:

- list and inspect paths;
- bounded binary reads;
- create UTF-8 text files and directories;
- copy, move/rename and delete;
- stream a ChatGPT/client attachment directly to a chosen workspace path;
- snapshot a workspace file into immutable artifact storage when required.

All public paths are relative to `/workspace`. The implementation resolves paths against
that root and rejects traversal or symlink resolution outside it.

Terminal uses named execution directories under `/workspace/projects/<workspace_id>`, but
the shared filesystem is not limited to those directories. Files may also organize inputs,
artifacts or scratch data elsewhere under `/workspace` when useful.

Terminal's own job metadata and retained process logs are not stored in the shared
filesystem. They live under the persistent agent home so Files operations cannot corrupt
job state accidentally.

## Direct ingress

`file_workspace_ingest` accepts a client attachment through the MCP file parameter and
streams it directly to a requested workspace path. Partial data is written to a sibling
temporary file and atomically published only after size/SHA-256 validation succeeds.

This is the preferred ingress when the file will immediately be inspected, unpacked,
patched, built or otherwise manipulated through Terminal.

The legacy `file_ingest` tool remains available when an immutable artifact is wanted
immediately.

## Web downloads

Curl and Files share the same workspace volume. `curl_download` and
`curl_stream_capture` accept an optional `workspace_path`; when supplied, their output is
placed directly into the shared workspace and no immutable artifact is created.

Without `workspace_path`, existing behavior is retained and the result is committed to
the immutable artifact store.

## Immutable artifact identity

Immutable files are addressed by their SHA-256 content identity:

```text
sha256:<64-hex-digest>
```

Names and MIME types are metadata. Re-uploading identical bytes does not create a second
stored object.

The persistent `/files` volume contains the internal object tree and SQLite metadata
index. It is not mounted into the Terminal container.

## Resumable artifact upload

The existing `file_upload_*` protocol remains the generic resumable route for creating
immutable artifacts. Upload sessions survive disconnects, validate sequential offsets,
sizes and optional SHA-256, and commit into content-addressed storage.

It is not required for normal workspace file manipulation.

## Collections and references

Archive collections and durable consumer references remain artifact-store concepts.
Collections content-address archive members, while references protect immutable objects
used by consumers from garbage collection.

## Ghidra boundary

Ghidra project storage remains separate from the shared workspace and is never mounted into
Terminal/Files.

When a workspace file must enter a Ghidra workflow, first create an explicit immutable
snapshot with `file_workspace_snapshot`, then use the existing Ghidra/Analysis import
adapter with that file ID. This preserves a reproducible source identity and prevents
ordinary shell/file operations from touching Ghidra project databases.

Ghidra exports continue to enter immutable artifact storage and can later be copied or
otherwise materialized into normal working files through an explicit adapter when needed.

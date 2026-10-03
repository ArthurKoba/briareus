# Files storage migration

The legacy content-addressed Files store has been retired.

Before removal, production migrated every live object into the shared workspace at:

```text
/workspace/projects/migrated-files/
```

The migration copied all 16 legacy objects, verified each SHA-256 checksum, and wrote
`migration-manifest.json` containing the former object identifiers and provenance
metadata. Ghidra project data was not moved because Ghidra owns separate isolated project
storage.

## Current storage

The active stack uses:

```text
management         -> /management
auth               -> /auth
terminal-workspace -> /workspace
terminal-home      -> /home/agent
```

Files, Curl, Terminal and the Management API share `terminal-workspace`. There is no
`/files` volume, Files SQLite database, immutable object index, collection/reference
registry, or resumable CAS upload session.

## Current public file contract

The Files MCP at `/files/mcp` is path-based. Paths are relative to `/workspace`.
Attachments, downloads and generated files are placed directly into that filesystem.

## Rollback note

The migration manifest preserves the previous SHA-256 identifiers for historical
traceability. Runtime code intentionally contains no compatibility path back to the old
CAS model.

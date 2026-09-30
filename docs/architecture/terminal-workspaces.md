# Terminal workspace architecture

Status: design baseline for `feat/terminal-workspaces`.

## Goal

Provide agents with a persistent, inspectable Linux workspace for local source work,
builds and interactive hardware sessions without giving arbitrary shell code host root,
Docker control or direct access to MCP provider credentials.

The first implementation targets one server and a small number of concurrent agent
sessions. It optimizes for deterministic behavior, persistence, auditability and a compact
MCP surface rather than multi-tenant cloud scheduling.

## Topology

```text
ChatGPT / MCP client
        |
        | /terminal/mcp
        v
gateway
        |
        v
terminal  -----------------> management
   |  \--------------------> Files store/API
   |
   | private execution API
   v
workspace
   |
   +-- persistent /workspace
   +-- persistent /home/agent
   +-- outbound Internet
   +-- optional explicitly-passed serial devices

workspace is NOT attached to the normal provider network.
workspace has NO Docker socket and NO sudo/root execution path.
```

The terminal runtime is an ordinary MCP Bridge module. The workspace runtime is not a
public MCP backend; it is an execution worker owned by the terminal module.

## Workspace filesystem

Initial layout:

```text
/workspace/
  projects/      # cloned/created repositories
  scratch/       # disposable but persistent working data
  artifacts/     # build/export staging when useful

/home/agent/
  .cache/
  .config/
  .local/
  .ssh/          # only if an explicit credential profile is later attached
```

Both roots are persistent named volumes. The workspace process runs as a fixed non-root
user. MCP path parameters are workspace-relative and are canonicalized before use.

Raw shell commands may navigate anywhere the workspace UID can read, so the image itself
must not contain secrets and must not mount control-plane volumes.

## MCP surface: phase 1

### Runtime / workspace

- `terminal_status`
  - image/build identity, tool versions, disk usage, active jobs/sessions, serial aliases.
- `workspace_list`
- `workspace_create`
- `workspace_info`
- `workspace_delete`
  - guarded; refuses while active jobs/sessions exist unless an explicit force policy is
    later added.
- `workspace_import_file`
  - Files `file_id` -> confined workspace path.
- `workspace_export_file`
  - confined workspace path -> immutable Files `file_id`.

A workspace is initially a directory-level project space within the single trusted
workspace container. The API preserves an explicit `workspace_id` so execution can move
to per-workspace containers/VMs later without changing callers.

### Short commands

- `terminal_exec(workspace_id, command, cwd, env, timeout_seconds)`
  - bounded non-PTY execution;
  - stdout/stderr returned separately with byte limits and truncation metadata;
  - exit code, signal, timestamps and duration are structured;
  - environment overrides reject protected names and secrets are redacted from audit.

This is for grep, git status/diff, quick scripts and small tests.

### Long-running jobs

- `job_start(..., kind="generic|build|test|server")`
- `job_status(job_id)`
- `job_read(job_id, cursor, max_bytes)`
- `job_wait(job_id, timeout_seconds)`
- `job_cancel(job_id, grace_seconds)`
- `job_list(workspace_id, state, kind)`

Output is written incrementally to durable logs. MCP calls never need to hold an SSE
request open for a long build. A disconnected ChatGPT session can later resume reading
from a cursor.

### Interactive PTY

- `terminal_open(workspace_id, cwd, shell, cols, rows)`
- `terminal_read(session_id, cursor, max_bytes, wait_seconds)`
- `terminal_write(session_id, data)`
- `terminal_resize(session_id, cols, rows)`
- `terminal_close(session_id, signal)`
- `terminal_list(workspace_id)`

This supports interactive installers/debuggers, REPLs, `git rebase -i` style workflows
when appropriate, and serial console tooling. The API is chunk/cursor based rather than
trying to keep one MCP request open indefinitely.

## Build handling

A build is a normal job with `kind=build`, not a separate execution engine. Admin can
therefore show build state without parsing every build system.

Optional build metadata:

- label;
- expected artifact paths;
- source revision at start;
- environment/profile name.

The workspace image should include Make/Buildroot prerequisites so OpenIPC builds can run
without root package installation. Project-specific Python tooling should prefer `uv`
and workspace-local virtual environments.

## Git

Raw `git` is available in the workspace for local history, branches, grep/log/blame,
patch application, rebases and worktree operations.

Provider-native network mutations remain better served by GitHub/GitLab MCP when possible.
For raw authenticated Git transport, phase 2 adds explicit credential profiles rather
than copying all Management provider tokens into the shell.

Recommended local defaults:

- no global credential embedded in the image;
- workspace-local Git identity may be configured;
- credential attachment is explicit and auditable;
- SSH host keys are verified, not silently disabled.

## Patching and repository inspection

The base image includes `git`, `patch`, `diff`, `grep`, `ripgrep`, `find`,
`sed`, `awk`, `jq` and normal archive tools. This intentionally makes common source
inspection cheaper than repeated provider API calls.

The MCP layer should not reimplement each Unix tool. The structured boundary is around
execution/session lifecycle, paths, artifacts, credentials and privilege.

## Resource and safety controls

Workspace container baseline:

- non-root UID/GID;
- no sudo;
- `cap_drop: ALL`;
- `security_opt: no-new-privileges:true`;
- no Docker/Podman socket;
- no host filesystem bind mounts;
- dedicated network, separated from provider/control-plane services;
- CPU/memory/PID limits configurable in Compose;
- bounded exec output and job log retention;
- explicit kill/cancel APIs;
- root filesystem may become read-only once tool/cache write paths are proven.

Outbound Internet remains enabled because builds and dependency resolution require it.
Network egress policy/allowlists can be added later if there is a concrete need.

## Serial/UART

The serial contract is alias-based:

```text
camera-uart -> /dev/uart0
```

The repository stores only the logical alias contract. Coolify/Compose deployment maps the
real host device into the workspace.

Planned tools:

- `serial_list`
- `serial_open(alias, baudrate, data_bits, parity, stop_bits, flow_control)`
- reuse `terminal_read/write/close` for the resulting session.

Serial transcript storage follows the same bounded durable log policy as PTYs. Flashing
tools may run as ordinary jobs when the required USB device is explicitly passed through
and accessible to the non-root workspace user.

## Privileged approval path: phase 3

Do not start with arbitrary privileged command execution.

The future flow is:

1. agent submits exact privileged action request;
2. Management stores command/action, rationale, target, cwd and a content hash;
3. Admin operator approves or rejects;
4. approval creates a one-shot short-lived authorization bound to that hash;
5. a dedicated privileged runner executes only that approved action;
6. stdout/stderr/exit status and audit identity are persisted.

The privileged runner is a separate security domain from the normal workspace. A generic
reusable root shell is explicitly out of scope.

## Admin UI

Add a Terminal section with:

- Workspaces: storage, project/revision hints, last activity, delete/export controls;
- Jobs: running/completed/failed/cancelled, kind, duration, exit status, log tail;
- Terminals: PTY/serial type, workspace, cwd/device alias, last activity, close action;
- Settings: output limits, job retention, idle/session policy, resource policy;
- later: credential attachments and privileged approval queue.

Dashboard cards should include active workspaces, running jobs, failed jobs and open
terminal/serial sessions.

## Observability

Reuse existing common observability middleware for MCP calls. Add workspace-side runtime
metrics/logs without exporting command contents:

- runtime up/started;
- exec/job/PTY counts and failures;
- active/running job gauges;
- command/job duration histograms;
- bytes read/written;
- workspace disk usage;
- session last-activity.

Execution logs/transcripts are operational data and stay in the workspace/Management
storage path, not OTLP attributes.

## External designs reviewed

Daytona demonstrates durable sandbox filesystems, process/session APIs and web terminal
management. E2B demonstrates a stronger microVM boundary at much greater infrastructure
cost. OpenHands uses dedicated runtime images and explicit workspace mounts. mcp-shell
demonstrates the useful split between typed safe tools and an opt-in unrestricted shell.

For this single-server stack, reusing those concepts is preferable to embedding an entire
external sandbox platform. The MCP contract is intentionally designed so the workspace
executor can later be replaced by containers/VMs without changing agent-facing tools.

## Implementation order

1. terminal/workspace settings and isolated Compose topology;
2. workspace execution API + persistent volumes;
3. terminal MCP: status/workspace + bounded exec;
4. job lifecycle with durable cursor-based logs;
5. PTY lifecycle;
6. Files import/export;
7. Management/Admin views and settings;
8. telemetry and architecture tests;
9. serial/UART aliases and session integration;
10. credential profiles;
11. privileged approval runner only if still required.

The first acceptance gate is phases 1-8: persistent source/build work without host
privilege. UART and privileged execution are separate gates because they change the
hardware/security boundary.

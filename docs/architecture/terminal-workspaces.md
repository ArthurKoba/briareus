# Terminal workspace architecture

Status: MVP design baseline for `feat/terminal-workspaces`.

## Goal

Give agents a persistent Linux development environment that is fast to use for source
inspection, patching, local Git workflows, builds, Python environments and interactive
hardware work.

This is not a hostile multi-tenant sandbox. The MVP uses ordinary Linux/Docker permissions
and a non-root runtime user as the practical safety boundary.

## Topology

```text
ChatGPT / MCP client
        |
        | /terminal/mcp
        v
gateway
        |
        v
terminal
   |
   +-- persistent /workspace
   +-- persistent /home/agent
   +-- normal outbound network
   +-- shared /workspace with Files and Curl
   +-- optional deployed UART/USB devices
```

One persistent terminal service is sufficient for the MVP. There is no separate workspace
executor/control-plane split.

## Workspace filesystem

Initial layout:

```text
/workspace/
  projects/
  scratch/
  artifacts/

/home/agent/
  .cache/
  .config/
  .local/
  .ssh/
```

The container runs as a fixed non-root user. Source trees, virtual environments, package
caches and build outputs survive container recreation through named volumes.

Named workspaces may simply be directories under `/workspace/projects`; we do not need
per-workspace containers initially.

## MCP surface

### Status and workspace

- `terminal_status`
- `workspace_list`
- `workspace_create`
- `workspace_info`
- `workspace_delete`

Keep these tools small and operational. Workspace deletion must refuse while jobs are
using it unless an explicit force flag is supplied.

### Quick commands

`terminal_exec(workspace_id, command, cwd, env, timeout_seconds)`

Use for grep, git status/diff, short scripts and quick tests.

Return structured:

- exit code / signal;
- stdout;
- stderr;
- timestamps/duration;
- truncation metadata.

### Jobs: universal process abstraction

All long-running and interactive work uses jobs:

- `job_start(workspace_id, command, cwd, env, interactive=false, label="")`
- `job_status(job_id)`
- `job_read(job_id, cursor=0, max_bytes=..., wait_seconds=0)`
- `job_write(job_id, data)`
- `job_resize(job_id, cols, rows)`
- `job_wait(job_id, timeout_seconds)`
- `job_cancel(job_id, grace_seconds)`
- `job_list(workspace_id, state, offset, limit)`
- `job_delete(job_id)`
- `job_cleanup(older_than_hours, dry_run, limit)`

`job_write` and `job_resize` are valid only for interactive jobs.

A build is simply a job. A shell is an interactive job. A development server is a job. A
serial console is an interactive job running a serial utility.

## Incremental log contract

This is a first-class optimization, not an afterthought.

Each job output stream is append-only and addressed by a byte cursor.

Example flow:

```text
job_start(...) -> job_id=abc
job_read(abc, cursor=0)    -> output="...", next_cursor=1842
job_read(abc, cursor=1842) -> output="only new bytes", next_cursor=2310
job_read(abc, cursor=2310) -> output="", next_cursor=2310
```

The response also reports:

- `eof` / process state;
- whether older output was truncated by retention;
- current total output size;
- optional stdout/stderr stream identity when not PTY-backed.

This lets an agent poll a long build without repeatedly consuming the full log. A caller
may explicitly request from cursor 0 when the complete retained log is needed.

Logs remain available after process exit and can be deleted individually or cleaned up in
bounded batches by age. Job listings are paginated so a long-lived terminal does not push
its complete process history into every agent/Admin request.

## Interactive jobs

Interactive jobs allocate a PTY. The agent reads output through the same cursor-based
`job_read`, writes stdin with `job_write`, and changes terminal size with `job_resize`.

There is no separate terminal-session entity. The job itself is the session.

This supports:

- interactive shells;
- REPL/debuggers;
- installers;
- text-mode tools where appropriate;
- UART/serial programs.

## Serial/UART

Serial is deliberately not a separate MCP subsystem.

The operator exposes a device to the terminal container using normal Docker/Linux device
permissions. The image contains a normal serial utility.

The agent then starts, for example, an interactive job conceptually equivalent to:

```text
picocom <device> --baud <rate>
```

After that, all interaction is ordinary `job_read` / `job_write` / `job_cancel`.

The same model also works for flashing/debug tooling that needs a passed-through USB
device: it is just another command/job once Linux permissions permit access.

## Base development image

The image should be useful without package installation during routine work.

Baseline:

- bash/sh;
- git + OpenSSH client;
- curl/wget;
- grep/ripgrep/find/sed/awk;
- patch/diff/rsync;
- jq;
- tar/zip/unzip/xz;
- make;
- gcc/g++/binutils;
- cmake/ninja/pkg-config;
- Python + uv + pip/venv;
- Buildroot/OpenIPC common prerequisites;
- picocom and pyserial.

Project-local dependencies are allowed under the normal user account.

If a system dependency is missing, the agent gets the real command error and reports the
missing package instead of attempting privilege escalation.

## Git

Local Git should be fully usable because repository inspection through a filesystem is much
cheaper than repeated provider API calls.

Typical work:

- clone/fetch where credentials permit;
- status/diff/log/blame;
- branches/worktrees;
- apply patches;
- rebase/cherry-pick when appropriate;
- build/test from the working tree.

GitHub/GitLab MCP remains available for provider-native repository/PR/MR operations. We do
not need to duplicate all of that inside Terminal.

## Files integration

Files and Terminal mount the same persistent `/workspace` volume. Normal working files
therefore require no import/export operation: a file uploaded, downloaded, moved or edited
through Files is immediately visible to Terminal by path, and files produced by Terminal
are immediately visible to Files.

There is no separate Files object store. Files and Terminal are two interfaces over the
same working filesystem.

Terminal job metadata and retained process logs live under `/home/agent/.terminal`, not
inside the shared workspace.

## Admin MVP

Add one Terminal section, not a large configuration product.

Show:

- workspaces;
- active/recent jobs;
- interactive/non-interactive;
- command/label and cwd;
- state, exit code and duration;
- last activity;
- current output tail;
- installed tool availability and free disk;
- Linux groups and persistent Git/SSH setup indicators;
- serial devices visible to the container and whether they are readable/writable;
- cancel, retained-log delete and old-job cleanup actions.

Dashboard cards may show running jobs and failed recent jobs.

Package lists, Linux permissions, device mappings and most resource settings remain in
Docker/Linux configuration, not Admin forms. A missing OS package, supplemental group,
host device mapping or mount is a deployment-level blocker: Admin should make the missing
capability visible, but granting it requires an image/Compose change and container recreate.
User-space dependencies, Git configuration and SSH keys remain agent-manageable inside the
persistent home/workspace without root.

## Safety baseline

Keep it intentionally simple:

- run as non-root;
- no sudo by default;
- do not run the container privileged by default;
- package/device permission failures are surfaced normally;
- operator changes permissions or Compose configuration when a task genuinely needs it.

Do not spend MVP time building a security system intended to resist a malicious agent that
already has authorized repository/infrastructure mutation tools.

## Observability

Reuse current OpenTelemetry integration with `mcp.scope=terminal`.

Terminal intentionally does not send command arguments, stdin or job output into the
Admin API MCP-call payload audit. Durable job metadata/output is already retained in the
terminal workspace, while OpenTelemetry records operational metrics without command bodies.

Useful metrics:

- running/completed/failed jobs;
- job duration;
- command failures;
- output bytes;
- active interactive jobs;
- workspace disk usage.

Do not export command bodies, stdin, credentials or full output as telemetry attributes.

## Implementation order

1. terminal runtime + persistent volumes + non-root image/toolchain;
2. workspace directory lifecycle;
3. `terminal_exec`;
4. jobs with durable cursor/delta logs;
5. PTY input/resize on interactive jobs;
6. shared Files/Curl workspace access;
7. compact Admin API/Admin view;
8. telemetry/tests;
9. validate UART by passing one real device and running it as an interactive job.

That is the MVP acceptance gate. Stronger isolation, credential brokers and privileged
approval workflows are deferred until actual usage proves they are necessary.

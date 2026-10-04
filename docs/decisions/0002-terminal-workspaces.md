# ADR 0002: Persistent terminal workspaces

Status: proposed

## Context

Agents need a durable Linux environment for repository inspection, grep/search, patching,
local Git work, Python virtual environments, builds, long-running commands, interactive
shells and UART/device work.

This is an operator-owned single-server environment used cooperatively with agents. The
goal is not hostile multi-tenant isolation. The useful safety boundary is simpler: normal
agent work runs as a non-root user, privileged operations fail naturally, and the operator
changes permissions/devices/packages when required.

The terminal must survive normal MCP redeploys and chat handoffs without losing source
trees, local changes, virtual environments, caches or build artifacts.

## Decision

Add one dedicated public `terminal` MCP runtime with persistent workspace/home volumes.

### Runtime model

The terminal container:

- runs as a fixed non-root user;
- has no sudo/root execution path by default;
- has normal outbound network access;
- is part of the normal Compose application;
- keeps `/workspace` and `/home/agent` on persistent volumes;
- may receive explicitly configured Linux device access (UART/USB/etc.) through deployment;
- contains a practical engineering toolchain installed at image build time.

No extra sandbox control-plane/executor split is required for the MVP. We rely on normal
Linux/Docker permissions to reject operations the runtime user cannot perform.

### Execution model

There are two public execution patterns:

- bounded synchronous exec for quick commands;
- persistent jobs for long-running or interactive processes.

A job is the universal process abstraction. Builds, tests, servers, shells, debuggers and
serial consoles are all jobs.

Jobs have stable IDs and durable output logs. Reads are cursor-based: callers pass the last
cursor they consumed and receive only newly appended output plus a next cursor. This avoids
re-sending large build logs on every poll.

Interactive jobs use the same object with PTY input/resize support. Serial/UART is not a
separate MCP entity: the agent starts an interactive job running a normal serial program
such as `picocom` against a device exposed to the container.

### Base toolchain

System packages are installed while building the image. The runtime user cannot install
system packages with sudo.

The base image should include at least:

- git and OpenSSH client;
- curl/wget;
- grep/ripgrep/find/sed/awk;
- patch/diff/rsync;
- jq;
- tar/zip/unzip/xz;
- make;
- gcc/g++/binutils;
- cmake/ninja/pkg-config;
- Python and uv/pip/venv support;
- common Buildroot/OpenIPC prerequisites;
- practical serial tools such as picocom and pyserial.

Project/language dependencies may be installed into the workspace or user home without
root. If an OS package/device permission is missing, the command fails and the operator
updates the image or host/container permissions deliberately.

### Files integration

Files and Terminal operate on the same persistent `/workspace` filesystem. Files is the
path-based file-manager/transport surface; Terminal is the process-execution surface.
No import/export copy or immutable file identifier is required between them.

### Git and credentials

Raw Git is available for local operations: clone/fetch when credentials are available,
status/diff/log/blame, branches, worktrees, rebases and patch workflows.

Provider-native GitHub/GitLab actions can continue to use their existing MCPs. The MVP
does not need a large credential-broker subsystem. If raw authenticated Git is needed,
credentials can be provided later through ordinary operator-managed environment/file/SSH
mechanisms appropriate to the deployment.

### Privileged operations

There is no custom privileged approval service in the MVP.

Normal privileged commands fail because the runtime user is non-root. The agent reports
the blocker. User-space dependencies and persistent Git/SSH setup can be changed without
root. OS packages, supplemental groups, host device mappings and mounts are deployment
changes and require an image/Compose update plus container recreation.

Admin surfaces tool availability, group membership and visible serial-device access so the
operator can distinguish an agent/workspace problem from a deployment-level capability
gap. A more structured privileged approval mechanism may be added later only if real usage
demonstrates a need.

### Admin and observability

Admin API/Admin gets a compact Terminal section showing:

- workspaces and storage usage;
- running/recent jobs;
- command/type, cwd, start/end, duration and exit status;
- output tail;
- interactive state and last activity;
- cancel/close controls.

Do not make every runtime knob configurable in Admin. Environment/image/Linux permissions
remain the primary configuration mechanism.

OpenTelemetry uses the existing `service.name=mcp-bridge` convention with
`mcp.scope=terminal`. Command contents, stdin, credentials and full terminal output are
not exported as telemetry attributes.

## Consequences

The MVP is intentionally simple and optimized for getting useful engineering work running
quickly on one trusted server.

It does not attempt to defend against a deliberately malicious agent that can already
modify infrastructure source through authorized repository MCPs. It does protect against
ordinary accidental privilege use by removing root/sudo and relying on explicit operator
changes when more access is needed.

The process/job API is designed to survive later hardening without changing agent
workflows: stronger isolation, per-workspace containers or approval gates can be added
behind the same execution contract if they become necessary.

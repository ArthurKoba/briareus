# ADR 0002: Persistent terminal workspaces

Status: proposed

## Context

Agents need a durable Linux execution environment for work that does not fit provider APIs:
repository exploration, grep/search, patching, local Git workflows, Python virtual
environments, dependency installation into user/workspace scope, builds, long-running
commands, interactive shells and embedded-device UART sessions.

The environment must remain available across ChatGPT conversations and normal MCP Bridge
redeploys, but arbitrary agent code must not receive host root access, the Docker socket,
Management credentials or the private provider network. Missing system packages should be
an explicit operator-visible limitation rather than something an agent silently installs
with sudo.

The existing MCP Bridge already has dedicated provider runtimes, persistent Files,
Management/Admin, OAuth, OpenTelemetry and a thin public gateway. The terminal capability
should follow those boundaries instead of introducing a second platform.

## Decision

Add a dedicated public `terminal` MCP runtime and a separate private `workspace`
execution runtime.

### Trust boundary

`terminal` is control-plane. It joins the normal MCP service network, uses Management for
audit/settings, and may use the canonical Files store for explicit import/export.

`workspace` is data-plane. It runs arbitrary agent commands as a fixed non-root UID/GID,
owns the persistent workspace volume, has outbound network access, and is not attached to
the normal MCP provider network. It exposes only a narrow private execution API to
`terminal` over a Unix-domain socket on a tiny shared control volume. There is no network
path from the workspace container back into the MCP provider/control-plane network.

Neither runtime receives the Docker socket. The workspace is attached only to a dedicated
outbound/egress network; the terminal control-plane is not attached to that network.
 The workspace image has no sudo path and
runtime containers use `no-new-privileges` with capabilities dropped unless a narrowly
defined future hardware feature requires otherwise.

### Persistence model

Source trees, virtual environments, downloaded dependencies, tool caches, build artifacts,
shell configuration and command transcripts live on named persistent volumes. Normal
container recreation or server reboot may terminate running processes, but it must not
erase workspace filesystem state.

Multiple PTY sessions and background jobs may coexist inside one workspace. Sessions and
jobs have stable IDs so another agent/chat can inspect or continue them later.

### Execution model

The public API separates short commands, long-running jobs and interactive terminals:

- bounded exec for quick commands with structured exit status/output;
- jobs for builds, tests, servers and other long-running processes, with start/status/read/
  wait/cancel operations and durable logs;
- PTY sessions with create/read/write/resize/close/list operations.

Raw shell execution is allowed inside the workspace because the container boundary is the
security boundary. High-level typed tools remain available for operations that need safer
semantics or integration, such as Files transfer, workspace lifecycle, Git identity,
serial sessions and privileged-action requests.

### Base toolchain

System packages are installed only while building the workspace image. The runtime user
cannot use apt/dpkg as root and has no sudo. The base image should include the common
engineering toolchain: Git/OpenSSH client, curl/wget, grep/ripgrep, findutils, patch/diff,
rsync, tar/zip/xz, jq, make, compilers/binutils, cmake/ninja/pkg-config, Python/uv/pip
support and common Buildroot/OpenIPC prerequisites.

Language/project dependencies may be installed into the workspace or user home (for
example `uv venv`, pip virtual environments and project-local package managers) without
changing the base system. If a missing OS package is required, the tool reports it and the
operator updates the image deliberately.

### Files integration

The workspace never receives raw access to the Files object store. `terminal` performs
explicit import/export operations between a Files `file_id` and a path under the
workspace root, enforcing path confinement and overwrite guards. Export returns a normal
immutable Files object.

### Credentials

Provider credentials are not copied into the workspace by default. GitHub/GitLab MCP
remains preferred for provider-native actions.

A later credential-profile capability may attach an explicitly selected credential to a
workspace through a narrow Git credential/SSH-agent broker. Secret material must remain
encrypted at rest in Management and must not be included in telemetry or normal command
results.

### Privileged operations

There is no general sudo tool in the workspace. A future privileged runner may execute an
operator-approved action only after Management records the exact request and an
administrator approves it. Approval must be one-shot, short-lived and bound to the exact
action/request hash; it must not grant a reusable root shell.

Package changes to the base image are not a privileged runtime action: they remain normal
source/image changes.

### UART / serial

Serial support is an extension of the terminal session model. Host-specific devices are
passed explicitly at deployment and exposed inside the workspace under logical aliases.
The MCP surface should create serial sessions by alias and baud/settings, then reuse the
same read/write/close transcript model used by PTYs.

No host device path is hard-coded in the repository. The runtime must remain functional
when no serial device is attached.

### Admin and observability

Management/Admin gains Terminal/Workspaces views for:

- workspace storage/state and active sessions;
- jobs/builds with command, cwd, start/end, exit status and log tail;
- PTY/serial sessions and last activity;
- Files imports/exports;
- resource limits and lifecycle settings;
- pending privileged-action requests/approvals when that feature exists.

OpenTelemetry uses the existing `service.name=mcp-bridge` convention with
`mcp.scope=terminal` and `mcp.scope=workspace`. Command contents, stdin, environment
secrets and terminal output are not exported as telemetry attributes.

## Consequences

This design is intentionally smaller than a general sandbox platform such as Daytona or
E2B while preserving the same useful separation between control plane, durable filesystem
and process/session execution.

The main security boundary is container-to-host and workspace-to-MCP-network isolation,
not isolation between directories inside one workspace. If mutually hostile tenants or
independent agent sandboxes become a requirement, the execution layer can later move to
per-workspace containers/VMs behind the same MCP contract.

Dynamic creation of arbitrary Docker containers is deliberately excluded from the first
implementation because exposing the Docker API would collapse the host security boundary.

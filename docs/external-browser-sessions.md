# External Playwright MCP: session states and recovery

This contract applies to the legacy MCP Bridge Web provider (/web/mcp),
not to Briareus Hands or the Web-managed Chromium/DevTools profile.

## Two independent sessions

- **Operator Chrome / Playwright MCP**: the upstream process may have multiple
  active approved client sessions. The Web proxy cannot enumerate or take over
  sessions created by another agent. An open Chrome grant window or live agent
  session is not equivalent to a Web-owned connection.
- **Koba Web proxy**: browser_external_connect creates or reuses its own upstream
  MCP client. Only that connection is represented by connected and
  proxy_connected. browser_external_status is read-only and never initializes
  the upstream MCP, opens tabs, resets Chrome or requests another approval.
- **Managed Chromium and devtools_***: a separate Koba Web profile. Listing
  its pages does not inspect tabs from the external operator Chrome.

## Diagnostic fields

The existing connected field remains, scoped to session_scope =
koba_web_proxy_only. other_client_sessions = not_observable explicitly
means *unknown*, not disconnected. connection_state distinguishes disabled,
proxy_disconnected, proxy_connected_unverified, tab_list_responded and
tab_check_failed.

browser_ready is null until a Web-owned tab probe finishes, true only if
the upstream browser_tabs(action=list) call returns without an MCP error,
and false after a failed tab probe. It does **not** prove granted debugger/CDP
or extension-management permissions. grant_state = unverified until an
independent provider-specific grant observation is implemented.

last_successful_tab_probe_at is the last Web-owned successful check.
On disconnect it clears; an old probe must not masquerade as live access.
The status endpoint does not independently check upstream TCP reachability.

Each explicit Connect returns ok, connection_state and, on failure,
last_error = {code, stage, message, next_action, retryable}. It never
returns upstream session IDs, extension tokens, private tab URLs,
raw exceptions or auth headers. Management must not emit
external.connected when ok is false; emit external.connect_failed.

## Failure / next action

| Code | Stage | Meaning and next action |
| --- | --- | --- |
| UPSTREAM_UNREACHABLE | mcp_initialize / tools_list / tabs_list | Verify the Playwright MCP process and configured HTTP endpoint/port. |
| UPSTREAM_TIMEOUT | any stage | Check server responsiveness or a pending Chrome approval; retain the same grant and avoid retry loops. |
| UPSTREAM_HTTP_ERROR | any stage | HTTP response code is reported without content; verify Streamable HTTP route and upstream protocol. |
| UPSTREAM_PROTOCOL_ERROR | any stage | Inspect upstream MCP logs for the indicated stage and client/protocol compatibility. |
| BROWSER_TABS_FAILED | tabs_list | Upstream rejected tab query; inspect an existing approval prompt or server logs, do not assume all sessions died. |

Connect is a deliberate potentially permission-prompting action, not a
read-only health check. Reset explicitly affects only the Web-owned proxy
session; it must not reset external Chrome or other agents' sessions.
Avoid reset merely because connected is false.

## Current limitations

MCP Streamable HTTP sessions have client-specific handles. Koba Web cannot
attach to handles of independent agents or enumerate their grants. Do not
invent an "attach succeeded" result based on HTTP 200 from an unrelated tool.

This change improves truthful states, stage-specific diagnostics, HTTP
Host handling and observable recovery. It does **not** implement cross-agent
session adoption, durable proxy sessions across redeployments or Chrome
grant introspection. These require a separately authorized, secret-safe
server-owned session registry/API.

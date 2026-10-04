# Starlette Admin parity audit

Status: parity completed and legacy Starlette Admin removed after frontend acceptance.

This audit compares the legacy `services/management/presentation/admin.py` surface with the typed management API and authenticated realtime/browser surfaces. The target is functional parity, not removal of legacy routes in this change.

| Legacy surface | Legacy operation | Replacement surface | Status |
| --- | --- | --- | --- |
| GitHub/GitLab/SigNoz/Coolify account views | list/view/create/edit/delete | `GET/POST /admin/api/accounts`, `PUT/DELETE /admin/api/accounts/{provider}/{account_id}` | covered |
| Provider account row action | test connection | `POST /admin/api/accounts/{provider}/{account_id}/verify` | covered |
| MCP Calls | list | `GET /admin/api/calls` and realtime topic `mcp.calls` | covered |
| MCP Calls | delete one | `DELETE /admin/api/calls/{call_id}` | covered |
| MCP Calls | clear all | `DELETE /admin/api/calls` | covered |
| OAuth Sessions | list/read | `GET /admin/api/oauth-sessions` | covered |
| Reverse/Analysis | overview/projects/workers | `GET /admin/api/analysis`, worker/project endpoints | covered |
| Reverse project | detail/files/open programs/coverage | `GET /admin/api/analysis/projects/{project_id:path}` and `/coverage` | covered |
| Reverse project | create/open/release/delete | `POST /admin/api/analysis/projects`, `POST .../open`, `POST .../release`, `DELETE .../{project_id:path}` | covered |
| Analysis worker | enable/disable routing | `PUT /admin/api/analysis/workers/{worker_index}` | covered |
| Analysis worker | clear queue | `POST /admin/api/analysis/workers/{worker_index}/clear-queue` | covered |
| Analysis worker | recover worker | `POST /admin/api/analysis/workers/{worker_index}/recover` | covered |
| Analysis worker | current worker/queue state | `GET /admin/api/analysis/workers` and `GET .../{worker_index}` | covered |
| Terminal | overview/workspaces/jobs | `GET /admin/api/terminal` | covered |
| Terminal job | detail/tail | `GET /admin/api/terminal/jobs/{job_id}` | covered |
| Terminal job | cancel/delete | `POST .../{job_id}/cancel`, `DELETE .../{job_id}` | covered |
| Terminal jobs | retained-job cleanup | `POST /admin/api/terminal/jobs/cleanup` | covered |
| Terminal workspace | delete | `DELETE /admin/api/terminal/workspaces/{workspace_id}` | covered |
| Files | list/stats | `GET /admin/api/files` | covered |
| Files | upload/mkdir/download/delete | `/admin/api/files/upload`, `/mkdir`, `/download`, `DELETE /admin/api/files` | covered |
| Browser | state | `GET /admin/api/browser/state` | covered |
| Browser | operator controls (tabs, navigation, input, access policy, DevTools, clean/reopen) | session-authenticated `WS /admin/api/browser/operator/ws`, relaying the existing operator protocol | covered |
| Browser | viewport/resolution | `PUT /admin/api/browser/viewport`; Web MCP capability/tool `browser_set_viewport` | covered |
| Settings | read/save | `GET/PUT /admin/api/settings` | covered |
| Settings | apply invocation retention cleanup | `POST /admin/api/settings/cleanup-logs` | covered |
| Dashboard | summary cards/state | `GET /admin/api/dashboard` plus realtime snapshots | covered |

Additional migration surfaces not present in legacy Admin:

- `WS /admin/api/realtime`: session-authenticated versioned event bus with subscribe/unsubscribe. Topics include `mcp.calls`, `system.metrics`, `system.notifications`, `browser.runtime`, and `management.events`.
- Valkey-backed realtime fanout and short-lived snapshots, with process-local fallback when Valkey is unavailable.
- `POST /admin/api/telemetry`: authenticated frontend telemetry batch ingest with redaction, bounded buffering and server-side upstream forwarding.
- Normalized JSON error envelope for `/admin/api/*`; 401/403 represent authorization failures, while 502/503 do not clear the management session.

## Parity conclusion

No Starlette Admin-only mutation/action remained at cutover. The `starlette-admin` dependency, legacy templates/static/plugin code, browser ticket endpoint, and legacy `/admin/browser/ws` surface were removed after frontend acceptance. The backend `/admin` path intentionally has no HTML UI and returns 404; the standalone frontend is deployed separately.

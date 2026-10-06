import { adminApiUrl, runtimeConfig } from "@/shared/config/runtime"
import { AdminApiError } from "@/shared/api/error"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { notifications } from "@/shared/notifications/bus"
import { i18n } from "@/shared/i18n"
import type { SettingsUpdatePayload } from "@/shared/settings/payload"

export interface RequestOptions { notifyErrors?: boolean }
export interface SessionState { authenticated: boolean; username: string | null }
export interface NavigationItem { id: string; label: string; enabled: boolean }
export interface AdminBootstrap { product: string; environment: string; navigation: NavigationItem[] }

export interface DashboardSnapshotMeta {
  status?: string
  updated_at?: string | null
  attempted_at?: string | null
  age_seconds?: number | null
  stale?: boolean
  error_type?: string
  error_message?: string
}
export interface DashboardState {
  accounts: { total: number; enabled: number; by_provider: Record<string, number> }
  calls: { total: number; errors: number; error_rate: number; average_duration_ms: number }
  oauth: { tracked: number; active: number }
  workspace: Record<string, unknown>
  workspace_meta: DashboardSnapshotMeta
  analysis: { projects: number; active_sessions: number; workers: number; running_workers: number }
  analysis_meta: DashboardSnapshotMeta
}

export interface AccountRecord {
  id: string; alias: string; provider: "github" | "gitlab" | "signoz" | "coolify"; auth_type: string
  base_url: string; external_id: string | null; verify_tls: boolean; ca_cert_pem: string | null
  enabled: boolean; created_at: string; updated_at: string
}
export interface AccountPayload {
  alias: string; provider: AccountRecord["provider"]; auth_type: string; base_url?: string; external_id?: string
  verify_tls?: boolean; ca_cert_pem?: string; enabled?: boolean; credential?: string
}
export interface AccountCandidatePayload extends AccountPayload { account_id?: string; draft_revision: string }
export interface AccountCandidateResult { ok: true; provider: AccountRecord["provider"]; draft_revision: string }

export interface InvocationRecord {
  id: string; request_id: string; module: string; tool: string; account_id: string; provider: string
  status: "success" | "error"; duration_ms: number; error_type: string; arguments_json: string
  result_json: string; error_message: string; occurred_at: string
}
export interface InvocationQuery {
  limit?: number
  offset?: number
  cursor?: string
  module?: string
  tool?: string
  provider?: string
  account_id?: string
  status?: "success" | "error"
  search?: string
}
export interface InvocationPage {
  events: InvocationRecord[]
  count: number
  total: number
  limit: number
  offset: number
  has_more: boolean
  next_cursor: string
}

export type AccessLevel = "read_only" | "full_access"
export type AccountScope = "none" | "all" | "selected"
export type EnforcementMode = "unrestricted" | "session_enforced"
export interface AccessUser { id: string; username: string; enabled: boolean }
export interface AccessSessionRecord {
  id: string; uid: string; user_id: string; oauth_client_id: string; oauth_session_id: string
  surface_id: number; access_level: AccessLevel; account_scope: AccountScope; account_ids: string[]
  status: "active" | "revoked" | "expired"; label: string; expires_at: number
}
export interface AccessRequestRecord {
  id: string; session_id: string; kind: "full_access" | "extension"; status: string
  requested_access_level: string; requested_account_scope: AccountScope
  requested_account_ids: string[]; requested_expires_at: number
}
export interface AccessControlRecord { surface: string; surface_id: number; mode: EnforcementMode }
export interface AccessSessionUpdate {
  access_level?: AccessLevel; account_scope?: AccountScope; account_ids?: string[]
  expires_at?: number; label?: string
}

export interface OAuthRecord {
  id: string; client_id: string; client_name: string; resource: string; login: string; subject: string
  scopes: string[]; status: string; last_event: string; access_jti: string; refresh_jti: string
  previous_refresh_jti: string; access_expires_at: string | null; refresh_expires_at: string | null
  last_used_at: string | null; last_refresh_at: string | null; revoked_at: string | null
  error_type: string; error_message: string; created_at: string; updated_at: string
}

export interface FilesState {
  listing: { path: string; entries: Array<Record<string, unknown>>; count: number; total: number; offset: number; limit: number; truncated: boolean }
  current_path: string; parent_path: string; stats: Record<string, unknown>; stats_meta: Record<string, unknown>
}

export interface TerminalState { status: Record<string, unknown>; workspaces: Array<Record<string, unknown>>; jobs: Array<Record<string, unknown>> }
export interface TerminalJobState { job: Record<string, unknown>; tail: Record<string, unknown> }
export interface AnalysisState { overview: Record<string, unknown>; meta: Record<string, unknown> }
export interface AnalysisProjectState { session: Record<string, unknown>; files: Record<string, unknown>; programs: unknown[]; folder: string }

export interface BrowserState {
  running?: boolean
  color_scheme?: "system" | "light" | "dark"
  capabilities?: Record<string, boolean>
  viewport?: { width?: number; height?: number }
}
export interface BrowserRemoteDebug {
  page_id: string
  target_id: string
  frontend_url: string
  websocket_url: string
  expires_in_seconds: number
}

export interface BrowserRuntimeSettings {
  external_enabled: boolean
  external_mcp_url: string
  call_timeout_seconds: number
  auto_disconnect_enabled: boolean
  idle_timeout_seconds: number
  profile_dir_name: string
  extension_token_configured: boolean
}

export interface BrowserExternalStatus {
  configured?: boolean
  enabled?: boolean
  connected?: boolean
  browser_ready?: boolean
  provider?: string
  namespace?: string
  endpoint_origin?: string
  profile_dir_name?: string
  extension_token_configured?: boolean
  session_connect_count?: number
  last_activity_at?: string
  call_timeout_seconds?: number
  auto_disconnect_enabled?: boolean
  idle_timeout_seconds?: number
  tool_count?: number
}

export interface VcsPolicyState {
  local_first_guidance: boolean
  local_git_transport_enabled: boolean
  remote_source_mutations_enabled: boolean
}

export interface SettingsState {
  revision: string
  admin: { logging_enabled: boolean; logging_capture_payloads: boolean; logging_retention_days: number; logging_max_records: number; maintenance_interval_minutes: number }
  terminal: { max_exec_timeout_seconds: number; max_job_runtime_seconds: number }
  mcp: { call_timeout_seconds: number }
  browser: BrowserRuntimeSettings
  github: VcsPolicyState
  gitlab: VcsPolicyState
  analysis: { idle_timeout_seconds?: number; auto_release_enabled?: boolean; source?: string }
  analysis_error: string
}

const previewBootstrap: AdminBootstrap = {
  product: "MCP Bridge", environment: "frontend-preview",
  navigation: [
    { id: "overview", label: "Overview", enabled: true }, { id: "accounts", label: "Accounts", enabled: true },
    { id: "calls", label: "MCP Calls", enabled: true }, { id: "files", label: "Files", enabled: true },
    { id: "terminal", label: "Terminal", enabled: true }, { id: "browser", label: "Browser", enabled: true },
    { id: "analysis", label: "Analysis", enabled: true }, { id: "access", label: "Access", enabled: true }, { id: "oauth", label: "OAuth Sessions", enabled: true },
    { id: "settings", label: "Settings", enabled: true },
  ],
}

async function request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const method = init.method ?? "GET"
  const started = performance.now()
  let response: Response
  try {
    response = await fetch(adminApiUrl(path), { credentials: "include", ...init, headers })
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw new AdminApiError("Request cancelled", "aborted", null, "", "", { cause: caught })
    }
    frontendTelemetry.error("api.network_error", caught, { path, method, duration_ms: performance.now() - started })
    const message = caught instanceof Error ? caught.message : String(caught)
    const error = new AdminApiError(message, "network", null, "", "", { cause: caught })
    if (options.notifyErrors !== false) notifications.error(
      String(i18n.global.t("notifications.apiError")),
      `${method} ${new URL(adminApiUrl(path)).pathname} — ${message}`,
      `api:network:${method}:${new URL(adminApiUrl(path)).pathname}`,
    )
    throw error
  }

  frontendTelemetry.api(adminApiUrl(path), method, response.status, performance.now() - started)
  if (!response.ok) {
    let detail = `Admin API request failed: ${response.status}`
    let code = ""
    try {
      const body = await response.json() as { detail?: unknown; error?: { message?: unknown; code?: unknown } }
      const nested = body.detail && typeof body.detail === "object" ? body.detail as Record<string, unknown> : null
      const message = body.error?.message ?? nested?.message ?? body.detail
      if (typeof message === "string" && message) detail = message
      else if (message !== undefined) detail = JSON.stringify(message)
      const errorCode = body.error?.code ?? nested?.code
      if (typeof errorCode === "string") code = errorCode
    } catch { /* non-JSON upstream error */ }
    const requestId = response.headers.get("x-request-id") ?? response.headers.get("x-correlation-id") ?? ""
    const error = new AdminApiError(detail, "http", response.status, code, requestId)
    if (response.status === 401) window.dispatchEvent(new CustomEvent("admin:auth-expired"))
    if (options.notifyErrors !== false) notifications.error(
      `${response.status} · ${String(i18n.global.t("notifications.apiError"))}`,
      `${method} ${new URL(adminApiUrl(path)).pathname} — ${detail}${requestId ? ` · ${requestId}` : ""}`,
      `api:${response.status}:${method}:${new URL(adminApiUrl(path)).pathname}`,
    )
    throw error
  }
  const contentType = response.headers.get("content-type") || ""
  return (contentType.includes("application/json") ? await response.json() : await response.text()) as T
}

function jsonBody(value: unknown): BodyInit { return JSON.stringify(value) }

export const adminApi = {
  session: (): Promise<SessionState> => runtimeConfig.preview ? Promise.resolve({ authenticated: true, username: "preview" }) : request("/session"),
  login: (username: string, password: string): Promise<SessionState> => runtimeConfig.preview ? Promise.resolve({ authenticated: true, username: username || "preview" }) : request("/login", { method: "POST", body: jsonBody({ username, password }) }),
  logout: (): Promise<SessionState> => runtimeConfig.preview ? Promise.resolve({ authenticated: false, username: null }) : request("/logout", { method: "POST", body: "{}" }),
  bootstrap: (): Promise<AdminBootstrap> => runtimeConfig.preview ? Promise.resolve(previewBootstrap) : request("/bootstrap"),
  dashboard: (options: RequestOptions = {}): Promise<DashboardState> => request("/dashboard", {}, options),
  accounts: (options: RequestOptions = {}): Promise<{ accounts: AccountRecord[]; count: number }> => request("/accounts", {}, options),
  createAccount: (payload: AccountPayload): Promise<AccountRecord> => request("/accounts", { method: "POST", body: jsonBody(payload) }),
  updateAccount: (record: AccountRecord, payload: AccountPayload): Promise<AccountRecord> => request(`/accounts/${record.provider}/${record.id}`, { method: "PUT", body: jsonBody({ ...payload, expected_updated_at: record.updated_at }) }),
  deleteAccount: (record: AccountRecord): Promise<unknown> => request(`/accounts/${record.provider}/${record.id}`, { method: "DELETE" }),
  verifyAccount: (record: AccountRecord): Promise<Record<string, unknown>> => request(`/accounts/${record.provider}/${record.id}/verify`, { method: "POST", body: "{}" }, { notifyErrors: false }),
  verifyAccountCandidate: (payload: AccountCandidatePayload): Promise<AccountCandidateResult> => request("/accounts/verify-candidate", { method: "POST", body: jsonBody(payload) }, { notifyErrors: false }),
  calls: (query: number | InvocationQuery = 100, options: RequestOptions = {}): Promise<InvocationPage> => {
    const normalized: InvocationQuery = typeof query === "number" ? { limit: query } : query
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(normalized)) {
      if (value !== undefined && value !== "") params.set(key, String(value))
    }
    return request(`/calls?${params.toString()}`, {}, options)
  },
  clearCalls: (): Promise<{ deleted: number }> => request("/calls", { method: "DELETE" }),
  deleteCall: (id: string): Promise<unknown> => request(`/calls/${id}`, { method: "DELETE" }),
  callsStreamUrl: adminApiUrl("/calls/stream"),
  accessSessions: (): Promise<{ user: AccessUser; sessions: AccessSessionRecord[] }> => request("/access/sessions"),
  accessRequests: (): Promise<{ user: AccessUser; requests: AccessRequestRecord[] }> => request("/access/requests"),
  accessControls: (): Promise<{ user: AccessUser; controls: AccessControlRecord[] }> => request("/access/controls"),
  resolveAccessRequest: (id: string, payload: { approve: boolean; account_scope?: AccountScope; account_ids?: string[]; expires_at?: number }): Promise<Record<string, unknown>> => request(`/access/requests/${encodeURIComponent(id)}/resolve`, { method: "POST", body: jsonBody(payload) }),
  revokeAccessSession: (id: string): Promise<unknown> => request(`/access/sessions/${encodeURIComponent(id)}/revoke`, { method: "POST", body: "{}" }),
  updateAccessSession: (id: string, payload: AccessSessionUpdate): Promise<AccessSessionRecord> => request(`/access/sessions/${encodeURIComponent(id)}`, { method: "PATCH", body: jsonBody(payload) }),
  updateAccessControls: (items: Array<{ surface_id: number; mode: EnforcementMode }>): Promise<{ user: AccessUser; controls: AccessControlRecord[] }> => request("/access/controls", { method: "PUT", body: jsonBody({ items }) }),
  oauthSessions: (limit = 500): Promise<{ sessions: OAuthRecord[]; count: number }> => request(`/oauth-sessions?limit=${limit}`),
  files: (path = "", offset = 0, limit = 200): Promise<FilesState> => request(`/files?path=${encodeURIComponent(path)}&offset=${offset}&limit=${limit}`),
  uploadFile: (path: string, file: File, overwrite = false): Promise<Record<string, unknown>> => { const body = new FormData(); body.set("path", path); body.set("overwrite", String(overwrite)); body.set("file", file); return request("/files/upload", { method: "POST", body }) },
  mkdir: (path: string, name: string): Promise<Record<string, unknown>> => { const body = new FormData(); body.set("path", path); body.set("name", name); return request("/files/mkdir", { method: "POST", body }) },
  deleteFile: (path: string, recursive = false): Promise<Record<string, unknown>> => request(`/files?path=${encodeURIComponent(path)}&recursive=${recursive}`, { method: "DELETE" }),
  fileDownloadUrl: (path: string): string => adminApiUrl(`/files/download?path=${encodeURIComponent(path)}`),
  terminal: (): Promise<TerminalState> => request("/terminal"),
  terminalJob: (id: string): Promise<TerminalJobState> => request(`/terminal/jobs/${encodeURIComponent(id)}`),
  cancelTerminalJob: (id: string): Promise<Record<string, unknown>> => request(`/terminal/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" }),
  deleteTerminalJob: (id: string): Promise<Record<string, unknown>> => request(`/terminal/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  cleanupTerminalJobs: (hours = 168): Promise<Record<string, unknown>> => request(`/terminal/jobs/cleanup?older_than_hours=${hours}`, { method: "POST", body: "{}" }),
  deleteWorkspace: (id: string): Promise<Record<string, unknown>> => request(`/terminal/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" }),
  analysis: (): Promise<AnalysisState> => request("/analysis"),
  analysisProject: (id: string, folder = "/"): Promise<AnalysisProjectState> => request(`/analysis/projects/${encodeURIComponent(id)}?folder=${encodeURIComponent(folder)}`),
  createAnalysisProject: (name: string, parentDir = ""): Promise<Record<string, unknown>> => request("/analysis/projects", { method: "POST", body: jsonBody({ name, parent_dir: parentDir }) }),
  openAnalysisProject: (id: string): Promise<Record<string, unknown>> => request(`/analysis/projects/${encodeURIComponent(id)}/open`, { method: "POST", body: "{}" }),
  releaseAnalysisProject: (id: string): Promise<Record<string, unknown>> => request(`/analysis/projects/${encodeURIComponent(id)}/release`, { method: "POST", body: "{}" }),
  deleteAnalysisProject: (id: string): Promise<Record<string, unknown>> => request(`/analysis/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  setAnalysisWorker: (index: number, enabled: boolean): Promise<Record<string, unknown>> => request(`/analysis/workers/${index}`, { method: "PUT", body: jsonBody({ enabled }) }),
  clearAnalysisWorkerQueue: (index: number): Promise<Record<string, unknown>> => request(`/analysis/workers/${index}/clear-queue`, { method: "POST", body: "{}" }),
  recoverAnalysisWorker: (index: number): Promise<Record<string, unknown>> => request(`/analysis/workers/${index}/recover`, { method: "POST", body: "{}" }),
  analysisCoverage: (id: string, program: string, full = false): Promise<Record<string, unknown>> => request(`/analysis/projects/${encodeURIComponent(id)}/coverage?program=${encodeURIComponent(program)}&full=${full}`),
  browserState: (): Promise<BrowserState> => request("/browser/state"),
  setBrowserTheme: (colorScheme: "system" | "light" | "dark"): Promise<BrowserState> => request("/browser/theme", { method: "PUT", body: jsonBody({ color_scheme: colorScheme }) }),
  browserRemoteDebug: (pageId: string): Promise<BrowserRemoteDebug> => request("/browser/remote-debug", { method: "POST", body: jsonBody({ page_id: pageId }) }),
  setBrowserViewport: (pageId: string, width: number, height: number): Promise<Record<string, unknown>> => request("/browser/viewport", { method: "PUT", body: jsonBody({ page_id: pageId, width, height }) }),
  browserExternalStatus: (): Promise<BrowserExternalStatus> => request("/browser/external/status"),
  browserExternalConnect: (): Promise<BrowserExternalStatus> => request("/browser/external/connect", { method: "POST", body: "{}" }),
  browserExternalDisconnect: (): Promise<BrowserExternalStatus> => request("/browser/external/disconnect", { method: "POST", body: "{}" }),
  browserExternalReset: (): Promise<BrowserExternalStatus> => request("/browser/external/reset", { method: "POST", body: "{}" }),
  settings: (options: RequestOptions = {}): Promise<SettingsState> => request("/settings", {}, options),
  updateSettings: (payload: SettingsUpdatePayload): Promise<SettingsState> => request("/settings", { method: "PUT", body: jsonBody(payload) }),
  cleanupLogs: (): Promise<{ removed: number }> => request("/settings/cleanup-logs", { method: "POST", body: "{}" }),
}

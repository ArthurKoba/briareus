import { runtimeConfig } from "@/shared/config/runtime"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { notifications } from "@/shared/notifications/bus"
import { i18n } from "@/shared/i18n"

export interface SessionState { authenticated: boolean; username: string | null }
export interface NavigationItem { id: string; label: string; enabled: boolean }
export interface ManagementBootstrap { product: string; environment: string; legacy_admin_path: string; navigation: NavigationItem[] }

export interface DashboardState {
  accounts: { total: number; enabled: number; by_provider: Record<string, number> }
  calls: { total: number; errors: number; error_rate: number; average_duration_ms: number }
  oauth: { tracked: number; active: number }
  workspace: Record<string, unknown>
  workspace_meta: Record<string, unknown>
  analysis: { projects: number; active_sessions: number; workers: number; running_workers: number }
  analysis_meta: Record<string, unknown>
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

export interface InvocationRecord {
  id: string; request_id: string; module: string; tool: string; account_id: string; provider: string
  status: "success" | "error"; duration_ms: number; error_type: string; arguments_json: string
  result_json: string; error_message: string; occurred_at: string
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

export interface SettingsState {
  management: { logging_enabled: boolean; logging_capture_payloads: boolean; logging_retention_days: number; logging_max_records: number; maintenance_interval_minutes: number }
  terminal: { max_exec_timeout_seconds: number; max_job_runtime_seconds: number }
  mcp: { call_timeout_seconds: number }
  analysis: { idle_timeout_seconds?: number; auto_release_enabled?: boolean; source?: string }
  analysis_error: string
}

const previewBootstrap: ManagementBootstrap = {
  product: "MCP Bridge", environment: "frontend-preview", legacy_admin_path: "#",
  navigation: [
    { id: "overview", label: "Overview", enabled: true }, { id: "accounts", label: "Accounts", enabled: true },
    { id: "calls", label: "MCP Calls", enabled: true }, { id: "files", label: "Files", enabled: true },
    { id: "terminal", label: "Terminal", enabled: true }, { id: "browser", label: "Browser", enabled: true },
    { id: "analysis", label: "Analysis", enabled: true }, { id: "oauth", label: "OAuth Sessions", enabled: true },
    { id: "settings", label: "Settings", enabled: true },
  ],
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const method=init.method??"GET"
  const started=performance.now()
  try {
    const response = await fetch(path, { credentials: "same-origin", ...init, headers })
    frontendTelemetry.api(path,method,response.status,performance.now()-started)
    if (!response.ok) {
      let detail = `Management API request failed: ${response.status}`
      try { const body = await response.json() as { detail?: string }; if (body.detail) detail = body.detail } catch { /* no json */ }
      notifications.error(`${response.status} · ${String(i18n.global.t("notifications.apiError"))}`, `${method} ${new URL(path, location.origin).pathname} — ${detail}`, `api:${response.status}:${method}:${new URL(path, location.origin).pathname}`)
      throw new Error(detail)
    }
    const contentType = response.headers.get("content-type") || ""
    return (contentType.includes("application/json") ? await response.json() : await response.text()) as T
  } catch (caught) {
    if (!(caught instanceof Error && caught.message.startsWith("Management API request failed"))) {
      frontendTelemetry.error("api.network_error",caught,{path,method,duration_ms:performance.now()-started})
      notifications.error(String(i18n.global.t("notifications.apiError")), `${method} ${new URL(path, location.origin).pathname} — ${caught instanceof Error?caught.message:String(caught)}`, `api:network:${method}:${new URL(path, location.origin).pathname}`)
    }
    throw caught
  }
}

function jsonBody(value: unknown): BodyInit { return JSON.stringify(value) }

export const managementApi = {
  session: (): Promise<SessionState> => runtimeConfig.preview ? Promise.resolve({ authenticated: true, username: "preview" }) : request("/api/session"),
  login: (username: string, password: string): Promise<SessionState> => runtimeConfig.preview ? Promise.resolve({ authenticated: true, username: username || "preview" }) : request("/api/login", { method: "POST", body: jsonBody({ username, password }) }),
  logout: (): Promise<SessionState> => runtimeConfig.preview ? Promise.resolve({ authenticated: false, username: null }) : request("/api/logout", { method: "POST", body: "{}" }),
  bootstrap: (): Promise<ManagementBootstrap> => runtimeConfig.preview ? Promise.resolve(previewBootstrap) : request("/api/bootstrap"),
  dashboard: (): Promise<DashboardState> => request("/api/dashboard"),
  accounts: (): Promise<{ accounts: AccountRecord[]; count: number }> => request("/api/accounts"),
  createAccount: (payload: AccountPayload): Promise<AccountRecord> => request("/api/accounts", { method: "POST", body: jsonBody(payload) }),
  updateAccount: (record: AccountRecord, payload: AccountPayload): Promise<AccountRecord> => request(`/api/accounts/${record.provider}/${record.id}`, { method: "PUT", body: jsonBody(payload) }),
  deleteAccount: (record: AccountRecord): Promise<unknown> => request(`/api/accounts/${record.provider}/${record.id}`, { method: "DELETE" }),
  verifyAccount: (record: AccountRecord): Promise<Record<string, unknown>> => request(`/api/accounts/${record.provider}/${record.id}/verify`, { method: "POST", body: "{}" }),
  calls: (limit = 250): Promise<{ events: InvocationRecord[]; count: number }> => request(`/api/calls?limit=${limit}`),
  clearCalls: (): Promise<{ deleted: number }> => request("/api/calls", { method: "DELETE" }),
  deleteCall: (id: string): Promise<unknown> => request(`/api/calls/${id}`, { method: "DELETE" }),
  callsStreamUrl: "/api/calls/stream",
  oauthSessions: (limit = 500): Promise<{ sessions: OAuthRecord[]; count: number }> => request(`/api/oauth-sessions?limit=${limit}`),
  files: (path = "", offset = 0, limit = 200): Promise<FilesState> => request(`/api/files?path=${encodeURIComponent(path)}&offset=${offset}&limit=${limit}`),
  uploadFile: (path: string, file: File, overwrite = false): Promise<Record<string, unknown>> => { const body = new FormData(); body.set("path", path); body.set("overwrite", String(overwrite)); body.set("file", file); return request("/api/files/upload", { method: "POST", body }) },
  mkdir: (path: string, name: string): Promise<Record<string, unknown>> => { const body = new FormData(); body.set("path", path); body.set("name", name); return request("/api/files/mkdir", { method: "POST", body }) },
  deleteFile: (path: string, recursive = false): Promise<Record<string, unknown>> => request(`/api/files?path=${encodeURIComponent(path)}&recursive=${recursive}`, { method: "DELETE" }),
  fileDownloadUrl: (path: string): string => `/api/files/download?path=${encodeURIComponent(path)}`,
  terminal: (): Promise<TerminalState> => request("/api/terminal"),
  terminalJob: (id: string): Promise<TerminalJobState> => request(`/api/terminal/jobs/${encodeURIComponent(id)}`),
  cancelTerminalJob: (id: string): Promise<Record<string, unknown>> => request(`/api/terminal/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" }),
  deleteTerminalJob: (id: string): Promise<Record<string, unknown>> => request(`/api/terminal/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  cleanupTerminalJobs: (hours = 168): Promise<Record<string, unknown>> => request(`/api/terminal/jobs/cleanup?older_than_hours=${hours}`, { method: "POST", body: "{}" }),
  deleteWorkspace: (id: string): Promise<Record<string, unknown>> => request(`/api/terminal/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" }),
  analysis: (): Promise<AnalysisState> => request("/api/analysis"),
  analysisProject: (id: string, folder = "/"): Promise<AnalysisProjectState> => request(`/api/analysis/projects/${encodeURIComponent(id)}?folder=${encodeURIComponent(folder)}`),
  createAnalysisProject: (name: string, parentDir = ""): Promise<Record<string, unknown>> => request("/api/analysis/projects", { method: "POST", body: jsonBody({ name, parent_dir: parentDir }) }),
  openAnalysisProject: (id: string): Promise<Record<string, unknown>> => request(`/api/analysis/projects/${encodeURIComponent(id)}/open`, { method: "POST", body: "{}" }),
  releaseAnalysisProject: (id: string): Promise<Record<string, unknown>> => request(`/api/analysis/projects/${encodeURIComponent(id)}/release`, { method: "POST", body: "{}" }),
  deleteAnalysisProject: (id: string): Promise<Record<string, unknown>> => request(`/api/analysis/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  setAnalysisWorker: (index: number, enabled: boolean): Promise<Record<string, unknown>> => request(`/api/analysis/workers/${index}`, { method: "PUT", body: jsonBody({ enabled }) }),
  analysisCoverage: (id: string, program: string, full = false): Promise<Record<string, unknown>> => request(`/api/analysis/projects/${encodeURIComponent(id)}/coverage?program=${encodeURIComponent(program)}&full=${full}`),
  browserTicket: (): Promise<{ ticket: string }> => request("/api/browser/ticket"),
  settings: (): Promise<SettingsState> => request("/api/settings"),
  updateSettings: (payload: object): Promise<SettingsState> => request("/api/settings", { method: "PUT", body: jsonBody(payload) }),
  cleanupLogs: (): Promise<{ removed: number }> => request("/api/settings/cleanup-logs", { method: "POST", body: "{}" }),
}

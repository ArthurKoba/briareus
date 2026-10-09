/** Legacy Admin v1 cookie transport; deliberately refuses scoped Project usage. */
import { adminApiUrl } from "@/shared/config/runtime"
import { AdminApiError } from "@/shared/api/error"
import { frontendTelemetry } from "@/shared/telemetry/client"
import { notifications } from "@/shared/notifications/bus"
import { i18n } from "@/shared/i18n"

export interface RequestOptions { notifyErrors?: boolean }

// Dynamic REST paths may contain opaque IDs, filesystem paths or OAuth data.
// Preserve status+method+request ID for legacy operator diagnosis, never the
// raw path in toast dedupe keys, telemetry or browser error strings.
const safeLegacyPath = "[legacy-admin-api]"

const requests = new Set<AbortController>()
/** Legacy transport knows only a small authorization gate, not Project domain objects. */
interface LegacyBoundaryState {
  legacy: boolean
  legacyLogout: boolean
  unauthenticated: boolean
  revision: number
}
const signedOut = (): LegacyBoundaryState => ({legacy:false,legacyLogout:false,unauthenticated:false,revision:-1})
let boundary: () => LegacyBoundaryState = signedOut

/** App composition root supplies verified legacy-scope state, never a cookie guess. */
export function bindLegacyRequestBoundary(read: () => LegacyBoundaryState): () => void {
  invalidateLegacyRequests()
  boundary = read
  return () => { boundary = signedOut; invalidateLegacyRequests() }
}
/** Abort old global requests when the app transitions to another User/Team/Project. */
export function invalidateLegacyRequests(): void {
  for (const controller of requests) controller.abort()
  requests.clear()
}

export async function request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  const context = boundary()
  const revision = context.revision
  // Even legacy authentication/bootstrap routes cannot read global state
  // while a verified Team/Project/operator scope is selected.
  const method = (init.method ?? "GET").toUpperCase()
  const initialSignIn = context.unauthenticated && ["/session", "/login"].includes(path)
  const operatorSignOut = context.legacyLogout && path === "/logout" && method === "POST"
  if (!context.legacy && !initialSignIn && !operatorSignOut) {
    throw new AdminApiError("Project-scoped API contract is not connected", "aborted")
  }
  const ensureCurrentContext = () => {
    const next = boundary()
    if (revision !== next.revision ||
        (context.legacy && !next.legacy) ||
        (context.legacyLogout && !next.legacyLogout) ||
        (context.unauthenticated && !next.unauthenticated)) {
      // Preview and one-use hash changes can revoke the old UI access
      // WITHOUT a new ProjectContext revision: discard late global responses.
      throw new AdminApiError("Request invalidated by a context change", "aborted")
    }
  }
  const controller = new AbortController()
  requests.add(controller)
  try {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const started = performance.now()
  let response: Response
  try {
    const signal = init.signal ? AbortSignal.any([controller.signal, init.signal]) : controller.signal
    response = await fetch(adminApiUrl(path), { credentials: "include", ...init, headers, signal })
  } catch (caught) {
    ensureCurrentContext()
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw new AdminApiError("Request cancelled", "aborted", null, "", "", { cause: caught })
    }
    // Raw network exceptions may include internal URLs, headers or credentials.
    // Record only a stable event label and sanitized HTTP path, never error text.
    frontendTelemetry.event("api.network_error", { path:safeLegacyPath, method, duration_ms: performance.now() - started }, {level:"error"})
    const error = new AdminApiError("Network request failed", "network")
    if (options.notifyErrors !== false) notifications.error(
      String(i18n.global.t("notifications.apiError")),
      `${method} ${safeLegacyPath} — ${String(i18n.global.t("notifications.technicalError"))}`,
      `api:network:${method}:${safeLegacyPath}`,
    )
    throw error
  }

  ensureCurrentContext()
  frontendTelemetry.api(adminApiUrl(path), method, response.status, performance.now() - started)
  if (!response.ok) {
    let code = ""
    try {
      const body = await response.json() as { detail?: unknown; error?: { code?: unknown } }
      const nested = body.detail && typeof body.detail === "object" ? body.detail as Record<string, unknown> : null
      const errorCode = body.error?.code ?? nested?.code
      if (typeof errorCode === "string" && /^[a-z0-9_.-]{1,96}$/i.test(errorCode)) code = errorCode
    } catch { /* discard non-JSON or malformed upstream error text */ }
    ensureCurrentContext()
    const rawRequestId = response.headers.get("x-request-id") ?? response.headers.get("x-correlation-id") ?? ""
    const requestId = /^[a-zA-Z0-9_-]{1,128}$/.test(rawRequestId) ? rawRequestId : ""
    const safeDetail = `Admin API request failed: ${response.status}${code ? ` (${code})` : ""}`
    const error = new AdminApiError(safeDetail, "http", response.status, code, requestId)
    // Wrong credentials during an initial login are NOT an existing session
    // revocation; triggering auth-expired there would strand the login form.
    if (response.status === 401 && !["/login", "/session"].includes(path) && boundary().legacy) {
      window.dispatchEvent(new CustomEvent("admin:auth-expired"))
    }
    if (options.notifyErrors !== false) notifications.error(
      `${response.status} · ${String(i18n.global.t("notifications.apiError"))}`,
      `${method} ${safeLegacyPath} — ${String(i18n.global.t("notifications.technicalError"))}${requestId ? ` · ${requestId}` : ""}`,
      `api:${response.status}:${method}:${safeLegacyPath}`,
    )
    throw error
  }
  const contentType = response.headers.get("content-type") || ""
  const body = contentType.includes("application/json") ? await response.json() : await response.text()
  ensureCurrentContext()
  return body as T
  } finally {
    requests.delete(controller)
  }
}

export function jsonBody(value: unknown): BodyInit { return JSON.stringify(value) }

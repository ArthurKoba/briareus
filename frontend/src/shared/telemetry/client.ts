import { reactive, readonly } from "vue"

import { runtimeConfig } from "@/shared/config/runtime"
import { uiPreferences } from "@/shared/lib/preferences"

export type TelemetryLevel = "debug" | "info" | "warn" | "error"
export type TelemetryDeliveryStatus = "disabled" | "idle" | "sending" | "delivered" | "retrying" | "error"

export interface FrontendTelemetryEvent {
  id: string
  name: string
  level: TelemetryLevel
  occurredAt: string
  durationMs?: number
  route: string
  attributes: Record<string, string | number | boolean | null>
}

const buffer = reactive<FrontendTelemetryEvent[]>([])
const pending: FrontendTelemetryEvent[] = []
const delivery = reactive({
  status: (runtimeConfig.telemetry.enabled ? "idle" : "disabled") as TelemetryDeliveryStatus,
  pending: 0,
  lastSuccessAt: "",
  lastError: "",
  retryAt: "",
})
const MAX_BUFFER = 500
const MAX_BATCH = 40
const MAX_PENDING = MAX_BATCH * 5
const FLUSH_INTERVAL_MS = 5000
const MAX_BACKOFF_MS = 60000
const SENSITIVE_KEY = /(password|passwd|credential|token|cookie|authorization|secret|payload|body|private[_-]?key)/i
const SECRET_ASSIGNMENT = /(password|passwd|credential|token|cookie|authorization|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+/gi
const BEARER = /\bBearer\s+[A-Za-z0-9._~+\-/]+=*/gi
const JWT = /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g
const PROVIDER_TOKEN = /\b(?:ghp_|github_pat_|glpat-|sk-)[A-Za-z0-9_-]{12,}\b/g
let failures = 0
let nextAttemptAt = 0
let flushing = false

function redactText(value: string): string {
  if (/-----BEGIN [^-]*PRIVATE KEY-----/i.test(value)) return "[redacted private key]"
  return value
    .replace(BEARER, "Bearer [redacted]")
    .replace(JWT, "[redacted jwt]")
    .replace(PROVIDER_TOKEN, "[redacted token]")
    .replace(SECRET_ASSIGNMENT, (_match, key: string) => `${key}=[redacted]`)
    .slice(0, 1200)
}

function safeAttributes(input: Record<string, unknown> = {}): Record<string, string | number | boolean | null> {
  const output: Record<string, string | number | boolean | null> = {}
  for (const [key, value] of Object.entries(input)) {
    if (SENSITIVE_KEY.test(key)) continue
    if (value === null || typeof value === "number" || typeof value === "boolean") output[key] = value
    else if (typeof value === "string") output[key] = redactText(value)
  }
  return output
}

function safeRoute(): string {
  if (/^#[A-Za-z0-9._\-/]+$/.test(location.hash)) return location.hash
  return location.pathname
}

function safeApiPath(path: string): string {
  try {
    return new URL(path, location.origin).pathname
  } catch {
    return "[invalid-path]"
  }
}

function telemetryEndpoint(): string | null {
  try {
    const endpoint = new URL(runtimeConfig.telemetry.endpoint, location.origin)
    if (endpoint.origin !== location.origin) return null
    return `${endpoint.pathname}${endpoint.search}`
  } catch {
    return null
  }
}

function sampled(): boolean {
  const sampleRate = Math.max(0, Math.min(1, runtimeConfig.telemetry.sampleRate))
  return Math.random() <= sampleRate
}

function syncDeliveryState(): void {
  delivery.pending = pending.length
  if (!runtimeConfig.telemetry.enabled || !telemetryEndpoint()) delivery.status = "disabled"
}

function queue(item: FrontendTelemetryEvent): void {
  if (!uiPreferences.telemetryEnabled.value || !runtimeConfig.telemetry.enabled || !sampled() || !telemetryEndpoint()) return
  pending.push(item)
  if (pending.length > MAX_PENDING) pending.splice(0, pending.length - MAX_PENDING)
  syncDeliveryState()
  if (pending.length >= MAX_BATCH) void flush()
}

function retryDelay(response?: Response): number {
  const retryAfter = response?.headers.get("retry-after")
  if (retryAfter) {
    const seconds = Number(retryAfter)
    if (Number.isFinite(seconds) && seconds >= 0) return Math.min(MAX_BACKOFF_MS, seconds * 1000)
  }
  return Math.min(MAX_BACKOFF_MS, 1000 * 2 ** Math.min(failures, 6))
}

function markFailure(message: string, response?: Response): void {
  failures += 1
  const delay = retryDelay(response)
  nextAttemptAt = Date.now() + delay
  delivery.status = "retrying"
  delivery.lastError = redactText(message)
  delivery.retryAt = new Date(nextAttemptAt).toISOString()
}

async function flush(): Promise<void> {
  const endpoint = telemetryEndpoint()
  syncDeliveryState()
  if (!runtimeConfig.telemetry.enabled || !endpoint || !pending.length || flushing) return
  if (Date.now() < nextAttemptAt) return

  const events = pending.splice(0, MAX_BATCH)
  flushing = true
  delivery.status = "sending"
  delivery.pending = pending.length
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
      keepalive: true,
    })
    if (!response.ok) {
      pending.unshift(...events)
      if (response.status === 401 || response.status === 403) {
        delivery.status = "error"
        delivery.lastError = `HTTP ${response.status}`
        window.dispatchEvent(new CustomEvent("management:auth-expired"))
      } else {
        markFailure(`HTTP ${response.status}`, response)
      }
      return
    }
    failures = 0
    nextAttemptAt = 0
    delivery.status = "delivered"
    delivery.lastSuccessAt = new Date().toISOString()
    delivery.lastError = ""
    delivery.retryAt = ""
  } catch (caught) {
    pending.unshift(...events)
    markFailure(caught instanceof Error ? caught.message : String(caught))
  } finally {
    if (pending.length > MAX_PENDING) pending.splice(0, pending.length - MAX_PENDING)
    delivery.pending = pending.length
    flushing = false
  }
}

function flushBeacon(): void {
  const endpoint = telemetryEndpoint()
  if (!runtimeConfig.telemetry.enabled || !endpoint || !pending.length || !navigator.sendBeacon) return
  const events = pending.splice(0, MAX_BATCH)
  const accepted = navigator.sendBeacon(
    endpoint,
    new Blob([JSON.stringify({ events })], { type: "application/json" }),
  )
  if (!accepted) pending.unshift(...events)
  delivery.pending = pending.length
}

function event(
  name: string,
  attributes: Record<string, unknown> = {},
  options: { level?: TelemetryLevel; durationMs?: number } = {},
): FrontendTelemetryEvent {
  const item: FrontendTelemetryEvent = {
    id: crypto.randomUUID(),
    name,
    level: options.level ?? "info",
    occurredAt: new Date().toISOString(),
    durationMs: options.durationMs,
    route: safeRoute(),
    attributes: safeAttributes(attributes),
  }
  if (uiPreferences.telemetryEnabled.value) {
    buffer.unshift(item)
    if (buffer.length > MAX_BUFFER) buffer.splice(MAX_BUFFER)
    queue(item)
  }
  return item
}

function error(name: string, caught: unknown, attributes: Record<string, unknown> = {}): FrontendTelemetryEvent {
  const err = caught instanceof Error ? caught : null
  return event(name, {
    ...attributes,
    error_type: err?.name ?? "unknown",
    error_message: redactText(err?.message ?? String(caught)),
    error_stack: err?.stack ? redactText(err.stack) : null,
  }, { level: "error" })
}

window.setInterval(() => void flush(), FLUSH_INTERVAL_MS)
window.addEventListener("pagehide", flushBeacon)
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushBeacon()
})

export const frontendTelemetry = {
  events: readonly(buffer),
  delivery: readonly(delivery),
  event,
  error,
  flush,
  get pendingCount() { return pending.length },
  get deliveryConfigured() { return runtimeConfig.telemetry.enabled && Boolean(telemetryEndpoint()) },
  api(path: string, method: string, status: number, durationMs: number) {
    return event("api.request", { path: safeApiPath(path), method, status }, {
      level: status >= 500 ? "error" : status >= 400 ? "warn" : "info",
      durationMs,
    })
  },
  navigation(id: string) { return event("navigation", { page: id }) },
  websocket(state: string, topic?: string, transport?: string) {
    return event("realtime.websocket", { state, topic: topic ?? null, transport: transport ?? null })
  },
}

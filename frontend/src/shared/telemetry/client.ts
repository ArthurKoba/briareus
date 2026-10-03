import { reactive, readonly } from "vue"

import { runtimeConfig } from "@/shared/config/runtime"

export type TelemetryLevel = "debug" | "info" | "warn" | "error"

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
const MAX_BUFFER = 500
const SENSITIVE_KEY = /(password|passwd|credential|token|cookie|authorization|secret|payload|body|private[_-]?key)/i
const SECRET_ASSIGNMENT = /(password|passwd|credential|token|cookie|authorization|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+/gi
const BEARER = /\bBearer\s+[A-Za-z0-9._~+\-/]+=*/gi
const JWT = /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g
const PROVIDER_TOKEN = /\b(?:ghp_|github_pat_|glpat-|sk-)[A-Za-z0-9_-]{12,}\b/g

function redactText(value: string): string {
  if (/-----BEGIN [^-]*PRIVATE KEY-----/i.test(value)) return "[redacted private key]"
  return value
    .replace(BEARER, "Bearer [redacted]")
    .replace(JWT, "[redacted jwt]")
    .replace(PROVIDER_TOKEN, "[redacted token]")
    .replace(SECRET_ASSIGNMENT, (_match, key: string) => `${key}=[redacted]`)
    .slice(0, 500)
}

function safeAttributes(
  input: Record<string, unknown> = {},
): Record<string, string | number | boolean | null> {
  const output: Record<string, string | number | boolean | null> = {}
  for (const [key, value] of Object.entries(input)) {
    if (SENSITIVE_KEY.test(key)) continue
    if (value === null || typeof value === "number" || typeof value === "boolean") {
      output[key] = value
    } else if (typeof value === "string") {
      output[key] = redactText(value)
    }
  }
  return output
}

function safeRoute(): string {
  if (/^#[A-Za-z0-9._-]+$/.test(location.hash)) return location.hash
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
  buffer.unshift(item)
  if (buffer.length > MAX_BUFFER) buffer.splice(MAX_BUFFER)

  const endpoint = telemetryEndpoint()
  const sampleRate = Math.max(0, Math.min(1, runtimeConfig.telemetry.sampleRate))
  if (runtimeConfig.telemetry.enabled && endpoint && Math.random() <= sampleRate) {
    void fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item),
      keepalive: true,
    }).catch(() => {})
  }
  return item
}

function error(
  name: string,
  caught: unknown,
  attributes: Record<string, unknown> = {},
): FrontendTelemetryEvent {
  return event(
    name,
    {
      ...attributes,
      error_type: caught instanceof Error ? caught.name : "unknown",
      error_message: redactText(caught instanceof Error ? caught.message : String(caught)),
    },
    { level: "error" },
  )
}

export const frontendTelemetry = {
  events: readonly(buffer),
  event,
  error,
  api(path: string, method: string, status: number, durationMs: number) {
    return event(
      "api.request",
      { path: safeApiPath(path), method, status },
      { level: status >= 500 ? "error" : status >= 400 ? "warn" : "info", durationMs },
    )
  },
  navigation(id: string) {
    return event("navigation", { page: id })
  },
  websocket(state: string, topic?: string) {
    return event("realtime.websocket", { state, topic: topic ?? null })
  },
}

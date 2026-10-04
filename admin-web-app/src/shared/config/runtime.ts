export type EventTransportMode = "mock" | "websocket"

export interface AdminUiRuntimeConfig {
  preview: boolean
  apiBaseUrl: string
  telemetry: { enabled: boolean; endpoint: string; sampleRate: number }
  events: { mode: EventTransportMode }
}

declare global {
  interface Window {
    __KOBA_ADMIN_UI_CONFIG__?: Partial<AdminUiRuntimeConfig> & {
      telemetry?: Partial<AdminUiRuntimeConfig["telemetry"]>
      events?: Partial<AdminUiRuntimeConfig["events"]>
    }
  }
}

function inferredApiBaseUrl(): string {
  const url = new URL(location.origin)
  if (url.hostname.startsWith("admin.")) url.hostname = `api.${url.hostname.slice("admin.".length)}`
  url.pathname = "/v1"
  return url.toString().replace(/\/$/, "")
}

const raw = window.__KOBA_ADMIN_UI_CONFIG__
const configuredApiBase = raw?.apiBaseUrl?.trim().replace(/\/+$/, "")
const apiBaseUrl = configuredApiBase || inferredApiBaseUrl()

export const runtimeConfig: AdminUiRuntimeConfig = {
  preview: raw?.preview ?? false,
  apiBaseUrl,
  telemetry: {
    enabled: raw?.telemetry?.enabled ?? true,
    endpoint: `${apiBaseUrl}/telemetry`,
    sampleRate: raw?.telemetry?.sampleRate ?? 1,
  },
  events: { mode: raw?.events?.mode ?? "websocket" },
}

export function adminApiUrl(path = ""): string {
  const suffix = path ? (path.startsWith("/") ? path : `/${path}`) : ""
  return `${runtimeConfig.apiBaseUrl}${suffix}`
}

export function adminApiWebSocketUrl(path = ""): string {
  const url = new URL(adminApiUrl(path))
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  return url.toString()
}

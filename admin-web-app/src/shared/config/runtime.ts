export type EventTransportMode = "mock" | "websocket" | "hybrid"
export interface AdminUiRuntimeConfig {
  preview: boolean
  telemetry: { enabled: boolean; endpoint: string; sampleRate: number }
  events: { mode: EventTransportMode; url: string }
}
declare global { interface Window { __MCP_ADMIN_UI_CONFIG__?: Partial<AdminUiRuntimeConfig> & { telemetry?: Partial<AdminUiRuntimeConfig["telemetry"]>; events?: Partial<AdminUiRuntimeConfig["events"]> } } }
const raw=window.__MCP_ADMIN_UI_CONFIG__
export const runtimeConfig: AdminUiRuntimeConfig={
  preview: raw?.preview ?? true,
  telemetry:{ enabled:raw?.telemetry?.enabled ?? true, endpoint:raw?.telemetry?.endpoint ?? "/api/telemetry", sampleRate:raw?.telemetry?.sampleRate ?? 1 },
  events:{ mode:raw?.events?.mode ?? "hybrid", url:raw?.events?.url ?? "/api/realtime" },
}

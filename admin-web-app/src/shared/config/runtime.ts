export type EventTransportMode = "mock" | "websocket" | "hybrid"
export interface ManagementUiRuntimeConfig {
  preview: boolean
  telemetry: { enabled: boolean; endpoint: string; sampleRate: number }
  events: { mode: EventTransportMode; url: string }
}
declare global { interface Window { __MCP_MANAGEMENT_UI_CONFIG__?: Partial<ManagementUiRuntimeConfig> & { telemetry?: Partial<ManagementUiRuntimeConfig["telemetry"]>; events?: Partial<ManagementUiRuntimeConfig["events"]> } } }
const raw=window.__MCP_MANAGEMENT_UI_CONFIG__
export const runtimeConfig: ManagementUiRuntimeConfig={
  preview: raw?.preview ?? true,
  telemetry:{ enabled:raw?.telemetry?.enabled ?? true, endpoint:raw?.telemetry?.endpoint ?? "/api/telemetry", sampleRate:raw?.telemetry?.sampleRate ?? 1 },
  events:{ mode:raw?.events?.mode ?? "hybrid", url:raw?.events?.url ?? "/api/realtime" },
}

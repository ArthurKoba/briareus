/**
 * Retired legacy Admin configuration shim. Briareus never imports this file.
 * There is no automatic admin.* -> api.* hostname rewrite, no legacy cookie
 * proxy, no preview principal and no browser-configurable transport/telemetry.
 * The old modules remain outside the Briareus application import graph and
 * these fail-closed exports prevent an accidental runtime fallback.
 */
export type EventTransportMode = "websocket"
export interface AdminUiRuntimeConfig {
  preview: false
  apiBaseUrl: ""
  telemetry: {enabled:false;endpoint:"";sampleRate:0}
  events: {mode:EventTransportMode}
}
export const runtimeConfig={
  preview:false,apiBaseUrl:"",
  telemetry:{enabled:false,endpoint:"",sampleRate:0},
  events:{mode:"websocket"},
} as const satisfies AdminUiRuntimeConfig
export function adminApiUrl(_path=""):never {
  throw new Error("Legacy Admin routing is not part of Briareus")
}
export function adminApiWebSocketUrl(_path=""):never {
  throw new Error("Legacy Admin realtime is not part of Briareus")
}

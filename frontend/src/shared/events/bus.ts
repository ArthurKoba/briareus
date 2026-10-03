import { reactive, readonly } from "vue"

import { runtimeConfig } from "@/shared/config/runtime"
import { tabWorkspace, topicRealtimeEnabled } from "@/shared/lib/tab-workspace"
import { frontendTelemetry } from "@/shared/telemetry/client"

export type EventTopic = "mcp.calls" | "dashboard.metrics" | "browser.activity" | "system.notifications" | "runtime.state" | string
export interface BusEvent<T = unknown> { topic: EventTopic; type: string; occurredAt: string; data: T }
type Handler = (event: BusEvent) => void

const handlers = new Map<EventTopic, Set<Handler>>()
const state = reactive({
  status: "idle" as "idle" | "connecting" | "connected" | "reconnecting" | "mock" | "disabled",
  transport: "none" as "none" | "websocket" | "sse" | "mock",
  subscriptions: 0,
  lastEventAt: "",
  lastRemoteEventAt: "",
  enabled: tabWorkspace.realtimeEnabled,
})
let socket: WebSocket | null = null
let reconnectTimer = 0
let reconnectAttempt = 0
const sse = new Map<string, EventSource>()

function dispatch(event: BusEvent, remote = false): void {
  state.lastEventAt = event.occurredAt
  if (remote) state.lastRemoteEventAt = event.occurredAt
  for (const handler of handlers.get(event.topic) ?? []) handler(event)
}

function normalizeRemoteEvent(input: unknown): BusEvent | null {
  if (!input || typeof input !== "object") return null
  const payload = input as Record<string, unknown>
  if (["subscribed", "unsubscribed", "pong", "hello"].includes(String(payload.type))) return null
  if (typeof payload.topic !== "string" || typeof payload.type !== "string") return null
  const occurredAt = typeof payload.occurredAt === "string"
    ? payload.occurredAt
    : typeof payload.occurred_at === "string"
      ? payload.occurred_at
      : new Date().toISOString()
  return { topic: payload.topic, type: payload.type, occurredAt, data: payload.data }
}

function enabledFor(topic: EventTopic): boolean {
  return state.enabled && topicRealtimeEnabled(topic)
}

function closeSse(topic: EventTopic): void {
  const source = sse.get(topic)
  if (!source) return
  source.close()
  sse.delete(topic)
  if (!sse.size && state.transport === "sse") state.transport = "none"
}

function closeAllSse(): void {
  for (const topic of [...sse.keys()]) closeSse(topic)
}

function wireSseCompat(topic: EventTopic): void {
  if (!enabledFor(topic) || topic !== "mcp.calls" || sse.has(topic) || state.transport === "websocket") return
  const source = new EventSource("/api/calls/stream")
  source.onopen = () => {
    if (state.transport === "websocket") return closeSse(topic)
    state.status = "connected"
    state.transport = "sse"
    frontendTelemetry.websocket("connected", topic, "sse")
  }
  source.onerror = () => {
    if (!state.enabled || state.transport === "websocket") return
    state.status = "reconnecting"
    frontendTelemetry.websocket("reconnecting", topic, "sse")
  }
  source.onmessage = (event) => {
    try {
      dispatch({ topic, type: "item", occurredAt: new Date().toISOString(), data: JSON.parse(event.data) }, true)
    } catch (caught) {
      frontendTelemetry.error("realtime.sse_decode", caught, { topic })
    }
  }
  sse.set(topic, source)
}

function closeTransports(): void {
  clearTimeout(reconnectTimer)
  closeAllSse()
  socket?.close()
  socket = null
  reconnectAttempt = 0
  state.transport = "none"
}

function sendSubscription(type: "subscribe" | "unsubscribe", topic: EventTopic): void {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type, topic }))
}

function activateCompatFallback(): void {
  if (runtimeConfig.events.mode !== "hybrid" || state.transport === "websocket") return
  for (const topic of handlers.keys()) wireSseCompat(topic)
  if (!sse.size && state.enabled) state.status = handlers.size ? "reconnecting" : "idle"
}

function scheduleReconnect(): void {
  if (!state.enabled || !handlers.size || runtimeConfig.events.mode === "mock") return
  clearTimeout(reconnectTimer)
  const delay = Math.min(30000, 1000 * 2 ** Math.min(reconnectAttempt++, 5))
  reconnectTimer = window.setTimeout(connectWebSocket, delay)
}

function connectWebSocket(): void {
  if (!state.enabled || runtimeConfig.events.mode === "mock" || socket) return
  state.status = reconnectAttempt ? "reconnecting" : "connecting"
  const scheme = location.protocol === "https:" ? "wss:" : "ws:"
  const url = runtimeConfig.events.url.startsWith("/")
    ? `${scheme}//${location.host}${runtimeConfig.events.url}`
    : runtimeConfig.events.url
  socket = new WebSocket(url)
  socket.onopen = () => {
    closeAllSse()
    state.status = "connected"
    state.transport = "websocket"
    reconnectAttempt = 0
    frontendTelemetry.websocket("connected", undefined, "websocket")
    for (const topic of handlers.keys()) if (enabledFor(topic)) sendSubscription("subscribe", topic)
  }
  socket.onmessage = (event) => {
    try {
      const normalized = normalizeRemoteEvent(JSON.parse(event.data))
      if (normalized) dispatch(normalized, true)
    } catch (caught) {
      frontendTelemetry.error("realtime.decode", caught)
    }
  }
  socket.onclose = (event) => {
    socket = null
    if (state.transport === "websocket") state.transport = "none"
    if (event.code === 4401 || event.code === 4403) {
      state.status = "disabled"
      frontendTelemetry.websocket("authorization_expired", undefined, "websocket")
      window.dispatchEvent(new CustomEvent("management:auth-expired"))
      return
    }
    if (!state.enabled || !handlers.size) {
      state.status = state.enabled ? "idle" : "disabled"
      return
    }
    state.status = "reconnecting"
    frontendTelemetry.websocket("reconnecting", undefined, "websocket")
    activateCompatFallback()
    scheduleReconnect()
  }
  socket.onerror = () => frontendTelemetry.websocket("error", undefined, "websocket")
}

function connectTopics(): void {
  if (!state.enabled) {
    state.status = "disabled"
    return
  }
  if (runtimeConfig.events.mode === "mock") {
    state.status = "mock"
    state.transport = "mock"
    return
  }
  connectWebSocket()
}

function subscribe(topic: EventTopic, handler: Handler): () => void {
  let set = handlers.get(topic)
  const firstForTopic = !set?.size
  if (!set) {
    set = new Set()
    handlers.set(topic, set)
  }
  set.add(handler)
  state.subscriptions = [...handlers.values()].reduce((count, listeners) => count + listeners.size, 0)

  if (firstForTopic && enabledFor(topic) && socket?.readyState === WebSocket.OPEN) sendSubscription("subscribe", topic)
  connectTopics()

  return () => {
    const current = handlers.get(topic)
    current?.delete(handler)
    if (!current?.size) {
      handlers.delete(topic)
      closeSse(topic)
      sendSubscription("unsubscribe", topic)
    }
    state.subscriptions = [...handlers.values()].reduce((count, listeners) => count + listeners.size, 0)
    if (!handlers.size) {
      closeTransports()
      state.status = state.enabled ? (runtimeConfig.events.mode === "mock" ? "mock" : "idle") : "disabled"
      state.transport = runtimeConfig.events.mode === "mock" && state.enabled ? "mock" : "none"
    }
  }
}

function setEnabled(enabled: boolean): void {
  if (state.enabled === enabled) return
  state.enabled = enabled
  tabWorkspace.realtimeEnabled = enabled
  if (!enabled) {
    closeTransports()
    state.status = "disabled"
    frontendTelemetry.websocket("disabled")
    return
  }
  frontendTelemetry.websocket("enabled")
  connectTopics()
}

function publishMock(topic: EventTopic, type: string, data: unknown): void {
  dispatch({ topic, type, occurredAt: new Date().toISOString(), data })
}

export const eventBus = { state: readonly(state), subscribe, publishMock, setEnabled }

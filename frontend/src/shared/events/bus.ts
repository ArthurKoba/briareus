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
  subscriptions: 0,
  lastEventAt: "",
  enabled: tabWorkspace.realtimeEnabled,
})
let socket: WebSocket | null = null
let reconnectTimer = 0
let reconnectAttempt = 0
const sse = new Map<string, EventSource>()

function dispatch(event: BusEvent): void {
  state.lastEventAt = event.occurredAt
  for (const handler of handlers.get(event.topic) ?? []) handler(event)
}

function enabledFor(topic: EventTopic): boolean {
  return state.enabled && topicRealtimeEnabled(topic)
}

function wireSseCompat(topic: EventTopic): void {
  if (!enabledFor(topic) || topic !== "mcp.calls" || sse.has(topic)) return
  const source = new EventSource("/api/calls/stream")
  source.onopen = () => {
    state.status = "connected"
    frontendTelemetry.websocket("connected", topic)
  }
  source.onerror = () => {
    if (!state.enabled) return
    state.status = "reconnecting"
    frontendTelemetry.websocket("reconnecting", topic)
  }
  source.onmessage = (event) => dispatch({
    topic,
    type: "item",
    occurredAt: new Date().toISOString(),
    data: JSON.parse(event.data),
  })
  sse.set(topic, source)
}

function closeSse(topic: EventTopic): void {
  const source = sse.get(topic)
  if (!source) return
  source.close()
  sse.delete(topic)
}

function closeTransports(): void {
  clearTimeout(reconnectTimer)
  for (const topic of sse.keys()) closeSse(topic)
  socket?.close()
  socket = null
  reconnectAttempt = 0
}

function connectWebSocket(): void {
  if (!state.enabled || runtimeConfig.events.mode === "mock" || socket) return
  state.status = "connecting"
  const scheme = location.protocol === "https:" ? "wss:" : "ws:"
  const url = runtimeConfig.events.url.startsWith("/")
    ? `${scheme}//${location.host}${runtimeConfig.events.url}`
    : runtimeConfig.events.url
  socket = new WebSocket(url)
  socket.onopen = () => {
    state.status = "connected"
    reconnectAttempt = 0
    frontendTelemetry.websocket("connected")
    for (const topic of handlers.keys()) {
      if (enabledFor(topic)) socket?.send(JSON.stringify({ type: "subscribe", topic }))
    }
  }
  socket.onmessage = (event) => {
    try {
      dispatch(JSON.parse(event.data) as BusEvent)
    } catch (caught) {
      frontendTelemetry.error("realtime.decode", caught)
    }
  }
  socket.onclose = () => {
    socket = null
    if (!state.enabled || !handlers.size) {
      state.status = state.enabled ? "idle" : "disabled"
      return
    }
    state.status = "reconnecting"
    frontendTelemetry.websocket("reconnecting")
    const delay = Math.min(30000, 1000 * 2 ** Math.min(reconnectAttempt++, 5))
    reconnectTimer = window.setTimeout(connectWebSocket, delay)
  }
  socket.onerror = () => frontendTelemetry.websocket("error")
}

function connectTopics(): void {
  if (!state.enabled) {
    state.status = "disabled"
    return
  }
  if (runtimeConfig.events.mode === "mock") {
    state.status = "mock"
    return
  }
  if (runtimeConfig.events.mode === "websocket") {
    connectWebSocket()
    return
  }
  for (const topic of handlers.keys()) wireSseCompat(topic)
  if (![...handlers.keys()].some((topic) => topic === "mcp.calls")) state.status = "idle"
}

function subscribe(topic: EventTopic, handler: Handler): () => void {
  let set = handlers.get(topic)
  if (!set) {
    set = new Set()
    handlers.set(topic, set)
  }
  set.add(handler)
  state.subscriptions = [...handlers.values()].reduce((count, listeners) => count + listeners.size, 0)
  connectTopics()

  return () => {
    const current = handlers.get(topic)
    current?.delete(handler)
    if (!current?.size) {
      handlers.delete(topic)
      closeSse(topic)
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "unsubscribe", topic }))
    }
    state.subscriptions = [...handlers.values()].reduce((count, listeners) => count + listeners.size, 0)
    if (!handlers.size) {
      closeTransports()
      state.status = state.enabled ? (runtimeConfig.events.mode === "mock" ? "mock" : "idle") : "disabled"
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

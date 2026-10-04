import { reactive, readonly } from "vue"

import { adminApiWebSocketUrl, runtimeConfig } from "@/shared/config/runtime"
import { pageActivity } from "@/shared/lib/page-activity"
import { frontendTelemetry } from "@/shared/telemetry/client"

export type EventTopic = "mcp.calls" | "system.metrics" | "system.notifications" | "browser.runtime" | "admin.events" | string
export interface BusEvent<T = unknown> { topic: EventTopic; type: string; occurredAt: string; data: T }
type Handler = (event: BusEvent) => void
type ConnectionStatus = "idle" | "connecting" | "connected" | "reconnecting" | "mock" | "disabled" | "error"

const handlers = new Map<EventTopic, Set<Handler>>()
const state = reactive({
  status: "idle" as ConnectionStatus,
  transport: "none" as "none" | "websocket" | "mock",
  subscriptions: 0,
  lastEventAt: "",
  lastRemoteEventAt: "",
  enabled: true,
  sessionActive: false,
  active: pageActivity.isActive(),
  retryAttempt: 0,
})
let socket: WebSocket | null = null
let socketGeneration = 0
let reconnectTimer = 0
let reconnectAttempt = 0

function dispatch(event: BusEvent, remote = false): void {
  state.lastEventAt = event.occurredAt
  if (remote) state.lastRemoteEventAt = event.occurredAt
  for (const handler of handlers.get(event.topic) ?? []) handler(event)
}

function normalizeRemoteEvent(input: unknown): BusEvent | null {
  if (!input || typeof input !== "object") return null
  const payload = input as Record<string, unknown>
  if (["subscribed", "unsubscribed", "pong", "hello", "ready"].includes(String(payload.type))) return null
  if (typeof payload.topic !== "string" || typeof payload.type !== "string") return null
  const occurredAt = typeof payload.occurredAt === "string"
    ? payload.occurredAt
    : typeof payload.occurred_at === "string"
      ? payload.occurred_at
      : new Date().toISOString()
  return { topic: payload.topic, type: payload.type, occurredAt, data: payload.data }
}

function canConnect(): boolean {
  return state.enabled && state.sessionActive && handlers.size > 0
}

function closeTransports(resetAttempt = true): void {
  clearTimeout(reconnectTimer)
  reconnectTimer = 0
  const current = socket
  socket = null
  socketGeneration += 1
  current?.close()
  if (resetAttempt) reconnectAttempt = 0
  state.retryAttempt = reconnectAttempt
  state.transport = "none"
}

function sendSubscription(type: "subscribe" | "unsubscribe", topic: EventTopic): void {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type, topic }))
}

function scheduleReconnect(): void {
  if (!canConnect() || !state.active || runtimeConfig.events.mode === "mock") return
  clearTimeout(reconnectTimer)
  const delay = Math.min(30000, 1000 * 2 ** Math.min(reconnectAttempt++, 5))
  state.retryAttempt = reconnectAttempt
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = 0
    connectWebSocket()
  }, delay)
}

function connectWebSocket(): void {
  if (!canConnect() || !state.active || runtimeConfig.events.mode === "mock" || socket) return
  state.status = reconnectAttempt ? "reconnecting" : "connecting"
  const url = adminApiWebSocketUrl("/realtime")
  const generation = ++socketGeneration
  const current = new WebSocket(url)
  socket = current
  const isCurrent = () => socket === current && generation === socketGeneration

  current.onopen = () => {
    if (!isCurrent()) return
    if (!canConnect() || !state.active) return closeTransports()
    state.status = "connected"
    state.transport = "websocket"
    reconnectAttempt = 0
    state.retryAttempt = 0
    frontendTelemetry.websocket("connected", undefined, "websocket")
    for (const topic of handlers.keys()) sendSubscription("subscribe", topic)
  }
  current.onmessage = (event) => {
    if (!isCurrent()) return
    try {
      const normalized = normalizeRemoteEvent(JSON.parse(event.data))
      if (normalized) dispatch(normalized, true)
    } catch (caught) {
      frontendTelemetry.error("realtime.decode", caught)
    }
  }
  current.onclose = (event) => {
    if (!isCurrent()) return
    socket = null
    if (state.transport === "websocket") state.transport = "none"
    if (event.code === 4401) {
      state.sessionActive = false
      state.status = "disabled"
      frontendTelemetry.websocket("authorization_expired", undefined, "websocket")
      window.dispatchEvent(new CustomEvent("admin:auth-expired"))
      return
    }
    if (event.code === 4403) {
      state.status = "error"
      frontendTelemetry.websocket("forbidden", undefined, "websocket")
      return
    }
    if (!canConnect()) {
      state.status = state.enabled ? "idle" : "disabled"
      return
    }
    state.status = "reconnecting"
    frontendTelemetry.websocket("reconnecting", undefined, "websocket")
    scheduleReconnect()
  }
  current.onerror = () => {
    if (isCurrent()) frontendTelemetry.websocket("error", undefined, "websocket")
  }
}

function connectTopics(): void {
  if (!state.enabled) {
    state.status = "disabled"
    return
  }
  if (!state.sessionActive || !handlers.size) {
    state.status = "idle"
    return
  }
  if (runtimeConfig.events.mode === "mock") {
    state.status = "mock"
    state.transport = "mock"
    return
  }
  if (!state.active) {
    state.status = "reconnecting"
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

  if (firstForTopic && canConnect() && socket?.readyState === WebSocket.OPEN) sendSubscription("subscribe", topic)
  connectTopics()

  return () => {
    const current = handlers.get(topic)
    current?.delete(handler)
    if (!current?.size) {
      handlers.delete(topic)
      sendSubscription("unsubscribe", topic)
    }
    state.subscriptions = [...handlers.values()].reduce((count, listeners) => count + listeners.size, 0)
    if (!handlers.size) {
      closeTransports()
      state.status = state.enabled ? "idle" : "disabled"
    }
  }
}

function setEnabled(enabled: boolean): void {
  if (state.enabled === enabled) return
  state.enabled = enabled
  if (!enabled) {
    closeTransports()
    state.status = "disabled"
    frontendTelemetry.websocket("disabled")
    return
  }
  frontendTelemetry.websocket("enabled")
  connectTopics()
}

function setSessionActive(active: boolean): void {
  if (state.sessionActive === active) {
    if (active) connectTopics()
    return
  }
  state.sessionActive = active
  if (!active) {
    closeTransports()
    state.status = state.enabled ? "idle" : "disabled"
    return
  }
  connectTopics()
}

pageActivity.subscribe((active) => {
  state.active = active
  if (!active) {
    clearTimeout(reconnectTimer)
    reconnectTimer = 0
    return
  }
  if (canConnect() && !socket && runtimeConfig.events.mode !== "mock") {
    clearTimeout(reconnectTimer)
    reconnectTimer = 0
    connectWebSocket()
  }
})

function publishMock(topic: EventTopic, type: string, data: unknown): void {
  dispatch({ topic, type, occurredAt: new Date().toISOString(), data })
}

export const eventBus = { state: readonly(state), subscribe, publishMock, setEnabled, setSessionActive }

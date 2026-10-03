import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const activity = vi.hoisted(() => ({ active: true, listeners: new Set<(active: boolean) => void>() }))
const telemetry = vi.hoisted(() => ({ websocket: vi.fn(), error: vi.fn() }))
vi.mock("@/shared/lib/page-activity", () => ({
  pageActivity: {
    isActive: () => activity.active,
    state: { get active() { return activity.active } },
    subscribe: (listener: (active: boolean) => void) => { activity.listeners.add(listener); return () => activity.listeners.delete(listener) },
  },
}))
vi.mock("@/shared/config/runtime", () => ({ runtimeConfig: { events: { mode: "websocket", url: "/api/realtime" } } }))
vi.mock("@/shared/telemetry/client", () => ({ frontendTelemetry: telemetry }))

class FakeWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 3
  static instances: FakeWebSocket[] = []
  readyState = FakeWebSocket.CONNECTING
  onopen: null | (() => void) = null
  onmessage: null | ((event: MessageEvent) => void) = null
  onclose: null | ((event: CloseEvent) => void) = null
  onerror: null | (() => void) = null
  sent: string[] = []
  closed = false
  constructor(readonly url: string) { FakeWebSocket.instances.push(this) }
  send(value: string) { this.sent.push(value) }
  close() { this.closed = true; this.readyState = FakeWebSocket.CLOSED }
  open() { this.readyState = FakeWebSocket.OPEN; this.onopen?.() }
  closeWith(code: number) { this.readyState = FakeWebSocket.CLOSED; this.onclose?.({ code } as CloseEvent) }
}

function setActivity(active: boolean): void {
  activity.active = active
  for (const listener of [...activity.listeners]) listener(active)
}

async function loadBus() {
  vi.stubGlobal("WebSocket", FakeWebSocket)
  vi.resetModules()
  return (await import("@/shared/events/bus")).eventBus
}

beforeEach(() => {
  vi.useFakeTimers()
  activity.active = true
  activity.listeners.clear()
  FakeWebSocket.instances = []
  telemetry.websocket.mockReset()
  telemetry.error.mockReset()
  sessionStorage.clear()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("event bus connection lifecycle", () => {
  it("does not connect before an authenticated session is confirmed", async () => {
    const bus = await loadBus()
    bus.subscribe("mcp.calls", vi.fn())
    expect(FakeWebSocket.instances).toHaveLength(0)
    bus.setSessionActive(true)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it("ignores obsolete close callbacks after a fast OFF/ON", async () => {
    const bus = await loadBus()
    bus.subscribe("mcp.calls", vi.fn())
    bus.setSessionActive(true)
    const first = FakeWebSocket.instances[0]!
    first.open()
    bus.setEnabled(false)
    expect(first.closed).toBe(true)
    bus.setEnabled(true)
    const second = FakeWebSocket.instances[1]!
    second.open()
    first.closeWith(1006)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(bus.state.status).toBe("connected")
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it("does not retry a sleeping/background tab and reconnects immediately on focus", async () => {
    const bus = await loadBus()
    bus.subscribe("mcp.calls", vi.fn())
    bus.setSessionActive(true)
    const first = FakeWebSocket.instances[0]!
    first.open()
    setActivity(false)
    first.closeWith(1006)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(bus.state.status).toBe("reconnecting")
    setActivity(true)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it("treats 4403 as policy failure, not expired authentication", async () => {
    const bus = await loadBus()
    const expired = vi.fn()
    window.addEventListener("management:auth-expired", expired)
    bus.subscribe("mcp.calls", vi.fn())
    bus.setSessionActive(true)
    FakeWebSocket.instances[0]!.open()
    FakeWebSocket.instances[0]!.closeWith(4403)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(bus.state.status).toBe("error")
    expect(bus.state.sessionActive).toBe(true)
    expect(expired).not.toHaveBeenCalled()
    expect(FakeWebSocket.instances).toHaveLength(1)
    window.removeEventListener("management:auth-expired", expired)
  })

  it("expires the session on 4401 and does not retry", async () => {
    const bus = await loadBus()
    const expired = vi.fn()
    window.addEventListener("management:auth-expired", expired)
    bus.subscribe("mcp.calls", vi.fn())
    bus.setSessionActive(true)
    FakeWebSocket.instances[0]!.open()
    FakeWebSocket.instances[0]!.closeWith(4401)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(bus.state.sessionActive).toBe(false)
    expect(expired).toHaveBeenCalledTimes(1)
    expect(FakeWebSocket.instances).toHaveLength(1)
    window.removeEventListener("management:auth-expired", expired)
  })

  it("ignores legacy persisted operational flags", async () => {
    sessionStorage.setItem("mcp-bridge:tab-workspace", JSON.stringify({ realtimeEnabled: false }))
    const bus = await loadBus()
    bus.subscribe("mcp.calls", vi.fn())
    bus.setSessionActive(true)
    expect(bus.state.enabled).toBe(true)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})

import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import BrowserPage from "@/pages/browser/BrowserPage.vue"

const activity = vi.hoisted(() => ({ active: true, listeners: new Set<(active: boolean) => void>() }))
const notify = vi.hoisted(() => ({ error: vi.fn() }))
const telemetry = vi.hoisted(() => ({ websocket: vi.fn(), error: vi.fn(), event: vi.fn() }))
const api = vi.hoisted(() => ({
  setBrowserViewport: vi.fn(),
  setBrowserTheme: vi.fn(),
  browserRemoteDebug: vi.fn(),
}))
vi.mock("@/shared/lib/page-activity", () => ({
  pageActivity: {
    isActive: () => activity.active,
    subscribe: (listener: (active: boolean) => void) => { activity.listeners.add(listener); return () => activity.listeners.delete(listener) },
  },
}))
vi.mock("@/shared/notifications/bus", () => ({ notifications: notify }))
vi.mock("@/shared/telemetry/client", () => ({ frontendTelemetry: telemetry }))
vi.mock("@/shared/events/bus", () => ({ eventBus: { publishMock: vi.fn() } }))
vi.mock("@/shared/api/management", () => ({ managementApi: api }))
vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock("ant-design-vue", () => ({ Select: { template: "<div />" } }))

class FakeWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 3
  static instances: FakeWebSocket[] = []
  readyState = FakeWebSocket.CONNECTING
  onopen: null | (() => void) = null
  onmessage: null | ((event: MessageEvent) => void | Promise<void>) = null
  onclose: null | ((event: CloseEvent) => void) = null
  onerror: null | (() => void) = null
  closed = false
  sent: string[] = []
  constructor(readonly url: string) { FakeWebSocket.instances.push(this) }
  send(payload: string) { this.sent.push(payload) }
  close() { this.closed = true; this.readyState = FakeWebSocket.CLOSED }
  open() { this.readyState = FakeWebSocket.OPEN; this.onopen?.() }
  fail() { this.onerror?.() }
  closeWith(code: number) { this.readyState = FakeWebSocket.CLOSED; this.onclose?.({ code } as CloseEvent) }
  message(payload: unknown) { return this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) })) }
}

function setActivity(active: boolean): void {
  activity.active = active
  for (const listener of [...activity.listeners]) listener(active)
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal("WebSocket", FakeWebSocket)
  activity.active = true
  activity.listeners.clear()
  FakeWebSocket.instances = []
  notify.error.mockReset()
  telemetry.websocket.mockReset()
  telemetry.error.mockReset()
  telemetry.event.mockReset()
  api.setBrowserViewport.mockReset()
  api.setBrowserTheme.mockReset()
  api.browserRemoteDebug.mockReset()
  api.browserRemoteDebug.mockResolvedValue({
    page_id: "page-1",
    target_id: "TARGET123",
    frontend_url: "https://mcp.koba-nexus.ru/api/browser/devtools/token/page/TARGET123/devtools/inspector.html?wss=example",
    websocket_url: "wss://mcp.koba-nexus.ru/api/browser/cdp/token/page/TARGET123",
    expires_in_seconds: 3600,
  })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ""
})

describe("Browser operator connection lifecycle", () => {
  it("suppresses background disconnect alerts and reconnects when the tab becomes active", async () => {
    const wrapper = mount(BrowserPage, { attachTo: document.body })
    const first = FakeWebSocket.instances[0]!
    first.open()
    setActivity(false)
    first.fail()
    first.closeWith(1006)
    expect(notify.error).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
    setActivity(true)
    expect(FakeWebSocket.instances).toHaveLength(2)
    wrapper.unmount()
  })

  it("shows one alert for an active transport failure even when error precedes close", async () => {
    const wrapper = mount(BrowserPage, { attachTo: document.body })
    const first = FakeWebSocket.instances[0]!
    first.open()
    first.fail()
    first.closeWith(1006)
    expect(notify.error).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(FakeWebSocket.instances).toHaveLength(2)
    wrapper.unmount()
  })

  it("does not let an unmounted socket schedule a reconnect", async () => {
    const wrapper = mount(BrowserPage, { attachTo: document.body })
    const first = FakeWebSocket.instances[0]!
    wrapper.unmount()
    expect(first.closed).toBe(true)
    first.closeWith(1006)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it("opens the graphical remote DevTools frontend for the selected tab", async () => {
    const popup = { location: { href: "about:blank" }, close: vi.fn() }
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window)
    const wrapper = mount(BrowserPage, { attachTo: document.body })
    const socket = FakeWebSocket.instances[0]!
    socket.open()
    await socket.message({
      type: "state",
      selected_page_id: "page-1",
      pages: [{ page_id: "page-1", title: "MCP Bridge", url: "https://mcp.koba-nexus.ru/admin/" }],
      capabilities: { set_viewport: true, set_theme: true, remote_devtools: true },
      color_scheme: "dark",
      viewport: { width: 1280, height: 720 },
    })
    await flushPromises()

    const button = wrapper.find('button[title="browser.remoteDevtools"]')
    expect(button.exists()).toBe(true)
    await button.trigger("click")
    await flushPromises()

    expect(api.browserRemoteDebug).toHaveBeenCalledWith("page-1")
    expect(popup.location.href).toContain("/api/browser/devtools/")
    wrapper.unmount()
  })

  it("still surfaces explicit protocol/command errors while the tab is backgrounded", async () => {
    const wrapper = mount(BrowserPage, { attachTo: document.body })
    const first = FakeWebSocket.instances[0]!
    first.open()
    setActivity(false)
    await first.message({ type: "error", message: "Command failed" })
    await flushPromises()
    expect(notify.error).toHaveBeenCalledTimes(1)
    expect(notify.error).toHaveBeenCalledWith("notifications.websocketError", "Command failed")
    wrapper.unmount()
  })
})

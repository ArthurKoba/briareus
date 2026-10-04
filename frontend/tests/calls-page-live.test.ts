import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import CallsPage from "@/pages/calls/CallsPage.vue"
import { callStore } from "@/pages/calls/model/call-store"
import DataTable from "@/shared/ui/DataTable.vue"
import type { InvocationRecord } from "@/shared/api/management"
import type { BusEvent } from "@/shared/events/bus"

const api = vi.hoisted(() => ({ calls: vi.fn(), accounts: vi.fn(), clearCalls: vi.fn(), deleteCall: vi.fn() }))
const bus = vi.hoisted(() => ({ handler: undefined as undefined | ((event: BusEvent) => void), state: { status: "connected", enabled: true, active: true } }))
vi.mock("@/shared/api/management", () => ({ managementApi: api }))
vi.mock("@/shared/events/bus", () => ({
  eventBus: { state: bus.state, subscribe: vi.fn((_topic: string, handler: (event: BusEvent) => void) => { bus.handler = handler; return vi.fn() }) },
}))
vi.mock("@/shared/notifications/bus", () => ({ notifications: { success: vi.fn() } }))
vi.mock("vue-i18n", () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock("@/shared/lib/preferences", () => ({ uiPreferences: { density: { value: "compact" } } }))
vi.mock("@tanstack/vue-virtual", async (original) => {
  const actual = await original<typeof import("@tanstack/vue-virtual")>()
  return { ...actual, useVirtualizer: (options: { value: { count: number; getItemKey?: (index: number) => unknown } }) => ({ value: {
    getVirtualItems: () => Array.from({ length: options.value.count }, (_, index) => ({ key: options.value.getItemKey?.(index) ?? index, index, start: index * 32, size: 32 })),
    getTotalSize: () => options.value.count * 32,
  } }) }
})

function call(id: string, second: number): InvocationRecord {
  return { id, request_id: `request-${id}`, module: "web", tool: `tool-${id}`, account_id: "", provider: "web", status: "success",
    duration_ms: second, error_type: "", arguments_json: "{}", result_json: "{}", error_message: "",
    occurred_at: `2026-10-03T20:00:${String(second).padStart(2,"0")}.000Z` }
}

const mounted: ReturnType<typeof mount>[] = []
beforeEach(async () => {
  callStore.stop()
  callStore.setSessionActive(false)
  api.calls.mockReset()
  api.calls.mockResolvedValue({ events: [call("old", 1)], count: 1 })
  api.accounts.mockResolvedValue({ accounts: [] })
  bus.handler = undefined
  bus.state.status = "connected"
  bus.state.enabled = true
  bus.state.active = true
  callStore.start()
  callStore.setSessionActive(true)
  await flushPromises()
})
afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  callStore.stop()
  callStore.setSessionActive(false)
})

async function page() {
  const wrapper = mount(CallsPage, { attachTo: document.body })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

describe("MCP calls live window", () => {
  it("renders a batch delta as the new first row without refresh", async () => {
    const wrapper = await page()
    expect(wrapper.text()).toContain("tool-old")
    bus.handler?.({ topic: "mcp.calls", type: "batch", occurredAt: call("new", 2).occurred_at, data: { events: [call("new", 2)], count: 1 } })
    await flushPromises()
    const rows = wrapper.findAll(".ts-table-row")
    expect(rows[0].text()).toContain("tool-new")
    expect(wrapper.text()).toContain("tool-old")
    expect(api.calls).toHaveBeenCalledTimes(1)
  })

  it("does not show a page-local live control and hides refresh after domain reconciliation", async () => {
    const wrapper = await page()
    expect(wrapper.text()).not.toContain("calls.liveControl")
    expect(callStore.state.synced).toBe(true)
    expect(wrapper.text()).not.toContain("common.refresh")
  })

  it("keeps history stable away from the live edge and exposes queued events", async () => {
    const wrapper = await page()
    wrapper.getComponent(DataTable).vm.$emit("scrollPosition", false)
    await flushPromises()
    bus.handler?.({ topic: "mcp.calls", type: "batch", occurredAt: call("new", 2).occurred_at, data: { events: [call("new", 2)], count: 1 } })
    await flushPromises()
    expect(wrapper.findAll(".ts-table-row")[0].text()).toContain("tool-old")
    expect(wrapper.text()).toContain("1 calls.new")
  })
})
